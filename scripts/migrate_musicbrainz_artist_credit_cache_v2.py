"""Copy a v1 artist-credit cache into verified v2 projections without network access."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ingest.musicbrainz.artist_credit_enrichment import _projection_sha256
from opennoise.ingest.musicbrainz.release_hydration import CachedFailure, CachedResponse


def main() -> int:
    """Copy only validated safe payloads to an unused v2 cache directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.destination.exists():
        raise SystemExit("destination already exists; v1 cache is preserved")
    arguments.destination.mkdir(parents=True)
    count = 0
    for path in sorted(arguments.source.glob("*.json")):
        raw = path.read_bytes()
        try:
            cached = CachedResponse.model_validate_json(raw)
        except ValueError:
            CachedFailure.model_validate_json(raw)
            target = arguments.destination / path.name
            target.write_bytes(raw)
            continue
        migrated = cached.model_copy(
            update={
                "projection_sha256": _projection_sha256(
                    endpoint=cached.endpoint, payload=cached.payload
                )
            }
        )
        (arguments.destination / path.name).write_text(
            migrated.model_dump_json(exclude_none=True), encoding="utf-8"
        )
        count += 1
    print(count)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
