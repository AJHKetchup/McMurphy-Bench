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
    }


def write_prompt_inventory(prompt_path: Path, out_path: Path) -> dict[str, Any]:
    inventory = build_prompt_inventory(load_prompts(prompt_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory
