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
            "evaluation_mode": manifest.get("evaluation_mode"),
            "judge": manifest.get("judge"),
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
