"""Build the compact custody-only MusicBrainz direct proper-genre source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    build_portable_direct_proper_genre_custody,
    verify_portable_direct_proper_genre_custody,
)


def main() -> int:
    """Build and immediately verify one custody-only source object."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-direct-proper-genre-custody")
    parser.add_argument("--seed-target", required=True, type=Path)
    parser.add_argument("--seed-target-byte-sha256", required=True)
    parser.add_argument("--seed-target-output-sha256", required=True)
    parser.add_argument("--reconciliation", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = build_portable_direct_proper_genre_custody(
        seed_target=arguments.seed_target,
        seed_target_byte_sha256=arguments.seed_target_byte_sha256,
        seed_target_output_sha256=arguments.seed_target_output_sha256,
        reconciliation=arguments.reconciliation,
        object_store=arguments.object_store,
        receipt_output=arguments.receipt_output,
    )
    verify_portable_direct_proper_genre_custody(receipt, object_store=arguments.object_store)
    sys.stdout.write(
        json.dumps(
            {
                "claim_count": receipt.claim_count,
                "claims_object_sha256": receipt.claims_object_sha256,
                "public_export_authorized": receipt.public_export_authorized,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
