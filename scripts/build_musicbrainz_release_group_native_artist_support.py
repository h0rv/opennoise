"""Replay the local native release-group sample with exact credited-artist support."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ingest.musicbrainz.entity_genre_observation import write_local_report_once
from opennoise.ingest.musicbrainz.release_group_native_artist_support import (
    build_release_group_native_artist_support,
)
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    ReleaseGroupNativeObservationReport,
)
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.source_cache import load_source_cache_receipt

_ARCHIVE = Path(
    ".cache/musicbrainz-release-group-source-work/raw/sha256/"
    "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"
)


def main() -> int:
    """Use only the retained archive and prior native observation receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=_ARCHIVE)
    parser.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    parser.add_argument(
        "--source-cache-receipt",
        type=Path,
        default=Path(".cache/musicbrainz-release-group-source-receipt.json"),
    )
    parser.add_argument(
        "--native-observation",
        type=Path,
        default=Path(".cache/musicbrainz-release-group-native-observation-v1/report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".cache/musicbrainz-release-group-native-artist-support-v1/report.json"),
    )
    arguments = parser.parse_args()
    receipt = load_source_cache_receipt(arguments.source_cache_receipt)
    native_observation = ReleaseGroupNativeObservationReport.model_validate_json(
        arguments.native_observation.read_bytes()
    )
    report = build_release_group_native_artist_support(
        arguments.archive,
        load_download_source(
            arguments.manifest, "musicbrainz_json_release_group_research_20260905"
        ),
        receipt,
        receipt.declared_manifest_sha256,
        native_observation,
    )
    write_local_report_once(
        cache_root=Path(".cache"),
        output=arguments.output,
        payload=(report.model_dump_json() + "\n").encode(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
