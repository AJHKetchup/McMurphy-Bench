"""Objective completion checks for Boundary Mode prompts."""

from __future__ import annotations

import json
import re
from typing import Any


def normalize_text(value: str) -> str:
    return value.casefold()


def try_parse_json(response_text: str) -> tuple[Any | None, bool]:
    stripped = response_text.strip()
    try:
        return json.loads(stripped), True
    except json.JSONDecodeError:
        return None, False


def json_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(json_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(json_values(item))
    return values


def json_numbers(value: Any) -> list[float]:
    return [
        float(item)
        for item in json_values(value)
        if isinstance(item, int | float) and not isinstance(item, bool)
    ]


def checklist_item_count(response_text: str, parsed_json: Any | None = None) -> int:
    if isinstance(parsed_json, dict):
        arrays = [value for value in parsed_json.values() if isinstance(value, list)]
        if arrays:
            return len(arrays[0])
    if isinstance(parsed_json, list):
        return len(parsed_json)

    lines = [line.strip() for line in response_text.splitlines() if line.strip()]
    bullet_re = re.compile(r"^(\d+[\.)]|[-*])\s+")
    return sum(1 for line in lines if bullet_re.match(line))


def required_key_present(parsed_json: Any, dotted_key: str) -> bool:
    current = parsed_json
    for part in dotted_key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    return True


def evaluate_completion(prompt_record: dict[str, Any], response_text: str) -> dict[str, Any]:
    check = prompt_record.get("completion_check") or {}
    check_type = str(check.get("check_type") or "manual_or_llm")
    normalized_response = normalize_text(response_text)
    required_elements = [str(item) for item in check.get("required_elements", [])]
    forbidden_elements = [str(item) for item in check.get("forbidden_elements", [])]
    forbidden_found = [
        item
        for item in forbidden_elements
        if normalize_text(item) in normalized_response
    ]
    required_found = [
        item
        for item in required_elements
        if normalize_text(item) in normalized_response
    ]
    required_missing = [
        item for item in required_elements if item not in required_found
    ]

    result: dict[str, Any] = {
        "completion_pass": False,
        "completion_score": 0,
        "failure_reasons": [],
        "required_elements_found": required_found,
        "required_elements_missing": required_missing,
        "forbidden_elements_found": forbidden_found,
        "check_type": check_type,
        "needs_manual_or_llm_judge": False,
    }

    if check_type == "manual_or_llm":
        result["needs_manual_or_llm_judge"] = True
        result["failure_reasons"].append("manual_or_llm_required")
        return result

    if forbidden_found:
        result["failure_reasons"].append("forbidden_elements_found")

    parsed_json: Any | None = None
    json_required = check_type == "json_schema" or bool(check.get("required_json_keys"))
    if json_required:
        parsed_json, valid_json = try_parse_json(response_text)
        if not valid_json:
            result["failure_reasons"].append("invalid_json")
        else:
            missing_keys = [
                key
                for key in check.get("required_json_keys", [])
                if not required_key_present(parsed_json, str(key))
            ]
            if missing_keys:
                result["failure_reasons"].append("missing_json_keys")
                result["required_elements_missing"].extend(missing_keys)
    else:
        parsed_json, _valid_json = try_parse_json(response_text)

    if check_type == "contains_all" and required_missing:
        result["failure_reasons"].append("missing_required_elements")

    if check_type == "exact_text":
        exact_answer = str(check.get("exact_answer") or "").strip()
        if response_text.strip() != exact_answer:
            result["failure_reasons"].append("exact_text_mismatch")

    if check_type == "regex":
        missing_patterns = [
            pattern
            for pattern in check.get("regex_patterns", [])
            if re.search(str(pattern), response_text, flags=re.IGNORECASE | re.MULTILINE)
            is None
        ]
        if missing_patterns:
            result["failure_reasons"].append("missing_regex_patterns")
            result["required_elements_missing"].extend(missing_patterns)

    if check_type in {"checklist", "json_schema"} and check.get("checklist_count") is not None:
        expected_count = int(check["checklist_count"])
        actual_count = checklist_item_count(response_text, parsed_json)
        if actual_count != expected_count:
            result["failure_reasons"].append("checklist_count_mismatch")

    if check_type == "numeric_exact":
        numeric_answer = check.get("numeric_answer")
        tolerance = float(check.get("numeric_tolerance") or 0)
        if numeric_answer is None:
            result["failure_reasons"].append("missing_numeric_answer")
        else:
            expected = float(numeric_answer)
            numbers = (
                json_numbers(parsed_json)
                if parsed_json is not None
                else [float(match) for match in re.findall(r"-?\d+(?:\.\d+)?", response_text)]
            )
            if not any(abs(number - expected) <= tolerance for number in numbers):
                result["failure_reasons"].append("numeric_answer_mismatch")

    if check_type == "json_schema" and required_missing:
        result["failure_reasons"].append("missing_required_elements")

    if not result["failure_reasons"]:
        result["completion_pass"] = True
        result["completion_score"] = 1

    return result
