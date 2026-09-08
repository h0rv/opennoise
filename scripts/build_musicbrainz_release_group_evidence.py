"""Build research-only MusicBrainz release-group artist support evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceSettings,
    build_release_group_evidence,
    publish_release_group_evidence,
)
from musix.musicbrainz_seed_targets import load_seed_target_artifact
from musix.pipeline.manifest import load_download_source
from musix.pipeline.source_cache import load_source_cache_receipt
from musix.storage import LocalObjectStore


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
    return result


def main() -> int:
    """Stream only release-group metadata into a typed local research artifact."""
    arguments = parser().parse_args()
    source = load_download_source(arguments.manifest, arguments.source_id)
    sys.stderr.write("loading verified seed-target artifact\n")
    sys.stderr.flush()
    seed_target = load_seed_target_artifact(arguments.seed_target_artifact)
    sys.stderr.write("streaming pinned MusicBrainz release-group dump\n")
    sys.stderr.flush()
    artifact = build_release_group_evidence(
        arguments.archive,
        seed_target,
        source,
        load_source_cache_receipt(arguments.source_cache_receipt),
        _sha256_file(arguments.manifest),
        arguments.database,
        ReleaseGroupEvidenceSettings(
            max_release_groups_per_membership=arguments.max_release_groups_per_membership,
            heldout_direct_anchor_percent=arguments.heldout_direct_anchor_percent,
        ),
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
