"""Write a non-overwriting local-only exact-credit playlist signal audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_playlist_signal_quality import (
    PlaylistSignalQualityError,
    audit_playlist_signal_quality,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--cohort-sha256", required=True)
    parser.add_argument("--artist-bridge", type=Path, required=True)
    parser.add_argument("--artist-bridge-sha256", required=True)
    parser.add_argument("--lastfm-artifact", type=Path)
    parser.add_argument("--lastfm-companion-receipt", type=Path)
    parser.add_argument("--lastfm-database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _local_cache_output_path(path: Path) -> Path:
    """Permit only non-symlink outputs below the resolved local cache directory."""
    output = path.resolve(strict=False)
    if not output.is_relative_to(Path(".cache").resolve()):
        raise PlaylistSignalQualityError("playlist signal output must resolve under .cache")
    return output


def main() -> int:
    """Refuse replacement and retain the report below the local cache only."""
    arguments = _arguments()
    try:
        output = _local_cache_output_path(arguments.output)
        if output.exists() or output.is_symlink():
            sys.stderr.write("playlist signal output already exists\n")
            return 2
        report = audit_playlist_signal_quality(
            cohort_path=arguments.cohort,
            expected_cohort_sha256=arguments.cohort_sha256,
            artist_bridge_path=arguments.artist_bridge,
            expected_artist_bridge_sha256=arguments.artist_bridge_sha256,
            lastfm_artifact_path=arguments.lastfm_artifact,
            lastfm_companion_receipt_path=arguments.lastfm_companion_receipt,
            lastfm_database_path=arguments.lastfm_database,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(report.model_dump_json(indent=2) + "\n")
    except (OSError, PlaylistSignalQualityError, ValueError) as error:
        sys.stderr.write(f"playlist signal audit failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only playlist signal audit: {output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
