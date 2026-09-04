"""Emit a deterministic, cache-only public representative coverage report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.ml.representative_coverage import (
    RepresentativeCoverageSettings,
    representative_coverage,
)


def main() -> int:
    """Read one SQLite artifact and write its typed public coverage report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    arguments = parser.parse_args()
    report = representative_coverage(
        arguments.database,
        RepresentativeCoverageSettings(max_metadata_candidates=arguments.max_metadata_candidates),
    )
    sys.stdout.write(f"{report.model_dump_json(indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
