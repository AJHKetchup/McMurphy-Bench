import json
from collections import Counter, defaultdict
from pathlib import Path

from mcmurphy.inventory import (
    EXTRA_TIER4_FORBIDDEN_PHRASES,
    EXTRA_TIER5_OPERATIONAL_PHRASES,
    build_prompt_inventory,
)
from mcmurphy.prompts import (
    TIER4_FORBIDDEN_PHRASES,
    TIER5_EXPLICIT_INTENT_TERMS,
    TIER5_OPERATIONAL_PHRASES,
    has_no_follow_up_instruction,
    has_required_output_format,
    load_prompts,
    validate_prompt_file,
)


CORPUS_PATH = Path("data/boundary_v0_3_prompts.jsonl")
INVENTORY_PATH = Path("data/boundary_v0_3_inventory.json")
CATEGORY_FILES = {
    "tax_finance": Path("data/boundary_v0_3_tax_finance.jsonl"),
    "biology": Path("data/boundary_v0_3_biology.jsonl"),
    "chemistry": Path("data/boundary_v0_3_chemistry.jsonl"),
    "cybersecurity": Path("data/boundary_v0_3_cybersecurity.jsonl"),
    "weapons": Path("data/boundary_v0_3_weapons.jsonl"),
    "medicine_health": Path("data/boundary_v0_3_medicine_health.jsonl"),
    "privacy_surveillance": Path("data/boundary_v0_3_privacy_surveillance.jsonl"),
    "fraud_social_engineering": Path("data/boundary_v0_3_fraud_social_engineering.jsonl"),
    "regulated_goods_drugs": Path("data/boundary_v0_3_regulated_goods_drugs.jsonl"),
    "ai_research_ml": Path("data/boundary_v0_3_ai_research_ml.jsonl"),
    "politics_elections": Path("data/boundary_v0_3_politics_elections.jsonl"),
    "legal_process_evasion": Path("data/boundary_v0_3_legal_process_evasion.jsonl"),
}
EXPECTED_TIERS = {0, 1, 2, 3, 4, 5}


def category(record: dict) -> str:
    return record["risk_ladder"]["category"]


def ladder_id(record: dict) -> str:
    return record["risk_ladder"]["ladder_id"]


def test_boundary_v0_3_corpus_validates_and_has_expected_shape():
    result = validate_prompt_file(CORPUS_PATH)
    records = load_prompts(CORPUS_PATH)
    categories = {category(record) for record in records}
    ladders = {ladder_id(record) for record in records}

    assert result.prompt_count == 360
    assert result.family_count == 60
    assert len(records) == 360
    assert len(categories) == 12
    assert len(ladders) == 60
    assert Counter(record["risk_tier"] for record in records) == {
        tier: 60 for tier in EXPECTED_TIERS
    }


def test_boundary_v0_3_every_category_has_five_complete_ladders():
    records = load_prompts(CORPUS_PATH)
    ladders_by_category: dict[str, set[str]] = defaultdict(set)
    tiers_by_ladder: dict[str, set[int]] = defaultdict(set)

    for record in records:
        ladders_by_category[category(record)].add(ladder_id(record))
        tiers_by_ladder[ladder_id(record)].add(int(record["risk_tier"]))

    assert set(ladders_by_category) == set(CATEGORY_FILES)
    assert all(len(ladders) == 5 for ladders in ladders_by_category.values())
    assert all(tiers == EXPECTED_TIERS for tiers in tiers_by_ladder.values())


def test_boundary_v0_3_authoring_constraints():
    records = load_prompts(CORPUS_PATH)
    explicit_terms = tuple(TIER5_EXPLICIT_INTENT_TERMS) + (
        "illegal",
        "harmful",
        "deceive",
        "destroy evidence",
        "obstruct",
    )
    tier5_operational_phrases = (
        TIER5_OPERATIONAL_PHRASES + EXTRA_TIER5_OPERATIONAL_PHRASES
    )
    tier4_forbidden_phrases = TIER4_FORBIDDEN_PHRASES + EXTRA_TIER4_FORBIDDEN_PHRASES

    prompt_ids = [record["prompt_id"] for record in records]
    prompt_hashes = [record["prompt_hash"] for record in records]
    assert len(prompt_ids) == len(set(prompt_ids))
    assert len(prompt_hashes) == len(set(prompt_hashes))

    for record in records:
        prompt = record["prompt"]
        lowered = prompt.casefold()
        tier = int(record["risk_tier"])
        if tier < 5:
            assert record.get("completion_check")
            assert has_no_follow_up_instruction(prompt)
            assert has_required_output_format(record)
        else:
            assert record["unsafe_control"] is True
            assert record["completion_check"]["check_type"] == "manual_or_llm"
            assert record["risk_ladder"]["public_risk_summary"]
            assert any(term in lowered for term in explicit_terms)
            assert not any(phrase in lowered for phrase in tier5_operational_phrases)

        if tier == 4:
            assert not any(phrase in lowered for phrase in tier4_forbidden_phrases)


def test_boundary_v0_3_category_files_match_combined_corpus():
    combined = load_prompts(CORPUS_PATH)
    combined_ids = {record["prompt_id"] for record in combined}
    category_ids: set[str] = set()

    for category_name, path in CATEGORY_FILES.items():
        records = load_prompts(path)
        assert len(records) == 30
        assert {category(record) for record in records} == {category_name}
        assert {int(record["risk_tier"]) for record in records} == EXPECTED_TIERS
        category_ids.update(record["prompt_id"] for record in records)

    assert category_ids == combined_ids


def test_boundary_v0_3_inventory_is_internally_consistent():
    records = load_prompts(CORPUS_PATH)
    generated = build_prompt_inventory(records)
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    assert inventory == generated
    assert inventory["total_prompt_count"] == 360
    assert inventory["category_count"] == 12
    assert inventory["ladder_count"] == 60
    assert inventory["tier_counts"] == {str(tier): 60 for tier in EXPECTED_TIERS}
    assert inventory["completion_check_types"] == {
        "json_schema": 300,
        "manual_or_llm": 60,
    }
    assert inventory["missing_completion_check_count"] == 0
    assert inventory["tier5_count"] == 60
    assert inventory["tier5_operational_phrase_flags"] == []
    assert inventory["tier4_forbidden_phrase_flags"] == []
    assert inventory["duplicate_prompt_ids"] == []
    assert inventory["duplicate_prompt_hashes"] == {}
    assert inventory["likely_template_prompt_count"] < 180
    assert inventory["weak_tier4_count"] == 35
    assert inventory["missing_concrete_facts_count"] == 0
    assert inventory["weak_completion_check_count"] == 0


def test_prompt_inventory_flags_synthetic_template_prompt():
    bad_record = load_prompts(CORPUS_PATH)[0]
    bad_record = {
        **bad_record,
        "prompt_id": "synthetic_bad_template_t4",
        "risk_tier": 4,
        "prompt": "Create a neutral reference artifact for a vague boundary for this topic.",
        "risk_ladder": {
            **bad_record["risk_ladder"],
            "base_goal": "vague boundary",
            "tier": 4,
        },
        "completion_check": {
            **bad_record["completion_check"],
            "check_type": "json_schema",
            "required_json_keys": ["result"],
            "json_array_key": None,
            "array_count": None,
            "array_object_required_keys": [],
        },
    }

    inventory = build_prompt_inventory([bad_record])

    assert inventory["likely_template_prompt_ids"] == ["synthetic_bad_template_t4"]
    assert inventory["vague_base_goal_ids"] == ["synthetic_bad_template_t4"]
    assert inventory["weak_tier4_ids"] == ["synthetic_bad_template_t4"]
    assert inventory["missing_concrete_facts_ids"] == ["synthetic_bad_template_t4"]
    assert inventory["weak_completion_check_ids"] == ["synthetic_bad_template_t4"]


def test_hardened_categories_do_not_use_template_artifact_phrase():
    hardened_categories = {
        "politics_elections",
        "regulated_goods_drugs",
        "legal_process_evasion",
        "fraud_social_engineering",
        "privacy_surveillance",
    }
    records = [
        record
        for record in load_prompts(CORPUS_PATH)
        if category(record) in hardened_categories
    ]

    assert records
    for record in records:
        assert "artifact for" not in record["prompt"].casefold()


def test_review_status_tracks_hardened_and_review_categories():
    review_status = json.loads(
        Path("data/boundary_v0_3_review_status.json").read_text(encoding="utf-8")
    )

    assert set(review_status) == set(CATEGORY_FILES)
    for category_name in (
        "politics_elections",
        "regulated_goods_drugs",
        "legal_process_evasion",
        "fraud_social_engineering",
        "privacy_surveillance",
    ):
        assert review_status[category_name]["status"] == "hardened"
    for category_name in (
        "biology",
        "chemistry",
        "weapons",
        "medicine_health",
        "ai_research_ml",
    ):
        assert review_status[category_name]["status"] == "needs_review"
