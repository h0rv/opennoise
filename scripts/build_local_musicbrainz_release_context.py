"""Export or independently replay retained offline release-credit context metadata."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.catalog.musicbrainz_release_context import (
    verify_artist_release_contexts,
    write_artist_release_contexts,
)


def main() -> int:
    """Keep the portable source defaults fixed while requiring a local destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-catalog-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    operation = (
        verify_artist_release_contexts if args.verify_only else write_artist_release_contexts
    )
    result = operation(
        direct_catalog_directory=args.direct_catalog_directory,
        output_directory=args.output_directory,
    )
    sys.stdout.write(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"artist_paths", "genre_paths", "artifacts"}
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
