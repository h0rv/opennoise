"""Build the receipt-bound sparse source-neutral membership signal checkpoint."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.full_graph_signal import (
    FullGraphSignalInputs,
    FullGraphSignalRunReport,
    FullGraphSignalSettings,
    build_full_graph_signal,
    write_full_graph_signal,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-database", type=Path, required=True)
    parser.add_argument("--graph-receipt", type=Path, required=True)
    parser.add_argument("--construction-certificate", type=Path, required=True)
    parser.add_argument("--cache-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--run-report", type=Path, required=True)
    parser.add_argument("--split-seed", type=int, default=20260913)
    parser.add_argument("--heldout-fraction", type=float, default=0.2)
    parser.add_argument("--maximum-genre-neighbors", type=int, default=200)
    parser.add_argument("--maximum-genres-per-artist-for-cooccurrence", type=int, default=32)
    parser.add_argument("--maximum-cooccurrence-nnz", type=int, default=20_000_000)
    parser.add_argument(
        "--maximum-evaluation-artists",
        type=int,
        default=5_000,
        help="Canonical laptop-safe checkpoint sample; override only for a new named run.",
    )
    parser.add_argument("--maximum-containment-candidates", type=int, default=10_000)
    return parser


def main() -> int:
    """Build once and include operational timing/memory outside the logical artifact."""
    arguments = _parser().parse_args()
    settings = FullGraphSignalSettings(
        split_seed=arguments.split_seed,
        heldout_fraction=arguments.heldout_fraction,
        maximum_genre_neighbors=arguments.maximum_genre_neighbors,
        maximum_genres_per_artist_for_cooccurrence=(
            arguments.maximum_genres_per_artist_for_cooccurrence
        ),
        maximum_cooccurrence_nnz=arguments.maximum_cooccurrence_nnz,
        maximum_evaluation_artists=arguments.maximum_evaluation_artists,
        maximum_containment_candidates=arguments.maximum_containment_candidates,
    )
    started = time.monotonic()
    artifact = build_full_graph_signal(
        FullGraphSignalInputs(
            graph_database=arguments.graph_database,
            graph_receipt=arguments.graph_receipt,
            construction_certificate=arguments.construction_certificate,
            cache_directory=arguments.cache_directory,
        ),
        settings,
    )
    receipt = write_full_graph_signal(arguments.output, arguments.receipt, artifact)
    elapsed = time.monotonic() - started
    peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = FullGraphSignalRunReport(
        logical_output_sha256=artifact.output_sha256,
        elapsed_seconds=round(elapsed, 3),
        peak_rss_kib=peak_rss_kib,
    )
    write_atomic_bytes(arguments.run_report, report.model_dump_json(indent=2).encode() + b"\n")
    sys.stdout.write(
        json.dumps(
            {
                "artifact": artifact.model_dump(),
                "receipt": receipt.model_dump(),
                "operational": report.model_dump(),
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
