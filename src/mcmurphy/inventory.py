"""Prompt corpus inventory helpers."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .prompts import TIER4_FORBIDDEN_PHRASES, TIER5_OPERATIONAL_PHRASES, load_prompts


EXTRA_TIER4_FORBIDDEN_PHRASES = (
    "help me evade",
    "hide this",
    "fake this",
    "bypass this",
    "commit fraud",
    "acquire illegal weapon",
    "weaponize pathogen",
    "hack without authorization",
)

EXTRA_TIER5_OPERATIONAL_PHRASES = (
    "exploit steps",
    "vendor route",
    "vendor routes",
    "procurement detail",
    "procurement details",
    "concealment method",
    "concealment methods",
    "bypass detail",
    "bypass details",
    "payload",
    "payloads",
    "fake document",
    "fake documents",
    "exact operational implementation",
)

TEMPLATE_PROMPT_PHRASES = (
    "artifact for",
    "boundary for",
    "create a neutral reference artifact",
    "create a clearly lawful real-world assistance artifact",
    "create an aggressive but defensible optimization artifact",
    "create a gray-zone analysis artifact",
    "create the broadest defensible boundary memo for",
)

VAGUE_BASE_GOAL_PHRASES = (
    "boundary",
    "to harmful",
    "to dangerous",
    "to deceptive",
    "to illegal",
)

CONCRETE_FACT_MARKERS = (
    "jurisdiction:",
    "time period:",
    "facts:",
)

TIER4_PRESSURE_MARKERS = (
    "risky interpretation",
    "evidence needed",
    "what crosses the line",
    "what would cross the line",
    "lawful condition",
    "defensible",
)


def _category_for(record: dict[str, Any]) -> str:
    ladder = record.get("risk_ladder") or {}
    return str(ladder.get("category") or "<missing>")


def _ladder_id_for(record: dict[str, Any]) -> str:
    ladder = record.get("risk_ladder") or {}
    return str(ladder.get("ladder_id") or record.get("family_id") or "<missing>")


def _phrase_flags(
    records: list[dict[str, Any]],
    *,
    tier: int,
    phrases: tuple[str, ...],
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    for record in records:
        if int(record.get("risk_tier", -1)) != tier:
            continue
        prompt = str(record.get("prompt", "")).casefold()
        for phrase in phrases:
            if phrase.casefold() in prompt:
                flags.append(
                    {
                        "prompt_id": str(record.get("prompt_id")),
                        "phrase": phrase,
                    }
                )
    return flags


def _contains_any(value: str, phrases: tuple[str, ...]) -> bool:
    lowered = value.casefold()
    return any(phrase.casefold() in lowered for phrase in phrases)


def likely_template_prompt_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(record.get("prompt_id"))
        for record in records
        if _contains_any(str(record.get("prompt", "")), TEMPLATE_PROMPT_PHRASES)
    )


def vague_base_goal_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(record.get("prompt_id"))
        for record in records
        if _contains_any(
            str((record.get("risk_ladder") or {}).get("base_goal", "")),
            VAGUE_BASE_GOAL_PHRASES,
        )
    )


def weak_tier4_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for record in records:
        if int(record.get("risk_tier", -1)) != 4:
            continue
        prompt = str(record.get("prompt", ""))
        if _contains_any(prompt, TEMPLATE_PROMPT_PHRASES) or not all(
            marker in prompt.casefold()
            for marker in ("evidence needed", "what crosses the line")
        ):
            ids.append(str(record.get("prompt_id")))
            continue
        if not any(marker in prompt.casefold() for marker in TIER4_PRESSURE_MARKERS):
            ids.append(str(record.get("prompt_id")))
    return sorted(ids)


def missing_concrete_facts_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for record in records:
        if int(record.get("risk_tier", -1)) == 5:
            continue
        prompt = str(record.get("prompt", ""))
        lowered = prompt.casefold()
        fact_bullets = sum(
            1 for line in prompt.splitlines() if line.strip().startswith("- ")
        )
        if (
            not all(marker in lowered for marker in CONCRETE_FACT_MARKERS)
            or fact_bullets < 3
        ):
            ids.append(str(record.get("prompt_id")))
    return sorted(ids)


def weak_completion_check_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for record in records:
        if int(record.get("risk_tier", -1)) == 5:
            continue
        check = record.get("completion_check")
        if not isinstance(check, dict):
            ids.append(str(record.get("prompt_id")))
            continue
        check_type = str(check.get("check_type") or "")
        if check_type == "json_schema" and not (
            check.get("json_array_key")
            and check.get("array_count") is not None
            and check.get("array_object_required_keys")
        ):
            ids.append(str(record.get("prompt_id")))
        elif check_type == "contains_all":
            ids.append(str(record.get("prompt_id")))
    return sorted(ids)


def build_prompt_inventory(records: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({_category_for(record) for record in records})
    ladder_ids = sorted({_ladder_id_for(record) for record in records})
    prompts_by_category = Counter(_category_for(record) for record in records)
    ladders_by_category: dict[str, set[str]] = defaultdict(set)
    tiers_present_by_ladder: dict[str, set[int]] = defaultdict(set)
    tier_counts: Counter[str] = Counter()
    completion_check_types: Counter[str] = Counter()

    for record in records:
        category = _category_for(record)
        ladder_id = _ladder_id_for(record)
        ladders_by_category[category].add(ladder_id)
        tier = int(record.get("risk_tier", -1))
        tiers_present_by_ladder[ladder_id].add(tier)
        tier_counts[str(tier)] += 1
        check = record.get("completion_check")
        if isinstance(check, dict):
            completion_check_types[str(check.get("check_type") or "<missing>")] += 1

    prompt_id_counts = Counter(str(record.get("prompt_id")) for record in records)
    prompt_hash_counts = Counter(str(record.get("prompt_hash")) for record in records)
    duplicate_prompt_hashes = {
        digest: [
            str(record.get("prompt_id"))
            for record in records
            if str(record.get("prompt_hash")) == digest
        ]
        for digest, count in sorted(prompt_hash_counts.items())
        if count > 1
    }
    template_ids = likely_template_prompt_ids(records)
    vague_ids = vague_base_goal_ids(records)
    weak_tier4_prompt_ids = weak_tier4_ids(records)
    missing_facts_ids = missing_concrete_facts_ids(records)
    weak_check_ids = weak_completion_check_ids(records)

    return {
        "total_prompt_count": len(records),
        "category_count": len(categories),
        "ladder_count": len(ladder_ids),
        "prompts_by_category": dict(sorted(prompts_by_category.items())),
        "ladders_by_category": {
            category: sorted(ladders)
            for category, ladders in sorted(ladders_by_category.items())
        },
        "tiers_present_by_ladder": {
            ladder_id: sorted(tiers)
            for ladder_id, tiers in sorted(tiers_present_by_ladder.items())
        },
        "tier_counts": dict(sorted(tier_counts.items(), key=lambda item: int(item[0]))),
        "completion_check_types": dict(sorted(completion_check_types.items())),
        "missing_completion_check_count": sum(
            1 for record in records if not record.get("completion_check")
        ),
        "tier5_count": sum(1 for record in records if int(record.get("risk_tier", -1)) == 5),
        "tier5_operational_phrase_flags": _phrase_flags(
            records,
            tier=5,
            phrases=TIER5_OPERATIONAL_PHRASES + EXTRA_TIER5_OPERATIONAL_PHRASES,
        ),
        "tier4_forbidden_phrase_flags": _phrase_flags(
            records,
            tier=4,
            phrases=TIER4_FORBIDDEN_PHRASES + EXTRA_TIER4_FORBIDDEN_PHRASES,
        ),
        "duplicate_prompt_ids": sorted(
            prompt_id for prompt_id, count in prompt_id_counts.items() if count > 1
        ),
        "duplicate_prompt_hashes": duplicate_prompt_hashes,
        "likely_template_prompt_count": len(template_ids),
        "likely_template_prompt_ids": template_ids,
        "vague_base_goal_count": len(vague_ids),
        "vague_base_goal_ids": vague_ids,
        "weak_tier4_count": len(weak_tier4_prompt_ids),
        "weak_tier4_ids": weak_tier4_prompt_ids,
        "missing_concrete_facts_count": len(missing_facts_ids),
        "missing_concrete_facts_ids": missing_facts_ids,
        "weak_completion_check_count": len(weak_check_ids),
        "weak_completion_check_ids": weak_check_ids,
    }


def write_prompt_inventory(prompt_path: Path, out_path: Path) -> dict[str, Any]:
    inventory = build_prompt_inventory(load_prompts(prompt_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory
