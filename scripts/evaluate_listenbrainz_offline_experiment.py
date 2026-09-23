"""Evaluate aggregate-only co-listen rankings without emitting neighbors."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

from opennoise.ingest.listenbrainz.offline_experiment import (
    ListenBrainzOfflineExperimentSettings,
    evaluate_listenbrainz_offline_experiment,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listenbrainz-db", type=Path, required=True)
    parser.add_argument("--public-db", type=Path, required=True)
    parser.add_argument("--expected-listenbrainz-sha256")
    parser.add_argument("--expected-public-sha256")
    parser.add_argument("--reverse-window-order", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_expected_hash(actual: str, expected: str | None, source: str) -> None:
    if expected is not None and actual != expected:
        raise ValueError(f"{source} does not match required source receipt")


def _local_cache_output_path(path: Path) -> Path:
    candidate = path.absolute()
    if candidate.is_symlink():
        raise ValueError("offline experiment output must not be a symlink")
    output = candidate.resolve(strict=False)
    if not output.is_relative_to(Path(".cache").resolve()):
        raise ValueError("offline experiment output must resolve under .cache")
    if output.exists():
        raise ValueError("offline experiment output already exists")
    return output


def main() -> int:
    """Write only a local aggregate evaluation artifact."""
    arguments = _arguments()
    try:
        listenbrainz_sha256 = _sha256(arguments.listenbrainz_db)
        public_sha256 = _sha256(arguments.public_db)
        _require_expected_hash(
            listenbrainz_sha256, arguments.expected_listenbrainz_sha256, "ListenBrainz database"
        )
        _require_expected_hash(public_sha256, arguments.expected_public_sha256, "public database")
        output = _local_cache_output_path(arguments.output)
        artifact = evaluate_listenbrainz_offline_experiment(
            listenbrainz_path=arguments.listenbrainz_db,
            public_database_path=arguments.public_db,
            listenbrainz_database_sha256=listenbrainz_sha256,
            public_database_sha256=public_sha256,
            settings=ListenBrainzOfflineExperimentSettings(
                evaluation_window_order=(
                    "reverse_chronological" if arguments.reverse_window_order else "chronological"
                )
            ),
        )
        payload = artifact.model_dump_json(indent=2) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.stderr.write(f"offline ListenBrainz experiment failed: {error}\n")
        return 2
    sys.stdout.write(f"source windows: {artifact.source_window_count}\n")
    sys.stdout.write(
        "split pairs: "
        f"train={artifact.train_pair_count} heldout={artifact.heldout_pair_count} "
        f"novel={artifact.novel_heldout_pair_count}\n"
    )
    for metric in artifact.metrics:
        sys.stdout.write(
            f"{metric.method}: scored={metric.scored_query_count}/{metric.query_count} "
            f"hit@10={metric.hit_rate_at_10:.6f} recall@10={metric.recall_at_10:.6f} "
            f"hit@25={metric.hit_rate_at_25:.6f} recall@25={metric.recall_at_25:.6f}\n"
        )
    sys.stdout.write(
        "common scored cohort: "
        f"queries={artifact.common_scored_query_count} "
        f"references={artifact.common_scored_reference_pair_count}\n"
    )
    for metric in artifact.common_scored_metrics:
        sys.stdout.write(
            f"common {metric.method}: hit@10={metric.hit_rate_at_10:.6f} "
            f"recall@10={metric.recall_at_10:.6f} hit@25={metric.hit_rate_at_25:.6f} "
            f"recall@25={metric.recall_at_25:.6f}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
