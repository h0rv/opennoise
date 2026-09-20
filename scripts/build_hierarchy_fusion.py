"""Build the source-neutral, multi-parent hierarchy fusion checkpoint."""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.hierarchy_fusion import (
    HierarchyFusionInputs,
    HierarchyFusionSettings,
    build_hierarchy_fusion,
    verify_hierarchy_fusion,
)


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
        "--reconciliation",
        type=Path,
        default=cache_root / "musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
    )
    parser.add_argument(
        "--evidence-graph-database", type=Path, default=cache_root / "evidence-graph-v2.sqlite"
    )
    parser.add_argument(
        "--evidence-graph-receipt", type=Path, default=cache_root / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--factual-taxonomy",
        type=Path,
        default=cache_root / "taxonomy-relation-expansion-v3-replay-candidate/artifact.json",
    )
    parser.add_argument(
        "--public-candidate-corpus",
        type=Path,
        default=cache_root
        / "musicbrainz-full-seed-targets/pipeline/genre-hierarchy-candidates.json",
    )
    parser.add_argument(
        "--public-candidate-receipt",
        type=Path,
        default=cache_root
        / "musicbrainz-full-seed-targets/pipeline/genre-hierarchy-candidates.receipt.json",
    )
    parser.add_argument(
        "--full-graph-signal",
        type=Path,
        default=cache_root / "hierarchy-fusion-v1/full-graph-signal.json",
    )
    parser.add_argument(
        "--full-graph-signal-receipt",
        type=Path,
        default=cache_root / "hierarchy-fusion-v1/full-graph-signal.receipt.json",
    )
    parser.add_argument(
        "--output", type=Path, default=cache_root / "hierarchy-fusion-v1/artifact.json"
    )
    parser.add_argument(
        "--run-report", type=Path, default=cache_root / "hierarchy-fusion-v1/run-report.json"
    )
    parser.add_argument("--factual-split-seed", type=int, default=20260913)
    parser.add_argument("--calibration-recovery-tolerance", type=float, default=0.02)
    return parser


def main() -> int:
    """Stream source evidence once and write a hash-bound checkpoint."""
    arguments = build_parser(shared_cache_root()).parse_args()
    started = time.monotonic()
    artifact = build_hierarchy_fusion(
        HierarchyFusionInputs(
            reconciliation=arguments.reconciliation,
            evidence_graph_database=arguments.evidence_graph_database,
            evidence_graph_receipt=arguments.evidence_graph_receipt,
            factual_taxonomy=arguments.factual_taxonomy,
            public_candidate_corpus=arguments.public_candidate_corpus,
            public_candidate_receipt=arguments.public_candidate_receipt,
            full_graph_signal=arguments.full_graph_signal,
            full_graph_signal_receipt=arguments.full_graph_signal_receipt,
        ),
        HierarchyFusionSettings(
            factual_split_seed=arguments.factual_split_seed,
            calibration_recovery_tolerance=arguments.calibration_recovery_tolerance,
        ),
    )
    verify_hierarchy_fusion(artifact)
    write_atomic_bytes(arguments.output, artifact.model_dump_json(indent=2).encode() + b"\n")
    report = {
        "revision": "hierarchy-fusion-run-report-v1",
        "logical_output_sha256": artifact.output_sha256,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "coverage": artifact.coverage.model_dump(mode="json"),
        "factual_holdout_evaluation": artifact.factual_holdout_evaluation.model_dump(mode="json"),
    }
    write_atomic_bytes(
        arguments.run_report,
        (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
    )
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
