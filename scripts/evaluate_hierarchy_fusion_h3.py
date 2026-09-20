"""Evaluate a completed hierarchy fusion checkpoint against H3 neighborhoods only."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.hierarchy_fusion.contracts import HierarchyFusionArtifact
from opennoise.ml.hierarchy_fusion.h3_evaluation import evaluate_h3_overlap, verify_h3_overlap
from opennoise.ml.hierarchy_fusion.pipeline import verify_hierarchy_fusion


def shared_cache_root() -> Path:
    """Find the common checkout cache from main or a linked worktree."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to locate the shared OpenNoise cache")
    completed = subprocess.run(  # noqa: S603 - fixed git subcommand after absolute PATH lookup.
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).parent / ".cache"


def build_parser(cache_root: Path) -> argparse.ArgumentParser:
    """Build the CLI with deterministic shared-cache defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hierarchy-fusion", type=Path, default=cache_root / "hierarchy-fusion-v1/artifact.json"
    )
    parser.add_argument(
        "--h3-evaluation",
        type=Path,
        default=cache_root / "historical-signal-hierarchy/historical-signal-hierarchy-v1.json",
    )
    parser.add_argument(
        "--output", type=Path, default=cache_root / "hierarchy-fusion-v1/h3-overlap-report.json"
    )
    return parser


def main() -> int:
    """Write a separate report so H3 data cannot influence fusion construction."""
    arguments = build_parser(shared_cache_root()).parse_args()
    artifact = HierarchyFusionArtifact.model_validate_json(arguments.hierarchy_fusion.read_bytes())
    verify_hierarchy_fusion(artifact)
    report = evaluate_h3_overlap(artifact, arguments.h3_evaluation)
    verify_h3_overlap(report)
    write_atomic_bytes(arguments.output, report.model_dump_json(indent=2).encode() + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
