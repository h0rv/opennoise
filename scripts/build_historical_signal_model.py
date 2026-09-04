"""Build the all-scale local Every Noise reconstruction from H3 memberships only."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from musix.historical_signal_model import build_historical_signal_model
from musix.models.historical import HistoricalCompatibilityManifest
from musix.models.historical_signal import HistoricalSignalSettings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-manifest", type=Path, required=True)
    parser.add_argument("--membership-database", type=Path, required=True)
    parser.add_argument("--h3-artifact-sha256", required=True)
    parser.add_argument(
        "--embedding-method",
        choices=("anchored_diffusion", "normalized_laplacian_spectral", "spectral_force_refined"),
        default="spectral_force_refined",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _require_exact_rerun(first_hash: str, second_hash: str) -> None:
    """Fail before publication when deterministic rebuilds disagree."""
    if first_hash != second_hash:
        raise ValueError("determinism failure: independent build hashes differ")


def _settings(embedding_method: str) -> HistoricalSignalSettings:
    """Create a discriminated, hash-bound method configuration from CLI input."""
    match embedding_method:
        case "anchored_diffusion":
            return HistoricalSignalSettings(
                method="idf_membership_knn_diffusion_v1",
                embedding_method="anchored_diffusion",
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
            raise ValueError("unsupported embedding method")


def main() -> int:
    """Build twice and fail closed unless the full content hash is exactly reproducible."""
    arguments = _arguments()
    try:
        historical = HistoricalCompatibilityManifest.model_validate_json(
            arguments.historical_manifest.read_text(encoding="utf-8")
        )
        started = time.monotonic()
        artifact = build_historical_signal_model(
            historical=historical,
            membership_database=arguments.membership_database,
            h3_artifact_sha256=arguments.h3_artifact_sha256,
            settings=_settings(arguments.embedding_method),
        )
        rerun = build_historical_signal_model(
            historical=historical,
            membership_database=arguments.membership_database,
            h3_artifact_sha256=arguments.h3_artifact_sha256,
            settings=_settings(arguments.embedding_method),
        )
        _require_exact_rerun(artifact.quality.artifact_sha256, rerun.quality.artifact_sha256)
        _atomic_write(arguments.output, (artifact.model_dump_json(indent=2) + "\n").encode())
        report = {
            "revision": artifact.revision,
            "artifact_sha256": artifact.quality.artifact_sha256,
            "exact_rerun": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1_024,
            "inputs": artifact.inputs.model_dump(mode="json"),
            "quality": artifact.quality.model_dump(mode="json"),
            "geometry": artifact.geometry.model_dump(mode="json"),
            "progressive_lods": [lod.model_dump(mode="json") for lod in artifact.progressive_lods],
            "coordinate_evaluation": artifact.coordinate_evaluation.model_dump(mode="json"),
            "ablations": [ablation.model_dump(mode="json") for ablation in artifact.ablations],
        }
        _atomic_write(
            arguments.report, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.stderr.write(f"historical signal model failed: {error}\n")
        return 2
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
