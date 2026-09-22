"""Publish the verified MusicBrainz credit source slice to a portable object store."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.deployment.musicbrainz_credit_portable_release import (
    MusicBrainzCreditCatalogCustodyScope,
    build_portable_musicbrainz_credit_source,
    publish_portable_musicbrainz_credit_source,
)
from opennoise.storage import LocalObjectStore


def main() -> int:
    """Package only already-verified CC0 core metadata; never fetch MusicBrainz."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hydration-artifact", required=True, type=Path)
    parser.add_argument("--credit-artifact", required=True, type=Path)
    parser.add_argument("--cache-directory", required=True, type=Path)
    parser.add_argument("--candidate-database", required=True, type=Path)
    parser.add_argument("--candidate-report", required=True, type=Path)
    parser.add_argument("--custody-scope", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    arguments = parser.parse_args()
    custody_scope = MusicBrainzCreditCatalogCustodyScope.model_validate_json(
        arguments.custody_scope.read_bytes()
    )
    source = build_portable_musicbrainz_credit_source(
        hydration_artifact=arguments.hydration_artifact,
        credit_artifact=arguments.credit_artifact,
        cache_directory=arguments.cache_directory,
        candidate_database=arguments.candidate_database,
        candidate_report=arguments.candidate_report,
    )
    receipt = publish_portable_musicbrainz_credit_source(
        source,
        store=LocalObjectStore(arguments.object_store),
        custody_scope=custody_scope,
        candidate_database=arguments.candidate_database,
        candidate_report=arguments.candidate_report,
        receipt_output=arguments.receipt,
    )
    print(receipt.model_dump_json())  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
