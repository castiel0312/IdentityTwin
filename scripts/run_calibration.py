#!/usr/bin/env python3
"""
Measure the shipped risk engine on the committed synthetic dataset.

The script replays every synthetic identity through the pure engine and writes
the measured result to docs/calibration-report.md. It never edits the
configuration: the report is a measurement, not a fit.
"""

import json
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
)

from app.core.config import settings
from app.risk.calibration import render_markdown, run_calibration

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURE_PATH = os.path.join(REPO_ROOT, "data", "synthetic", "synthetic_identities.json")
REPORT_PATH = os.path.join(REPO_ROOT, "docs", "calibration-report.md")


def run(report_path: str = REPORT_PATH) -> str:
    seed = settings.RISK_SYNTHETIC_SEED
    report = run_calibration(seed)
    markdown = render_markdown(report)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)

    metrics = {
        "seed": seed,
        "identities": report.overall.identities,
        "calibration_false_positive_rate": report.calibration.false_positive_rate,
        "holdout_false_positive_rate": report.holdout.false_positive_rate,
        "calibration_detection_rate": report.calibration.detection_rate,
        "holdout_detection_rate": report.holdout.detection_rate,
        "holdout_sessions": report.holdout.sessions,
        "holdout_flagged_sessions": report.holdout.flagged_sessions,
    }
    print(json.dumps(metrics, indent=2))
    print(f"Calibration report written to: {report_path}")
    if os.path.exists(FIXTURE_PATH):
        print(f"Dataset: {FIXTURE_PATH}")
    return report_path


if __name__ == "__main__":
    run()
