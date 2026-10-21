#!/usr/bin/env python3
"""
Export OpenAPI specification from the FastAPI application.
Generates packages/contracts/openapi.json from the live app schema without drift.
"""

import json
import os
import sys

# Ensure apps/api is on the path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
)

from app.main import app


def export_openapi() -> None:
    schema = app.openapi()
    output_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "packages", "contracts")
    )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "openapi.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    print(f"OpenAPI specification successfully exported to: {output_path}")
    print(f"Total API Paths: {len(schema.get('paths', {}))}")


if __name__ == "__main__":
    export_openapi()
