"""Finalize completed external judgments into audited run reports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import create_audit_sample
from .judge import (
    load_responses,
    parse_bool,
    parse_float,
    parse_optional_bool,
    parse_optional_int,
)
from .prompts import load_prompts
from .report import write_report
from .schema import SCHEMA_VERSION, repository_root, validate_record
from .score import DEFAULT_MLI_WEIGHTS, Judgment, judgment_from_mapping


def load_completed_judgments(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        return records
    raise ValueError(f"Unsupported judgment input format: {path.suffix}")


def resolve_prompt_set(run_dir: Path, manifest: dict[str, Any]) -> Path:
    prompt_set = Path(manifest["prompt_set"])
    if prompt_set.is_absolute():
        return prompt_set
    if manifest.get("prompt_set_is_repo_relative") is True:
        candidate = repository_root(run_dir) / prompt_set
        if candidate.exists():
            return candidate.resolve()
    candidates = [
        run_dir.parent.parent / prompt_set,
        repository_root(run_dir) / prompt_set,
        Path.cwd().resolve() / prompt_set,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Could not resolve prompt_set={manifest['prompt_set']!r} for {run_dir}"
    )


def field_is_provided(record: dict[str, Any], field: str) -> bool:
    return field in record and record[field] not in (None, "")


def compare_value(field: str, value: Any) -> Any:
    if field in {"answerable", "is_harmful_control"}:
        return parse_bool(value)
    if field == "risk_tier":
        return int(value)
    return str(value)


def check_or_fill_field(
    record: dict[str, Any],
    field: str,
    expected: Any,
    *,
    model: str,
    prompt_id: str,
) -> None:
    if field_is_provided(record, field):
        actual = compare_value(field, record[field])
        normalized_expected = compare_value(field, expected)
        if actual != normalized_expected:
            raise ValueError(
                f"Judgment field mismatch for {field}: expected "
                f"{normalized_expected!r}, actual {actual!r}, "
                f"model={model!r}, prompt_id={prompt_id!r}"
            )
    record[field] = expected


def parse_status(record: dict[str, Any], *, model: str, prompt_id: str) -> str:
    status = str(record.get("judgment_status") or "completed").strip().lower()
    if status == "template":
        raise ValueError(
            "template records are not completed judgments: "
            f"model={model!r}, prompt_id={prompt_id!r}"
        )
    if status != "completed":
        raise ValueError(
            f"invalid judgment_status {status!r}: "
            f"model={model!r}, prompt_id={prompt_id!r}"
        )
    return "completed"


def normalize_completed_judgment(
    record: dict[str, Any],
    response: dict[str, Any],
    prompt: dict[str, Any],
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    normalized = dict(record)
    model = str(response["model"])
    prompt_id = str(response["prompt_id"])
    normalized["record_type"] = normalized.get("record_type") or "judgment"
    normalized["schema_version"] = str(
        normalized.get("schema_version") or SCHEMA_VERSION
    )
    normalized["judgment_status"] = parse_status(
        normalized, model=model, prompt_id=prompt_id
    )
    normalized["created_at_utc"] = str(
        normalized.get("created_at_utc")
        or response.get("created_at_utc")
        or manifest.get("created_at_utc")
        or ""
    )

    expected_fields = {
        "run_id": response["run_id"],
        "model": response["model"],
        "prompt_id": response["prompt_id"],
        "family_id": response["family_id"],
        "domain": response["domain"],
        "risk_tier": response["risk_tier"],
        "variant": response["variant"],
        "prompt_hash": response.get("prompt_hash") or prompt["prompt_hash"],
        "response_hash": response["response_hash"],
        "answerable": not bool(prompt["unsafe_control"]),
        "is_harmful_control": bool(prompt["unsafe_control"]),
    }
    for field, expected in expected_fields.items():
        check_or_fill_field(
            normalized, field, expected, model=model, prompt_id=prompt_id
        )

    usefulness = parse_float(normalized.get("usefulness_score"))
    normalized["usefulness_score"] = usefulness
    normalized["unsafe_score"] = parse_float(normalized.get("unsafe_score"))
    for field in (
        "directness_score",
        "specificity_score",
        "completeness_score",
        "correctness_score",
        "boundary_calibration_score",
    ):
        normalized[field] = parse_float(normalized.get(field), usefulness)
    normalized["disclaimer_load_score"] = parse_float(
        normalized.get("disclaimer_load_score"), 1.0
    )
    normalized["refusal_class"] = str(normalized.get("refusal_class") or "").upper()
    normalized["fallback_status"] = str(
        normalized.get("fallback_status") or "NONE"
    ).upper()
    normalized["clarification_success"] = parse_optional_bool(
        normalized.get("clarification_success")
    )
    normalized["degradation_evidence_class"] = str(
        normalized.get("degradation_evidence_class") or "UNSUPPORTED"
    ).upper()
    normalized["turn_index"] = parse_optional_int(normalized.get("turn_index"))
    normalized["judge_id"] = str(normalized.get("judge_id") or "")
    normalized["judge_version"] = str(normalized.get("judge_version") or "")
    normalized["rationale"] = str(normalized.get("rationale") or "")

    validate_record(normalized, root=root)
    return normalized


def judgment_key(record: dict[str, Any]) -> tuple[str, str]:
    model = str(record.get("model") or "").strip()
    prompt_id = str(record.get("prompt_id") or "").strip()
    if not model or not prompt_id:
        raise ValueError("completed judgment missing model or prompt_id")
    return (model, prompt_id)


def validate_judgment_coverage(
    judgments: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    response_keys = [
        (str(response["model"]), str(response["prompt_id"]))
        for response in responses
    ]
    response_key_set = set(response_keys)
    judgment_keys = [judgment_key(judgment) for judgment in judgments]
    judgment_counts = Counter(judgment_keys)

    duplicate_keys = sorted(key for key, count in judgment_counts.items() if count > 1)
    extra_keys = sorted(key for key in judgment_counts if key not in response_key_set)
    missing_keys = sorted(
        key for key in response_key_set if judgment_counts.get(key, 0) == 0
    )

    coverage = {
        "complete": not (missing_keys or extra_keys or duplicate_keys),
        "judged_response_count": sum(
            1 for key in response_key_set if judgment_counts.get(key, 0) > 0
        ),
        "total_response_count": len(responses),
        "missing_judgment_count": len(missing_keys),
        "extra_judgment_count": sum(judgment_counts[key] for key in extra_keys),
        "duplicate_judgment_count": sum(
            judgment_counts[key] - 1 for key in duplicate_keys
        ),
    }

    if duplicate_keys:
        key = duplicate_keys[0]
        raise ValueError(
            f"duplicate judgment for model={key[0]!r}, prompt_id={key[1]!r}"
        )
    if extra_keys:
        key = extra_keys[0]
        raise ValueError(
            "judgment for a response that does not exist: "
            f"model={key[0]!r}, prompt_id={key[1]!r}"
        )
    if missing_keys and not allow_partial:
        key = missing_keys[0]
        raise ValueError(
            f"missing judgment for response: model={key[0]!r}, prompt_id={key[1]!r}"
        )
    return coverage


def normalize_completed_judgments_for_run(
    judgment_records: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    coverage: dict[str, Any],
    root: Path | None = None,
) -> list[dict[str, Any]]:
    response_by_key = {
        (str(response["model"]), str(response["prompt_id"])): response
        for response in responses
    }
    prompt_by_id = {str(prompt["prompt_id"]): prompt for prompt in prompts}
    judgment_by_key = {
        judgment_key(judgment): judgment for judgment in judgment_records
    }
    normalized: list[dict[str, Any]] = []
    for response in responses:
        key = (str(response["model"]), str(response["prompt_id"]))
        if key not in judgment_by_key:
            continue
        prompt = prompt_by_id[str(response["prompt_id"])]
        normalized.append(
            normalize_completed_judgment(
                judgment_by_key[key],
                response_by_key[key],
                prompt,
                manifest,
                root=root,
            )
        )
    if coverage["judged_response_count"] != len(normalized):
        raise ValueError(
            "normalized judgment count does not match coverage: "
            f"expected {coverage['judged_response_count']}, actual {len(normalized)}"
        )
    return normalized


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def records_to_rows(records: list[dict[str, Any]]) -> list[Judgment]:
    return [
        judgment_from_mapping(record, row_label=f"judgment {index}")
        for index, record in enumerate(records, start=1)
    ]


def scoring_weights(manifest: dict[str, Any]) -> dict[str, float]:
    weights = manifest.get("scoring_weights") or DEFAULT_MLI_WEIGHTS
    return {key: float(value) for key, value in weights.items()}


def load_run_bundle(
    run_dir: Path,
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], list[dict[str, Any]], Path]:
    manifest_path = run_dir / "manifest.json"
    responses_path = run_dir / "responses.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run directory missing required file: {manifest_path}")
    if not responses_path.exists():
        raise FileNotFoundError(f"Run directory missing required file: {responses_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = repository_root(run_dir)
    prompt_set = resolve_prompt_set(run_dir, manifest)
    prompts = load_prompts(prompt_set)
    responses = load_responses(responses_path, root=root)
    return manifest, prompt_set, prompts, responses, root


def build_report(
    run_dir: Path,
    manifest: dict[str, Any],
    normalized_judgments: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    rows = records_to_rows(normalized_judgments)
    return write_report(
        rows,
        run_dir / "report.json",
        mli_weights=scoring_weights(manifest),
        include_ci=True,
        manifest=manifest,
        judgment_coverage=coverage,
    )


def finalize_run(
    run_dir: Path,
    judgments_path: Path,
    audit_sample_rate: float,
    audit_seed: int,
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest, _prompt_set, prompts, responses, root = load_run_bundle(run_dir)
    raw_judgments = load_completed_judgments(judgments_path)
    coverage = validate_judgment_coverage(
        raw_judgments,
        responses,
        allow_partial=allow_partial,
    )
    normalized = normalize_completed_judgments_for_run(
        raw_judgments,
        responses,
        prompts,
        manifest,
        coverage=coverage,
        root=root,
    )
    write_jsonl(run_dir / "judgments.jsonl", normalized)
    report = build_report(run_dir, manifest, normalized, coverage)
    csv_path, jsonl_path = create_audit_sample(
        run_dir,
        prompts,
        responses,
        normalized,
        sample_rate=audit_sample_rate,
        seed=audit_seed,
    )
    return {
        "run_id": manifest["run_id"],
        "run_dir": run_dir,
        "judgments": normalized,
        "coverage": coverage,
        "report": report,
        "report_path": run_dir / "report.json",
        "audit_csv_path": csv_path,
        "audit_jsonl_path": jsonl_path,
    }


def report_run(
    run_dir: Path,
    *,
    audit: bool = False,
    audit_sample_rate: float = 0.20,
    audit_seed: int = 1729,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    judgments_path = run_dir / "judgments.jsonl"
    if not judgments_path.exists():
        raise FileNotFoundError(f"report-run missing required file: {judgments_path}")
    manifest, _prompt_set, prompts, responses, root = load_run_bundle(run_dir)
    raw_judgments = load_completed_judgments(judgments_path)
    coverage = validate_judgment_coverage(raw_judgments, responses, allow_partial=False)
    normalized = normalize_completed_judgments_for_run(
        raw_judgments,
        responses,
        prompts,
        manifest,
        coverage=coverage,
        root=root,
    )
    report = build_report(run_dir, manifest, normalized, coverage)
    result = {
        "run_id": manifest["run_id"],
        "run_dir": run_dir,
        "judgments": normalized,
        "coverage": coverage,
        "report": report,
        "report_path": run_dir / "report.json",
        "audit_csv_path": None,
        "audit_jsonl_path": None,
    }
    if audit:
        csv_path, jsonl_path = create_audit_sample(
            run_dir,
            prompts,
            responses,
            normalized,
            sample_rate=audit_sample_rate,
            seed=audit_seed,
        )
        result["audit_csv_path"] = csv_path
        result["audit_jsonl_path"] = jsonl_path
    return result
