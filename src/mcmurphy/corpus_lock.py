"""Corpus lockfile helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .prompts import load_prompts
from .schema import repository_root


LOCK_STATUS = "frozen_for_pilot"
LOCK_NOTES = (
    "Frozen for first multi-model pilot. Prompt text should not change without "
    "version bump."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Could not resolve git commit SHA from {root}") from exc
    return result.stdout.strip()


def repo_relative(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def build_corpus_lock(
    prompt_file: Path,
    inventory_file: Path,
    *,
    root: Path | None = None,
    created_at_utc: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    root = (root or repository_root(prompt_file)).resolve()
    prompt_file = prompt_file.resolve()
    inventory_file = inventory_file.resolve()
    prompts = load_prompts(prompt_file)
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))

    return {
        "corpus_name": "boundary_v0.3",
        "prompt_file": repo_relative(prompt_file, root),
        "inventory_file": repo_relative(inventory_file, root),
        "prompt_count": len(prompts),
        "category_count": len(
            {record["risk_ladder"]["category"] for record in prompts}
        ),
        "ladder_count": len(
            {record["risk_ladder"]["ladder_id"] for record in prompts}
        ),
        "tier_counts": inventory["tier_counts"],
        "prompt_file_sha256": file_sha256(prompt_file),
        "inventory_file_sha256": file_sha256(inventory_file),
        "created_at_utc": created_at_utc or utc_now(),
        "commit_sha": commit_sha or git_commit_sha(root),
        "status": LOCK_STATUS,
        "notes": LOCK_NOTES,
    }


def write_corpus_lock(
    prompt_file: Path,
    inventory_file: Path,
    out_path: Path,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    lock = build_corpus_lock(prompt_file, inventory_file, root=root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def resolve_locked_path(lock_path: Path, path_value: str) -> Path:
    raw = Path(path_value)
    if raw.is_absolute():
        return raw
    root = repository_root(lock_path)
    candidate = root / raw
    if candidate.exists():
        return candidate.resolve()
    return (lock_path.parent / raw).resolve()


def verify_corpus_lock(lock_path: Path) -> dict[str, Any]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    prompt_file = resolve_locked_path(lock_path, lock["prompt_file"])
    inventory_file = resolve_locked_path(lock_path, lock["inventory_file"])
    expected_prompt_hash = str(lock["prompt_file_sha256"])
    actual_prompt_hash = file_sha256(prompt_file)
    if actual_prompt_hash != expected_prompt_hash:
        raise ValueError(
            "Corpus lock mismatch for prompt_file: "
            f"expected {expected_prompt_hash}, actual {actual_prompt_hash}"
        )
    expected_inventory_hash = str(lock["inventory_file_sha256"])
    actual_inventory_hash = file_sha256(inventory_file)
    if actual_inventory_hash != expected_inventory_hash:
        raise ValueError(
            "Corpus lock mismatch for inventory_file: "
            f"expected {expected_inventory_hash}, actual {actual_inventory_hash}"
        )
    return lock
