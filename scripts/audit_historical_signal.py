"""Audit a sealed H3-only historical signal artifact without reading H2 coordinates."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from musix.history.signals.audit import audit_historical_signal
from musix.models.historical_signal import HistoricalSignalArtifact


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-artifact", type=Path, required=True)
    parser.add_argument("--membership-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _write_atomic(path: Path, payload: bytes) -> None:
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


def main() -> int:
    """Emit a bounded report with no raw H3 membership export."""
    arguments = _arguments()
    try:
        artifact = HistoricalSignalArtifact.model_validate_json(
            arguments.signal_artifact.read_text(encoding="utf-8")
        )
        report = audit_historical_signal(artifact, arguments.membership_database)
        _write_atomic(arguments.output, (report.model_dump_json(indent=2) + "\n").encode())
    except (OSError, ValueError) as error:
        sys.stderr.write(f"historical signal audit failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
