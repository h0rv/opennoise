"""Train/evaluate positive-only H3 imitation against sealed bridge inputs."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from musix.history.historical_imitation import (
    H3CustodyInput,
    HistoricalImitationSettings,
    build_historical_imitation,
    publish_historical_imitation,
)
from musix.ingest.musicbrainz.seed_targets import load_seed_target_artifact
from musix.ingest.spotify.artifact import load_receipted_musicbrainz_spotify_bridge
from musix.storage import LocalObjectStore
from musix.taxonomy.open.tag_feature_matrix import load_receipted_open_tag_feature_matrix


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build-historical-imitation")
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--bridge-receipt", type=Path, required=True)
    parser.add_argument("--bridge-receipt-sha256", required=True)
    parser.add_argument("--feature-manifest", type=Path, required=True)
    parser.add_argument("--feature-matrix", type=Path, required=True)
    parser.add_argument("--feature-receipt", type=Path, required=True)
    parser.add_argument("--feature-receipt-sha256", required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--split-seed", type=int, default=20260906)
    parser.add_argument("--cold-label-fraction", type=float, default=0.2)
    parser.add_argument("--edge-holdout-fraction", type=float, default=0.2)
    parser.add_argument("--retrieval-k", type=int, default=50)
    return parser


def main() -> int:
    """Build one hash-bound positive-only evaluation artifact."""
    arguments = _parser().parse_args()
    bridge = load_receipted_musicbrainz_spotify_bridge(
        arguments.bridge,
        arguments.bridge_receipt,
        arguments.bridge_receipt_sha256,
    )
    try:
        features = load_receipted_open_tag_feature_matrix(
            arguments.feature_manifest,
            arguments.feature_matrix,
            arguments.feature_receipt,
            arguments.feature_receipt_sha256,
        )
        try:
            result = build_historical_imitation(
                load_seed_target_artifact(arguments.source_artifact),
                bridge,
                features,
                H3CustodyInput(
                    database_path=arguments.historical_database,
                    snapshot_work_directory=arguments.output.parent,
                ),
                HistoricalImitationSettings(
                    split_seed=arguments.split_seed,
                    cold_label_fraction=arguments.cold_label_fraction,
                    edge_holdout_fraction=arguments.edge_holdout_fraction,
                    retrieval_k=arguments.retrieval_k,
                ),
            )
        finally:
            features.close()
    finally:
        bridge.close()
    receipt = publish_historical_imitation(
        result,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    _atomic_text(arguments.receipt, receipt.model_dump_json(indent=2))
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
