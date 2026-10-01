"""Build a bounded exact-UUID projection from retained MusicBrainz bulk files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import HttpUrl

from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import (
    CoreArtistPrefixReceipt,
    build_bulk_artist_tag_artifact,
)
from opennoise.models.sources import DownloadSource

_SNAPSHOT = "20260930-002222"
_ARCHIVE_URL = (
    f"https://data.metabrainz.org/pub/musicbrainz/data/fullexport/{_SNAPSHOT}/mbdump.tar.bz2"
)
_DERIVED_URL = (
    "https://data.metabrainz.org/pub/musicbrainz/data/fullexport/"
    f"{_SNAPSHOT}/mbdump-derived.tar.bz2"
)


def main() -> int:
    """Create a fresh local research projection and replay it from pinned bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-directory",
        type=Path,
        default=Path(".cache/musicbrainz-bulk-artist-tags-20260930-v1/source"),
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=Path(".cache/microgenre-features-primary-v1/artist-features.jsonl"),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path(".cache/musicbrainz-bulk-artist-tags-20260930-rebuilt"),
    )
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory already exists; choose a new path")

    derived_source = DownloadSource(
        id="musicbrainz_bulk_derived_20260930",
        adapter="musicbrainz_postgres_derived_v1",
        snapshot=_SNAPSHOT,
        url=HttpUrl(_DERIVED_URL),
        discovery_url=HttpUrl("https://musicbrainz.org/doc/MusicBrainz_Database/Download"),
        expected_content_type="application/octet-stream",
        compression="tar.bz2",
        expected_bytes=520_485_348,
        checksum_algorithm="sha256",
        checksum="e1fb2f376e5d45c5d5a0be8cbe9f978218c4be14c0304fb0ffc10316f8c641ab",
        data_license="CC-BY-NC-SA-3.0",
        license_url="https://musicbrainz.org/doc/About/Data_License",
        rights_classification="restricted_research",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=False,
    )
    core_receipt = CoreArtistPrefixReceipt(
        snapshot=_SNAPSHOT,
        archive_url=_ARCHIVE_URL,
        archive_bytes=7_577_615_628,
        archive_sha256="4342c77212a8807e351e619b49162bc796e19419628bad3c9e791dbdd8e5f587",
        prefix_bytes=209_715_200,
        prefix_sha256="bcbc97886d8226c12d7a6f2f28246498fdd961840be516b85f14dc6a6a0cc7a0",
        artist_member_bytes=441_457_090,
        artist_member_sha256="6234d354577f0460b56e62c6696b8d47d3b4da8a25c62f8fe27d61b5b25e6d4d",
        artist_row_count=2_999_670,
        schema_sequence="31",
        observed_at="2026-09-30T20:34:00Z",
        whole_archive_sha256_verified=False,
    )
    receipt = build_bulk_artist_tag_artifact(
        derived_archive=args.source_directory / "mbdump-derived.tar.bz2",
        derived_source=derived_source,
        core_prefix=args.source_directory / "mbdump-core-prefix-209715200.bz2",
        core_receipt=core_receipt,
        selection_source_path=args.selection,
        selection_artist_count=198_409,
        derived_observed_at="2026-09-30T01:54:38Z",
        output_directory=args.output_directory,
    )
    sys.stdout.write(f"{receipt['output_sha256']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
