"""Human audit packet generation and agreement summaries."""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


AUDIT_FIELDS = [
    "run_id",
    "model",
    "prompt_id",
    "family_id",
    "domain",
    "risk_tier",
    "variant",
    "prompt",
    "raw_response",
    "refusal_class",
    "usefulness_score",
    "unsafe_score",
    "rationale",
    "human_refusal_class",
    "human_usefulness_score",
    "human_unsafe_score",
    "human_notes",
    "human_agrees_with_auto_judge",
]


def create_audit_sample(
    run_dir: Path,
    prompts: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    *,
    sample_rate: float = 0.15,
    seed: int = 1729,
) -> tuple[Path, Path]:
    prompt_by_id = {prompt["prompt_id"]: prompt for prompt in prompts}
    response_by_key = {
        (response["model"], response["prompt_id"]): response for response in responses
    }
    rng = random.Random(seed)
    sample_size = max(1, round(len(judgments) * sample_rate))
    sample = rng.sample(judgments, min(sample_size, len(judgments)))

    rows: list[dict[str, Any]] = []
    for judgment in sample:
        response = response_by_key[(judgment["model"], judgment["prompt_id"])]
        prompt = prompt_by_id[judgment["prompt_id"]]
        rows.append(
            {
                "run_id": response["run_id"],
                "model": judgment["model"],
                "prompt_id": judgment["prompt_id"],
                "family_id": judgment["family_id"],
                "domain": judgment["domain"],
                "risk_tier": judgment["risk_tier"],
                "variant": judgment["variant"],
                "prompt": prompt["prompt"],
                "raw_response": response["raw_response"],
                "refusal_class": judgment["refusal_class"],
                "usefulness_score": judgment["usefulness_score"],
                "unsafe_score": judgment["unsafe_score"],
                "rationale": judgment.get("rationale", ""),
                "human_refusal_class": "",
                "human_usefulness_score": "",
                "human_unsafe_score": "",
                "human_notes": "",
                "human_agrees_with_auto_judge": "",
            }
        )

    csv_path = run_dir / "audit_sample.csv"
    jsonl_path = run_dir / "audit_sample.jsonl"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return csv_path, jsonl_path


def audit_agreement(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    completed = [
        row
        for row in rows
        if row.get("human_refusal_class") or row.get("human_agrees_with_auto_judge")
    ]
    if not completed:
        return {
            "completed_rows": 0,
            "agreement_rate": 0.0,
            "mean_absolute_error_usefulness": 0.0,
            "mean_absolute_error_unsafe": 0.0,
            "confusion_matrix_refusal_class": {},
        }

    agreement_values = [
        row.get("human_agrees_with_auto_judge", "").strip().lower()
        in {"true", "1", "yes", "y"}
        for row in completed
        if row.get("human_agrees_with_auto_judge", "").strip()
    ]
    usefulness_errors = [
        abs(float(row["usefulness_score"]) - float(row["human_usefulness_score"]))
        for row in completed
        if row.get("human_usefulness_score", "").strip()
    ]
    unsafe_errors = [
        abs(float(row["unsafe_score"]) - float(row["human_unsafe_score"]))
        for row in completed
        if row.get("human_unsafe_score", "").strip()
    ]
    matrix = Counter(
        (row["refusal_class"], row["human_refusal_class"])
        for row in completed
        if row.get("human_refusal_class")
    )
    return {
        "completed_rows": len(completed),
        "agreement_rate": sum(agreement_values) / len(agreement_values)
        if agreement_values
        else 0.0,
        "mean_absolute_error_usefulness": sum(usefulness_errors)
        / len(usefulness_errors)
        if usefulness_errors
        else 0.0,
        "mean_absolute_error_unsafe": sum(unsafe_errors) / len(unsafe_errors)
        if unsafe_errors
        else 0.0,
        "confusion_matrix_refusal_class": {
            f"{auto}->{human}": count for (auto, human), count in matrix.items()
        },
    }
