import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from mcmurphy.adapters import AdapterResponse, OpenAICompatibleAdapter
from mcmurphy.cli import main
from mcmurphy.report import write_report
from mcmurphy.run import config_root, run_models
from mcmurphy.schema import validate_record
from mcmurphy.score import read_judgments, score_model


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def corrupt_first_response_hash(run_dir: Path) -> None:
    responses_path = run_dir / "responses.jsonl"
    responses = read_jsonl(responses_path)
    responses[0]["response_hash"] = "0" * 64
    write_jsonl(responses_path, responses)


def live_model_config(*, live=True) -> dict:
    model = {
        "name": "openai_model_under_test",
        "provider": "openai",
        "adapter": "openai_compatible",
        "base_url": "https://api.example.invalid/v1",
        "api_key_env": "MCMURPHY_TEST_API_KEY",
        "model": "pilot-model",
        "timeout": 1,
    }
    if live is not None:
        model["live"] = live
    return model


def fake_live_generate(self, prompt_record, run_config, model_config):
    text = f"Fixture live response for {prompt_record['prompt_id']}."
    return AdapterResponse(
        raw_response=text,
        visible_refusal=False,
        visible_fallback=False,
        fallback_model=None,
        latency_ms=5,
        input_tokens=len(prompt_record["prompt"].split()),
        output_tokens=len(text.split()),
        provider_metadata={"fixture": True},
    )


def copy_core_files(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "data").mkdir()
    shutil.copy(Path("pyproject.toml"), tmp_path / "pyproject.toml")
    shutil.copy(Path("data/schema.json"), tmp_path / "data/schema.json")
    shutil.copy(Path("data/seed_prompts.jsonl"), tmp_path / "data/seed_prompts.jsonl")


def copy_pilot_files(tmp_path: Path) -> None:
    copy_core_files(tmp_path)
    shutil.copy(
        Path("data/pilot_public_t0_t4.jsonl"),
        tmp_path / "data/pilot_public_t0_t4.jsonl",
    )
    shutil.copy(
        Path("configs/pilot.mock.example.yaml"),
        tmp_path / "configs/pilot.mock.example.yaml",
    )


def copy_replay_files(tmp_path: Path) -> None:
    copy_core_files(tmp_path)
    (tmp_path / "tests/fixtures").mkdir(parents=True)
    shutil.copy(
        Path("tests/fixtures/replay_prompts.jsonl"),
        tmp_path / "tests/fixtures/replay_prompts.jsonl",
    )
    shutil.copy(
        Path("tests/fixtures/replay_responses.jsonl"),
        tmp_path / "tests/fixtures/replay_responses.jsonl",
    )
    shutil.copy(
        Path("tests/fixtures/replay_judgments.jsonl"),
        tmp_path / "tests/fixtures/replay_judgments.jsonl",
    )


def run_pilot_loop(tmp_path: Path, *, run_id: str = "run_pilot_finalize") -> Path:
    copy_pilot_files(tmp_path)
    config = yaml.safe_load(Path("configs/pilot.mock.example.yaml").read_text())
    config["run_id"] = run_id
    config_path = tmp_path / "configs/pilot.mock.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert main(["loop", str(config_path)]) == 0
    return tmp_path / f"reports/{run_id}"


def write_completed_fixture(run_dir: Path, records: list[dict]) -> Path:
    path = run_dir / "completed_judgments.jsonl"
    write_jsonl(path, records)
    return path


def test_custom_weight_confidence_interval_midpoint_matches_report(tmp_path):
    rows = read_judgments(Path("data/sample_judgments.csv"))
    model_b_rows = [row for row in rows if row.model == "Model B"]
    custom_weights = {
        "false_refusal_rate": 0.10,
        "soft_evasion_rate": 0.10,
        "paired_degradation_score": 0.40,
        "answerable_fallback_downgrade_rate": 0.20,
        "combined_trigger_fragility": 0.10,
        "clarification_failure_rate": 0.10,
    }

    report = write_report(
        rows,
        tmp_path / "report.json",
        mli_weights=custom_weights,
        include_ci=True,
    )
    expected = score_model(model_b_rows, mli_weights=custom_weights)["metrics"][
        "model_lobotomy_index"
    ]
    model_b = next(model for model in report["models"] if model["model"] == "Model B")

    assert model_b["metrics"]["model_lobotomy_index"] == expected
    assert model_b["confidence_intervals"]["model_lobotomy_index"]["mid"] == expected


def test_audit_regenerates_from_run_dir_and_report_path(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_audit_test"
    config["output_dir"] = "reports"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0
    run_dir = tmp_path / "reports/run_audit_test"
    (run_dir / "audit_sample.csv").unlink()
    (run_dir / "audit_sample.jsonl").unlink()

    assert main(["audit", str(run_dir), "--sample-rate", "0.15"]) == 0
    assert (run_dir / "audit_sample.csv").exists()
    assert (run_dir / "audit_sample.jsonl").exists()

    (run_dir / "audit_sample.csv").unlink()
    (run_dir / "audit_sample.jsonl").unlink()
    assert main(["audit", str(run_dir / "report.json"), "--sample-rate", "0.15"]) == 0
    assert (run_dir / "audit_sample.csv").exists()
    assert (run_dir / "audit_sample.jsonl").exists()


def sampled_pairs(path: Path) -> list[tuple[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [(row["model"], row["prompt_id"]) for row in rows]


def test_audit_seed_reproducibility_defaults_to_manifest(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_seed_test"
    config["audit"] = {"sample_rate": 0.2, "seed": 999}
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0
    run_dir = tmp_path / "reports/run_seed_test"

    assert main(["audit", str(run_dir)]) == 0
    first = sampled_pairs(run_dir / "audit_sample.csv")
    assert main(["audit", str(run_dir)]) == 0
    second = sampled_pairs(run_dir / "audit_sample.csv")
    assert first == second

    assert main(["audit", str(run_dir), "--seed", "1000"]) == 0
    third = sampled_pairs(run_dir / "audit_sample.csv")
    assert third != first


def test_judge_config_resolves_run_dir_from_outside_repo(tmp_path, monkeypatch):
    copy_core_files(tmp_path)
    run_config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    run_config["run_id"] = "run_example"
    run_config_path = tmp_path / "configs/run.example.yaml"
    run_config_path.write_text(yaml.safe_dump(run_config), encoding="utf-8")

    judge_config = yaml.safe_load(Path("configs/judge.example.yaml").read_text())
    judge_config_path = tmp_path / "configs/judge.example.yaml"
    judge_config_path.write_text(yaml.safe_dump(judge_config), encoding="utf-8")

    assert main(["run", str(run_config_path)]) == 0
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert main(["judge", str(judge_config_path)]) == 0
    assert (tmp_path / "reports/run_example/judgments.jsonl").exists()


def test_config_root_supports_config_outside_configs_directory(tmp_path):
    copy_core_files(tmp_path)
    nested = tmp_path / "experiments"
    nested.mkdir()
    config_path = nested / "custom.yaml"
    config_path.write_text("prompt_set: data/seed_prompts.jsonl\n", encoding="utf-8")

    assert config_root(config_path) == tmp_path.resolve()


def test_invalid_generated_records_fail_validation(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_schema_test"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run_dir, responses, manifest = run_models(config_path)

    validate_record(manifest, root=tmp_path)
    validate_record(responses[0], root=tmp_path)

    bad_manifest = dict(manifest)
    bad_manifest.pop("run_id")
    with pytest.raises(ValueError):
        validate_record(bad_manifest, root=tmp_path)

    bad_response = dict(responses[0])
    bad_response["latency_ms"] = "slow"
    with pytest.raises(ValueError):
        validate_record(bad_response, root=tmp_path)


def test_run_models_accepts_pilot_subset_when_incomplete_families_allowed(tmp_path):
    copy_pilot_files(tmp_path)
    config = yaml.safe_load(Path("configs/pilot.mock.example.yaml").read_text())
    config["run_id"] = "run_pilot_allowed"
    config_path = tmp_path / "configs/pilot.mock.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    run_dir, responses, manifest = run_models(config_path)

    assert run_dir == tmp_path / "reports/run_pilot_allowed"
    assert len(responses) == 150
    assert {response["risk_tier"] for response in responses} == {0, 1, 2, 3, 4}
    assert manifest["allow_incomplete_families"] is True
    assert manifest["run_prompt_count"] == 50
    assert manifest["run_prompt_count_by_tier"] == {
        "0": 10,
        "1": 10,
        "2": 10,
        "3": 10,
        "4": 10,
        "5": 0,
    }


def test_run_models_rejects_pilot_subset_without_incomplete_family_flag(tmp_path):
    copy_pilot_files(tmp_path)
    config = yaml.safe_load(Path("configs/pilot.mock.example.yaml").read_text())
    config["run_id"] = "run_pilot_rejected"
    config["allow_incomplete_families"] = False
    config_path = tmp_path / "configs/pilot.mock.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="expected tiers 0-5"):
        run_models(config_path)


def test_command_loop_passes_incomplete_family_flag_for_pilot_subset(tmp_path):
    copy_pilot_files(tmp_path)
    config = yaml.safe_load(Path("configs/pilot.mock.example.yaml").read_text())
    config["run_id"] = "run_pilot_loop"
    config_path = tmp_path / "configs/pilot.mock.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    run_dir = tmp_path / "reports/run_pilot_loop"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert manifest["allow_incomplete_families"] is True
    assert report["run_manifest"]["allow_incomplete_families"] is True
    assert report["models"][0]["metrics"]["unsafe_fulfillment_measured"] is False


def test_finalize_run_success_for_pilot_subset(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_success")

    assert (
        main(
            [
                "finalize-run",
                str(run_dir),
                "--judgments",
                str(run_dir / "judgments.jsonl"),
                "--audit-sample-rate",
                "0.20",
                "--audit-seed",
                "1729",
            ]
        )
        == 0
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert (run_dir / "judgments.jsonl").exists()
    assert (run_dir / "audit_sample.csv").exists()
    assert (run_dir / "audit_sample.jsonl").exists()
    assert report["judgment_coverage"]["complete"] is True
    assert report["judgment_coverage"]["judged_response_count"] == 150
    assert report["judgment_coverage"]["total_response_count"] == 150
    assert all(
        model["metrics"]["unsafe_fulfillment_measured"] is False
        for model in report["models"]
    )
    assert report["run_manifest"]["allow_incomplete_families"] is True
    assert report["run_manifest"]["run_prompt_count_by_tier"]["5"] == 0


def test_finalize_run_rejects_template_judgments(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_template")
    template_path = run_dir / "judgment_template.jsonl"
    assert (
        main(
            [
                "judgment-template",
                str(run_dir),
                "--out",
                str(template_path),
                "--include-response",
            ]
        )
        == 0
    )

    with pytest.raises(ValueError, match="template records are not completed judgments"):
        main(["finalize-run", str(run_dir), "--judgments", str(template_path)])


def test_finalize_run_rejects_missing_judgment_by_default(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_missing")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    path = write_completed_fixture(run_dir, judgments[:-1])

    with pytest.raises(ValueError, match="missing judgment"):
        main(["finalize-run", str(run_dir), "--judgments", str(path)])


def test_finalize_run_rejects_duplicate_judgment(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_duplicate")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    path = write_completed_fixture(run_dir, [*judgments, dict(judgments[0])])

    with pytest.raises(ValueError, match="duplicate judgment"):
        main(["finalize-run", str(run_dir), "--judgments", str(path)])


def test_finalize_run_rejects_extra_judgment(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_extra")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    extra = dict(judgments[0])
    extra["model"] = "missing_model"
    path = write_completed_fixture(run_dir, [*judgments, extra])

    with pytest.raises(ValueError, match="response that does not exist"):
        main(["finalize-run", str(run_dir), "--judgments", str(path)])


def test_finalize_run_rejects_response_hash_mismatch(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_response_hash")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    judgments[0]["response_hash"] = "0" * 64
    path = write_completed_fixture(run_dir, judgments)

    with pytest.raises(ValueError, match="response_hash"):
        main(["finalize-run", str(run_dir), "--judgments", str(path)])


def test_finalize_run_rejects_prompt_hash_mismatch(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_prompt_hash")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    judgments[0]["prompt_hash"] = "0" * 64
    path = write_completed_fixture(run_dir, judgments)

    with pytest.raises(ValueError, match="prompt_hash"):
        main(["finalize-run", str(run_dir), "--judgments", str(path)])


def test_finalize_run_fills_missing_inferable_provenance(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_fill")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    stripped = dict(judgments[0])
    for field in (
        "run_id",
        "family_id",
        "domain",
        "risk_tier",
        "variant",
        "prompt_hash",
        "response_hash",
        "answerable",
        "is_harmful_control",
    ):
        stripped.pop(field)
    judgments[0] = stripped
    path = write_completed_fixture(run_dir, judgments)

    assert main(["finalize-run", str(run_dir), "--judgments", str(path)]) == 0

    written = read_jsonl(run_dir / "judgments.jsonl")
    responses = {
        (response["model"], response["prompt_id"]): response
        for response in read_jsonl(run_dir / "responses.jsonl")
    }
    filled = next(
        record
        for record in written
        if record["model"] == stripped["model"]
        and record["prompt_id"] == stripped["prompt_id"]
    )
    response = responses[(filled["model"], filled["prompt_id"])]
    for field in (
        "run_id",
        "family_id",
        "domain",
        "risk_tier",
        "variant",
        "prompt_hash",
        "response_hash",
    ):
        assert filled[field] == response[field]
    assert filled["answerable"] is True
    assert filled["is_harmful_control"] is False


def test_finalize_run_allows_partial_judgments_with_debug_flag(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_finalize_partial")
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    path = write_completed_fixture(run_dir, judgments[:-1])

    assert (
        main(
            [
                "finalize-run",
                str(run_dir),
                "--judgments",
                str(path),
                "--allow-partial-judgments",
            ]
        )
        == 0
    )

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["judgment_coverage"]["complete"] is False
    assert report["judgment_coverage"]["judged_response_count"] == 149
    assert report["judgment_coverage"]["total_response_count"] == 150
    assert "Partial judgment coverage is not directly comparable" in report["ranking_note"]


def test_report_run_rebuilds_report_and_optionally_audit(tmp_path):
    run_dir = run_pilot_loop(tmp_path, run_id="run_report_run")
    (run_dir / "report.json").unlink()

    assert main(["report-run", str(run_dir)]) == 0

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["run_manifest"]["run_id"] == "run_report_run"
    assert report["judgment_coverage"]["complete"] is True

    judgments_path = run_dir / "judgments.jsonl"
    saved_judgments = read_jsonl(judgments_path)
    judgments_path.unlink()
    with pytest.raises(FileNotFoundError, match="judgments.jsonl"):
        main(["report-run", str(run_dir)])
    write_jsonl(judgments_path, saved_judgments)

    (run_dir / "audit_sample.csv").unlink()
    (run_dir / "audit_sample.jsonl").unlink()
    assert main(["report-run", str(run_dir), "--audit"]) == 0
    assert (run_dir / "audit_sample.csv").exists()
    assert (run_dir / "audit_sample.jsonl").exists()


def test_completed_mock_judgments_have_completed_status(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_mock_status"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    judgments = read_jsonl(tmp_path / "reports/run_mock_status/judgments.jsonl")
    assert judgments
    assert {judgment["judgment_status"] for judgment in judgments} == {"completed"}


def test_unknown_judge_type_fails(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_unknown_judge"
    config["judge"] = {"type": "typo_judge"}
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown judge type: typo_judge"):
        main(["loop", str(config_path)])


def test_mock_judge_unknown_model_fails_by_default(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_unknown_mock_model"
    config["models"] = [
        {
            "name": "real_model_name",
            "provider": "mock",
            "adapter": "mock_good",
            "model_version": "test",
        }
    ]
    config["judge"] = {"type": "mock"}
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown mock model: real_model_name"):
        main(["loop", str(config_path)])


def test_file_replay_missing_prompt_failure(tmp_path):
    copy_replay_files(tmp_path)
    lines = Path("tests/fixtures/replay_responses.jsonl").read_text().splitlines()
    (tmp_path / "tests/fixtures/replay_responses.jsonl").write_text(
        "\n".join(lines[:-1]) + "\n",
        encoding="utf-8",
    )
    config = yaml.safe_load(Path("configs/replay.example.yaml").read_text())
    config["run_id"] = "run_replay_missing"
    config_path = tmp_path / "configs/replay.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Replay file has no response"):
        main(["loop", str(config_path)])


def test_replay_judgment_family_id_mismatch_fails(tmp_path):
    copy_replay_files(tmp_path)
    judgment_path = tmp_path / "tests/fixtures/replay_judgments.jsonl"
    judgments = read_jsonl(judgment_path)
    judgments[0]["family_id"] = "wrong_family"
    write_jsonl(judgment_path, judgments)
    config = yaml.safe_load(Path("configs/replay.example.yaml").read_text())
    config["run_id"] = "run_replay_family_mismatch"
    config_path = tmp_path / "configs/replay.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="field mismatch for family_id"):
        main(["loop", str(config_path)])


def test_replay_judgment_response_hash_mismatch_fails(tmp_path):
    copy_replay_files(tmp_path)
    judgment_path = tmp_path / "tests/fixtures/replay_judgments.jsonl"
    judgments = read_jsonl(judgment_path)
    judgments[0]["response_hash"] = "0" * 64
    write_jsonl(judgment_path, judgments)
    config = yaml.safe_load(Path("configs/replay.example.yaml").read_text())
    config["run_id"] = "run_replay_response_hash_mismatch"
    config_path = tmp_path / "configs/replay.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="field mismatch for response_hash"):
        main(["loop", str(config_path)])


def test_replay_judgment_missing_response_hash_is_filled(tmp_path):
    copy_replay_files(tmp_path)
    judgment_path = tmp_path / "tests/fixtures/replay_judgments.jsonl"
    judgments = read_jsonl(judgment_path)
    for judgment in judgments:
        judgment.pop("response_hash")
    write_jsonl(judgment_path, judgments)
    config = yaml.safe_load(Path("configs/replay.example.yaml").read_text())
    config["run_id"] = "run_replay_filled_hash"
    config_path = tmp_path / "configs/replay.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    run_dir = tmp_path / "reports/run_replay_filled_hash"
    responses = {
        (response["model"], response["prompt_id"]): response
        for response in read_jsonl(run_dir / "responses.jsonl")
    }
    generated_judgments = read_jsonl(run_dir / "judgments.jsonl")
    for judgment in generated_judgments:
        response = responses[(judgment["model"], judgment["prompt_id"])]
        expected_hash = hashlib.sha256(
            response["raw_response"].encode("utf-8")
        ).hexdigest()
        assert judgment["response_hash"] == expected_hash
        assert judgment["judge_id"] == "fixture_replay_judge"


def test_file_replay_successful_loop(tmp_path):
    copy_replay_files(tmp_path)
    config = yaml.safe_load(Path("configs/replay.example.yaml").read_text())
    config["run_id"] = "run_replay_success"
    config_path = tmp_path / "configs/replay.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    run_dir = tmp_path / "reports/run_replay_success"
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    judgments = read_jsonl(run_dir / "judgments.jsonl")
    assert (run_dir / "responses.jsonl").exists()
    assert (run_dir / "judgments.jsonl").exists()
    assert report["run_manifest"]["run_id"] == "run_replay_success"
    assert judgments[0]["usefulness_score"] == 3.75
    assert judgments[0]["judge_id"] == "fixture_replay_judge"
    assert judgments[0]["judgment_status"] == "completed"
    assert report["models"][0]["metrics"]["safe_utility"] > 90


def test_judgment_template_emits_one_record_per_response(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_template"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    run_dir = tmp_path / "reports/run_template"
    out_path = run_dir / "judgment_template.jsonl"
    assert main(["judgment-template", str(run_dir), "--out", str(out_path)]) == 0

    responses = read_jsonl(run_dir / "responses.jsonl")
    template = read_jsonl(out_path)
    assert len(template) == len(responses)
    assert "raw_response" not in template[0]
    assert template[0]["judgment_status"] == "template"
    assert template[0]["run_id"] == "run_template"
    assert template[0]["prompt_hash"]
    assert template[0]["response_hash"]
    assert template[0]["judge_id"] == ""


def test_score_rejects_judgment_template_without_debug_flag(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_template_score"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    run_dir = tmp_path / "reports/run_template_score"
    template_path = run_dir / "judgment_template.jsonl"
    assert main(["judgment-template", str(run_dir), "--out", str(template_path)]) == 0

    with pytest.raises(ValueError, match="template judgment records"):
        main(["score", str(template_path)])
    assert main(["score", str(template_path), "--allow-template-records"]) == 0


def test_corrupted_response_hash_fails_during_audit(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_corrupt_audit"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0
    run_dir = tmp_path / "reports/run_corrupt_audit"
    corrupt_first_response_hash(run_dir)

    with pytest.raises(ValueError, match="response_hash mismatch"):
        main(["audit", str(run_dir), "--sample-rate", "0.15"])


def test_corrupted_response_hash_fails_during_judgment_template(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_corrupt_template"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0
    run_dir = tmp_path / "reports/run_corrupt_template"
    corrupt_first_response_hash(run_dir)

    with pytest.raises(ValueError, match="response_hash mismatch"):
        main(
            [
                "judgment-template",
                str(run_dir),
                "--out",
                str(run_dir / "judgment_template.jsonl"),
            ]
        )


def test_corrupted_response_hash_fails_during_judge(tmp_path):
    copy_core_files(tmp_path)
    run_config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    run_config["run_id"] = "run_example"
    run_config_path = tmp_path / "configs/run.example.yaml"
    run_config_path.write_text(yaml.safe_dump(run_config), encoding="utf-8")

    judge_config = yaml.safe_load(Path("configs/judge.example.yaml").read_text())
    judge_config_path = tmp_path / "configs/judge.example.yaml"
    judge_config_path.write_text(yaml.safe_dump(judge_config), encoding="utf-8")

    assert main(["run", str(run_config_path)]) == 0
    corrupt_first_response_hash(tmp_path / "reports/run_example")

    with pytest.raises(ValueError, match="response_hash mismatch"):
        main(["judge", str(judge_config_path)])


def test_openai_compatible_fails_without_api_key_env(tmp_path, monkeypatch):
    copy_core_files(tmp_path)
    monkeypatch.delenv("MCMURPHY_TEST_API_KEY", raising=False)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_missing_key"
    config["models"] = [live_model_config(live=True)]
    config_path = tmp_path / "configs/live.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing API key environment variable"):
        run_models(config_path)


def test_live_adapter_requires_live_true(tmp_path, monkeypatch):
    copy_core_files(tmp_path)
    monkeypatch.setenv("MCMURPHY_TEST_API_KEY", "fake-key")
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_live_required"
    config["models"] = [live_model_config(live=None)]
    config_path = tmp_path / "configs/live.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="requires live: true"):
        run_models(config_path)


def test_live_adapter_skips_tier5_by_default(tmp_path, monkeypatch):
    copy_core_files(tmp_path)
    monkeypatch.setenv("MCMURPHY_TEST_API_KEY", "fake-key")
    monkeypatch.setattr(OpenAICompatibleAdapter, "generate", fake_live_generate)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_live_skip_t5"
    config["models"] = [live_model_config(live=True)]
    config_path = tmp_path / "configs/live.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    _run_dir, responses, manifest = run_models(config_path)

    assert len(responses) == 50
    assert {response["risk_tier"] for response in responses} == {0, 1, 2, 3, 4}
    assert manifest["include_restricted_controls"] is False
    assert manifest["restricted_controls_excluded"] is True
    assert manifest["skipped_prompt_count"] == 10
    assert len(manifest["skipped_prompt_ids"]) == 10
    assert all(prompt_id.endswith("_t5") for prompt_id in manifest["skipped_prompt_ids"])
    assert manifest["run_prompt_count"] == 50
    assert manifest["prompt_count_by_tier"] == {
        "0": 10,
        "1": 10,
        "2": 10,
        "3": 10,
        "4": 10,
        "5": 10,
    }
    assert manifest["run_prompt_count_by_tier"] == {
        "0": 10,
        "1": 10,
        "2": 10,
        "3": 10,
        "4": 10,
        "5": 0,
    }
    model_counts = manifest["model_prompt_counts"]["openai_model_under_test"]
    assert model_counts["run_prompt_count"] == 50
    assert model_counts["skipped_prompt_count"] == 10
    assert model_counts["skipped_prompt_ids"] == manifest["skipped_prompt_ids"]
    assert model_counts["run_prompt_count_by_tier"]["5"] == 0
    assert manifest["estimated_cost_usd"] is None


def test_include_restricted_controls_true_includes_tier5(tmp_path, monkeypatch):
    copy_core_files(tmp_path)
    monkeypatch.setenv("MCMURPHY_TEST_API_KEY", "fake-key")
    monkeypatch.setattr(OpenAICompatibleAdapter, "generate", fake_live_generate)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_live_include_t5"
    config["include_restricted_controls"] = True
    config["models"] = [live_model_config(live=True)]
    config_path = tmp_path / "configs/live.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    _run_dir, responses, manifest = run_models(config_path)

    assert len(responses) == 60
    assert any(response["risk_tier"] == 5 for response in responses)
    assert manifest["include_restricted_controls"] is True
    assert manifest["restricted_controls_excluded"] is False
    assert manifest["skipped_prompt_count"] == 0
    assert manifest["skipped_prompt_ids"] == []
    assert manifest["run_prompt_count"] == 60
    model_counts = manifest["model_prompt_counts"]["openai_model_under_test"]
    assert model_counts["run_prompt_count"] == 60
    assert model_counts["skipped_prompt_count"] == 0
    assert model_counts["run_prompt_count_by_tier"]["5"] == 10


def test_response_load_validates_schema(tmp_path):
    from mcmurphy.judge import load_responses

    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_bad_response_schema"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    run_dir, _responses, _manifest = run_models(config_path)
    response_path = run_dir / "responses.jsonl"
    response_records = read_jsonl(response_path)
    response_records[0].pop("provider")
    write_jsonl(response_path, response_records)

    with pytest.raises(ValueError, match="response schema validation failed"):
        load_responses(response_path, root=tmp_path)


def test_external_prompt_set_path_does_not_crash_manifest_writing(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    copy_core_files(repo_root)
    external = tmp_path / "external"
    external.mkdir()
    external_prompt_set = external / "seed_prompts.jsonl"
    shutil.copy(Path("data/seed_prompts.jsonl"), external_prompt_set)

    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_external_prompt_set"
    config["prompt_set"] = str(external_prompt_set)
    config_path = repo_root / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    run_dir, _responses, manifest = run_models(config_path)

    assert run_dir == repo_root / "reports/run_external_prompt_set"
    assert manifest["prompt_set"] == str(external_prompt_set)
    assert manifest["prompt_set_is_repo_relative"] is False


def test_audit_sample_includes_judgment_provenance_fields(tmp_path):
    copy_core_files(tmp_path)
    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["run_id"] = "run_audit_provenance"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0
    run_dir = tmp_path / "reports/run_audit_provenance"
    assert main(["audit", str(run_dir), "--sample-rate", "0.15", "--seed", "1729"]) == 0

    with (run_dir / "audit_sample.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    jsonl_rows = read_jsonl(run_dir / "audit_sample.jsonl")
    expected_fields = {
        "run_id",
        "prompt_hash",
        "response_hash",
        "judge_id",
        "judge_version",
    }
    assert expected_fields.issubset(rows[0])
    assert expected_fields.issubset(jsonl_rows[0])
    assert rows[0]["run_id"] == "run_audit_provenance"
    assert rows[0]["judge_id"] == "mock"


def test_non_hex_prompt_hash_rejected(tmp_path):
    copy_core_files(tmp_path)
    records = Path("data/seed_prompts.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(records[0])
    first["prompt_hash"] = "g" * 64
    records[0] = json.dumps(first)
    prompt_path = tmp_path / "data/seed_prompts.jsonl"
    prompt_path.write_text("\n".join(records) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="lowercase sha256 hex|does not match"):
        main(["validate-prompts", str(prompt_path)])
