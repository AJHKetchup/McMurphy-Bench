"""Prompt corpus inventory helpers."""

from __future__ import annotations

import json
import re
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
    "evidence i would need",
    "strongest version",
    "most aggressive",
    "riskiest options",
    "pushed as far as possible",
    "defend if questioned",
    "what crosses the line",
    "what would cross the line",
    "lawful condition",
    "defensible",
)

SAFETY_TELEGRAPH_PHRASES = (
    "explicit illegal",
    "harmful request",
    "illegal conduct",
    "avoid harm",
    "avoid illegal",
    "cross the boundary",
    "safety boundary",
    "what crosses the line",
    "this is an explicit",
    "compliance artifact",
    "boundary memo",
    "safe boundary",
)

META_BOUNDARY_LANGUAGE_PHRASES = (
    "boundary for",
    "boundary ladder",
    "risk ladder",
    "tier",
    "corpus",
    "benchmark",
)

USER_FACING_BOUNDARY_TERMS = (
    "boundary",
    "risk ladder",
    "tier",
    "benchmark",
    "corpus",
    "explicit illegal",
    "harmful request",
    "cross the line",
    "safety boundary",
    "compliance artifact",
)

JSON_STYLE_PROMPT_PHRASES = (
    "return json only",
    "json only",
)

KEY_SCHEMA_LANGUAGE_PHRASES = (
    "key ",
    "containing exactly",
    "objects",
    "array",
    "required_json",
    "unsupported_items",
    "pressure_positions",
    "gray_zone_items",
    "lawful_steps",
    "reference_points",
    "completion_check",
)

BENCHMARK_BOILERPLATE_PHRASES = (
    "do not ask follow-up questions",
    "don't ask follow-up questions",
    "completion_check",
    "risk ladder",
    "tier",
    "boundary",
    "benchmark",
    "corpus",
)

VAGUE_TASK_PHRASES = (
    "practical checklist",
    "concise reference summary",
    "pressure points",
    "boundary memo",
    "reference artifact",
    "lawful steps",
    "gray-zone items",
    "pressure positions",
    "include the limit",
    "where the support runs out",
)

ABSTRACT_FIELD_NAME_PHRASES = (
    "reference_points",
    "lawful_steps",
    "optimization_options",
    "gray_zone_items",
    "pressure_positions",
    "boundary_positions",
    "safe_boundary",
    "allowed_limit",
    "unsupported_move",
    "what_crosses_the_line",
)

JSON_HOMEWORK_STYLE_PHRASES = (
    "return json only with key",
    "containing exactly",
    "each object must have keys",
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


def _contains_any_wordlike(value: str, phrases: tuple[str, ...]) -> bool:
    lowered = value.casefold()
    return any(_phrase_present(lowered, phrase.casefold()) for phrase in phrases)


def _phrase_present(value: str, phrase: str) -> bool:
    if " " in phrase:
        return phrase in value
    return re.search(rf"\b{re.escape(phrase)}\b", value) is not None


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
        lowered = prompt.casefold()
        has_evidence_requirement = "evidence" in lowered
        has_pressure = any(marker in lowered for marker in TIER4_PRESSURE_MARKERS)
        if _contains_any(prompt, TEMPLATE_PROMPT_PHRASES) or not (
            has_evidence_requirement and has_pressure
        ):
            ids.append(str(record.get("prompt_id")))
            continue
        if not has_pressure:
            ids.append(str(record.get("prompt_id")))
    return sorted(ids)


def missing_concrete_facts_ids(records: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    terminal_tier = terminal_tier_for(records)
    for record in records:
        if int(record.get("risk_tier", -1)) == terminal_tier:
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
    terminal_tier = terminal_tier_for(records)
    for record in records:
        if int(record.get("risk_tier", -1)) == terminal_tier:
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


def safety_telegraph_prompt_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(record.get("prompt_id"))
        for record in records
        if _contains_any(str(record.get("prompt", "")), SAFETY_TELEGRAPH_PHRASES)
    )


def meta_boundary_language_prompt_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(record.get("prompt_id"))
        for record in records
        if _contains_any_wordlike(
            str(record.get("prompt", "")),
            META_BOUNDARY_LANGUAGE_PHRASES,
        )
    )


def is_v0_4_corpus(records: list[dict[str, Any]]) -> bool:
    return any("boundary_v0.4" in str(record.get("task_intent", "")) for record in records)


def is_v0_5_corpus(records: list[dict[str, Any]]) -> bool:
    return any("boundary_v0.5" in str(record.get("task_intent", "")) for record in records)


def is_v0_6_corpus(records: list[dict[str, Any]]) -> bool:
    return any("boundary_v0.6" in str(record.get("task_intent", "")) for record in records)


def is_v0_6_clarity_corpus(records: list[dict[str, Any]]) -> bool:
    return any(
        "boundary_v0.6 clarity" in str(record.get("task_intent", ""))
        for record in records
    )


def is_naturalistic_corpus(records: list[dict[str, Any]]) -> bool:
    return is_v0_4_corpus(records) or is_v0_5_corpus(records) or is_v0_6_corpus(records)


def terminal_tier_for(records: list[dict[str, Any]]) -> int:
    return 6 if is_v0_5_corpus(records) or is_v0_6_corpus(records) else 5


def _scenario_lines(record: dict[str, Any]) -> str:
    prompt = str(record.get("prompt", ""))
    selected: list[str] = []
    for line in prompt.splitlines():
        lowered = line.casefold()
        if lowered.startswith(("user:", "situation:", "jurisdiction:", "time period:")):
            selected.append(" ".join(line.casefold().split()))
    return " ".join(selected)


def _scenario_key_for_ladder(records: list[dict[str, Any]]) -> str:
    tier0 = next(
        (record for record in records if int(record.get("risk_tier", -1)) == 0),
        records[0],
    )
    return _scenario_lines(tier0)


def duplicate_scenario_ladders(records: list[dict[str, Any]]) -> list[str]:
    by_ladder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_ladder[_ladder_id_for(record)].append(record)

    ladders_by_key: dict[str, list[str]] = defaultdict(list)
    for ladder_id, ladder_records in by_ladder.items():
        ladders_by_key[_scenario_key_for_ladder(ladder_records)].append(ladder_id)

    return sorted(
        ladder_id
        for ladder_ids in ladders_by_key.values()
        if len(ladder_ids) > 1
        for ladder_id in ladder_ids
    )


def _tokens(value: str) -> set[str]:
    return {
        token.strip(".,;:!?()[]{}\"'")
        for token in value.casefold().split()
        if len(token.strip(".,;:!?()[]{}\"'")) > 3
    }


def over_similar_ladder_ids(records: list[dict[str, Any]]) -> list[str]:
    by_ladder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_ladder[_ladder_id_for(record)].append(record)

    scenario_by_ladder = {
        ladder_id: _scenario_key_for_ladder(ladder_records)
        for ladder_id, ladder_records in by_ladder.items()
    }
    category_by_ladder = {
        ladder_id: _category_for(ladder_records[0])
        for ladder_id, ladder_records in by_ladder.items()
    }
    flagged: set[str] = set()
    ladder_ids = sorted(scenario_by_ladder)
    for index, left in enumerate(ladder_ids):
        for right in ladder_ids[index + 1 :]:
            if category_by_ladder[left] != category_by_ladder[right]:
                continue
            left_tokens = _tokens(scenario_by_ladder[left])
            right_tokens = _tokens(scenario_by_ladder[right])
            if not left_tokens or not right_tokens:
                continue
            similarity = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
            if similarity >= 0.92:
                flagged.update({left, right})
    return sorted(flagged)


def user_facing_boundary_term_prompt_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(record.get("prompt_id"))
        for record in records
        if _contains_any_wordlike(
            str(record.get("prompt", "")),
            USER_FACING_BOUNDARY_TERMS,
        )
    )


def prompt_ids_with_phrases(
    records: list[dict[str, Any]],
    phrases: tuple[str, ...],
) -> list[str]:
    return sorted(
        str(record.get("prompt_id"))
        for record in records
        if _contains_any_wordlike(str(record.get("prompt", "")), phrases)
    )


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

    inventory = {
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
    if is_naturalistic_corpus(records):
        safety_ids = safety_telegraph_prompt_ids(records)
        meta_ids = meta_boundary_language_prompt_ids(records)
        duplicate_ladders = duplicate_scenario_ladders(records)
        similar_ladders = over_similar_ladder_ids(records)
        inventory.update(
            {
                "safety_telegraph_count": len(safety_ids),
                "safety_telegraph_prompt_ids": safety_ids,
                "meta_boundary_language_count": len(meta_ids),
                "meta_boundary_language_prompt_ids": meta_ids,
                "duplicate_scenario_count": len(duplicate_ladders),
                "duplicate_scenario_ladders": duplicate_ladders,
                "over_similar_ladder_count": len(similar_ladders),
                "over_similar_ladder_ids": similar_ladders,
            }
        )
    if is_v0_5_corpus(records) or is_v0_6_corpus(records):
        user_facing_ids = user_facing_boundary_term_prompt_ids(records)
        terminal_ids = sorted(
            str(record.get("prompt_id"))
            for record in records
            if int(record.get("risk_tier", -1)) == 6
        )
        tier5_ids = sorted(
            str(record.get("prompt_id"))
            for record in records
            if int(record.get("risk_tier", -1)) == 5
        )
        inventory.update(
            {
                "structured_tier_counts": {
                    str(tier): tier_counts.get(str(tier), 0)
                    for tier in range(6)
                },
                "terminal_control_count": sum(
                    1
                    for record in records
                    if int(record.get("risk_tier", -1)) == 6
                    and bool(record.get("unsafe_control"))
                ),
                "tier6_count": tier_counts.get("6", 0),
                "tier5_structured_count": sum(
                    1
                    for record in records
                    if int(record.get("risk_tier", -1)) == 5
                    and isinstance(record.get("completion_check"), dict)
                    and record["completion_check"].get("check_type") != "manual_or_llm"
                ),
                "terminal_control_prompt_ids": terminal_ids,
                "tier5_prompt_ids": tier5_ids,
                "user_facing_boundary_term_count": len(user_facing_ids),
                "user_facing_boundary_term_prompt_ids": user_facing_ids,
            }
        )
    if is_v0_6_corpus(records):
        json_style_ids = prompt_ids_with_phrases(records, JSON_STYLE_PROMPT_PHRASES)
        key_schema_ids = prompt_ids_with_phrases(records, KEY_SCHEMA_LANGUAGE_PHRASES)
        boilerplate_ids = prompt_ids_with_phrases(records, BENCHMARK_BOILERPLATE_PHRASES)
        non_natural_ids = set(json_style_ids) | set(key_schema_ids) | set(boilerplate_ids)
        contract_ids = sorted(
            str(record.get("prompt_id"))
            for record in records
            if isinstance(record.get("scoring_contract"), dict)
        )
        inventory.update(
            {
                "json_style_prompt_count": len(json_style_ids),
                "json_style_prompt_ids": json_style_ids,
                "key_schema_language_count": len(key_schema_ids),
                "key_schema_language_prompt_ids": key_schema_ids,
                "benchmark_boilerplate_count": len(boilerplate_ids),
                "benchmark_boilerplate_prompt_ids": boilerplate_ids,
                "natural_prompt_count": len(records) - len(non_natural_ids),
                "natural_prompt_ids": sorted(
                    str(record.get("prompt_id"))
                    for record in records
                    if str(record.get("prompt_id")) not in non_natural_ids
                ),
                "scoring_contract_count": len(contract_ids),
                "scoring_contract_prompt_ids": contract_ids,
            }
        )
    if is_v0_6_clarity_corpus(records):
        vague_ids = prompt_ids_with_phrases(records, VAGUE_TASK_PHRASES)
        abstract_ids = prompt_ids_with_phrases(records, ABSTRACT_FIELD_NAME_PHRASES)
        homework_ids = prompt_ids_with_phrases(records, JSON_HOMEWORK_STYLE_PHRASES)
        non_clarity_ids = set(vague_ids) | set(abstract_ids) | set(homework_ids)
        inventory.update(
            {
                "vague_task_count": len(vague_ids),
                "vague_task_prompt_ids": vague_ids,
                "abstract_field_name_count": len(abstract_ids),
                "abstract_field_name_prompt_ids": abstract_ids,
                "json_homework_style_count": len(homework_ids),
                "json_homework_style_prompt_ids": homework_ids,
                "natural_prompt_clarity_count": len(records) - len(non_clarity_ids),
            }
        )
    return inventory


def write_prompt_inventory(prompt_path: Path, out_path: Path) -> dict[str, Any]:
    inventory = build_prompt_inventory(load_prompts(prompt_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory
