"""Prompt loading and validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import DOMAINS, SCHEMA_VERSION, validate_record


RESTRICTED_PLACEHOLDER_TERMS = (
    "RESTRICTED",
    "WITHHELD",
    "Public summary:",
)
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PromptValidationResult:
    path: Path
    prompt_count: int
    family_count: int
    warnings: tuple[str, ...] = ()


def stable_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return records


def load_prompts(path: Path) -> list[dict[str, Any]]:
    records = load_jsonl(path)
    for record in records:
        record.setdefault("record_type", "prompt_instance")
        record.setdefault("schema_version", SCHEMA_VERSION)
    return records


def validate_prompt_records(
    records: list[dict[str, Any]], *, root: Path | None = None
) -> PromptValidationResult:
    if not records:
        raise ValueError("Prompt set is empty.")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prompt_ids: set[str] = set()
    warnings: list[str] = []

    for index, record in enumerate(records, start=1):
        try:
            validate_record(record, root=root)
        except ValueError as exc:
            raise ValueError(f"Prompt record {index} failed schema validation: {exc}") from exc

        prompt_id = record["prompt_id"]
        if prompt_id in prompt_ids:
            raise ValueError(f"Duplicate prompt_id: {prompt_id}")
        prompt_ids.add(prompt_id)

        for hash_field in (
            "prompt_hash",
            "public_prompt_hash",
            "restricted_prompt_hash",
        ):
            hash_value = record.get(hash_field)
            if hash_value is not None and not SHA256_HEX_RE.fullmatch(hash_value):
                raise ValueError(
                    f"{prompt_id}: {hash_field} must be lowercase sha256 hex"
                )

        domain = record["domain"]
        if domain not in DOMAINS:
            raise ValueError(f"{prompt_id}: unknown domain {domain!r}")

        expected_hash = stable_prompt_hash(record["prompt"])
        if record.get("prompt_hash") != expected_hash:
            raise ValueError(
                f"{prompt_id}: prompt_hash must equal sha256(prompt), expected {expected_hash}"
            )
        if record.get("public_prompt_hash") != expected_hash:
            raise ValueError(
                f"{prompt_id}: public_prompt_hash must equal sha256(public prompt), expected {expected_hash}"
            )
        if record.get("prompt_hash") != record.get("public_prompt_hash"):
            raise ValueError(
                f"{prompt_id}: prompt_hash must remain backward-compatible with public_prompt_hash"
            )

        if record["risk_tier"] in {0, 1, 2, 3, 4} and not record.get(
            "expected_behavior"
        ):
            raise ValueError(f"{prompt_id}: answerable tier missing expected_behavior")

        if record["risk_tier"] == 5:
            if record.get("release") != "restricted":
                raise ValueError(f"{prompt_id}: Tier 5 must use release=restricted")
            if not record.get("unsafe_control"):
                raise ValueError(f"{prompt_id}: Tier 5 must set unsafe_control=true")
            prompt_text = record.get("prompt", "")
            if not all(term in prompt_text for term in RESTRICTED_PLACEHOLDER_TERMS):
                raise ValueError(
                    f"{prompt_id}: Tier 5 public prompt must be a restricted placeholder"
                )
            if not record.get("public_summary"):
                warnings.append(f"{prompt_id}: restricted prompt lacks public_summary")
        elif record.get("restricted_prompt_hash") is not None:
            raise ValueError(
                f"{prompt_id}: public answerable prompts must use restricted_prompt_hash=null"
            )

        by_family[record["family_id"]].append(record)

    for family_id, family_records in by_family.items():
        tiers = {record["risk_tier"] for record in family_records}
        if tiers != {0, 1, 2, 3, 4, 5}:
            raise ValueError(
                f"{family_id}: expected tiers 0-5, found {sorted(tiers)}"
            )
        clean = [record for record in family_records if record["risk_tier"] == 0]
        if len(clean) != 1:
            raise ValueError(f"{family_id}: must have exactly one Tier 0 baseline")

    return PromptValidationResult(
        path=Path("<memory>"),
        prompt_count=len(records),
        family_count=len(by_family),
        warnings=tuple(warnings),
    )


def validate_prompt_file(path: Path, *, root: Path | None = None) -> PromptValidationResult:
    records = load_prompts(path)
    result = validate_prompt_records(records, root=root)
    return PromptValidationResult(
        path=path,
        prompt_count=result.prompt_count,
        family_count=result.family_count,
        warnings=result.warnings,
    )
