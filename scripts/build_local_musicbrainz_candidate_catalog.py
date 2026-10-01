"""Build a local exact-ID enriched catalog from the checked-in portable MusicBrainz corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.catalog.musicbrainz_candidate import build_local_musicbrainz_candidate_catalog


def main() -> int:
    """Seal a deterministic local candidate without changing any release inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--direct-receipt",
        type=Path,
        default=Path("config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json"),
    )
    parser.add_argument(
        "--direct-object-store",
        type=Path,
        default=Path("data/release/musicbrainz-direct-proper-genre-custody-v1/objects"),
    )
    parser.add_argument(
        "--name-receipt",
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
        "--output-directory",
        type=Path,
        default=Path(".cache/musicbrainz-candidate-catalog"),
    )
    args = parser.parse_args()
    receipt = build_local_musicbrainz_candidate_catalog(
        direct_receipt_path=args.direct_receipt,
        direct_object_store=args.direct_object_store,
        name_receipt_path=args.name_receipt,
        name_object_store=args.name_object_store,
        output_directory=args.output_directory,
    )
    sys.stdout.write(receipt.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
