import json
import shutil
from pathlib import Path

import pytest

from mcmurphy.cli import main
from mcmurphy.corpus_lock import build_corpus_lock, file_sha256, verify_corpus_lock


FROZEN_BOUNDARY_V0_3_PROMPT_SHA256 = (
    "da24f641726ac333222a6ab311a62d498e7178b252fc61c5b407d1ae99109e3a"
)
BOUNDARY_LOCK_PATH = Path("data/boundary_v0_3_lock.json")
BOUNDARY_PROMPT_PATH = Path("data/boundary_v0_3_prompts.jsonl")
BOUNDARY_INVENTORY_PATH = Path("data/boundary_v0_3_inventory.json")


def test_corpus_lock_writes_expected_metadata(tmp_path):
    out_path = tmp_path / "boundary_v0_3_lock.json"

    assert (
        main(
            [
                "corpus-lock",
                str(BOUNDARY_PROMPT_PATH),
                "--inventory",
                str(BOUNDARY_INVENTORY_PATH),
                "--out",
                str(out_path),
            ]
        )
        == 0
    )

    lock = json.loads(out_path.read_text(encoding="utf-8"))
    assert lock["corpus_name"] == "boundary_v0.3"
    assert lock["prompt_file"] == "data/boundary_v0_3_prompts.jsonl"
    assert lock["inventory_file"] == "data/boundary_v0_3_inventory.json"
    assert lock["prompt_count"] == 360
    assert lock["category_count"] == 12
    assert lock["ladder_count"] == 60
    assert lock["tier_counts"] == {str(tier): 60 for tier in range(6)}
    assert lock["prompt_file_sha256"] == FROZEN_BOUNDARY_V0_3_PROMPT_SHA256
    assert lock["inventory_file_sha256"] == file_sha256(BOUNDARY_INVENTORY_PATH)
    assert lock["status"] == "frozen_for_pilot"
    assert "Prompt text should not change without version bump." in lock["notes"]


def test_verify_corpus_lock_passes_on_current_files():
    assert main(["verify-corpus-lock", str(BOUNDARY_LOCK_PATH)]) == 0


def test_verify_corpus_lock_fails_after_prompt_file_mutation(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tmp'\n", encoding="utf-8")
    prompt_copy = data_dir / "boundary_v0_3_prompts.jsonl"
    inventory_copy = data_dir / "boundary_v0_3_inventory.json"
    shutil.copy(BOUNDARY_PROMPT_PATH, prompt_copy)
    shutil.copy(BOUNDARY_INVENTORY_PATH, inventory_copy)
    lock = build_corpus_lock(
        prompt_copy,
        inventory_copy,
        root=tmp_path,
        created_at_utc="2026-06-15T00:00:00+00:00",
        commit_sha="test-commit",
    )
    lock_path = data_dir / "boundary_v0_3_lock.json"
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

    prompt_copy.write_text(
        prompt_copy.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="prompt_file"):
        verify_corpus_lock(lock_path)


def test_boundary_v0_3_lock_exists_and_points_to_current_prompt_file():
    lock = json.loads(BOUNDARY_LOCK_PATH.read_text(encoding="utf-8"))

    assert lock["prompt_file"] == "data/boundary_v0_3_prompts.jsonl"
    assert lock["inventory_file"] == "data/boundary_v0_3_inventory.json"
    assert lock["prompt_file_sha256"] == file_sha256(BOUNDARY_PROMPT_PATH)
    assert lock["inventory_file_sha256"] == file_sha256(BOUNDARY_INVENTORY_PATH)


def test_boundary_v0_3_prompt_text_is_unchanged_from_frozen_hash():
    assert file_sha256(BOUNDARY_PROMPT_PATH) == FROZEN_BOUNDARY_V0_3_PROMPT_SHA256
