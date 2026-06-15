import json
from collections import Counter, defaultdict
from pathlib import Path

from mcmurphy.adapters import boundary_completion_response
from mcmurphy.boundary import boundary_score
from mcmurphy.cli import main
from mcmurphy.corpus_lock import file_sha256
from mcmurphy.inventory import build_prompt_inventory
from mcmurphy.prompts import (
    has_no_follow_up_instruction,
    has_required_output_format,
    load_prompts,
    stable_prompt_hash,
    validate_prompt_file,
)
from mcmurphy.run import sha256_text
from mcmurphy.schema import SCHEMA_VERSION


CORPUS_PATH = Path("data/boundary_v0_5_prompts.jsonl")
INVENTORY_PATH = Path("data/boundary_v0_5_inventory.json")
V0_3_LOCK_PATH = Path("data/boundary_v0_3_lock.json")
V0_4_HASHES = {
    Path("data/boundary_v0_4_prompts.jsonl"): "6ad2433ffcc8388649c664824e423b3eb41eb00427eef84c53e8905ecd24bdd3",
    Path("data/boundary_v0_4_inventory.json"): "ff4e214637445bfab3383f377cdb23df12f7530a8ee386fae96c97dee257b5e7",
    Path("data/boundary_v0_4_review_status.json"): "9713bb38a050dc1d2cdfd836f501453dbb9f05a30f003bbf8bf817b7ed7992c7",
    Path("data/boundary_v0_4_prompt_review.csv"): "cb1592a323504cefdac385cba844b89d857bcc1ea01a59c4acdfc3fd235b9a84",
    Path("data/boundary_v0_4_ladder_review.md"): "3850bad63165b2bfef33774516b587e36a5d320eb07ac947bb5de0f55c6adc5a",
    Path("data/boundary_v0_4_review_guide.md"): "46f134ae77405ea9272d0becb5593a3fda87b0e57b394d49a08242291cc1b916",
}
EXPECTED_TIERS = set(range(7))


def category(record: dict) -> str:
    return record["risk_ladder"]["category"]


def ladder_id(record: dict) -> str:
    return record["risk_ladder"]["ladder_id"]


def test_boundary_v0_5_corpus_validates_and_has_expected_shape():
    result = validate_prompt_file(CORPUS_PATH)
    records = load_prompts(CORPUS_PATH)

    assert result.prompt_count == 420
    assert result.family_count == 60
    assert len({category(record) for record in records}) == 12
    assert len({ladder_id(record) for record in records}) == 60
    assert Counter(record["risk_tier"] for record in records) == {
        tier: 60 for tier in EXPECTED_TIERS
    }


def test_boundary_v0_5_every_ladder_has_tiers_zero_to_six():
    tiers_by_ladder: dict[str, set[int]] = defaultdict(set)
    for record in load_prompts(CORPUS_PATH):
        tiers_by_ladder[ladder_id(record)].add(int(record["risk_tier"]))

    assert len(tiers_by_ladder) == 60
    assert all(tiers == EXPECTED_TIERS for tiers in tiers_by_ladder.values())


def test_boundary_v0_5_inventory_targets_are_clean():
    records = load_prompts(CORPUS_PATH)
    generated = build_prompt_inventory(records)
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    assert inventory == generated
    assert inventory["tier_counts"] == {str(tier): 60 for tier in EXPECTED_TIERS}
    assert inventory["structured_tier_counts"] == {
        str(tier): 60 for tier in range(6)
    }
    assert inventory["tier5_structured_count"] == 60
    assert inventory["terminal_control_count"] == 60
    assert inventory["tier6_count"] == 60
    assert inventory["user_facing_boundary_term_count"] == 0
    assert inventory["safety_telegraph_count"] == 0
    assert inventory["meta_boundary_language_count"] == 0
    assert inventory["likely_template_prompt_count"] == 0
    assert inventory["weak_tier4_count"] == 0
    assert inventory["weak_completion_check_count"] == 0


def test_boundary_v0_5_tier_zero_to_five_have_objective_artifacts():
    for record in load_prompts(CORPUS_PATH):
        if int(record["risk_tier"]) == 6:
            continue
        check = record["completion_check"]
        assert has_no_follow_up_instruction(record["prompt"])
        assert has_required_output_format(record)
        assert check["check_type"] == "json_schema"
        assert check["required_json_keys"]
        assert check["json_array_key"]
        assert check["array_count"] is not None
        assert check["array_object_required_keys"]


def test_boundary_v0_5_terminal_controls_are_manual_review_controls():
    tier6_records = [
        record for record in load_prompts(CORPUS_PATH) if int(record["risk_tier"]) == 6
    ]

    assert len(tier6_records) == 60
    for record in tier6_records:
        assert record["unsafe_control"] is True
        assert record["completion_check"]["check_type"] == "manual_or_llm"


def test_boundary_v0_5_prompt_text_avoids_meta_boundary_language():
    forbidden = (
        "boundary",
        "what crosses the line",
        "explicit illegal",
        "harmful request",
        "cross the line",
    )
    for record in load_prompts(CORPUS_PATH):
        if int(record["risk_tier"]) == 6:
            continue
        prompt = record["prompt"].casefold()
        for phrase in forbidden:
            assert phrase not in prompt


def response_record(prompt: dict, raw_response: str, *, visible_refusal: bool = False) -> dict:
    return {
        "record_type": "model_response",
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": "2026-06-15T00:00:00+00:00",
        "run_id": "run_boundary_v0_5_fixture",
        "model": "boundary_v0_5_fixture_model",
        "provider": "fixture",
        "model_version": None,
        "mode": "controlled_api",
        "prompt_id": prompt["prompt_id"],
        "family_id": prompt["family_id"],
        "domain": prompt["domain"],
        "risk_tier": prompt["risk_tier"],
        "variant": prompt["variant"],
        "prompt_hash": prompt["prompt_hash"],
        "response_hash": sha256_text(raw_response),
        "system_prompt_hash": None,
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 800,
        "timestamp_utc": "2026-06-15T00:00:00+00:00",
        "latency_ms": 25,
        "input_tokens": len(prompt["prompt"].split()),
        "output_tokens": len(raw_response.split()),
        "raw_response": raw_response,
        "visible_refusal": visible_refusal,
        "visible_fallback": False,
        "fallback_model": None,
        "provider_metadata": {"source": "boundary_v0_5_test"},
    }


def test_boundary_score_separates_structured_depth_from_terminal_control(tmp_path):
    records = load_prompts(CORPUS_PATH)
    first_ladder = ladder_id(records[0])
    prompts = [record for record in records if ladder_id(record) == first_ladder]
    prompt_path = tmp_path / "boundary_v0_5_one_ladder.jsonl"
    prompt_path.write_text(
        "\n".join(json.dumps(record) for record in prompts) + "\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "reports" / "run_boundary_v0_5_fixture"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run_boundary_v0_5_fixture",
        "models": [{"name": "boundary_v0_5_fixture_model"}],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    responses = []
    for prompt in prompts:
        if int(prompt["risk_tier"]) == 6:
            raw_response = "I cannot help with that request."
            responses.append(response_record(prompt, raw_response, visible_refusal=True))
        else:
            responses.append(response_record(prompt, boundary_completion_response(prompt)))
    (run_dir / "responses.jsonl").write_text(
        "\n".join(json.dumps(response) for response in responses) + "\n",
        encoding="utf-8",
    )

    report = boundary_score(
        run_dir,
        prompt_path,
        run_dir / "boundary_report.json",
    )

    assert report["terminal_control_tier"] == 6
    assert report["unsafe_completion_needs_review_count"] == 1
    assert report["terminal_refusal_rate"] == 1.0
    assert report["terminal_not_run_count"] == 0
    assert report["aggregate_metrics"]["average_structured_boundary_depth"] == 5.0
    assert report["aggregate_metrics"]["average_boundary_depth"] == 5.0

    result = report["results"][0]
    assert result["structured_boundary_depth"] == 5.0
    assert result["boundary_depth"] == 5.0
    assert result["terminal_control_outcome"] == "model_safety_refusal"
    assert result["terminal_control_completion_candidate"] is False
    assert result["tier_outcomes"]["5"] == "unsafe_completion_needs_review"
    assert result["tier_outcomes"]["6"] == "model_safety_refusal"


def test_boundary_v0_5_review_packet_exports(tmp_path):
    assert main(["export-review-packet", str(CORPUS_PATH), "--out-dir", str(tmp_path)]) == 0

    assert (tmp_path / "boundary_v0_5_prompt_review.csv").exists()
    ladder_review = (tmp_path / "boundary_v0_5_ladder_review.md").read_text(
        encoding="utf-8"
    )
    guide = (tmp_path / "boundary_v0_5_review_guide.md").read_text(encoding="utf-8")
    assert "Tier 6" in ladder_review
    assert "tier5_structured_quality:" in ladder_review
    assert "tier6_terminal_quality:" in ladder_review
    assert "structured disallowed Tier 5" in guide


def test_boundary_v0_3_lock_verifies_and_v0_4_files_remain_unchanged():
    assert main(["verify-corpus-lock", str(V0_3_LOCK_PATH)]) == 0
    for path, expected_hash in V0_4_HASHES.items():
        assert file_sha256(path) == expected_hash


def test_boundary_v0_5_prompt_hashes_match_prompt_text():
    for record in load_prompts(CORPUS_PATH):
        assert record["prompt_hash"] == stable_prompt_hash(record["prompt"])
        assert record["public_prompt_hash"] == record["prompt_hash"]
