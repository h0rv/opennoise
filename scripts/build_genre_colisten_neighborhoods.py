"""Build or replay the sealed, source-neutral co-listen genre neighborhood checkpoint."""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.genre_neighborhoods import (
    GenreNeighborhoodInputs,
    GenreNeighborhoodSettings,
    build_genre_neighborhoods,
    certify_neighborhood_cache,
    write_genre_neighborhoods,
)
from opennoise.ml.genre_neighborhoods.evaluation import write_quality_diagnostics


def _shared_cache() -> Path:
    """Locate the Git-common checkout cache, which is the same from linked worktrees."""
    common = subprocess.run(
        ("git", "rev-parse", "--path-format=absolute", "--git-common-dir"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(common).parent / ".cache"


def _parser() -> argparse.ArgumentParser:
    cache = _shared_cache()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-database", type=Path, default=cache / "evidence-graph-v2.sqlite")
    parser.add_argument(
        "--graph-receipt", type=Path, default=cache / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--colisten-database",
        type=Path,
        default=cache / "listenbrainz-dual-overlay-v1/colisten.sqlite",
    )
    parser.add_argument(
        "--colisten-receipt",
        type=Path,
        default=cache / "listenbrainz-dual-overlay-v1/colisten.receipt.json",
    )
    parser.add_argument(
        "--cache-directory", type=Path, default=cache / "genre-colisten-neighborhoods-v1"
    )
    parser.add_argument("--split-seed", type=int, default=20260913)
    parser.add_argument("--heldout-fraction", type=float, default=0.2)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--minimum-window-support", type=int, default=2)
    parser.add_argument("--minimum-raw-mass", type=float, default=0.05)
    parser.add_argument("--shrinkage-prior-mass", type=float, default=3.0)
    return parser


def main() -> int:
    """Build/replay the cache, then emit operational and evaluation-only reports."""
    args = _parser().parse_args()
    settings = GenreNeighborhoodSettings(
        split_seed=args.split_seed,
        heldout_fraction=args.heldout_fraction,
        top_k=args.top_k,
        minimum_window_support=args.minimum_window_support,
        minimum_raw_mass=args.minimum_raw_mass,
        shrinkage_prior_mass=args.shrinkage_prior_mass,
    )
    inputs = GenreNeighborhoodInputs(
        graph_database=args.graph_database,
        graph_receipt=args.graph_receipt,
        colisten_database=args.colisten_database,
        colisten_receipt=args.colisten_receipt,
        cache_directory=args.cache_directory,
    )
    started = time.monotonic()
    artifact = build_genre_neighborhoods(inputs, settings)
    output_directory = args.cache_directory / artifact.input_sha256
    output, receipt, diagnostics = (
        output_directory / "artifact.json",
        output_directory / "receipt.json",
        output_directory / "quality-diagnostics.json",
    )
    custody = write_genre_neighborhoods(output, receipt, artifact)
    certified = certify_neighborhood_cache(
        output_directory / "genre-neighborhoods.sqlite", artifact, custody
    )
    write_quality_diagnostics(certified, args.graph_database, diagnostics)
    report = {
        "logical_output_sha256": artifact.output_sha256,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "diagnostics": str(diagnostics),
    }
    write_atomic_bytes(
        output_directory / "run-report.json",
        json.dumps(report, sort_keys=True, indent=2).encode() + b"\n",
    )
    sys.stdout.write(
        json.dumps(
            {
                "artifact": artifact.model_dump(),
                "receipt": custody.model_dump(),
                "operational": report,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
