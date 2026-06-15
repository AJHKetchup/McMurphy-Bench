"""Command-line interface for McMurphy-Bench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from .audit import audit_agreement, create_audit_sample
from .boundary import boundary_score
from .corpus_lock import verify_corpus_lock, write_corpus_lock
from .finalize import finalize_run, report_run
from .inventory import write_prompt_inventory
from .judge import judge_run, load_responses, write_judgment_template
from .prompts import (
    load_prompts,
    make_prompt_subset,
    parse_tier_list,
    validate_prompt_file,
)
from .report import write_report
from .run import config_root, load_run_config, resolve_config_path, run_models
from .schema import repository_root
from .score import DEFAULT_MLI_WEIGHTS, print_table, read_judgments, score_all


def load_weights(config_path: Path | None) -> dict[str, float] | None:
    if config_path is None:
        return None
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return config.get("scoring", {}).get("mli_weights")


def command_validate_prompts(args: argparse.Namespace) -> int:
    result = validate_prompt_file(
        Path(args.prompt_file),
        allow_incomplete_families=bool(args.allow_incomplete_families),
    )
    print(
        f"Validated {result.prompt_count} prompts across {result.family_count} families."
    )
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return 0


def command_make_subset(args: argparse.Namespace) -> int:
    input_path = Path(args.prompt_file)
    records = load_prompts(input_path)
    tiers = parse_tier_list(str(args.tiers))
    subset = make_prompt_subset(
        records,
        family_count=int(args.families),
        tiers=tiers,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in subset:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(
        f"Wrote {len(subset)} prompts across {args.families} families "
        f"for tiers {','.join(str(tier) for tier in tiers)} to {out_path}"
    )
    return 0


def command_prompt_inventory(args: argparse.Namespace) -> int:
    inventory = write_prompt_inventory(Path(args.prompt_file), Path(args.out))
    print(
        "Inventory: "
        f"{inventory['total_prompt_count']} prompts, "
        f"{inventory['category_count']} categories, "
        f"{inventory['ladder_count']} ladders."
    )
    print(f"Wrote {args.out}")
    return 0


def command_corpus_lock(args: argparse.Namespace) -> int:
    lock = write_corpus_lock(
        Path(args.prompt_file),
        Path(args.inventory),
        Path(args.out),
    )
    print(f"Wrote corpus lock to {args.out}")
    print(f"prompt_file_sha256: {lock['prompt_file_sha256']}")
    print(f"inventory_file_sha256: {lock['inventory_file_sha256']}")
    return 0


def command_verify_corpus_lock(args: argparse.Namespace) -> int:
    lock = verify_corpus_lock(Path(args.lock_file))
    print(f"Verified corpus lock: {args.lock_file}")
    print(f"prompt_file_sha256: {lock['prompt_file_sha256']}")
    print(f"inventory_file_sha256: {lock['inventory_file_sha256']}")
    return 0


def command_score(args: argparse.Namespace) -> int:
    rows = read_judgments(
        Path(args.input), allow_template_records=bool(args.allow_template_records)
    )
    weights = load_weights(Path(args.config)) if args.config else None
    report = score_all(
        rows,
        mli_weights=weights,
        allow_template_records=bool(args.allow_template_records),
    )
    print_table(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote {out}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    run_dir, responses, _manifest = run_models(Path(args.config))
    print(f"Wrote {len(responses)} responses to {run_dir / 'responses.jsonl'}")
    return 0


def command_judge(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = load_run_config(config_path)
    root = config_root(config_path)
    if not config.get("run_dir"):
        raise SystemExit("judge config must include run_dir")
    run_dir = resolve_config_path(root, config["run_dir"], "reports/run_example")
    prompt_set = resolve_config_path(root, config.get("prompt_set"), "data/seed_prompts.jsonl")
    judgments = judge_run(
        run_dir, prompt_set, judge_config=config.get("judge", {"type": "mock"}), root=root
    )
    print(f"Wrote {len(judgments)} judgments to {run_dir / 'judgments.jsonl'}")
    return 0


def load_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def resolve_audit_prompt_set(run_dir: Path, manifest: dict[str, Any]) -> Path:
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


def command_audit(args: argparse.Namespace) -> int:
    path = Path(args.input).resolve()
    run_dir = path.parent if path.name == "report.json" else path
    if not run_dir.is_dir():
        raise SystemExit(f"Audit input must be a run directory or report.json: {path}")

    manifest_path = run_dir / "manifest.json"
    responses_path = run_dir / "responses.jsonl"
    judgments_path = run_dir / "judgments.jsonl"
    for required in (manifest_path, responses_path, judgments_path):
        if not required.exists():
            raise SystemExit(f"Audit input missing required file: {required}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompt_set = resolve_audit_prompt_set(run_dir, manifest)
    prompts = load_prompts(prompt_set)
    responses = load_responses(responses_path, root=repository_root(run_dir))
    judgments = load_jsonl_dicts(judgments_path)
    manifest_audit = manifest.get("audit", {})
    sample_rate = (
        float(args.sample_rate)
        if args.sample_rate is not None
        else float(manifest_audit.get("sample_rate", 0.15))
    )
    seed = (
        int(args.seed)
        if args.seed is not None
        else int(manifest_audit.get("seed", 1729))
    )
    csv_path, jsonl_path = create_audit_sample(
        run_dir,
        prompts,
        responses,
        judgments,
        sample_rate=sample_rate,
        seed=seed,
    )
    print(f"Wrote audit sample CSV to {csv_path}")
    print(f"Wrote audit sample JSONL to {jsonl_path}")
    return 0


def command_audit_agreement(args: argparse.Namespace) -> int:
    print(json.dumps(audit_agreement(Path(args.completed_csv)), indent=2))
    return 0


def harmful_controls_measured(report: dict[str, Any]) -> bool:
    return any(
        bool(model["metrics"].get("unsafe_fulfillment_measured"))
        for model in report.get("models", [])
    )


def command_finalize_run(args: argparse.Namespace) -> int:
    result = finalize_run(
        Path(args.run_dir),
        Path(args.judgments),
        float(args.audit_sample_rate),
        int(args.audit_seed),
        allow_partial=bool(args.allow_partial_judgments),
    )
    report = result["report"]
    coverage = result["coverage"]
    print_table(report)
    print()
    print(f"run_id: {result['run_id']}")
    print(f"judged responses: {coverage['judged_response_count']}")
    print(f"total responses: {coverage['total_response_count']}")
    print(f"judgment coverage complete: {str(coverage['complete']).lower()}")
    print(f"report: {result['report_path']}")
    print(f"audit CSV: {result['audit_csv_path']}")
    print(f"audit JSONL: {result['audit_jsonl_path']}")
    print(f"harmful controls measured: {str(harmful_controls_measured(report)).lower()}")
    return 0


def command_report_run(args: argparse.Namespace) -> int:
    result = report_run(
        Path(args.run_dir),
        audit=bool(args.audit),
        audit_sample_rate=float(args.audit_sample_rate),
        audit_seed=int(args.audit_seed),
    )
    print_table(result["report"])
    print(f"\nWrote report to {result['report_path']}")
    if args.audit:
        print(f"Wrote audit sample CSV to {result['audit_csv_path']}")
        print(f"Wrote audit sample JSONL to {result['audit_jsonl_path']}")
    return 0


def command_boundary_score(args: argparse.Namespace) -> int:
    report = boundary_score(Path(args.run_dir), Path(args.prompts), Path(args.out))
    print(f"Wrote boundary report to {args.out}")
    print(f"missing responses: {report['missing_response_count']}")
    return 0


def command_judgment_template(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    manifest_path = run_dir / "manifest.json"
    responses_path = run_dir / "responses.jsonl"
    for required in (manifest_path, responses_path):
        if not required.exists():
            raise SystemExit(f"Judgment template input missing required file: {required}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompt_set = resolve_audit_prompt_set(run_dir, manifest)
    records = write_judgment_template(
        run_dir,
        prompt_set,
        Path(args.out),
        include_response=bool(args.include_response),
        root=repository_root(run_dir),
    )
    print(f"Wrote {len(records)} judgment template records to {args.out}")
    return 0


def command_loop(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = load_run_config(config_path)
    root = config_root(config_path)
    prompt_set = resolve_config_path(root, config.get("prompt_set"), "data/seed_prompts.jsonl")
    prompts = load_prompts(prompt_set)
    validate_prompt_file(
        prompt_set,
        root=root,
        allow_incomplete_families=bool(config.get("allow_incomplete_families", False)),
    )

    run_dir, responses, manifest = run_models(config_path)
    judgments = judge_run(
        run_dir, prompt_set, judge_config=config.get("judge", {"type": "mock"}), root=root
    )
    rows = read_judgments(run_dir / "judgments.jsonl")
    weights = config.get("scoring", {}).get("mli_weights") or DEFAULT_MLI_WEIGHTS
    report = write_report(
        rows,
        run_dir / "report.json",
        mli_weights=weights,
        include_ci=True,
        manifest=manifest,
    )
    manifest_audit = manifest.get("audit", {})
    sample_rate = float(manifest_audit.get("sample_rate", 0.15))
    seed = int(manifest_audit.get("seed", 1729))
    create_audit_sample(
        run_dir,
        prompts,
        responses,
        judgments,
        sample_rate=sample_rate,
        seed=seed,
    )
    print_table(report)
    print(f"\nWrote run bundle to {run_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcmurphy")
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate-prompts")
    validate.add_argument("prompt_file")
    validate.add_argument("--allow-incomplete-families", action="store_true")
    validate.set_defaults(func=command_validate_prompts)

    subset = subcommands.add_parser("make-subset")
    subset.add_argument("prompt_file")
    subset.add_argument("--families", type=int, required=True)
    subset.add_argument("--tiers", default="0,1,2,3,4")
    subset.add_argument("--out", required=True)
    subset.set_defaults(func=command_make_subset)

    inventory = subcommands.add_parser("prompt-inventory")
    inventory.add_argument("prompt_file")
    inventory.add_argument("--out", required=True)
    inventory.set_defaults(func=command_prompt_inventory)

    corpus_lock = subcommands.add_parser("corpus-lock")
    corpus_lock.add_argument("prompt_file")
    corpus_lock.add_argument("--inventory", required=True)
    corpus_lock.add_argument("--out", required=True)
    corpus_lock.set_defaults(func=command_corpus_lock)

    verify_lock = subcommands.add_parser("verify-corpus-lock")
    verify_lock.add_argument("lock_file")
    verify_lock.set_defaults(func=command_verify_corpus_lock)

    score = subcommands.add_parser("score")
    score.add_argument("input")
    score.add_argument("--out")
    score.add_argument("--config")
    score.add_argument("--allow-template-records", action="store_true")
    score.set_defaults(func=command_score)

    run = subcommands.add_parser("run")
    run.add_argument("config")
    run.set_defaults(func=command_run)

    judge = subcommands.add_parser("judge")
    judge.add_argument("config")
    judge.set_defaults(func=command_judge)

    audit = subcommands.add_parser("audit")
    audit.add_argument("input")
    audit.add_argument("--sample-rate", type=float)
    audit.add_argument("--seed", type=int)
    audit.set_defaults(func=command_audit)

    audit_agree = subcommands.add_parser("audit-agreement")
    audit_agree.add_argument("completed_csv")
    audit_agree.set_defaults(func=command_audit_agreement)

    finalize_parser = subcommands.add_parser("finalize-run")
    finalize_parser.add_argument("run_dir")
    finalize_parser.add_argument("--judgments", required=True)
    finalize_parser.add_argument("--audit-sample-rate", type=float, default=0.20)
    finalize_parser.add_argument("--audit-seed", type=int, default=1729)
    finalize_parser.add_argument("--allow-partial-judgments", action="store_true")
    finalize_parser.set_defaults(func=command_finalize_run)

    report_parser = subcommands.add_parser("report-run")
    report_parser.add_argument("run_dir")
    report_parser.add_argument("--audit", action="store_true")
    report_parser.add_argument("--audit-sample-rate", type=float, default=0.20)
    report_parser.add_argument("--audit-seed", type=int, default=1729)
    report_parser.set_defaults(func=command_report_run)

    boundary_parser = subcommands.add_parser("boundary-score")
    boundary_parser.add_argument("run_dir")
    boundary_parser.add_argument("--prompts", required=True)
    boundary_parser.add_argument("--out", required=True)
    boundary_parser.set_defaults(func=command_boundary_score)

    judgment_template = subcommands.add_parser("judgment-template")
    judgment_template.add_argument("run_dir")
    judgment_template.add_argument("--out", required=True)
    judgment_template.add_argument("--include-response", action="store_true")
    judgment_template.set_defaults(func=command_judgment_template)

    loop = subcommands.add_parser("loop")
    loop.add_argument("config")
    loop.set_defaults(func=command_loop)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
