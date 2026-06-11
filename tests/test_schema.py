from pathlib import Path

from mcmurphy.prompts import load_prompts
from mcmurphy.schema import validate_record


def test_prompt_schema_validation_accepts_seed_record():
    record = load_prompts(Path("data/seed_prompts.jsonl"))[0]

    validate_record(record)


def test_prompt_schema_rejects_extra_properties():
    record = load_prompts(Path("data/seed_prompts.jsonl"))[0]
    record["surprise"] = "nope"

    try:
        validate_record(record)
    except ValueError as exc:
        assert "Additional properties" in str(exc)
    else:
        raise AssertionError("Expected extra property to fail")

