import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

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


def copy_core_files(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "data").mkdir()
    shutil.copy(Path("pyproject.toml"), tmp_path / "pyproject.toml")
    shutil.copy(Path("data/schema.json"), tmp_path / "data/schema.json")
    shutil.copy(Path("data/seed_prompts.jsonl"), tmp_path / "data/seed_prompts.jsonl")


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
