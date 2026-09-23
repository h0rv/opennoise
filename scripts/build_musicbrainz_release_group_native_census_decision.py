"""Write a create-only local decision report from the completed native census."""

from pathlib import Path

from opennoise.ingest.musicbrainz.release_group_native_census_decision import (
    build_release_group_native_census_decision,
    write_release_group_native_census_decision_once,
)


def main() -> int:
    """Use only the completed census and its pinned seed inputs."""
    report = build_release_group_native_census_decision(
        Path(".cache/musicbrainz-release-group-native-census-v1/report.json"),
        Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
        Path(".cache/semantic-map-layout-v3/artifact.json"),
    )
    write_release_group_native_census_decision_once(
        cache_root=Path(".cache"),
        output=Path(".cache/musicbrainz-release-group-native-census-decision-v1/report.json"),
        report=report,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
