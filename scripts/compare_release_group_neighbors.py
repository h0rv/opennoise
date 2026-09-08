"""Write a bounded local comparison of direct and release-group neighborhoods."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from musix.local_release_group_neighbor_comparison import (
    LocalReleaseGroupNeighborComparisonError,
    compare_neighbors,
)

_DEFAULT_SEEDS = ("item5", "item94", "item379", "item675", "item577")


def main() -> int:
    """Write the requested bounded local comparison JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--frozen-peer-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--limit", type=int, default=10)
    arguments = parser.parse_args()
    try:
        result = compare_neighbors(
            evidence_database=arguments.database,
            evidence_artifact=arguments.artifact,
            frozen_peer_index=arguments.frozen_peer_index,
            query_seed_ids=tuple(arguments.seed) or _DEFAULT_SEEDS,
            limit=arguments.limit,
        )
    except (LocalReleaseGroupNeighborComparisonError, OSError, sqlite3.Error) as error:
        sys.stderr.write(f"release-group neighborhood comparison failed: {error}\n")
        return 2
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sys.stdout.write("release-group neighborhood comparison complete\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
