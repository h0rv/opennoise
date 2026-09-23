"""Write a create-only aggregate native release-group census."""

from pathlib import Path

from opennoise.ingest.musicbrainz.entity_genre_observation import write_local_report_once
from opennoise.ingest.musicbrainz.release_group_native_census import (
    build_release_group_native_census,
)
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.source_cache import load_source_cache_receipt


def main() -> int:
    """Run only against retained, pinned local files."""
    archive = Path(
        ".cache/musicbrainz-release-group-source-work/raw/sha256/6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"
    )
    receipt = load_source_cache_receipt(
        Path(".cache/musicbrainz-release-group-source-receipt.json")
    )
    report = build_release_group_native_census(
        archive,
        load_download_source(
            Path("config/data_sources.toml"), "musicbrainz_json_release_group_research_20260905"
        ),
        receipt,
        receipt.declared_manifest_sha256,
        Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
        Path(".cache/semantic-map-layout-v3/artifact.json"),
    )
    write_local_report_once(
        cache_root=Path(".cache"),
        output=Path(".cache/musicbrainz-release-group-native-census-v1/report.json"),
        payload=(report.model_dump_json() + "\n").encode(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
