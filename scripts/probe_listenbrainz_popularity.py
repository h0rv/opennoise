"""Fetch local-only ListenBrainz top-ten rankings for supplied artist MBIDs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from uuid import UUID

from opennoise.evidence.musicbrainz_album_review import MusicBrainzAlbumReviewPacket
from opennoise.ingest.listenbrainz.popularity import (
    PopularityProbeReport,
    compare_album_candidate_packet,
    fetch_popularity_probe,
)

_MAX_PACKET_BYTES = 16 * 1024 * 1024


def _write_once(path: Path, payload: bytes) -> None:
    """Write the local receipt-bound artifact without replacing an earlier run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".staging", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def _run(arguments: argparse.Namespace) -> PopularityProbeReport:
    bundle = await fetch_popularity_probe(arguments.artist_mbid)
    packet_sha256: str | None = None
    overlaps = ()
    if arguments.album_packet is not None:
        packet_bytes = arguments.album_packet.read_bytes()
        if len(packet_bytes) > _MAX_PACKET_BYTES:
            raise ValueError("album review packet exceeds the bounded input size")
        packet = MusicBrainzAlbumReviewPacket.model_validate_json(packet_bytes, strict=True)
        packet_sha256 = hashlib.sha256(packet_bytes).hexdigest()
        overlaps = compare_album_candidate_packet(bundle, packet)
    return PopularityProbeReport(
        bundle=bundle,
        album_packet_sha256=packet_sha256,
        album_candidate_overlap=overlaps,
    )


def main() -> int:
    """Fetch only explicitly supplied IDs and write a local-only report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artist-mbid",
        action="append",
        required=True,
        type=UUID,
        help="exact MusicBrainz artist MBID; may be supplied at most 20 times",
    )
    parser.add_argument(
        "--album-packet",
        type=Path,
        help="optional retained MusicBrainz album review packet for exact candidate-ID joins",
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = asyncio.run(_run(arguments))
    _write_once(arguments.output, (report.model_dump_json(indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
