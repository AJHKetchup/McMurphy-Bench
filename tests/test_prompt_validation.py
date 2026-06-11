from pathlib import Path

from mcmurphy.prompts import load_prompts, validate_prompt_file


def test_seed_prompts_validate():
    result = validate_prompt_file(Path("data/seed_prompts.jsonl"))

    assert result.prompt_count == 60
    assert result.family_count == 10


def test_every_family_has_tiers_zero_to_five():
    records = load_prompts(Path("data/seed_prompts.jsonl"))
    by_family = {}
    for record in records:
        by_family.setdefault(record["family_id"], set()).add(record["risk_tier"])

    assert by_family
    assert all(tiers == {0, 1, 2, 3, 4, 5} for tiers in by_family.values())


def test_tier_5_controls_are_restricted_placeholders():
    records = load_prompts(Path("data/seed_prompts.jsonl"))
    tier_5 = [record for record in records if record["risk_tier"] == 5]

    assert tier_5
    assert all(record["release"] == "restricted" for record in tier_5)
    assert all(record["unsafe_control"] is True for record in tier_5)
    assert all("WITHHELD" in record["prompt"] for record in tier_5)

