"""Write one local-only JSPF and Last.fm matched holdout receipt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_playlist_lastfm_holdout import (
    PlaylistLastFmHoldoutError,
    evaluate_playlist_lastfm_matched_holdout,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist-receipt", type=Path, required=True)
    parser.add_argument("--playlist-receipt-sha256", required=True)
    parser.add_argument("--lastfm-artifact", type=Path, required=True)
    parser.add_argument("--lastfm-companion-receipt", type=Path, required=True)
    parser.add_argument("--lastfm-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _local_cache_output_path(path: Path) -> Path:
    """Permit only outputs under the resolved local cache directory."""
    cache_directory = Path(".cache").resolve()
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(cache_directory):
        raise PlaylistLastFmHoldoutError("holdout output must resolve under .cache")
    return resolved_path


def main() -> int:
    """Refuse replacement and write a receipt-bound local research result."""
    arguments = _arguments()
    try:
        output_path = _local_cache_output_path(arguments.output)
        if output_path.exists() or output_path.is_symlink():
            sys.stderr.write("playlist and Last.fm holdout output already exists\n")
            return 2
        report = evaluate_playlist_lastfm_matched_holdout(
            playlist_receipt_path=arguments.playlist_receipt,
            expected_playlist_receipt_sha256=arguments.playlist_receipt_sha256,
            lastfm_artifact_path=arguments.lastfm_artifact,
            lastfm_companion_receipt_path=arguments.lastfm_companion_receipt,
            lastfm_database_path=arguments.lastfm_database,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8") as output:
            output.write(report.model_dump_json(indent=2) + "\n")
    except (OSError, PlaylistLastFmHoldoutError, ValueError) as error:
        sys.stderr.write(f"playlist and Last.fm holdout failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only playlist and Last.fm holdout: {output_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
