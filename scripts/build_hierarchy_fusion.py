"""Build the source-neutral, multi-parent hierarchy fusion checkpoint."""

from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.hierarchy_fusion import (
    HierarchyFusionInputs,
    HierarchyFusionSettings,
    build_hierarchy_fusion,
    verify_hierarchy_fusion,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--evidence-graph-database", type=Path, required=True)
    parser.add_argument("--evidence-graph-receipt", type=Path, required=True)
    parser.add_argument("--factual-taxonomy", type=Path, required=True)
    parser.add_argument("--public-candidate-corpus", type=Path, required=True)
    parser.add_argument("--public-candidate-receipt", type=Path, required=True)
    parser.add_argument("--full-graph-signal", type=Path, required=True)
    parser.add_argument("--full-graph-signal-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-report", type=Path, required=True)
    parser.add_argument("--factual-split-seed", type=int, default=20260913)
    parser.add_argument("--calibration-recovery-tolerance", type=float, default=0.02)
    return parser


def main() -> int:
    """Stream source evidence once and write a hash-bound checkpoint."""
    arguments = _parser().parse_args()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
