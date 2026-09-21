"""Benchmark a deterministic review-only latent genre retriever from the sealed sparse cache."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.ml.latent_genre_similarity import (
    LatentGenreSimilarityInputs,
    LatentGenreSimilaritySettings,
    build_latent_genre_similarity,
    write_latent_genre_similarity,
)


def _shared_cache() -> Path:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to locate the shared OpenNoise cache")
    completed = subprocess.run(  # noqa: S603 - fixed git subcommand after absolute lookup.
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).parent / ".cache"


def _parser(cache: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    root = cache / "hierarchy-fusion-v1"
    output = cache / "latent-genre-similarity-v1"
    parser.add_argument("--full-graph-artifact", type=Path, default=root / "full-graph-signal.json")
    parser.add_argument(
        "--full-graph-receipt", type=Path, default=root / "full-graph-signal.receipt.json"
    )
    parser.add_argument("--cache-directory", type=Path, default=root / "full-graph-cache")
    parser.add_argument("--output", type=Path, default=output / "artifact.json")
    parser.add_argument("--receipt", type=Path, default=output / "receipt.json")
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--maximum-evaluation-artists", type=int, default=5_000)
    return parser


def main() -> int:
    """Build and summarize the receipt-bound latent retrieval benchmark."""
    args = _parser(_shared_cache()).parse_args()
    artifact = build_latent_genre_similarity(
        LatentGenreSimilarityInputs(
            full_graph_artifact=args.full_graph_artifact,
            full_graph_receipt=args.full_graph_receipt,
            cache_directory=args.cache_directory,
        ),
        LatentGenreSimilaritySettings(
            rank=args.rank, maximum_evaluation_artists=args.maximum_evaluation_artists
        ),
    )
    receipt = write_latent_genre_similarity(args.output, args.receipt, artifact)
    sys.stdout.write(
        json.dumps(
            {
                "logical_output_sha256": artifact.output_sha256,
                "artifact_sha256": receipt.artifact_sha256,
                "latent": artifact.latent.model_dump(mode="json"),
                "binary_jaccard": artifact.binary_jaccard.model_dump(mode="json"),
                "train_only_popularity": artifact.train_only_popularity.model_dump(mode="json"),
                "direct_only": artifact.direct_only.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
