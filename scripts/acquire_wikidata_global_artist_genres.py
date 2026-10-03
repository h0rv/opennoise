"""Acquire or replay the bounded open Wikidata artist-genre sample."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.wikidata.global_artist_genres import (
    CORE_DEFAULT,
    DEFAULT_PACK,
    acquire_global_artist_genres,
    retry_global_artist_genres_hydration,
    verify_global_artist_genres,
)


def main() -> None:
    """Acquire, hydrate, or offline-replay the bounded Wikidata evidence pack."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--core", type=Path, default=CORE_DEFAULT)
    parser.add_argument("--max-artists", type=int, default=3_000)
    parser.add_argument("--verify", action="store_true", help="replay an existing pack offline")
    parser.add_argument(
        "--retry-hydration",
        action="store_true",
        help="retry smaller exact-QID batches against the existing frozen roster",
    )
    arguments = parser.parse_args()
    if arguments.verify:
        manifest = verify_global_artist_genres(arguments.output, arguments.core)
    elif arguments.retry_hydration:
        manifest = retry_global_artist_genres_hydration(arguments.output, arguments.core)
    else:
        manifest = acquire_global_artist_genres(
            arguments.output, arguments.core, max_artists=arguments.max_artists
        )
    sys.stdout.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
