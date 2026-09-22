"""Write one bounded, evaluation-only exact artist--genre H3 recovery report."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_artist_genre_h3_recovery import (
    evaluate_direct_artist_genre_h3_positive_recovery,
)


def main() -> int:
    """Require all custody-bound inputs and refuse to overwrite a report."""
    parser = argparse.ArgumentParser(
        prog="evaluate-musicbrainz-direct-artist-genre-h3-positive-recovery"
    )
    parser.add_argument("--custody-receipt", type=Path, required=True)
    parser.add_argument("--custody-object-store", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--bridge-receipt", type=Path, required=True)
    parser.add_argument("--bridge-receipt-sha256", required=True)
    parser.add_argument("--historical-rebuild-receipt", type=Path, required=True)
    parser.add_argument("--historical-rebuild-receipt-sha256", required=True)
    parser.add_argument("--expected-h3-raw-sha256", required=True)
    parser.add_argument("--expected-h3-database-sha256", required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite evaluation: {arguments.output}")
    report = evaluate_direct_artist_genre_h3_positive_recovery(
        custody_receipt_path=arguments.custody_receipt,
        custody_object_store=arguments.custody_object_store,
        reconciliation_path=arguments.reconciliation,
        bridge_path=arguments.bridge,
        bridge_receipt_path=arguments.bridge_receipt,
        bridge_receipt_sha256=arguments.bridge_receipt_sha256,
        historical_rebuild_receipt_path=arguments.historical_rebuild_receipt,
        historical_rebuild_receipt_sha256=arguments.historical_rebuild_receipt_sha256,
        expected_h3_raw_sha256=arguments.expected_h3_raw_sha256,
        expected_h3_database_sha256=arguments.expected_h3_database_sha256,
        historical_database_path=arguments.historical_database,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as output:
        output.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
