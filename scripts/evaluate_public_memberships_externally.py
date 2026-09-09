"""Locally compare the sealed public membership model with MusicBrainz tag evidence."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from musix.serving.public.public_membership_external_evaluation import evaluate_public_memberships_externally


def main() -> int:
    """Write one local-only external evaluation report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--musicbrainz-research-database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--threshold", type=float, action="append", dest="thresholds")
    arguments = parser.parse_args()
    thresholds = (
        tuple(arguments.thresholds) if arguments.thresholds is not None else (1.0, 3.0, 5.0)
    )
    try:
        report = evaluate_public_memberships_externally(
            arguments.public_database,
            arguments.musicbrainz_research_database,
            thresholds=thresholds,
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.stderr.write(f"external public membership evaluation failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
