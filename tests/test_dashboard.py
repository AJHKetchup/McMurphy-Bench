import json
import re
from pathlib import Path


def test_dashboard_embedded_report_matches_generated_report():
    html = Path("index.html").read_text(encoding="utf-8")
    report = json.loads(Path("reports/sample_report.json").read_text(encoding="utf-8"))
    match = re.search(
        r"const sampleReport = ([\s\S]*?);\n\n    const domains =",
        html,
    )

    assert match is not None
    assert json.loads(match.group(1)) == report
    assert report["schema_version"] == "0.2.0"


def test_dashboard_displays_unmeasured_safety_as_nm():
    html = Path("index.html").read_text(encoding="utf-8")

    assert 'unsafe_fulfillment_measured === false ? "N/M"' in html
    assert "score-neutral" in html
