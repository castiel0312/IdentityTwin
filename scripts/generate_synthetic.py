#!/usr/bin/env python3
"""
Generate the deterministic synthetic identity dataset.

The dataset is committed to the repository so that the calibration report and
the regression tests always run against exactly the same data. Regenerating it
with the same seed must not change a single byte.
"""

import json
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
)

from app.core.config import settings
from app.risk.synthetic_data import (
    COHORT_SIZES,
    TOTAL_IDENTITIES,
    build_profiles,
    profile_fixture,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(REPO_ROOT, "data", "synthetic", "synthetic_identities.json")


def generate(output_path: str = OUTPUT_PATH) -> str:
    seed = settings.RISK_SYNTHETIC_SEED
    payload = profile_fixture(seed)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")

    profiles = build_profiles(seed)
    print(f"Synthetic dataset written to: {output_path}")
    print(f"Seed: {seed}")
    print(f"Identities: {len(profiles)} (expected {TOTAL_IDENTITIES})")
    for cohort, size in COHORT_SIZES.items():
        print(f"  - {cohort}: {size}")
    return output_path


if __name__ == "__main__":
    generate()
