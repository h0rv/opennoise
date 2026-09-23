"""Build a local-only literal Last.fm ArtistTags2007 candidate artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.evidence.lastfm_artisttags2007_seed_candidates import (
    build_lastfm_artisttags2007_literal_seed_candidates,
    compare_lastfm_artisttags2007_candidates_to_public_map,
)


def main() -> int:
    """Write candidates first, with an optional terminal public-map comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--seed-vocabulary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-map", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    arguments = parser.parse_args()
    if (arguments.public_map is None) != (arguments.comparison_output is None):
        parser.error("--public-map and --comparison-output must be supplied together")
    candidate = build_lastfm_artisttags2007_literal_seed_candidates(
        arguments.archive, arguments.seed_vocabulary
    )
    _write_new(arguments.output, candidate.model_dump_json(indent=2) + "\n")
    if arguments.public_map is not None and arguments.comparison_output is not None:
        comparison = compare_lastfm_artisttags2007_candidates_to_public_map(
            candidate, arguments.public_map
        )
        _write_new(arguments.comparison_output, comparison.model_dump_json(indent=2) + "\n")
    return 0


def _write_new(path: Path, payload: str) -> None:
    """Avoid replacing a sealed local candidate or comparison artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


if __name__ == "__main__":
    raise SystemExit(main())
