"""Build and publish the contextual-tag sparse prototype baseline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.ingest.musicbrainz_seed_targets import load_seed_target_artifact
from musix.sparse_genre_prototype import (
    SparsePrototypeSettings,
    build_sparse_genre_prototype,
    publish_sparse_genre_prototype,
)
from musix.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Expose the sealed extractor-to-prototype artifact boundary."""
    parser = argparse.ArgumentParser(prog="build-sparse-genre-prototype")
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--holdout-seed", type=int, default=20260905)
    parser.add_argument("--retrieval-k", type=int, default=25)
    parser.add_argument("--neighbors-per-seed", type=int, default=25)
    return parser


def main() -> int:
    """Build, gate, and custody one non-historical sparse baseline."""
    arguments = build_parser().parse_args()
    source = load_seed_target_artifact(arguments.source_artifact)
    settings = SparsePrototypeSettings(
        holdout_fraction=arguments.holdout_fraction,
        holdout_seed=arguments.holdout_seed,
        retrieval_k=arguments.retrieval_k,
        neighbors_per_seed=arguments.neighbors_per_seed,
    )
    artifact = build_sparse_genre_prototype(source, settings)
    receipt, _write = publish_sparse_genre_prototype(
        artifact, output_path=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(artifact.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
