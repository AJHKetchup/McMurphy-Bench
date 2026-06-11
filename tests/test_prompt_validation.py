import json
from pathlib import Path

import yaml

from mcmurphy.cli import main
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


def test_make_subset_tiers_zero_to_four_excludes_tier_five(tmp_path):
    out_path = tmp_path / "pilot_public_t0_t4.jsonl"

    assert (
        main(
            [
                "make-subset",
                "data/seed_prompts.jsonl",
                "--families",
                "10",
                "--tiers",
                "0,1,2,3,4",
                "--out",
                str(out_path),
            ]
        )
        == 0
    )

    records = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_family = {}
    for record in records:
        by_family.setdefault(record["family_id"], set()).add(record["risk_tier"])

    assert len(records) == 50
    assert set(by_family) and len(by_family) == 10
    assert all(tiers == {0, 1, 2, 3, 4} for tiers in by_family.values())
    assert all(record["risk_tier"] != 5 for record in records)


def test_make_subset_output_validates(tmp_path):
    out_path = tmp_path / "pilot_public_t0_t4.jsonl"

    assert (
        main(
            [
                "make-subset",
                "data/seed_prompts.jsonl",
                "--families",
                "10",
                "--tiers",
                "0,1,2,3,4",
                "--out",
                str(out_path),
            ]
        )
        == 0
    )

    result = validate_prompt_file(out_path, allow_incomplete_families=True)

    assert result.prompt_count == 50
    assert result.family_count == 10


def test_pilot_live_config_uses_public_subset_and_excludes_restricted_controls():
    config = yaml.safe_load(
        Path("configs/pilot.live.example.yaml").read_text(encoding="utf-8")
    )

    assert config["prompt_set"] == "data/pilot_public_t0_t4.jsonl"
    assert config["allow_incomplete_families"] is True
    assert config["include_restricted_controls"] is False
