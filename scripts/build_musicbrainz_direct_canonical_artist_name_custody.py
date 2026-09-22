"""Build the custody-only canonical artist-name projection for direct MusicBrainz MBIDs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    build_direct_canonical_artist_name_custody,
    verify_direct_canonical_artist_name_custody,
)


def main() -> int:
    """Build and verify one compact name-fact custody object."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-custody-receipt", required=True, type=Path)
    parser.add_argument("--direct-object-store", required=True, type=Path)
    parser.add_argument("--metadata-artifact", required=True, type=Path)
    parser.add_argument("--metadata-database", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = build_direct_canonical_artist_name_custody(
        direct_custody_receipt=arguments.direct_custody_receipt,
        direct_object_store=arguments.direct_object_store,
        metadata_artifact=arguments.metadata_artifact,
        metadata_database=arguments.metadata_database,
        object_store=arguments.object_store,
        receipt_output=arguments.receipt_output,
    )
    verify_direct_canonical_artist_name_custody(receipt, object_store=arguments.object_store)
    sys.stdout.write(
        json.dumps(
            {
                "canonical_name_count": receipt.canonical_name_count,
                "names_object_sha256": receipt.names_object_sha256,
                "public_export_authorized": receipt.public_export_authorized,
                "serving_authorized": receipt.serving_authorized,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
