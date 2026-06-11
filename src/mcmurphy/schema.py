"""Shared schema constants and light validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA_VERSION = "0.2.0"
BENCHMARK_VERSION = "0.2.0"

DOMAINS = {
    "medicine_health",
    "biology",
    "chemistry",
    "cybersecurity",
    "ai_research_ml",
    "law_finance",
    "politics_public_figures",
    "sex_relationships",
    "self_harm_adjacent",
    "fiction_history_metaphor",
}

REFUSAL_CLASSES = {
    "ANSWERED",
    "HARD_REFUSAL",
    "SOFT_REFUSAL",
    "OVERCAUTION_DEGRADATION",
    "BOUNDED_SAFE_HELP",
    "CLARIFIED",
}

FALLBACK_STATUSES = {
    "NONE",
    "TRANSPARENT_FALLBACK",
    "SUSPECTED_HIDDEN_DEGRADE",
    "TOOL_DISABLED",
}

DEGRADATION_EVIDENCE_CLASSES = {
    "CONFIRMED_PROVIDER_METADATA",
    "DISCLOSED_TO_USER",
    "SUSPECTED_BEHAVIORAL",
    "UNSUPPORTED",
}


def repository_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "data").exists():
            return candidate
    return Path.cwd().resolve()


def schema_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / "data" / "schema.json"


def load_json_schema(root: Path | None = None) -> dict[str, Any]:
    return json.loads(schema_path(root).read_text(encoding="utf-8"))


def validate_record(record: dict[str, Any], root: Path | None = None) -> None:
    schema = load_json_schema(root)
    record_type = record.get("record_type")
    if record_type in schema.get("$defs", {}):
        schema = {
            "$schema": schema.get("$schema"),
            "$defs": schema["$defs"],
            **schema["$defs"][record_type],
        }
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(record), key=lambda error: error.path)
    if errors:
        details = "; ".join(error.message for error in errors[:3])
        raise ValueError(details)
