"""Report generation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bootstrap import default_confidence_intervals
from .score import Judgment, score_all


def write_report(
    rows: list[Judgment],
    output_path: Path,
    *,
    mli_weights: dict[str, float] | None = None,
    include_ci: bool = False,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ci_fn = (
        (lambda model_rows: default_confidence_intervals(model_rows, mli_weights=mli_weights))
        if include_ci
        else None
    )
    report = score_all(rows, mli_weights=mli_weights, confidence_interval_fn=ci_fn)
    if manifest:
        report["run_manifest"] = {
            "run_id": manifest.get("run_id"),
            "created_at_utc": manifest.get("created_at_utc"),
            "benchmark_version": manifest.get("benchmark_version"),
            "prompt_set": manifest.get("prompt_set"),
            "prompt_set_sha256": manifest.get("prompt_set_sha256"),
            "include_restricted_controls": manifest.get("include_restricted_controls"),
            "restricted_controls_excluded": manifest.get("restricted_controls_excluded"),
            "skipped_prompt_count": manifest.get("skipped_prompt_count"),
            "skipped_prompt_ids": manifest.get("skipped_prompt_ids"),
            "run_prompt_count": manifest.get("run_prompt_count"),
            "prompt_count_by_tier": manifest.get("prompt_count_by_tier"),
            "run_prompt_count_by_tier": manifest.get("run_prompt_count_by_tier"),
            "model_prompt_counts": manifest.get("model_prompt_counts"),
            "evaluation_mode": manifest.get("evaluation_mode"),
            "judge": manifest.get("judge"),
            "audit": manifest.get("audit"),
            "estimated_input_tokens": manifest.get("estimated_input_tokens"),
            "estimated_output_tokens": manifest.get("estimated_output_tokens"),
            "estimated_cost_usd": manifest.get("estimated_cost_usd"),
            "pricing_notes": manifest.get("pricing_notes"),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
