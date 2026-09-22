"""Restore and verify the portable MusicBrainz credit catalog without network access."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.deployment.musicbrainz_credit_portable_release import (
    PortableMusicBrainzCreditReleaseReceipt,
    restore_portable_musicbrainz_credit_catalog,
)
from opennoise.storage import LocalObjectStore


def main() -> int:
    """Restore one fresh catalog artifact from the release-custodied source object."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--candidate-database", required=True, type=Path)
    parser.add_argument("--candidate-report", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = PortableMusicBrainzCreditReleaseReceipt.model_validate_json(
        arguments.receipt.read_bytes()
    )
    report = restore_portable_musicbrainz_credit_catalog(
        receipt,
        store=LocalObjectStore(arguments.object_store),
        candidate_database=arguments.candidate_database,
        candidate_report=arguments.candidate_report,
    )
    print(report.model_dump_json())  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
