"""Replay the bounded AcousticBrainz/Wikidata recording-diagnostic feasibility audit."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from opennoise.evidence.acousticbrainz_wikidata_recording_feasibility import (
    audit_acousticbrainz_wikidata_recording_feasibility,
)


def main() -> int:
    """Write the hash-pinned aggregate feasibility receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--credit-database", required=True, type=Path)
    parser.add_argument("--public-database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        report = audit_acousticbrainz_wikidata_recording_feasibility(
            arguments.source, arguments.credit_database, arguments.public_database
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError, sqlite3.Error) as error:
        sys.stderr.write(f"AcousticBrainz/Wikidata feasibility audit failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
