"""Extract a bounded, receipt-bound open-label vocabulary from release groups."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.ml.label_alignment.release_group_vocabulary import (
    ReleaseGroupVocabularySettings,
    build_release_group_vocabulary_with_report,
    write_release_group_vocabulary,
)


def _shared_cache_root() -> Path:
    """Find the common checkout cache from either main or a linked worktree."""
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


def _parser(cache_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        default=(
            cache_root / "musicbrainz-release-group-source-objects/source-artifacts/sha256/"
            "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"
        ),
    )
    parser.add_argument(
        "--source-cache-receipt",
        type=Path,
        default=cache_root / "musicbrainz-release-group-source-receipt.json",
    )
    parser.add_argument(
        "--output-root", type=Path, default=cache_root / "release-group-label-vocabulary-v1"
    )
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--maximum-records", type=int, default=50_000)
    parser.add_argument("--maximum-record-bytes", type=int, default=2 * 1024**2)
    return parser


def main() -> int:
    """Publish one explicitly partial-or-complete vocabulary sidecar."""
    arguments = _parser(_shared_cache_root()).parse_args()
    settings = ReleaseGroupVocabularySettings(
        maximum_records=arguments.maximum_records,
        maximum_record_bytes=arguments.maximum_record_bytes,
    )
    artifact, report = build_release_group_vocabulary_with_report(
        arguments.archive, arguments.source_cache_receipt, settings
    )
    receipt, artifact_path, receipt_path = write_release_group_vocabulary(
        artifact, arguments.output_root
    )
    report_path = arguments.run_report or arguments.output_root / "latest-run-report.json"
    write_atomic_bytes(report_path, report.model_dump_json(indent=2).encode() + b"\n")
    sys.stdout.write(
        json.dumps(
            {
                "artifact": str(artifact_path),
                "receipt": str(receipt_path),
                "run_report": str(report_path),
                "logical_output_sha256": artifact.output_sha256,
                "artifact_sha256": receipt.artifact_sha256,
                "completed_source_member": artifact.completed_source_member,
                "records_seen": artifact.records_seen,
                "label_count": len(artifact.labels),
                "elapsed_seconds": report.elapsed_seconds,
                "peak_rss_kib": report.peak_rss_kib,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
