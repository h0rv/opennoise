"""Write frozen direct-P136 predictions, their receipt, and a positive-only diagnostic."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from opennoise.evidence.acousticbrainz_wikidata_recording_diagnostic import (
    diagnose_positive_only_recordings,
    require_local_diagnostic_output,
    write_frozen_wikidata_predictions,
)


def main() -> int:
    """Construct predictions before opening the source label columns."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--credit-database", required=True, type=Path)
    parser.add_argument("--public-database", required=True, type=Path)
    parser.add_argument("--prediction-output", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--diagnostic-output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        require_local_diagnostic_output(arguments.diagnostic_output)
        write_frozen_wikidata_predictions(
            arguments.source,
            arguments.credit_database,
            arguments.public_database,
            arguments.prediction_output,
            arguments.receipt_output,
        )
        diagnostic = diagnose_positive_only_recordings(
            arguments.source,
            arguments.credit_database,
            arguments.public_database,
            arguments.prediction_output,
            arguments.receipt_output,
        )
        if arguments.diagnostic_output.exists():
            raise FileExistsError("refusing to overwrite a positive-only diagnostic")
        arguments.diagnostic_output.parent.mkdir(parents=True, exist_ok=True)
        with arguments.diagnostic_output.open("x", encoding="utf-8") as output:
            output.write(diagnostic.model_dump_json(indent=2) + "\n")
    except (OSError, TypeError, ValueError, sqlite3.Error) as error:
        sys.stderr.write(f"AcousticBrainz recording diagnostic failed: {error}\n")
        return 2
    sys.stdout.write(diagnostic.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
