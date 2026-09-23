"""Verify and stream the declared local MusicBrainz derived tag archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.ingest.musicbrainz.derived_entity_tags import (
    DerivedEntityTagLimits,
    iter_derived_entity_tag_facts,
)
from opennoise.pipeline.manifest import load_download_source


def main() -> int:
    """Print local aggregate counts without writing or exporting derived data."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    parser.add_argument("--source-id", default="musicbrainz_postgres_derived_20260829")
    arguments = parser.parse_args()
    source = load_download_source(arguments.manifest, arguments.source_id)
    counts = {"recording": 0, "release": 0, "release_group": 0}
    for fact in iter_derived_entity_tag_facts(arguments.archive, source, DerivedEntityTagLimits()):
        counts[fact.entity_kind] += 1
    sys.stdout.write(f"{counts}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
