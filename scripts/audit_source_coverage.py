"""Verify current source coverage and write a scope-safe checkpoint JSON artifact."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.checkpoints.source_coverage_audit import (
    SourceCoverageAuditError,
    SourceCoverageAuditInputs,
    build_source_coverage_audit,
    write_source_coverage_audit,
)


def _shared_cache_root() -> Path:
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


def _parser(root: Path, cache: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--cache-root", type=Path, default=cache)
    parser.add_argument("--output", type=Path, default=cache / "source-coverage-audit-v1.json")
    parser.add_argument("--graph-database", type=Path, default=cache / "evidence-graph-v2.sqlite")
    parser.add_argument(
        "--graph-receipt", type=Path, default=cache / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--full-graph", type=Path, default=cache / "hierarchy-fusion-v1/full-graph-signal.json"
    )
    parser.add_argument(
        "--release-group-evidence",
        type=Path,
        default=cache / "musicbrainz-release-group-evidence-candidate-v1/artifact.json",
    )
    parser.add_argument(
        "--artist-metadata",
        type=Path,
        default=cache / "musicbrainz-release-group-artist-metadata-v1/artifact.json",
    )
    parser.add_argument(
        "--frontier",
        type=Path,
        default=cache / "all-seed-evidence-frontier-v5-sealed/artifact.json",
    )
    return parser


def main() -> int:
    """Build and persist one fully verified source-coverage audit."""
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--cache-root", type=Path)
    preliminary, _ = bootstrap.parse_known_args()
    cache = preliminary.cache_root or _shared_cache_root()
    args = _parser(cache.parent, cache).parse_args()
    try:
        audit = build_source_coverage_audit(
            SourceCoverageAuditInputs(
                root=args.root,
                graph_database=args.graph_database,
                graph_receipt=args.graph_receipt,
                full_graph=args.full_graph,
                release_group_evidence=args.release_group_evidence,
                artist_metadata=args.artist_metadata,
                frontier=args.frontier,
            )
        )
        write_source_coverage_audit(args.output, audit)
    except (OSError, SourceCoverageAuditError, ValueError) as error:
        sys.stderr.write(f"source coverage audit failed: {error}\n")
        return 2
    sys.stdout.write(json.dumps(audit.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
