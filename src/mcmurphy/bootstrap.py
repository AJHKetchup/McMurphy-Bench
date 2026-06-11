"""Bootstrap confidence intervals for matched prompt-family metrics."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Callable

from .score import Judgment, score_model


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_metric_ci(
    rows: list[Judgment],
    metric_fn: Callable[[list[Judgment]], float],
    *,
    n_boot: int = 1000,
    seed: int = 1729,
    confidence: float = 0.95,
) -> dict[str, float]:
    by_family: dict[str, list[Judgment]] = defaultdict(list)
    for row in rows:
        by_family[row.family_id].append(row)
    families = list(by_family)
    if not families:
        return {"low": 0.0, "mid": 0.0, "high": 0.0}

    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(n_boot):
        sampled_rows: list[Judgment] = []
        for _ in families:
            family_id = rng.choice(families)
            sampled_rows.extend(by_family[family_id])
        estimates.append(metric_fn(sampled_rows))

    alpha = (1.0 - confidence) / 2.0
    return {
        "low": round(percentile(estimates, alpha), 4),
        "mid": round(metric_fn(rows), 4),
        "high": round(percentile(estimates, 1.0 - alpha), 4),
    }


def default_confidence_intervals(
    rows: list[Judgment],
    *,
    mli_weights: dict[str, float] | None = None,
    n_boot: int = 300,
    seed: int = 1729,
) -> dict[str, dict[str, float]]:
    def mli(sample: list[Judgment]) -> float:
        return float(
            score_model(sample, mli_weights=mli_weights)["metrics"][
                "model_lobotomy_index"
            ]
        )

    def false_refusal(sample: list[Judgment]) -> float:
        return float(
            score_model(sample, mli_weights=mli_weights)["metrics"][
                "false_refusal_rate"
            ]
        )

    def paired_degradation(sample: list[Judgment]) -> float:
        return float(
            score_model(sample, mli_weights=mli_weights)["metrics"][
                "paired_degradation_score"
            ]
        )

    return {
        "model_lobotomy_index": bootstrap_metric_ci(
            rows, mli, n_boot=n_boot, seed=seed
        ),
        "false_refusal_rate": bootstrap_metric_ci(
            rows, false_refusal, n_boot=n_boot, seed=seed + 1
        ),
        "paired_degradation_score": bootstrap_metric_ci(
            rows, paired_degradation, n_boot=n_boot, seed=seed + 2
        ),
    }
