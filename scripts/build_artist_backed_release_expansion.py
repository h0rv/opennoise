"""Run one bounded, reproducible artist-backed MusicBrainz metadata build."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from opennoise.serving.artist_backed_release_expansion import (
    ExpansionBuildRequest,
    build_artist_backed_release_expansion,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--cache-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--max-genres", type=int, default=48)
    parser.add_argument("--max-seeds-per-genre", type=int, default=2)
    parser.add_argument("--max-releases-per-seed", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run the source-module build and emit its strict receipt."""
    arguments = _arguments()
    report = asyncio.run(
        build_artist_backed_release_expansion(
            ExpansionBuildRequest(
                source_database=arguments.source_database,
                database=arguments.database,
                output=arguments.output,
                object_store=arguments.object_store,
                cache_directory=arguments.cache_directory,
                report_path=arguments.report,
                user_agent=arguments.user_agent,
                max_genres=arguments.max_genres,
                max_seeds_per_genre=arguments.max_seeds_per_genre,
                max_releases_per_seed=arguments.max_releases_per_seed,
                max_attempts=arguments.max_attempts,
                timeout_seconds=arguments.timeout_seconds,
                offline=arguments.offline,
            )
        )
    )
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
