"""Certify the reproducible source-neutral reconstruction status manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.checkpoints.reconstruction_checkpoint import (
    ReconstructionCheckpointError,
    ReconstructionCheckpointInputs,
    build_reconstruction_checkpoint,
    write_reconstruction_checkpoint,
)

_COLD_HASH = "b7482d6e3a9805bf62b484df4ce65b05480761a7661b7ffbf19491ce167f32b9"
_VOCAB_HASH = "20773899d2b817464b3fcda405c744917e5a2f9366010bab9cecdf733db94fbd"
_NEIGHBOR_HASH = "32017c0a2cff27485671151663dfc9f184e8b2f9e354ba73d712e3ca8140b141"


def _shared_cache_root() -> Path:
    """Find the common checkout cache from a main checkout or linked worktree."""
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
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=cache,
        help="Shared cache root; defaults to the Git common checkout cache.",
    )
    parser.add_argument("--output", type=Path, default=cache / "reconstruction-checkpoint-v1.json")
    parser.add_argument("--graph-database", type=Path, default=cache / "evidence-graph-v2.sqlite")
    parser.add_argument(
        "--graph-receipt", type=Path, default=cache / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--construction-certificate",
        type=Path,
        default=cache / "evidence-graph-v2.construction-certificate.json",
    )
    parser.add_argument(
        "--full-graph", type=Path, default=cache / "hierarchy-fusion-v1/full-graph-signal.json"
    )
    parser.add_argument(
        "--full-graph-receipt",
        type=Path,
        default=cache / "hierarchy-fusion-v1/full-graph-signal.receipt.json",
    )
    parser.add_argument(
        "--cold-alignment",
        type=Path,
        default=cache
        / f"cold-label-alignment-v1-full-vocabulary-20260920/sha256/{_COLD_HASH}.json",
    )
    parser.add_argument(
        "--cold-alignment-receipt",
        type=Path,
        default=cache
        / f"cold-label-alignment-v1-full-vocabulary-20260920/sha256/{_COLD_HASH}.receipt.json",
    )
    parser.add_argument(
        "--vocabulary-artifact",
        type=Path,
        default=cache / f"release-group-label-vocabulary-v1/sha256/{_VOCAB_HASH}.json",
    )
    parser.add_argument(
        "--vocabulary-receipt",
        type=Path,
        default=cache / f"release-group-label-vocabulary-v1/sha256/{_VOCAB_HASH}.receipt.json",
    )
    parser.add_argument(
        "--neighborhoods",
        type=Path,
        default=cache / f"genre-colisten-neighborhoods-v1/{_NEIGHBOR_HASH}/artifact.json",
    )
    parser.add_argument(
        "--neighborhoods-receipt",
        type=Path,
        default=cache / f"genre-colisten-neighborhoods-v1/{_NEIGHBOR_HASH}/receipt.json",
    )
    parser.add_argument(
        "--neighborhoods-database",
        type=Path,
        default=cache
        / f"genre-colisten-neighborhoods-v1/{_NEIGHBOR_HASH}/genre-neighborhoods.sqlite",
    )
    parser.add_argument(
        "--hierarchy", type=Path, default=cache / "hierarchy-fusion-v1/artifact.json"
    )
    parser.add_argument(
        "--hierarchy-receipt",
        type=Path,
        default=None,
        help="Optional hierarchy artifact receipt; construction remains valid without it.",
    )
    parser.add_argument(
        "--layout", type=Path, default=cache / "semantic-map-layout-v2/artifact.json"
    )
    parser.add_argument(
        "--membership-transfer",
        type=Path,
        default=cache / "colisten-membership-transfer-v1/artifact.json",
    )
    parser.add_argument(
        "--membership-transfer-receipt",
        type=Path,
        default=cache / "colisten-membership-transfer-v1/receipt.json",
    )
    parser.add_argument(
        "--historical-evaluation",
        type=Path,
        default=None,
        help="Terminal evaluation report; never admitted as a construction input.",
    )
    return parser


def main() -> int:
    """Validate every current signal and write one deterministic status artifact."""
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--cache-root", type=Path)
    preliminary, _ = bootstrap.parse_known_args()
    cache = preliminary.cache_root or _shared_cache_root()
    args = _parser(cache.parent, cache).parse_args()
    try:
        checkpoint = build_reconstruction_checkpoint(
            ReconstructionCheckpointInputs(
                root=args.root,
                graph_database=args.graph_database,
                graph_receipt=args.graph_receipt,
                construction_certificate=args.construction_certificate,
                full_graph=args.full_graph,
                full_graph_receipt=args.full_graph_receipt,
                cold_alignment=args.cold_alignment,
                cold_alignment_receipt=args.cold_alignment_receipt,
                neighborhoods=args.neighborhoods,
                neighborhoods_receipt=args.neighborhoods_receipt,
                neighborhoods_database=args.neighborhoods_database,
                hierarchy=args.hierarchy,
                hierarchy_receipt=args.hierarchy_receipt,
                layout=args.layout,
                membership_transfer=args.membership_transfer,
                membership_transfer_receipt=args.membership_transfer_receipt,
                vocabulary_artifact=args.vocabulary_artifact,
                vocabulary_receipt=args.vocabulary_receipt,
            ),
            historical_evaluation=args.historical_evaluation,
        )
        write_reconstruction_checkpoint(args.output, checkpoint)
    except (OSError, ReconstructionCheckpointError, ValueError) as error:
        sys.stderr.write(f"reconstruction checkpoint failed: {error}\n")
        return 2
    sys.stdout.write(
        json.dumps(checkpoint.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
