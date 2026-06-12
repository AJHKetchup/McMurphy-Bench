"""Prompt execution loop with mock adapters."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .adapters import adapter_for_model, adapter_requires_live, config_value
from .prompts import load_prompts, validate_prompt_records
from .schema import BENCHMARK_VERSION, SCHEMA_VERSION, validate_record


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_run_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def config_root(config_path: Path) -> Path:
    resolved = config_path.resolve()
    for candidate in (resolved.parent, *resolved.parent.parents):
        if (candidate / "pyproject.toml").exists() and (
            candidate / "data" / "schema.json"
        ).exists():
            return candidate.resolve()
    return resolved.parent.resolve()


def resolve_config_path(root: Path, value: str | None, default: str) -> Path:
    raw = Path(value or default)
    return raw if raw.is_absolute() else (root / raw).resolve()


def make_run_id() -> str:
    return "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def manifest_pricing(config: dict[str, Any]) -> dict[str, Any]:
    pricing = config.get("pricing") or {}
    return {
        "estimated_input_tokens": pricing.get("estimated_input_tokens"),
        "estimated_output_tokens": pricing.get("estimated_output_tokens"),
        "estimated_cost_usd": pricing.get("estimated_cost_usd"),
        "pricing_notes": pricing.get("pricing_notes"),
    }


def count_by_tier(prompts: list[dict[str, Any]]) -> dict[str, int]:
    counts = {str(tier): 0 for tier in range(6)}
    for prompt in prompts:
        tier = str(int(prompt["risk_tier"]))
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def prompt_ids(prompts: list[dict[str, Any]]) -> list[str]:
    return [str(prompt["prompt_id"]) for prompt in prompts]


def run_models(config_path: Path) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    config_path = config_path.resolve()
    config = load_run_config(config_path)
    root = config_root(config_path)
    prompt_set = resolve_config_path(root, config.get("prompt_set"), "data/seed_prompts.jsonl")
    output_root = resolve_config_path(root, config.get("output_dir"), "reports")
    prompts = load_prompts(prompt_set)
    allow_incomplete_families = bool(config.get("allow_incomplete_families", False))
    validate_prompt_records(
        prompts,
        root=root,
        allow_incomplete_families=allow_incomplete_families,
    )

    run_id = config.get("run_id") or make_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    models = config.get("models") or [
        {"name": "mock_good", "provider": "mock", "adapter": "mock_good"},
        {"name": "mock_suppressed", "provider": "mock", "adapter": "mock_suppressed"},
        {"name": "mock_unsafe", "provider": "mock", "adapter": "mock_unsafe"},
    ]
    mode = config.get("evaluation_mode", "controlled_api")
    created_at = utc_now()
    audit_config = {
        "sample_rate": float(config.get("audit", {}).get("sample_rate", 0.15)),
        "seed": int(config.get("audit", {}).get("seed", 1729)),
    }
    try:
        prompt_set_manifest_path = str(prompt_set.relative_to(root))
        prompt_set_is_repo_relative = True
    except ValueError:
        prompt_set_manifest_path = str(prompt_set)
        prompt_set_is_repo_relative = False
    include_restricted_controls = bool(config.get("include_restricted_controls", False))

    responses: list[dict[str, Any]] = []
    skipped_prompt_ids_by_model: dict[str, list[str]] = {}
    run_prompts_by_model: dict[str, list[dict[str, Any]]] = {}
    for model in models:
        adapter_name = str(model.get("adapter", model["name"]))
        adapter = adapter_for_model(root, config, model)
        model_prompts = prompts
        if adapter_requires_live(adapter_name) and not include_restricted_controls:
            model_prompts = [
                prompt for prompt in prompts if int(prompt["risk_tier"]) != 5
            ]
        selected_prompt_ids = set(prompt_ids(model_prompts))
        skipped_prompts = [
            prompt for prompt in prompts if prompt["prompt_id"] not in selected_prompt_ids
        ]
        run_prompts_by_model[str(model["name"])] = model_prompts
        skipped_prompt_ids_by_model[str(model["name"])] = sorted(
            prompt_ids(skipped_prompts)
        )

        for prompt in model_prompts:
            result = adapter.generate(prompt, config, model)
            response = {
                "record_type": "model_response",
                "schema_version": SCHEMA_VERSION,
                "created_at_utc": created_at,
                "run_id": run_id,
                "model": model["name"],
                "provider": model.get("provider", "mock"),
                "model_version": model.get("model_version", model.get("model")),
                "mode": mode,
                "prompt_id": prompt["prompt_id"],
                "family_id": prompt["family_id"],
                "domain": prompt["domain"],
                "risk_tier": prompt["risk_tier"],
                "variant": prompt["variant"],
                "prompt_hash": prompt["prompt_hash"],
                "response_hash": sha256_text(result.raw_response),
                "system_prompt_hash": None,
                "temperature": config_value(config, model, "temperature", 0),
                "top_p": config_value(config, model, "top_p", 1),
                "max_tokens": config_value(config, model, "max_tokens", 512),
                "timestamp_utc": created_at,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "raw_response": result.raw_response,
                "visible_refusal": result.visible_refusal,
                "visible_fallback": result.visible_fallback,
                "fallback_model": result.fallback_model,
                "provider_metadata": result.provider_metadata,
            }
            validate_record(response, root=root)
            responses.append(response)

    skipped_prompt_ids = sorted(
        {
            prompt_id
            for model_skipped in skipped_prompt_ids_by_model.values()
            for prompt_id in model_skipped
        }
    )
    run_prompts = [
        prompt for prompt in prompts if prompt["prompt_id"] not in set(skipped_prompt_ids)
    ]
    model_prompt_counts = {
        model_name: {
            "run_prompt_count": len(model_prompts),
            "skipped_prompt_count": len(skipped_prompt_ids_by_model[model_name]),
            "skipped_prompt_ids": skipped_prompt_ids_by_model[model_name],
            "run_prompt_count_by_tier": count_by_tier(model_prompts),
        }
        for model_name, model_prompts in sorted(run_prompts_by_model.items())
    }

    manifest = {
        "record_type": "run_manifest",
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": created_at,
        "benchmark_version": BENCHMARK_VERSION,
        "package_version": __version__,
        "prompt_set": prompt_set_manifest_path,
        "prompt_set_is_repo_relative": prompt_set_is_repo_relative,
        "prompt_set_sha256": file_sha256(prompt_set),
        "allow_incomplete_families": allow_incomplete_families,
        "include_restricted_controls": include_restricted_controls,
        "restricted_controls_excluded": bool(skipped_prompt_ids),
        "skipped_prompt_count": len(skipped_prompt_ids),
        "skipped_prompt_ids": skipped_prompt_ids,
        "run_prompt_count": len(run_prompts),
        "prompt_count_by_tier": count_by_tier(prompts),
        "run_prompt_count_by_tier": count_by_tier(run_prompts),
        "model_prompt_counts": model_prompt_counts,
        "models": models,
        "evaluation_mode": mode,
        "judge": config.get("judge", {"type": "mock"}),
        "audit": audit_config,
        "scoring_weights": config.get("scoring", {}).get("mli_weights", {}),
        "notes": config.get("notes", ""),
        **manifest_pricing(config),
    }
    validate_record(manifest, root=root)

    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    with (run_dir / "responses.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for response in responses:
            handle.write(json.dumps(response, ensure_ascii=False) + "\n")

    return run_dir, responses, manifest
