"""Build the sealed, review-only cold-artist transfer channel from local v2 checkpoints."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.ml.colisten_membership_transfer import (
    CoListenMembershipTransferInputs,
    CoListenMembershipTransferSettings,
    build_colisten_membership_transfer,
    write_colisten_membership_transfer,
)


def _shared_cache() -> Path:
    """Use the common Git cache so linked worktrees replay one local checkpoint."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to locate the shared OpenNoise cache")
    common = subprocess.run(  # noqa: S603 - fixed Git subcommand after absolute PATH lookup.
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(common).parent / ".cache"


def _parser(cache: Path) -> argparse.ArgumentParser:
    output = cache / "colisten-membership-transfer-v1"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-database", type=Path, default=cache / "evidence-graph-v2.sqlite")
    parser.add_argument(
        "--graph-receipt", type=Path, default=cache / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--colisten-database",
        type=Path,
        default=cache / "listenbrainz-dual-overlay-v1/colisten.sqlite",
    )
    parser.add_argument(
        "--colisten-receipt",
        type=Path,
        default=cache / "listenbrainz-dual-overlay-v1/colisten.receipt.json",
    )
    parser.add_argument("--output", type=Path, default=output / "artifact.json")
    parser.add_argument("--receipt", type=Path, default=output / "receipt.json")
    parser.add_argument("--split-seed", type=int, default=20260920)
    parser.add_argument("--heldout-fraction", type=float, default=0.2)
    return parser


def main() -> int:
    """Build one source-neutral review artifact without requiring environment variables."""
    args = _parser(_shared_cache()).parse_args()
    artifact = build_colisten_membership_transfer(
        CoListenMembershipTransferInputs(
            graph_database=args.graph_database,
            graph_receipt=args.graph_receipt,
            colisten_database=args.colisten_database,
            colisten_receipt=args.colisten_receipt,
        ),
        CoListenMembershipTransferSettings(
            split_seed=args.split_seed, heldout_fraction=args.heldout_fraction
        ),
    )
    receipt = write_colisten_membership_transfer(args.output, args.receipt, artifact)
    sys.stdout.write(
        json.dumps(
            {
                "artifact": str(args.output),
                "artifact_sha256": receipt.artifact_sha256,
                "coverage": artifact.coverage.model_dump(mode="json"),
                "heldout_evaluation": artifact.heldout_evaluation.model_dump(mode="json"),
                "logical_output_sha256": artifact.output_sha256,
                "receipt": str(args.receipt),
                "train_only_global_popularity_baseline": (
                    artifact.train_only_global_popularity_baseline.model_dump(mode="json")
                ),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
