"""Write a hash-bound, read-only Phase 3 candidate-versus-sealed SQLite report."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.pipeline.phase3_replay_comparator import compare_phase3_replay_databases


def main() -> int:
    """Compare the two explicitly pinned database files without mutating either."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sealed", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--sealed-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    comparison = compare_phase3_replay_databases(
        arguments.candidate,
        arguments.sealed,
        expected_candidate_sha256=arguments.candidate_sha256,
        expected_sealed_sha256=arguments.sealed_sha256,
    )
    arguments.report.write_text(comparison.to_json(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
