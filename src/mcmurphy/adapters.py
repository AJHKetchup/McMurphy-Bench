"""Provider adapter interfaces and built-in adapter implementations."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MOCK_ADAPTERS = {"mock_good", "mock_suppressed", "mock_unsafe"}
NON_LIVE_ADAPTERS = MOCK_ADAPTERS | {"file_replay"}


@dataclass(frozen=True)
class AdapterResponse:
    raw_response: str
    visible_refusal: bool
    visible_fallback: bool
    fallback_model: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    provider_metadata: dict[str, Any]


class ModelAdapter:
    def generate(
        self,
        prompt_record: dict[str, Any],
        run_config: dict[str, Any],
        model_config: dict[str, Any],
    ) -> AdapterResponse:
        raise NotImplementedError


def resolve_config_path(root: Path, value: str | None, default: str) -> Path:
    raw = Path(value or default)
    return raw if raw.is_absolute() else (root / raw).resolve()


def adapter_requires_live(adapter_name: str) -> bool:
    return adapter_name not in NON_LIVE_ADAPTERS


def config_value(
    run_config: dict[str, Any],
    model_config: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    return model_config.get(key, run_config.get(key, default))


def set_dotted_value(record: dict[str, Any], dotted_key: str, value: Any) -> None:
    current = record
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def safe_text_for_key(key: str, index: int = 0) -> str:
    label = key.replace("_", " ")
    return f"{label} safe bounded item {index + 1}"


def boundary_array_item(
    required_keys: list[str],
    required_elements: list[str],
    index: int,
) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key in required_keys:
        if key in {"strategy", "category", "question"} and index < len(required_elements):
            item[key] = required_elements[index]
        elif key.startswith("what_crosses") or "unacceptable" in key:
            item[key] = "Actions outside legal, safe, or authorized boundaries would cross the line."
        else:
            item[key] = safe_text_for_key(key, index)
    return item


def boundary_completion_response(prompt_record: dict[str, Any]) -> str:
    check = prompt_record.get("completion_check") or {}
    check_type = str(check.get("check_type") or "manual_or_llm")
    required_elements = [str(item) for item in (check.get("required_elements") or [])]

    if check_type == "checklist":
        count = int(check.get("checklist_count") or len(required_elements) or 1)
        items = list(required_elements)
        while len(items) < count:
            items.append(f"safe bounded checklist item {len(items) + 1}")
        return "\n".join(f"- {item}" for item in items[:count])

    data: dict[str, Any] = {}
    for key in check.get("required_json_keys") or []:
        key = str(key)
        if check.get("json_array_key") == key:
            continue
        if check.get("checklist_count") is not None and key in {
            "red_flags",
            "safer_alternatives",
        }:
            count = int(check.get("checklist_count") or 1)
            data[key] = [safe_text_for_key(key, index) for index in range(count)]
        else:
            set_dotted_value(data, key, safe_text_for_key(key))

    array_key = check.get("json_array_key")
    if array_key:
        count = int(
            check.get("array_count")
            or check.get("checklist_count")
            or len(required_elements)
            or 1
        )
        required_keys = [
            str(key) for key in (check.get("array_object_required_keys") or [])
        ]
        if not required_keys:
            required_keys = ["item"]
        set_dotted_value(
            data,
            str(array_key),
            [
                boundary_array_item(required_keys, required_elements, index)
                for index in range(count)
            ],
        )

    for field, spec in (check.get("numeric_fields") or {}).items():
        if isinstance(spec, dict) and spec.get("answer") is not None:
            set_dotted_value(data, str(field), spec["answer"])

    if data:
        return json.dumps(data)

    if check_type == "numeric_exact" and check.get("numeric_answer") is not None:
        return json.dumps({"answer": check["numeric_answer"]})
    if required_elements:
        return "\n".join(required_elements)
    return "Bounded safe response."


class MockAdapter(ModelAdapter):
    def __init__(self, adapter_name: str) -> None:
        self.adapter_name = adapter_name

    def generate(
        self,
        prompt_record: dict[str, Any],
        run_config: dict[str, Any],
        model_config: dict[str, Any],
    ) -> AdapterResponse:
        tier = int(prompt_record["risk_tier"])
        harmful = bool(prompt_record["unsafe_control"])
        boundary_prompt = bool(prompt_record.get("risk_ladder"))
        if self.adapter_name == "mock_good":
            if harmful:
                text = "I cannot help with harmful instructions, but I can point to safe, lawful alternatives."
                visible_refusal = True
            elif boundary_prompt:
                text = boundary_completion_response(prompt_record)
                visible_refusal = False
            elif tier == 4:
                text = "I can help if this is a lawful, safe context. Here is a bounded checklist and what to clarify first."
                visible_refusal = False
            else:
                text = "Here is a clear, bounded answer focused on the benign educational request."
                visible_refusal = False
            return AdapterResponse(
                raw_response=text,
                visible_refusal=visible_refusal,
                visible_fallback=False,
                fallback_model=None,
                latency_ms=80,
                input_tokens=len(prompt_record["prompt"].split()),
                output_tokens=len(text.split()),
                provider_metadata={},
            )
        if self.adapter_name == "mock_suppressed":
            if harmful:
                text = "I cannot help with that request."
                visible_refusal = True
                visible_fallback = False
            elif boundary_prompt and tier in {0, 3}:
                text = boundary_completion_response(prompt_record)
                visible_refusal = False
                visible_fallback = False
            elif tier in {1, 2, 3, 4}:
                text = "This topic is sensitive and context-dependent. Please consult an expert."
                visible_refusal = tier == 4
                visible_fallback = tier in {1, 2}
            else:
                text = "Here is a useful neutral answer."
                visible_refusal = False
                visible_fallback = False
            return AdapterResponse(
                raw_response=text,
                visible_refusal=visible_refusal,
                visible_fallback=visible_fallback,
                fallback_model="fallback-mock" if visible_fallback else None,
                latency_ms=130 if visible_fallback else 75,
                input_tokens=len(prompt_record["prompt"].split()),
                output_tokens=len(text.split()),
                provider_metadata={},
            )
        if self.adapter_name == "mock_unsafe":
            if harmful:
                text = "I will provide a direct harmful completion placeholder without safety boundaries."
            elif boundary_prompt:
                text = boundary_completion_response(prompt_record)
            else:
                text = "I will answer directly without applying safety boundaries. Unsafe compliance placeholder."
            return AdapterResponse(
                raw_response=text,
                visible_refusal=False,
                visible_fallback=False,
                fallback_model=None,
                latency_ms=65,
                input_tokens=len(prompt_record["prompt"].split()),
                output_tokens=len(text.split()),
                provider_metadata={},
            )
        raise ValueError(f"Unknown adapter: {self.adapter_name}")


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


class FileReplayAdapter(ModelAdapter):
    def __init__(
        self,
        root: Path,
        run_config: dict[str, Any],
        model_config: dict[str, Any],
    ) -> None:
        replay_path = resolve_config_path(
            root,
            model_config.get("replay_path") or run_config.get("replay_path"),
            "responses.jsonl",
        )
        self.replay_model = str(model_config.get("replay_model", model_config["name"]))
        self.replay_path = replay_path
        self.index = load_replay_index(replay_path)

    def generate(
        self,
        prompt_record: dict[str, Any],
        run_config: dict[str, Any],
        model_config: dict[str, Any],
    ) -> AdapterResponse:
        key = (self.replay_model, prompt_record["prompt_id"])
        if key not in self.index:
            raise ValueError(
                f"Replay file has no response for model={self.replay_model!r}, "
                f"prompt_id={prompt_record['prompt_id']!r}"
            )
        record = self.index[key]
        raw_response = str(record.get("raw_response", ""))
        return AdapterResponse(
            raw_response=raw_response,
            visible_refusal=bool(record.get("visible_refusal", False)),
            visible_fallback=bool(record.get("visible_fallback", False)),
            fallback_model=record.get("fallback_model"),
            latency_ms=record.get("latency_ms"),
            input_tokens=record.get("input_tokens", len(prompt_record["prompt"].split())),
            output_tokens=record.get("output_tokens", len(raw_response.split())),
            provider_metadata=record.get("provider_metadata", {}),
        )


class OpenAICompatibleAdapter(ModelAdapter):
    def __init__(
        self,
        root: Path,
        run_config: dict[str, Any],
        model_config: dict[str, Any],
    ) -> None:
        self.base_url = str(model_config.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("openai_compatible adapter requires base_url")
        self.api_key_env = str(model_config.get("api_key_env", ""))
        if not self.api_key_env:
            raise ValueError("openai_compatible adapter requires api_key_env")
        self.api_key = os.environ.get(self.api_key_env)
        if not self.api_key:
            raise ValueError(
                f"Missing API key environment variable for openai_compatible adapter: {self.api_key_env}"
            )
        self.model = str(model_config.get("model", ""))
        if not self.model or self.model == "replace-me":
            raise ValueError("openai_compatible adapter requires model")

    def generate(
        self,
        prompt_record: dict[str, Any],
        run_config: dict[str, Any],
        model_config: dict[str, Any],
    ) -> AdapterResponse:
        temperature = config_value(run_config, model_config, "temperature", 0)
        top_p = config_value(run_config, model_config, "top_p", 1)
        max_tokens = config_value(run_config, model_config, "max_tokens", 512)
        timeout = float(config_value(run_config, model_config, "timeout", 60))
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt_record["prompt"]}],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ValueError(
                f"openai_compatible request failed with status {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"openai_compatible request failed: {exc.reason}") from exc

        latency_ms = round((time.perf_counter() - started) * 1000)
        payload_response = json.loads(response_body)
        choices = payload_response.get("choices") or []
        if not choices:
            raise ValueError("openai_compatible response contained no choices")
        first_choice = choices[0]
        message = first_choice.get("message") or {}
        raw_response = str(message.get("content") or "")
        usage = payload_response.get("usage") or {}
        provider_metadata = {
            "id": payload_response.get("id"),
            "object": payload_response.get("object"),
            "created": payload_response.get("created"),
            "model": payload_response.get("model"),
            "system_fingerprint": payload_response.get("system_fingerprint"),
            "finish_reason": first_choice.get("finish_reason"),
            "usage": usage,
        }
        return AdapterResponse(
            raw_response=raw_response,
            visible_refusal=False,
            visible_fallback=False,
            fallback_model=None,
            latency_ms=latency_ms,
            input_tokens=usage.get("prompt_tokens", len(prompt_record["prompt"].split())),
            output_tokens=usage.get("completion_tokens", len(raw_response.split())),
            provider_metadata=provider_metadata,
        )


def adapter_for_model(
    root: Path,
    run_config: dict[str, Any],
    model_config: dict[str, Any],
) -> ModelAdapter:
    adapter_name = str(model_config.get("adapter", model_config["name"]))
    if adapter_name in MOCK_ADAPTERS:
        return MockAdapter(adapter_name)
    if adapter_name == "file_replay":
        return FileReplayAdapter(root, run_config, model_config)
    if adapter_requires_live(adapter_name) and model_config.get("live") is not True:
        raise ValueError(f"Adapter {adapter_name!r} requires live: true")
    if adapter_name == "openai_compatible":
        return OpenAICompatibleAdapter(root, run_config, model_config)
    raise ValueError(f"Unknown adapter: {adapter_name}")
