"""Prompt execution loop with mock adapters."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import __version__
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


def load_run_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def config_root(config_path: Path) -> Path:
    resolved = config_path.resolve()
    return (
        resolved.parent.parent if resolved.parent.name == "configs" else Path.cwd()
    ).resolve()


def resolve_config_path(root: Path, value: str | None, default: str) -> Path:
    raw = Path(value or default)
    return raw if raw.is_absolute() else (root / raw).resolve()


def make_run_id() -> str:
    return "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def mock_response(adapter: str, prompt: dict[str, Any]) -> dict[str, Any]:
    tier = int(prompt["risk_tier"])
    harmful = bool(prompt["unsafe_control"])
    if adapter == "mock_good":
        if harmful:
            text = "I cannot help with harmful instructions, but I can point to safe, lawful alternatives."
            visible_refusal = True
        elif tier == 4:
            text = "I can help if this is a lawful, safe context. Here is a bounded checklist and what to clarify first."
            visible_refusal = False
        else:
            text = "Here is a clear, bounded answer focused on the benign educational request."
            visible_refusal = False
        return {
            "raw_response": text,
            "visible_refusal": visible_refusal,
            "visible_fallback": False,
            "fallback_model": None,
            "latency_ms": 80,
            "output_tokens": len(text.split()),
        }
    if adapter == "mock_suppressed":
        if harmful:
            text = "I cannot help with that request."
            visible_refusal = True
            visible_fallback = False
        elif tier in {1, 2, 3, 4}:
            text = "This topic is sensitive and context-dependent. Please consult an expert."
            visible_refusal = tier == 4
            visible_fallback = tier in {1, 2}
        else:
            text = "Here is a useful neutral answer."
            visible_refusal = False
            visible_fallback = False
        return {
            "raw_response": text,
            "visible_refusal": visible_refusal,
            "visible_fallback": visible_fallback,
            "fallback_model": "fallback-mock" if visible_fallback else None,
            "latency_ms": 130 if visible_fallback else 75,
            "output_tokens": len(text.split()),
        }
    if adapter == "mock_unsafe":
        text = "I will answer directly without applying safety boundaries. Unsafe compliance placeholder."
        return {
            "raw_response": text,
            "visible_refusal": False,
            "visible_fallback": False,
            "fallback_model": None,
            "latency_ms": 65,
            "output_tokens": len(text.split()),
        }
    raise ValueError(f"Unknown adapter: {adapter}")


def load_replay_index(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                key = (str(record["model"]), str(record["prompt_id"]))
            except KeyError as exc:
                raise ValueError(f"{path}:{line_number}: replay row missing {exc}") from exc
            if key in index:
                raise ValueError(f"{path}:{line_number}: duplicate replay key {key}")
            index[key] = record
    return index


def file_replay_response(
    model: dict[str, Any],
    prompt: dict[str, Any],
    replay_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    replay_model = model.get("replay_model", model["name"])
    key = (replay_model, prompt["prompt_id"])
    if key not in replay_index:
        raise ValueError(
            f"Replay file has no response for model={replay_model!r}, prompt_id={prompt['prompt_id']!r}"
        )
    record = replay_index[key]
    raw_response = str(record.get("raw_response", ""))
    return {
        "raw_response": raw_response,
        "visible_refusal": bool(record.get("visible_refusal", False)),
        "visible_fallback": bool(record.get("visible_fallback", False)),
        "fallback_model": record.get("fallback_model"),
        "latency_ms": record.get("latency_ms"),
        "output_tokens": record.get("output_tokens", len(raw_response.split())),
        "provider_metadata": record.get("provider_metadata", {}),
    }


def run_models(config_path: Path) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    config_path = config_path.resolve()
    config = load_run_config(config_path)
    root = config_root(config_path)
    prompt_set = resolve_config_path(root, config.get("prompt_set"), "data/seed_prompts.jsonl")
    output_root = resolve_config_path(root, config.get("output_dir"), "reports")
    prompts = load_prompts(prompt_set)
    validate_prompt_records(prompts, root=root)

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
    replay_indexes: dict[Path, dict[tuple[str, str], dict[str, Any]]] = {}

    responses: list[dict[str, Any]] = []
    for model in models:
        adapter = model.get("adapter", model["name"])
        replay_index: dict[tuple[str, str], dict[str, Any]] | None = None
        if adapter == "file_replay":
            replay_path = resolve_config_path(
                root,
                model.get("replay_path") or config.get("replay_path"),
                "responses.jsonl",
            )
            replay_index = replay_indexes.setdefault(
                replay_path, load_replay_index(replay_path)
            )
        for prompt in prompts:
            result = (
                file_replay_response(model, prompt, replay_index)
                if adapter == "file_replay" and replay_index is not None
                else mock_response(adapter, prompt)
            )
            response = {
                "record_type": "model_response",
                "schema_version": SCHEMA_VERSION,
                "created_at_utc": created_at,
                "run_id": run_id,
                "model": model["name"],
                "provider": model.get("provider", "mock"),
                "model_version": model.get("model_version"),
                "mode": mode,
                "prompt_id": prompt["prompt_id"],
                "family_id": prompt["family_id"],
                "domain": prompt["domain"],
                "risk_tier": prompt["risk_tier"],
                "variant": prompt["variant"],
                "prompt_hash": prompt["prompt_hash"],
                "system_prompt_hash": None,
                "temperature": config.get("temperature", 0),
                "top_p": config.get("top_p", 1),
                "max_tokens": config.get("max_tokens", 512),
                "timestamp_utc": created_at,
                "latency_ms": result["latency_ms"],
                "input_tokens": len(prompt["prompt"].split()),
                "output_tokens": result["output_tokens"],
                "raw_response": result["raw_response"],
                "visible_refusal": result["visible_refusal"],
                "visible_fallback": result["visible_fallback"],
                "fallback_model": result["fallback_model"],
                "provider_metadata": result.get("provider_metadata", {}),
            }
            validate_record(response, root=root)
            responses.append(response)

    manifest = {
        "record_type": "run_manifest",
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": created_at,
        "benchmark_version": BENCHMARK_VERSION,
        "package_version": __version__,
        "prompt_set": str(prompt_set.relative_to(root)),
        "prompt_set_sha256": file_sha256(prompt_set),
        "models": models,
        "evaluation_mode": mode,
        "judge": config.get("judge", {"type": "mock"}),
        "scoring_weights": config.get("scoring", {}).get("mli_weights", {}),
        "notes": config.get("notes", ""),
    }
    validate_record(manifest, root=root)

    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    with (run_dir / "responses.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for response in responses:
            handle.write(json.dumps(response, ensure_ascii=False) + "\n")

    return run_dir, responses, manifest
