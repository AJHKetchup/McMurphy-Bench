import csv
from pathlib import Path

from mcmurphy.cli import main
from mcmurphy.corpus_lock import file_sha256
from mcmurphy.prompts import load_prompts


PROMPT_PATH = Path("data/boundary_v0_3_prompts.jsonl")
CANARY_PATH = Path("data/boundary_v0_3_canary_prompts.jsonl")
LOCK_PATH = Path("data/boundary_v0_3_lock.json")
FROZEN_PROMPT_SHA256 = (
    "da24f641726ac333222a6ab311a62d498e7178b252fc61c5b407d1ae99109e3a"
)


def test_export_review_packet_creates_all_three_files(tmp_path):
    assert main(["export-review-packet", str(PROMPT_PATH), "--out-dir", str(tmp_path)]) == 0

    assert (tmp_path / "boundary_v0_3_prompt_review.csv").exists()
    assert (tmp_path / "boundary_v0_3_ladder_review.md").exists()
    assert (tmp_path / "boundary_v0_3_review_guide.md").exists()


def test_review_csv_has_exactly_360_data_rows(tmp_path):
    assert main(["export-review-packet", str(PROMPT_PATH), "--out-dir", str(tmp_path)]) == 0

    with (tmp_path / "boundary_v0_3_prompt_review.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 360
    assert rows[0]["reviewer_decision"] == ""
    assert rows[0]["reviewer_notes"] == ""


def test_ladder_review_markdown_has_exactly_60_sections(tmp_path):
    assert main(["export-review-packet", str(PROMPT_PATH), "--out-dir", str(tmp_path)]) == 0

    markdown = (tmp_path / "boundary_v0_3_ladder_review.md").read_text(
        encoding="utf-8"
    )

    assert markdown.count("\n## Ladder: ") == 60
    assert "ladder_decision:" in markdown
    assert "tier4_quality:" in markdown
    assert "tier5_quality:" in markdown


def test_review_guide_contains_tier4_and_tier5_checklist_language(tmp_path):
    assert main(["export-review-packet", str(PROMPT_PATH), "--out-dir", str(tmp_path)]) == 0

    guide = (tmp_path / "boundary_v0_3_review_guide.md").read_text(encoding="utf-8")

    assert "Does Tier 4 push close to the boundary without crossing into explicit illegality?" in guide
    assert "Does Tier 5 clearly ask for illegal or harmful conduct?" in guide


def test_export_review_packet_does_not_modify_boundary_prompts(tmp_path):
    before = file_sha256(PROMPT_PATH)

    assert main(["export-review-packet", str(PROMPT_PATH), "--out-dir", str(tmp_path)]) == 0

    assert file_sha256(PROMPT_PATH) == before == FROZEN_PROMPT_SHA256


def test_canary_prompt_file_has_expected_shape():
    records = load_prompts(CANARY_PATH)
    ladders = {record["risk_ladder"]["ladder_id"] for record in records}
    tiers_by_ladder = {
        ladder: {
            record["risk_tier"]
            for record in records
            if record["risk_ladder"]["ladder_id"] == ladder
        }
        for ladder in ladders
    }

    assert len(records) == 12
    assert len(ladders) == 2
    assert {frozenset(tiers) for tiers in tiers_by_ladder.values()} == {
        frozenset({0, 1, 2, 3, 4, 5})
    }


def test_estimate_run_prints_total_api_calls_without_api_keys(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert main(["estimate-run", "configs/boundary.live.example.yaml"]) == 0

    output = capsys.readouterr().out
    assert "total_api_calls: 1800" in output
    assert "Cost not estimated: pricing not configured." in output


def test_preflight_run_passes_for_non_live_canary_config(capsys):
    assert main(["preflight-run", "configs/boundary.canary.replay.example.yaml"]) == 0

    output = capsys.readouterr().out
    assert "prompt_count: 12" in output
    assert "model_count: 1" in output
    assert "total_api_calls: 12" in output
    assert "Preflight complete: no API calls made." in output


def test_preflight_run_warns_for_large_live_example_config(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert main(["preflight-run", "configs/boundary.live.example.yaml"]) == 0

    output = capsys.readouterr().out
    assert "total_api_calls: 1800" in output
    assert "WARNING: Live config is an example file" in output
    assert "WARNING: total_api_calls > 100 (1800)" in output


def test_verify_corpus_lock_still_passes():
    assert main(["verify-corpus-lock", str(LOCK_PATH)]) == 0
