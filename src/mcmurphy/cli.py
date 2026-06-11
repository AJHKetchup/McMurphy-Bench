"""Command-line interface for McMurphy-Bench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from .audit import audit_agreement, create_audit_sample
from .judge import judge_run
from .prompts import load_prompts, validate_prompt_file
from .report import write_report
from .run import load_run_config, run_models
from .score import DEFAULT_MLI_WEIGHTS, print_table, read_judgments, score_all


def load_weights(config_path: Path | None) -> dict[str, float] | None:
    if config_path is None:
        return None
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return config.get("scoring", {}).get("mli_weights")


def command_validate_prompts(args: argparse.Namespace) -> int:
    result = validate_prompt_file(Path(args.prompt_file))
    print(
        f"Validated {result.prompt_count} prompts across {result.family_count} families."
    )
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return 0


def command_score(args: argparse.Namespace) -> int:
    rows = read_judgments(Path(args.input))
    weights = load_weights(Path(args.config)) if args.config else None
    report = score_all(rows, mli_weights=weights)
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
    config_path = Path(args.config)
    config = load_run_config(config_path)
    root = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    run_dir = Path(config["run_dir"]).resolve() if config.get("run_dir") else None
    if run_dir is None:
        raise SystemExit("judge config must include run_dir")
    prompt_set = (root / config.get("prompt_set", "data/seed_prompts.jsonl")).resolve()
    judgments = judge_run(run_dir, prompt_set)
    print(f"Wrote {len(judgments)} judgments to {run_dir / 'judgments.jsonl'}")
    return 0


def command_audit(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if path.name == "report.json":
        print("Audit samples are produced by mcmurphy loop. Use audit-agreement for completed samples.")
        return 0
    summary = audit_agreement(path)
    print(json.dumps(summary, indent=2))
    return 0


def command_audit_agreement(args: argparse.Namespace) -> int:
    print(json.dumps(audit_agreement(Path(args.completed_csv)), indent=2))
    return 0


def command_loop(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_run_config(config_path)
    root = config_path.parent.parent if config_path.parent.name == "configs" else Path.cwd()
    prompt_set = (root / config.get("prompt_set", "data/seed_prompts.jsonl")).resolve()
    prompts = load_prompts(prompt_set)
    validate_prompt_file(prompt_set, root=root)

    run_dir, responses, manifest = run_models(config_path)
    judgments = judge_run(run_dir, prompt_set)
    rows = read_judgments(run_dir / "judgments.jsonl")
    weights = config.get("scoring", {}).get("mli_weights") or DEFAULT_MLI_WEIGHTS
    report = write_report(
        rows,
        run_dir / "report.json",
        mli_weights=weights,
        include_ci=True,
        manifest=manifest,
    )
    sample_rate = float(config.get("audit", {}).get("sample_rate", 0.15))
    create_audit_sample(
        run_dir,
        prompts,
        responses,
        judgments,
        sample_rate=sample_rate,
        seed=int(config.get("audit", {}).get("seed", 1729)),
    )
    print_table(report)
    print(f"\nWrote run bundle to {run_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcmurphy")
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate-prompts")
    validate.add_argument("prompt_file")
    validate.set_defaults(func=command_validate_prompts)

    score = subcommands.add_parser("score")
    score.add_argument("input")
    score.add_argument("--out")
    score.add_argument("--config")
    score.set_defaults(func=command_score)

    run = subcommands.add_parser("run")
    run.add_argument("config")
    run.set_defaults(func=command_run)

    judge = subcommands.add_parser("judge")
    judge.add_argument("config")
    judge.set_defaults(func=command_judge)

    audit = subcommands.add_parser("audit")
    audit.add_argument("input")
    audit.add_argument("--sample-rate", type=float, default=0.15)
    audit.set_defaults(func=command_audit)

    audit_agree = subcommands.add_parser("audit-agreement")
    audit_agree.add_argument("completed_csv")
    audit_agree.set_defaults(func=command_audit_agreement)

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

