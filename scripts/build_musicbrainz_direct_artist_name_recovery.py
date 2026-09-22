"""Build a custody-only exact-MBID artist-name recovery object."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    build_direct_artist_name_recovery,
    verify_direct_artist_name_recovery,
)

_PINNED_DIRECT_RECEIPT_SHA256 = "41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615"
_PINNED_NAME_RECEIPT_SHA256 = "06445802bec5120d2068dfb51afc610211063f72994c1862bbc8bad05dda4f25"


def main() -> int:
    """Build and verify a new recovery receipt/object pair."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--direct-custody-receipt",
        type=Path,
        default=Path("config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json"),
    )
    parser.add_argument(
        "--direct-object-store",
        type=Path,
        default=Path("data/release/musicbrainz-direct-proper-genre-custody-v1/objects"),
    )
    parser.add_argument(
        "--name-custody-receipt",
        type=Path,
        default=Path(
            "config/releases/musicbrainz-direct-canonical-artist-name-custody-v1/receipt.json"
        ),
    )
    parser.add_argument(
        "--name-object-store",
        type=Path,
        default=Path("data/release/musicbrainz-direct-canonical-artist-name-custody-v1/objects"),
    )
    parser.add_argument(
        "--source-archive",
        type=Path,
        default=Path(
            "data/source-cache/raw/sha256/"
            "396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d"
        ),
    )
    parser.add_argument(
        "--object-store",
        type=Path,
        default=Path(".cache/musicbrainz-direct-artist-name-recovery-v1/objects"),
    )
    parser.add_argument(
        "--receipt-output",
        type=Path,
        default=Path(".cache/musicbrainz-direct-artist-name-recovery-v1/receipt.json"),
    )
    arguments = parser.parse_args()
    receipt = build_direct_artist_name_recovery(
        direct_custody_receipt=arguments.direct_custody_receipt,
        direct_object_store=arguments.direct_object_store,
        direct_custody_receipt_sha256=_PINNED_DIRECT_RECEIPT_SHA256,
        name_custody_receipt=arguments.name_custody_receipt,
        name_object_store=arguments.name_object_store,
        name_custody_receipt_sha256=_PINNED_NAME_RECEIPT_SHA256,
        source_archive=arguments.source_archive,
        object_store=arguments.object_store,
        receipt_output=arguments.receipt_output,
    )
    verify_direct_artist_name_recovery(receipt, object_store=arguments.object_store)
    sys.stdout.write(
        json.dumps(
            {
                "recovery_target_count": receipt.recovery_target_count,
                "recovered_unique_mbid_count": receipt.recovered_unique_mbid_count,
                "conflicting_mbid_count": receipt.conflicting_mbid_count,
                "missing_mbid_count": receipt.missing_mbid_count,
                "invalid_name_only_mbid_count": receipt.invalid_name_only_mbid_count,
                "recovery_object_sha256": receipt.recovery_object_sha256,
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
