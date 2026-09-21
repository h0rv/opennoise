"""Build a blind Last.fm ArtistTags2007 artist and genre review packet."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from opennoise.evidence.lastfm_artist_genre_review import build_lastfm_artist_genre_review


def _publish_no_replace(path: Path, payload: bytes) -> None:
    """Publish bytes atomically without replacing an existing review packet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
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


def main() -> int:
    """Write one deterministic, unlabeled review packet."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=100)
    arguments = parser.parse_args()
    packet = build_lastfm_artist_genre_review(arguments.archive, sample_size=arguments.sample_size)
    payload = (packet.model_dump_json(indent=2) + "\n").encode("utf-8")
    _publish_no_replace(arguments.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
