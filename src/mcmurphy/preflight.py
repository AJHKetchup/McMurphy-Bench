"""No-cost run estimation and preflight checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import adapter_requires_live, config_value
from .corpus_lock import verify_corpus_lock
from .prompts import load_prompts, validate_prompt_file
from .run import config_root, load_run_config, resolve_config_path


@dataclass(frozen=True)
class RunEstimate:
    prompt_set: str
    prompt_count: int
    model_count: int
    total_api_calls: int
    include_restricted_controls: bool
    estimated_input_tokens: int
    max_tokens_per_response: str
    estimated_max_output_tokens: int
    pricing_status: str
    input_cost: float | None = None
    max_output_cost: float | None = None
    max_total_cost: float | None = None


def default_models() -> list[dict[str, Any]]:
    return [
        {"name": "mock_good", "provider": "mock", "adapter": "mock_good"},
        {"name": "mock_suppressed", "provider": "mock", "adapter": "mock_suppressed"},
        {"name": "mock_unsafe", "provider": "mock", "adapter": "mock_unsafe"},
    ]


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def selected_prompts_for_model(
    prompts: list[dict[str, Any]],
    config: dict[str, Any],
    model: dict[str, Any],
) -> list[dict[str, Any]]:
    include_restricted_controls = bool(config.get("include_restricted_controls", False))
    adapter_name = str(model.get("adapter", model.get("name", "")))
    if adapter_requires_live(adapter_name) and not include_restricted_controls:
        return [prompt for prompt in prompts if int(prompt["risk_tier"]) != 5]
    return prompts


def estimate_config(config_path: Path) -> RunEstimate:
    config_path = config_path.resolve()
    config = load_run_config(config_path)
    root = config_root(config_path)
    prompt_set_path = resolve_config_path(
        root, config.get("prompt_set"), "data/seed_prompts.jsonl"
    )
    prompts = load_prompts(prompt_set_path)
    models = config.get("models") or default_models()
    max_tokens_values: list[int] = []
    total_calls = 0
    input_tokens = 0
    max_output_tokens = 0
    for model in models:
        selected = selected_prompts_for_model(prompts, config, model)
        model_max_tokens = int(config_value(config, model, "max_tokens", 512))
        max_tokens_values.append(model_max_tokens)
        total_calls += len(selected)
        input_tokens += sum(estimate_tokens(prompt["prompt"]) for prompt in selected)
        max_output_tokens += len(selected) * model_max_tokens

    pricing = config.get("pricing") or {}
    input_price = pricing.get("input_per_1m_tokens_usd")
    output_price = pricing.get("output_per_1m_tokens_usd")
    input_cost = None
    output_cost = None
    total_cost = None
    if input_price is None or output_price is None:
        pricing_status = "Cost not estimated: pricing not configured."
    else:
        input_cost = input_tokens / 1_000_000 * float(input_price)
        output_cost = max_output_tokens / 1_000_000 * float(output_price)
        total_cost = input_cost + output_cost
        pricing_status = "Cost estimated from configured pricing."

    max_tokens_display = (
        str(max_tokens_values[0])
        if len(set(max_tokens_values)) == 1
        else ",".join(str(value) for value in max_tokens_values)
    )
    return RunEstimate(
        prompt_set=str(config.get("prompt_set", "data/seed_prompts.jsonl")),
        prompt_count=len(prompts),
        model_count=len(models),
        total_api_calls=total_calls,
        include_restricted_controls=bool(config.get("include_restricted_controls", False)),
        estimated_input_tokens=input_tokens,
        max_tokens_per_response=max_tokens_display,
        estimated_max_output_tokens=max_output_tokens,
        pricing_status=pricing_status,
        input_cost=input_cost,
        max_output_cost=output_cost,
        max_total_cost=total_cost,
    )


def format_estimate(estimate: RunEstimate) -> str:
    lines = [
        f"prompt_set: {estimate.prompt_set}",
        f"prompt_count: {estimate.prompt_count}",
        f"model_count: {estimate.model_count}",
        f"total_api_calls: {estimate.total_api_calls}",
        f"include_restricted_controls: {str(estimate.include_restricted_controls).lower()}",
        f"estimated_input_tokens: {estimate.estimated_input_tokens}",
        f"max_tokens_per_response: {estimate.max_tokens_per_response}",
        f"estimated_max_output_tokens: {estimate.estimated_max_output_tokens}",
        f"pricing_status: {estimate.pricing_status}",
    ]
    if estimate.max_total_cost is not None:
        lines.extend(
            [
                f"input_cost: {estimate.input_cost:.6f}",
                f"max_output_cost: {estimate.max_output_cost:.6f}",
                f"max_total_cost: {estimate.max_total_cost:.6f}",
            ]
        )
    return "\n".join(lines)


def print_estimate(config_path: Path) -> RunEstimate:
    estimate = estimate_config(config_path)
    print(format_estimate(estimate))
    return estimate


def live_models(config: dict[str, Any]) -> list[dict[str, Any]]:
    models = config.get("models") or default_models()
    live: list[dict[str, Any]] = []
    for model in models:
        adapter_name = str(model.get("adapter", model.get("name", "")))
        if adapter_requires_live(adapter_name) or model.get("live") is True:
            live.append(model)
    return live


def preflight_config(config_path: Path, *, allow_large_run: bool = False) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_run_config(config_path)
    root = config_root(config_path)
    prompt_set_path = resolve_config_path(
        root, config.get("prompt_set"), "data/seed_prompts.jsonl"
    )
    if not prompt_set_path.exists():
        raise FileNotFoundError(f"Prompt file does not exist: {prompt_set_path}")
    validate_prompt_file(
        prompt_set_path,
        root=root,
        allow_incomplete_families=bool(config.get("allow_incomplete_families", False)),
    )
    if config.get("corpus_lock"):
        verify_corpus_lock(resolve_config_path(root, config.get("corpus_lock"), ""))

    warnings: list[str] = []
    live = live_models(config)
    if live and config_path.parent.name == "configs" and config_path.name.endswith(
        ".example.yaml"
    ):
        warnings.append(
            "Live config is an example file; copy it to configs/*.local.yaml before running live APIs."
        )
    for model in live:
        adapter_name = str(model.get("adapter", model.get("name", "")))
        if adapter_requires_live(adapter_name) and model.get("live") is not True:
            raise ValueError(
                f"Live adapter for model {model.get('name')} requires live: true"
            )
        api_key_env = model.get("api_key_env")
        if not api_key_env:
            raise ValueError(
                f"Live model {model.get('name')} must declare api_key_env"
            )
        warnings.append(
            f"Live model {model.get('name')} declares api_key_env={api_key_env}"
        )

    estimate = estimate_config(config_path)
    if estimate.total_api_calls > 100 and not allow_large_run:
        warnings.append(
            f"total_api_calls > 100 ({estimate.total_api_calls}); pass --allow-large-run after reviewing the plan."
        )
    return {"estimate": estimate, "warnings": warnings}


def print_preflight(config_path: Path, *, allow_large_run: bool = False) -> dict[str, Any]:
    result = preflight_config(config_path, allow_large_run=allow_large_run)
    print(format_estimate(result["estimate"]))
    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    print("Preflight complete: no API calls made.")
    return result
