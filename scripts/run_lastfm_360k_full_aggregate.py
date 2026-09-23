"""Write one non-overwriting local Last.fm 360K aggregate receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.lastfm_360k import run_lastfm_360k_full_aggregate


def main() -> int:
    """Run the all-time, counts-only Last.fm diagnostic without serving it."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--working-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists() or arguments.working_database.exists():
        raise FileExistsError("aggregate output or working database already exists")
    artifact = run_lastfm_360k_full_aggregate(
        archive_path=arguments.archive,
        catalog_path=arguments.catalog,
        working_database_path=arguments.working_database,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
