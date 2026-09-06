"""Build and publish the bounded MusicBrainz artist-to-Spotify bridge."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from musix.musicbrainz_spotify_bridge import (
    SpotifyBridgeSettings,
    build_musicbrainz_spotify_bridge,
    publish_musicbrainz_spotify_bridge,
)
from musix.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Expose source, historical join, and bounded extraction arguments."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-spotify-bridge")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--max-archive-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--max-member-bytes", type=int, default=64 * 1024**3)
    parser.add_argument("--max-record-bytes", type=int, default=64 * 1024**2)
    parser.add_argument("--max-records", type=int, default=10_000_000)
    parser.add_argument("--max-decompression-ratio", type=int, default=128)
    parser.add_argument("--max-relations-per-artist", type=int, default=512)
    parser.add_argument("--max-bridge-rows", type=int, default=1_000_000)
    return parser


def _write_receipt(path: Path, receipt_json: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(receipt_json)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build, verify, and custody one metadata-only bridge."""
    arguments = build_parser().parse_args()
    settings = SpotifyBridgeSettings(
        max_archive_bytes=arguments.max_archive_bytes,
        max_member_bytes=arguments.max_member_bytes,
        max_record_bytes=arguments.max_record_bytes,
        max_records=arguments.max_records,
        max_decompression_ratio=arguments.max_decompression_ratio,
        max_relations_per_artist=arguments.max_relations_per_artist,
        max_bridge_rows=arguments.max_bridge_rows,
    )
    artifact = build_musicbrainz_spotify_bridge(
        arguments.archive, arguments.historical_database, settings
    )
    receipt = publish_musicbrainz_spotify_bridge(
        artifact,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    _write_receipt(arguments.receipt, receipt.model_dump_json(indent=2))
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
