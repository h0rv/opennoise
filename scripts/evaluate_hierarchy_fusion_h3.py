"""Evaluate a completed hierarchy fusion checkpoint against H3 neighborhoods only."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.hierarchy_fusion.contracts import HierarchyFusionArtifact
from opennoise.ml.hierarchy_fusion.h3_evaluation import evaluate_h3_overlap, verify_h3_overlap
from opennoise.ml.hierarchy_fusion.pipeline import verify_hierarchy_fusion


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hierarchy-fusion", type=Path, required=True)
    parser.add_argument("--h3-evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    """Write a separate report so H3 data cannot influence fusion construction."""
    arguments = _parser().parse_args()
    artifact = HierarchyFusionArtifact.model_validate_json(arguments.hierarchy_fusion.read_bytes())
    verify_hierarchy_fusion(artifact)
    report = evaluate_h3_overlap(artifact, arguments.h3_evaluation)
    verify_h3_overlap(report)
    write_atomic_bytes(arguments.output, report.model_dump_json(indent=2).encode() + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
