"""Blind prompt-audit helpers for the Boundary v0.6 clarity prototype."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .adapters import adapter_for_model, config_value
from .clarity_cases import RowSupport, case_specs_by_id
from .objective import evaluate_scoring_contract, try_parse_json
from .outcomes import classify_outcome
from .prompts import load_prompts, validate_prompt_records
from .run import (
    config_root,
    load_run_config,
    resolve_config_path,
    sha256_text,
    utc_now,
)
from .schema import SCHEMA_VERSION, repository_root, validate_record


REVIEW_FIELDS = (
    "user_goal_in_my_words",
    "required_rows",
    "exact_decision_required",
    "contested_item_if_any",
    "contested_item_support_status",
    "ideal_good_answer_summary",
    "unsafe_answer_would_include",
    "over_refusal_would_include",
    "missing_context_yes_no",
    "ambiguous_row_yes_no",
    "answer_leak_yes_no",
    "prompt_quality_decision: approve / revise / reject",
)

SMOKE_REVIEW_COLUMNS = (
    "prompt_id",
    "model",
    "parsed_json_success",
    "outcome",
    "completion_pass",
    "failure_reasons",
    "prompt",
    "raw_response",
    "reviewer_decision",
    "reviewer_notes",
)


def support_by_row(case_id: str) -> dict[str, RowSupport]:
    spec = case_specs_by_id().get(case_id)
    if spec is None:
        return {}
    return {support.row: support for support in spec.row_support}


def _fact_present(prompt: str, support: RowSupport) -> bool:
    return any(fact in prompt for fact in support.facts)


def _first_present_index(prompt: str, values: tuple[str, ...]) -> int | None:
    indexes = [prompt.find(value) for value in values if value and prompt.find(value) >= 0]
    return min(indexes) if indexes else None


def row_fact_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    specs = case_specs_by_id()
    missing_flags: list[dict[str, str]] = []
    ambiguous_flags: list[dict[str, str]] = []
    premature_flags: list[dict[str, str]] = []
    hidden_boundary_flags: list[dict[str, str]] = []
    name_mismatch_flags: list[dict[str, str]] = []
    outside_expertise_flags: list[dict[str, str]] = []
    covered_prompt_ids: list[str] = []

    for record in records:
        prompt_id = str(record.get("prompt_id"))
        prompt = str(record.get("prompt", ""))
        tier = int(record.get("risk_tier", -1))
        spec = specs.get(str(record.get("family_id")))
        if spec is None:
            missing_flags.append(
                {
                    "prompt_id": prompt_id,
                    "row": "<case_spec>",
                    "reason": "missing case spec for row audit",
                }
            )
            continue

        support_map = {support.row: support for support in spec.row_support}
        prompt_has_row_problem = False
        for row in spec.required_rows:
            support = support_map.get(row)
            if row not in prompt:
                name_mismatch_flags.append(
                    {
                        "prompt_id": prompt_id,
                        "row": row,
                        "reason": "required row name not found in prompt",
                    }
                )
                prompt_has_row_problem = True
                continue
            if support is None:
                missing_flags.append(
                    {
                        "prompt_id": prompt_id,
                        "row": row,
                        "reason": "required row has no row_support entry",
                    }
                )
                prompt_has_row_problem = True
                continue
            if not _fact_present(prompt, support):
                missing_flags.append(
                    {
                        "prompt_id": prompt_id,
                        "row": row,
                        "reason": "supporting fact not present in prompt",
                    }
                )
                prompt_has_row_problem = True
            if not support.status:
                ambiguous_flags.append(
                    {
                        "prompt_id": prompt_id,
                        "row": row,
                        "reason": "row support status is empty",
                    }
                )
                prompt_has_row_problem = True
            if support.outside_expertise_required:
                outside_expertise_flags.append(
                    {
                        "prompt_id": prompt_id,
                        "row": row,
                        "reason": "row marked as requiring outside expertise",
                    }
                )
                prompt_has_row_problem = True

        contested_support = support_map.get(spec.contested_item)
        if contested_support is not None and spec.contested_item in prompt:
            item_index = prompt.find(spec.contested_item)
            support_index = _first_present_index(
                prompt,
                contested_support.facts + (spec.contested_item_missing_support,),
            )
            if support_index is None:
                if tier <= 4:
                    hidden_boundary_flags.append(
                        {
                            "prompt_id": prompt_id,
                            "row": spec.contested_item,
                            "reason": "lower-tier prompt names contested item without support facts",
                        }
                    )
                    prompt_has_row_problem = True
            elif item_index >= 0 and item_index < support_index:
                premature_flags.append(
                    {
                        "prompt_id": prompt_id,
                        "row": spec.contested_item,
                        "reason": "contested item appears before support facts",
                    }
                )
                prompt_has_row_problem = True

        if not prompt_has_row_problem:
            covered_prompt_ids.append(prompt_id)

    return {
        "row_fact_coverage_count": len(covered_prompt_ids),
        "row_fact_coverage_prompt_ids": sorted(covered_prompt_ids),
        "missing_row_fact_count": len(missing_flags) + len(name_mismatch_flags),
        "missing_row_fact_flags": missing_flags + name_mismatch_flags,
        "ambiguous_row_fact_count": len(ambiguous_flags) + len(outside_expertise_flags),
        "ambiguous_row_fact_flags": ambiguous_flags + outside_expertise_flags,
        "contested_item_premature_count": len(premature_flags),
        "contested_item_premature_flags": premature_flags,
        "lower_tier_hidden_boundary_count": len(hidden_boundary_flags),
        "lower_tier_hidden_boundary_flags": hidden_boundary_flags,
    }


def write_blind_prompt_audit(prompt_file: Path, out_path: Path) -> dict[str, Any]:
    records = load_prompts(prompt_file)
    audit = row_fact_audit(records)
    lines = [
        "# Blind Prompt Audit",
        "",
        "Reviewer sees only prompt_id and model-facing prompt text. Fill this packet without using any hidden benchmark metadata.",
        "",
        "## Row-Level Audit Counters",
        "",
    ]
    for key in (
        "row_fact_coverage_count",
        "missing_row_fact_count",
        "ambiguous_row_fact_count",
        "contested_item_premature_count",
        "lower_tier_hidden_boundary_count",
    ):
        lines.append(f"- {key}: {audit[key]}")

    lines.append("")
    lines.append("## Prompts")
    for record in records:
        lines.extend(
            [
                "",
                f"### {record['prompt_id']}",
                "",
                "```text",
                str(record["prompt"]),
                "```",
                "",
                "Reviewer fields:",
            ]
        )
        lines.extend(f"- {field}:" for field in REVIEW_FIELDS)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return audit


def _model_config_from_smoke_args(
    config_path: Path | None,
    model_name: str | None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if config_path is None:
        return (
            repository_root(),
            {"evaluation_mode": "controlled_api", "temperature": 0, "top_p": 1, "max_tokens": 800},
            {"name": "mock_good", "provider": "mock", "adapter": "mock_good"},
        )

    config_path = config_path.resolve()
    root = config_root(config_path)
    config = load_run_config(config_path)
    models = config.get("models") or []
    if not models:
        raise ValueError(f"Smoke config has no models: {config_path}")
    if model_name:
        selected = next(
            (model for model in models if str(model.get("name")) == model_name),
            None,
        )
        if selected is None:
            raise ValueError(f"Smoke config has no model named {model_name!r}")
    else:
        selected = models[0]
    return root, config, selected


def run_smoke(
    prompt_file: Path,
    out_dir: Path,
    *,
    limit: int,
    config_path: Path | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    root, run_config, model_config = _model_config_from_smoke_args(config_path, model_name)
    prompts = load_prompts(prompt_file)
    validate_prompt_records(prompts, root=root, allow_incomplete_families=True)
    selected_prompts = prompts[:limit]
    adapter = adapter_for_model(root, run_config, model_config)

    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = out_dir.name or "smoke_run"
    created_at = utc_now()
    model = str(model_config["name"])
    provider = str(model_config.get("provider", "mock"))
    responses: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []

    for prompt in selected_prompts:
        adapter_response = adapter.generate(prompt, run_config, model_config)
        response = {
            "record_type": "model_response",
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": created_at,
            "run_id": run_id,
            "model": model,
            "provider": provider,
            "model_version": model_config.get("model_version", model_config.get("model")),
            "mode": str(run_config.get("evaluation_mode", "controlled_api")),
            "prompt_id": prompt["prompt_id"],
            "family_id": prompt["family_id"],
            "domain": prompt["domain"],
            "risk_tier": prompt["risk_tier"],
            "variant": prompt["variant"],
            "prompt_hash": prompt["prompt_hash"],
            "response_hash": sha256_text(adapter_response.raw_response),
            "system_prompt_hash": None,
            "temperature": config_value(run_config, model_config, "temperature", 0),
            "top_p": config_value(run_config, model_config, "top_p", 1),
            "max_tokens": config_value(run_config, model_config, "max_tokens", 800),
            "timestamp_utc": created_at,
            "latency_ms": adapter_response.latency_ms,
            "input_tokens": adapter_response.input_tokens,
            "output_tokens": adapter_response.output_tokens,
            "raw_response": adapter_response.raw_response,
            "visible_refusal": adapter_response.visible_refusal,
            "visible_fallback": adapter_response.visible_fallback,
            "fallback_model": adapter_response.fallback_model,
            "provider_metadata": adapter_response.provider_metadata,
        }
        validate_record(response, root=root)
        completion = (
            evaluate_scoring_contract(prompt, response["raw_response"])
            if prompt.get("scoring_contract")
            else None
        )
        parsed_json, parsed_ok = try_parse_json(response["raw_response"])
        outcome = classify_outcome(prompt, response, completion)
        responses.append(response)
        result_rows.append(
            {
                "prompt_id": prompt["prompt_id"],
                "model": model,
                "parsed_json_success": parsed_ok and parsed_json is not None,
                "outcome": outcome,
                "completion_pass": bool(completion and completion.get("completion_pass")),
                "failure_reasons": completion.get("failure_reasons", []) if completion else [],
                "prompt": prompt["prompt"],
                "raw_response": response["raw_response"],
            }
        )

    (out_dir / "responses.jsonl").write_text(
        "".join(json.dumps(response, ensure_ascii=False) + "\n" for response in responses),
        encoding="utf-8",
    )
    (out_dir / "smoke_results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in result_rows),
        encoding="utf-8",
    )
    with (out_dir / "manual_review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SMOKE_REVIEW_COLUMNS)
        writer.writeheader()
        for row in result_rows:
            writer.writerow(
                {
                    **row,
                    "failure_reasons": ";".join(row["failure_reasons"]),
                    "reviewer_decision": "",
                    "reviewer_notes": "",
                }
            )

    manifest = {
        "run_id": run_id,
        "prompt_file": str(prompt_file),
        "prompt_count": len(selected_prompts),
        "model": model,
        "provider": provider,
        "created_at_utc": created_at,
        "config_path": str(config_path) if config_path else None,
        "outputs": [
            "responses.jsonl",
            "smoke_results.jsonl",
            "manual_review.csv",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return {
        "out_dir": out_dir,
        "response_count": len(responses),
        "manual_review_csv": out_dir / "manual_review.csv",
        "responses_jsonl": out_dir / "responses.jsonl",
        "smoke_results_jsonl": out_dir / "smoke_results.jsonl",
    }
