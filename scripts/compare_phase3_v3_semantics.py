"""Write a hash-pinned, read-only v3-versus-sealed semantic comparison report."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.pipeline.phase3_v3_semantic_comparator import (
    Phase3V3SemanticInputs,
    compare_phase3_v3_semantics,
)


def main() -> int:
    """Parse the pinned inputs, write the report, and signal semantic equality."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-model", type=Path, required=True)
    parser.add_argument("--sealed-model", type=Path, required=True)
    parser.add_argument("--v3-database", type=Path, required=True)
    parser.add_argument("--sealed-database", type=Path, required=True)
    parser.add_argument("--v3-model-sha256", required=True)
    parser.add_argument("--sealed-model-sha256", required=True)
    parser.add_argument("--v3-database-sha256", required=True)
    parser.add_argument("--sealed-database-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    report = compare_phase3_v3_semantics(
        Phase3V3SemanticInputs(
            v3_model=arguments.v3_model,
            sealed_model=arguments.sealed_model,
            v3_database=arguments.v3_database,
            sealed_database=arguments.sealed_database,
            expected_v3_model_sha256=arguments.v3_model_sha256,
            expected_sealed_model_sha256=arguments.sealed_model_sha256,
            expected_v3_database_sha256=arguments.v3_database_sha256,
            expected_sealed_database_sha256=arguments.sealed_database_sha256,
        )
    )
    arguments.report.write_text(report.to_json(), encoding="utf-8")
    return 0 if report.equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
