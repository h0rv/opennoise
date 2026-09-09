"""Publish a verified 6,291-node H3 signal map for explicit local opt-in only."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from musix.history.signals.publication import (
    HistoricalSignalPublicationError,
    build_historical_signal_publication,
    publish_historical_signal_publication,
)
from musix.models.historical import HistoricalCompatibilityReceipt
from musix.models.historical_signal import HistoricalSignalArtifact
from musix.storage import LocalObjectStore


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-artifact", type=Path, required=True)
    parser.add_argument("--compatibility-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def main() -> int:
    """Seal one already-deterministic signal artifact without changing the public default."""
    arguments = _arguments()
    try:
        started = time.monotonic()
        signal = HistoricalSignalArtifact.model_validate_json(
            arguments.signal_artifact.read_text(encoding="utf-8")
        )
        compatibility = HistoricalCompatibilityReceipt.model_validate_json(
            arguments.compatibility_receipt.read_text(encoding="utf-8")
        )
        artifact = build_historical_signal_publication(signal, compatibility)
        receipt, object_write = publish_historical_signal_publication(
            artifact,
            output_path=arguments.output,
            store=LocalObjectStore(arguments.object_store),
        )
        report = {
            "revision": artifact.revision,
            "source_signal_artifact_sha256": artifact.source_signal_artifact_sha256,
            "publication_receipt": receipt.model_dump(mode="json"),
            "object_write": object_write.model_dump(mode="json"),
            "quality": artifact.quality.model_dump(mode="json"),
            "signal_quality": signal.quality.model_dump(mode="json"),
            "coordinate_evaluation": signal.coordinate_evaluation.model_dump(mode="json"),
            "progressive_lods": [item.model_dump(mode="json") for item in signal.progressive_lods],
            "tile_count": len(signal.tiles),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1_024,
        }
        _write(arguments.receipt, receipt.model_dump_json(indent=2) + "\n")
        _write(arguments.report, json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError, HistoricalSignalPublicationError) as error:
        sys.stderr.write(f"historical signal map publication failed: {error}\n")
        return 2
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
