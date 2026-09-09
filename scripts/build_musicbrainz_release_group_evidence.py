"""Build research-only MusicBrainz release-group artist support evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from musix.ingest.musicbrainz.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceProgress,
    ReleaseGroupEvidenceSettings,
    build_release_group_evidence_from_seed_target_path,
    publish_release_group_evidence,
)
from musix.pipeline.manifest import load_download_source
from musix.pipeline.source_cache import load_source_cache_receipt
from musix.storage import LocalObjectStore

if TYPE_CHECKING:
    from collections.abc import Callable


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parser() -> argparse.ArgumentParser:
    """Declare a one-dump, one-build, no-audio source boundary."""
    result = argparse.ArgumentParser(prog="build-musicbrainz-release-group-evidence")
    result.add_argument("--archive", type=Path, required=True)
    result.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    result.add_argument("--source-id", default="musicbrainz_json_release_group_research_20260905")
    result.add_argument("--source-cache-receipt", type=Path, required=True)
    result.add_argument("--seed-target-artifact", type=Path, required=True)
    result.add_argument("--database", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--object-store", type=Path, required=True)
    result.add_argument("--receipt", type=Path, required=True)
    result.add_argument("--max-release-groups-per-membership", type=int, default=3)
    result.add_argument("--heldout-direct-anchor-percent", type=int, default=20)
    result.add_argument("--progress-every-records", type=int, default=100_000)
    return result


def _progress_reporter(*, every_records: int) -> Callable[[ReleaseGroupEvidenceProgress], None]:
    """Return a stderr-only aggregate progress reporter for this CLI invocation."""
    if every_records < 1:
        raise ValueError("progress_every_records must be positive")
    last_reported = 0

    def report(progress: ReleaseGroupEvidenceProgress) -> None:
        nonlocal last_reported
        if progress.records_seen - last_reported < every_records:
            return
        last_reported = progress.records_seen
        sys.stderr.write(
            "release-group progress "
            f"records_seen={progress.records_seen} "
            f"elapsed_seconds={progress.elapsed_seconds:.3f}\n"
        )
        sys.stderr.flush()

    return report


def main() -> int:
    """Stream only release-group metadata into a typed local research artifact."""
    arguments = parser().parse_args()
    try:
        progress_callback = _progress_reporter(every_records=arguments.progress_every_records)
    except ValueError as error:
        parser().error(str(error))
    source = load_download_source(arguments.manifest, arguments.source_id)
    sys.stderr.write("loading verified seed-target artifact\n")
    sys.stderr.flush()
    sys.stderr.write("streaming pinned MusicBrainz release-group dump\n")
    sys.stderr.flush()
    artifact = build_release_group_evidence_from_seed_target_path(
        arguments.archive,
        arguments.seed_target_artifact,
        source,
        load_source_cache_receipt(arguments.source_cache_receipt),
        _sha256_file(arguments.manifest),
        arguments.database,
        ReleaseGroupEvidenceSettings(
            max_release_groups_per_membership=arguments.max_release_groups_per_membership,
            heldout_direct_anchor_percent=arguments.heldout_direct_anchor_percent,
        ),
        progress_callback=progress_callback,
    )
    receipt = publish_release_group_evidence(
        artifact,
        database_path=arguments.database,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {"coverage": artifact.coverage.model_dump(), "receipt": receipt.model_dump()}, indent=2
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
