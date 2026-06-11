import json
import shutil
from pathlib import Path

import yaml

from mcmurphy.cli import main


def test_loop_smoke_outputs_run_bundle(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "data").mkdir()
    shutil.copy(Path("data/schema.json"), tmp_path / "data/schema.json")
    shutil.copy(Path("data/seed_prompts.jsonl"), tmp_path / "data/seed_prompts.jsonl")

    config = yaml.safe_load(Path("configs/run.example.yaml").read_text())
    config["output_dir"] = "reports"
    config["run_id"] = "run_test"
    config_path = tmp_path / "configs/run.example.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert main(["loop", str(config_path)]) == 0

    run_dir = tmp_path / "reports/run_test"
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "responses.jsonl").exists()
    assert (run_dir / "judgments.jsonl").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "audit_sample.csv").exists()

    report = json.loads((run_dir / "report.json").read_text())
    assert report["schema_version"] == "0.2.0"
    assert report["mli_weights"]
    assert "confidence_intervals" in report["models"][0]

