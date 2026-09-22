"""Verify the canonical artist-name custody object, with optional source replay."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyReceipt,
    verify_direct_canonical_artist_name_custody,
    verify_direct_canonical_artist_name_custody_from_inputs,
)


def main() -> int:
    """Verify only tracked bytes, or also replay the exact local source bindings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--direct-custody-receipt", type=Path)
    parser.add_argument("--direct-object-store", type=Path)
    parser.add_argument("--metadata-artifact", type=Path)
    parser.add_argument("--metadata-database", type=Path)
    arguments = parser.parse_args()
    receipt = DirectCanonicalArtistNameCustodyReceipt.model_validate_json(
        arguments.receipt.read_bytes()
    )
    replay_values = (
        arguments.direct_custody_receipt,
        arguments.direct_object_store,
        arguments.metadata_artifact,
        arguments.metadata_database,
    )
    if any(value is None for value in replay_values):
        if any(value is not None for value in replay_values):
            parser.error("all source replay arguments must be supplied together")
        verify_direct_canonical_artist_name_custody(receipt, object_store=arguments.object_store)
    else:
        verify_direct_canonical_artist_name_custody_from_inputs(
            receipt,
            object_store=arguments.object_store,
            direct_custody_receipt=arguments.direct_custody_receipt,
            direct_object_store=arguments.direct_object_store,
            metadata_artifact=arguments.metadata_artifact,
            metadata_database=arguments.metadata_database,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
