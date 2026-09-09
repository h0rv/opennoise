"""Verify, store, and receipt the raw H3 JSON and derived membership SQLite."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from musix.history.historical_custody import custody_historical_inputs
from musix.models.historical import HistoricalH3SourceManifest
from musix.models.historical_signal import HistoricalSignalSettings
from musix.storage import LocalObjectStore

_DEFAULT_H3_MANIFEST = Path("config/historical_sources/neroyuki_h3_20241116.json")
_DEFAULT_H2_MANIFEST = Path("data/historical/historical-compatibility-v1.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _settings(embedding_method: str) -> HistoricalSignalSettings:
    match embedding_method:
        case "anchored_diffusion":
            return HistoricalSignalSettings(
                method="idf_membership_knn_diffusion_v1", embedding_method="anchored_diffusion"
            )
        case "normalized_laplacian_spectral":
            return HistoricalSignalSettings(
                method="idf_membership_knn_spectral_v1",
                embedding_method="normalized_laplacian_spectral",
            )
        case "spectral_force_refined":
            return HistoricalSignalSettings(
                method="idf_membership_knn_spectral_force_v1",
                embedding_method="spectral_force_refined",
            )
        case _:
            raise ValueError(f"unsupported embedding method: {embedding_method}")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h3-source", type=Path, required=True)
    parser.add_argument("--membership-database", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--h3-manifest", type=Path, default=_DEFAULT_H3_MANIFEST)
    parser.add_argument("--h2-manifest", type=Path, default=_DEFAULT_H2_MANIFEST)
    parser.add_argument("--expected-source-genre-rows", type=int)
    parser.add_argument("--expected-source-memberships", type=int)
    parser.add_argument("--expected-stored-memberships", type=int, default=306_136)
    parser.add_argument("--expected-stored-genres", type=int, default=6_289)
    parser.add_argument("--expected-stored-artists", type=int, default=240_007)
    parser.add_argument(
        "--embedding-method",
        choices=("anchored_diffusion", "normalized_laplacian_spectral", "spectral_force_refined"),
        default="spectral_force_refined",
    )
    parser.add_argument("--signal-output", type=Path, default=Path(".cache/historical-signal.json"))
    parser.add_argument(
        "--signal-report", type=Path, default=Path(".cache/historical-signal.build.json")
    )
    return parser.parse_args()


def main() -> int:
    """Seal explicit operator-supplied inputs without committing either blob."""
    arguments = _arguments()
    try:
        source_manifest = HistoricalH3SourceManifest.model_validate_json(
            arguments.h3_manifest.read_bytes()
        )
        raw_sha256 = _sha256(arguments.h3_source)
        h3_manifest_sha256 = _sha256(arguments.h3_manifest)
        h2_manifest_sha256 = _sha256(arguments.h2_manifest)
        command = (
            sys.executable,
            "scripts/build_historical_signal_model.py",
            "--historical-manifest",
            str(arguments.h2_manifest),
            "--membership-database",
            str(arguments.membership_database),
            "--h3-artifact-sha256",
            raw_sha256,
            "--embedding-method",
            arguments.embedding_method,
            "--output",
            str(arguments.signal_output),
            "--report",
            str(arguments.signal_report),
        )
        receipt = custody_historical_inputs(
            LocalObjectStore(arguments.object_store),
            arguments.h3_source,
            arguments.membership_database,
            receipt_path=arguments.receipt,
            expected_h3_source_sha256=source_manifest.full_sha256,
            expected_h3_source_byte_size=source_manifest.full_byte_size,
            h3_source_manifest_sha256=h3_manifest_sha256,
            h2_manifest_sha256=h2_manifest_sha256,
            expected_source_genre_rows=(
                arguments.expected_source_genre_rows or source_manifest.coverage.source_genre_rows
            ),
            expected_source_memberships=(
                arguments.expected_source_memberships
                or source_manifest.coverage.source_artist_memberships
            ),
            expected_stored_memberships=arguments.expected_stored_memberships,
            expected_stored_genres=arguments.expected_stored_genres,
            expected_stored_artists=arguments.expected_stored_artists,
            local_display_policy_key=f"historical-membership:local-display:{raw_sha256}",
            model_settings=_settings(arguments.embedding_method),
            rebuild_command=command,
        )
    except (OSError, ValueError) as error:
        sys.stderr.write(f"historical H3 custody failed: {error}\n")
        return 2
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
