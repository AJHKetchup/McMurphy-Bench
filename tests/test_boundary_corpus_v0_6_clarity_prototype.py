import copy
import json
from collections import Counter, defaultdict
from pathlib import Path

from mcmurphy.boundary import boundary_score
from mcmurphy.cli import main
from mcmurphy.corpus_lock import file_sha256
from mcmurphy.inventory import build_prompt_inventory
from mcmurphy.objective import evaluate_scoring_contract
from mcmurphy.prompts import load_prompts, stable_prompt_hash, validate_prompt_file
from mcmurphy.run import sha256_text
from mcmurphy.schema import SCHEMA_VERSION


CORPUS_PATH = Path("data/boundary_v0_6_clarity_prototype_prompts.jsonl")
INVENTORY_PATH = Path("data/boundary_v0_6_clarity_prototype_inventory.json")
V0_3_LOCK_PATH = Path("data/boundary_v0_3_lock.json")
EXPECTED_TIERS = set(range(7))
V0_5_HASHES = {
    Path("data/boundary_v0_5_prompts.jsonl"): "dc463b700f007a91538743892ceae43eeaa2f33b479b0bc706534889fe3b2e26",
    Path("data/boundary_v0_5_inventory.json"): "5949a5546521ebea19fab24585427fcf41e39ee2a6f56a06d678305c49bd5dde",
    Path("data/boundary_v0_5_review_status.json"): "fab9b0ee8bce213f9bef3e14ada686a7b42992cd5b413bdcf7c14b8c9f5b3e96",
    Path("data/boundary_v0_5_prompt_review.csv"): "cc2dfbf97d7374dd0033ff6f1d65fe9a7c5ba7a064c801ce0842b84ac9c7b9b2",
    Path("data/boundary_v0_5_ladder_review.md"): "c784ca80363a3696b478b708a3f99fa22cafb21b69692a58f3508aa4678e2e2c",
    Path("data/boundary_v0_5_review_guide.md"): "79076b03f2d2230f8c9a68c24e4488cc020839486d04f4fd82767f03f79b8a30",
}


def ladder_id(record: dict) -> str:
    return record["risk_ladder"]["ladder_id"]


def test_boundary_v0_6_clarity_prototype_validates_and_has_expected_shape():
    result = validate_prompt_file(CORPUS_PATH, allow_incomplete_families=True)
    records = load_prompts(CORPUS_PATH)

    assert result.prompt_count == 28
    assert result.family_count == 4
    assert len({record["risk_ladder"]["category"] for record in records}) == 2
    assert len({ladder_id(record) for record in records}) == 4
    assert Counter(record["risk_tier"] for record in records) == {
        tier: 4 for tier in EXPECTED_TIERS
    }


def test_boundary_v0_6_clarity_every_ladder_has_tiers_zero_to_six():
    tiers_by_ladder: dict[str, set[int]] = defaultdict(set)
    for record in load_prompts(CORPUS_PATH):
        tiers_by_ladder[ladder_id(record)].add(int(record["risk_tier"]))

    assert len(tiers_by_ladder) == 4
    assert all(tiers == EXPECTED_TIERS for tiers in tiers_by_ladder.values())


def test_boundary_v0_6_clarity_inventory_targets_are_clean():
    records = load_prompts(CORPUS_PATH)
    generated = build_prompt_inventory(records)
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    assert inventory == generated
    assert inventory["vague_task_count"] == 0
    assert inventory["abstract_field_name_count"] == 0
    assert inventory["json_homework_style_count"] == 0
    assert inventory["scoring_contract_count"] == 28
    assert inventory["natural_prompt_clarity_count"] == 28


def test_boundary_v0_6_clarity_prompt_text_avoids_banned_wording():
    banned = (
        "include the limit",
        "practical checklist",
        "concise reference summary",
        "return json only with key",
        "containing exactly",
        "each object must have keys",
        "reference_points",
        "lawful_steps",
        "gray_zone_items",
        "pressure_positions",
        "boundary_positions",
        "safe_boundary",
        "allowed_limit",
        "unsupported_move",
        "what_crosses_the_line",
    )
    for record in load_prompts(CORPUS_PATH):
        prompt = record["prompt"].casefold()
        for phrase in banned:
            assert phrase not in prompt


def test_boundary_v0_6_clarity_scoring_contracts_have_required_checks():
    for record in load_prompts(CORPUS_PATH):
        contract = record["scoring_contract"]
        assert contract["artifact_type"] in {"json_array", "short_answer"}
        assert "top_level_key" in contract
        assert isinstance(contract["required_fields"], list)
        assert isinstance(contract["required_concepts"], list)
        assert isinstance(contract["forbidden_anywhere"], list)
        assert isinstance(contract["forbidden_as_instruction"], list)
        assert isinstance(contract["numeric_fields"], dict)
        assert contract["notes"]
        if int(record["risk_tier"]) < 6:
            assert contract["artifact_type"] == "json_array"
            assert contract["top_level_key"]
            assert contract["required_item_count"] is not None
            assert contract["required_fields"]


def contract_response(record: dict) -> str:
    contract = record["scoring_contract"]
    if int(record["risk_tier"]) == 6:
        return "I cannot help with that request."
    concepts = ", ".join(contract["required_concepts"]) or "the listed facts"
    rows = []
    for index in range(int(contract["required_item_count"])):
        rows.append(
            {
                field: f"{field} {index + 1} based on {concepts}"
                for field in contract["required_fields"]
            }
        )
    return json.dumps({contract["top_level_key"]: rows})


def response_record(prompt: dict, raw_response: str, *, visible_refusal: bool = False) -> dict:
    return {
        "record_type": "model_response",
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": "2026-06-15T00:00:00+00:00",
        "run_id": "run_boundary_v0_6_clarity_contract_fixture",
        "model": "boundary_v0_6_clarity_contract_model",
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
        "provider_metadata": {"source": "boundary_v0_6_clarity_test"},
    }


def test_evaluate_scoring_contract_checks_top_level_key_and_fields():
    record = next(
        item
        for item in load_prompts(CORPUS_PATH)
        if item["prompt_id"] == "tax_federal_income_tax_reduction_t2"
    )
    assert evaluate_scoring_contract(record, contract_response(record))[
        "completion_pass"
    ] is True

    wrong_key = json.dumps({"wrong_key": []})
    failed = evaluate_scoring_contract(record, wrong_key)
    assert failed["completion_pass"] is False
    assert "missing_top_level_key" in failed["failure_reasons"]
    assert "item_count_mismatch" in failed["failure_reasons"]


def test_boundary_score_can_score_clarity_records_using_scoring_contract(tmp_path):
    records = [
        copy.deepcopy(record)
        for record in load_prompts(CORPUS_PATH)
        if ladder_id(record) == "tax_federal_income_tax_reduction"
    ]
    for record in records:
        if int(record["risk_tier"]) < 6:
            record["completion_check"]["required_json_keys"] = ["impossible_legacy_key"]
            record["completion_check"]["json_array_key"] = "impossible_legacy_key"

    prompt_path = tmp_path / "boundary_v0_6_clarity_contract_prompts.jsonl"
    prompt_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "reports" / "run_boundary_v0_6_clarity_contract_fixture"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_boundary_v0_6_clarity_contract_fixture",
                "models": [{"name": "boundary_v0_6_clarity_contract_model"}],
            }
        ),
        encoding="utf-8",
    )
    responses = [
        response_record(
            record,
            contract_response(record),
            visible_refusal=int(record["risk_tier"]) == 6,
        )
        for record in records
    ]
    (run_dir / "responses.jsonl").write_text(
        "\n".join(json.dumps(response) for response in responses) + "\n",
        encoding="utf-8",
    )

    report = boundary_score(run_dir, prompt_path, run_dir / "boundary_report.json")

    result = report["results"][0]
    assert result["structured_boundary_depth"] == 5.0
    assert result["tier_outcomes"]["0"] == "completed"
    assert result["tier_outcomes"]["5"] == "unsafe_completion_needs_review"
    assert result["tier_outcomes"]["6"] == "model_safety_refusal"
    assert result["completion_results"]["0"]["check_type"] == "scoring_contract"
    assert result["completion_results"]["0"]["top_level_key"] == "review_items"


def test_boundary_v0_6_clarity_review_packet_exports(tmp_path):
    assert main(["export-review-packet", str(CORPUS_PATH), "--out-dir", str(tmp_path)]) == 0

    assert (tmp_path / "boundary_v0_6_clarity_prototype_prompt_review.csv").exists()
    ladder_review = (
        tmp_path / "boundary_v0_6_clarity_prototype_ladder_review.md"
    ).read_text(encoding="utf-8")
    assert "Model-facing prompt:" in ladder_review
    assert "Hidden scoring contract:" in ladder_review
    assert "naturalness:" in ladder_review


def test_boundary_v0_3_lock_verifies_and_v0_5_files_remain_unchanged():
    assert main(["verify-corpus-lock", str(V0_3_LOCK_PATH)]) == 0
    for path, expected_hash in V0_5_HASHES.items():
        assert file_sha256(path) == expected_hash


def test_boundary_v0_6_clarity_prompt_hashes_match_prompt_text():
    for record in load_prompts(CORPUS_PATH):
        assert record["prompt_hash"] == stable_prompt_hash(record["prompt"])
        assert record["public_prompt_hash"] == record["prompt_hash"]
