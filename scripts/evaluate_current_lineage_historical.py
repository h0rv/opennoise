"""Evaluate sealed current reconstruction signals against held-out history."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.checkpoints.current_lineage_evaluation import (
    CurrentLineageEvaluationError,
    CurrentLineageEvaluationInputs,
    build_current_lineage_historical_evaluation,
    write_current_lineage_historical_evaluation,
)


def _shared_cache_root() -> Path:
    """Find the cache beside the Git common checkout without environment state."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to locate the shared OpenNoise cache")
    completed = subprocess.run(  # noqa: S603 - fixed git subcommand after PATH lookup.
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).parent / ".cache"


def _parser(cache: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=cache)
    parser.add_argument(
        "--output", type=Path, default=cache / "current-lineage-historical-evaluation-v1.json"
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=cache / "current-lineage-historical-evaluation-v1.receipt.json",
    )
    parser.add_argument(
        "--construction-checkpoint",
        type=Path,
        default=cache / "reconstruction-checkpoint-v1.json",
    )
    parser.add_argument("--graph-database", type=Path, default=cache / "evidence-graph-v2.sqlite")
    parser.add_argument(
        "--graph-receipt", type=Path, default=cache / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--full-graph", type=Path, default=cache / "hierarchy-fusion-v1/full-graph-signal.json"
    )
    parser.add_argument(
        "--full-graph-receipt",
        type=Path,
        default=cache / "hierarchy-fusion-v1/full-graph-signal.receipt.json",
    )
    neighborhood = cache / (
        "genre-colisten-neighborhoods-v1/"
        "32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141"
    )
    parser.add_argument("--neighborhoods", type=Path, default=neighborhood / "artifact.json")
    parser.add_argument("--neighborhoods-receipt", type=Path, default=neighborhood / "receipt.json")
    parser.add_argument(
        "--neighborhoods-database",
        type=Path,
        default=neighborhood / "genre-neighborhoods.sqlite",
    )
    parser.add_argument(
        "--hierarchy", type=Path, default=cache / "hierarchy-fusion-v1/artifact.json"
    )
    parser.add_argument(
        "--historical-reference",
        type=Path,
        default=cache / "historical-signal-hierarchy/historical-signal-hierarchy-v1.json",
    )
    return parser


def main() -> int:
    """Write a terminal report after replaying the construction-only checkpoint."""
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--cache-root", type=Path)
    preliminary, _ = bootstrap.parse_known_args()
    cache = preliminary.cache_root or _shared_cache_root()
    args = _parser(cache).parse_args()
    try:
        report = build_current_lineage_historical_evaluation(
            CurrentLineageEvaluationInputs(
                root=args.cache_root.parent,
                construction_checkpoint=args.construction_checkpoint,
                graph_database=args.graph_database,
                graph_receipt=args.graph_receipt,
                full_graph=args.full_graph,
                full_graph_receipt=args.full_graph_receipt,
                neighborhoods=args.neighborhoods,
                neighborhoods_receipt=args.neighborhoods_receipt,
                neighborhoods_database=args.neighborhoods_database,
                hierarchy=args.hierarchy,
                historical_reference=args.historical_reference,
            )
        )
        write_current_lineage_historical_evaluation(args.output, args.receipt, report)
    except (OSError, CurrentLineageEvaluationError, ValueError) as error:
        sys.stderr.write(f"current-lineage historical evaluation failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
