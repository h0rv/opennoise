"""Reproduce all MusicBrainz core artist names from a pinned complete table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import CoreArtistPrefixReceipt
from opennoise.ingest.musicbrainz.core_artist_identities import build_core_artist_identities


def main() -> int:
    """Write a fresh core-only identity pack, not a genre or tag projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            ".cache/musicbrainz-bulk-artist-tags-20260930-v1/source/"
            "mbdump-core-prefix-209715200.bz2"
        ),
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    receipt = CoreArtistPrefixReceipt(
        snapshot="20260930-002222",
        archive_url=(
            "https://data.metabrainz.org/pub/musicbrainz/data/fullexport/"
            "20260930-002222/mbdump.tar.bz2"
        ),
        archive_bytes=7_577_615_628,
        archive_sha256="4342c77212a8807e351e619b49162bc796e19419628bad3c9e791dbdd8e5f587",
        prefix_bytes=209_715_200,
        prefix_sha256="bcbc97886d8226c12d7a6f2f28246498fdd961840be516b85f14dc6a6a0cc7a0",
        artist_member_bytes=441_457_090,
        artist_member_sha256="6234d354577f0460b56e62c6696b8d47d3b4da8a25c62f8fe27d61b5b25e6d4d",
        artist_row_count=2_999_670,
        schema_sequence="31",
        observed_at="2026-09-30T20:34:00Z",
    )
    result = build_core_artist_identities(
        args.source,
        receipt,
        args.output_directory,
        license_capture=args.source.parent / "license.html",
    )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
