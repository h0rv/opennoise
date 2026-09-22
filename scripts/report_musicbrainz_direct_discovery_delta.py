"""Write a local-only MusicBrainz direct discovery delta report."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_discovery_delta import (
    build_musicbrainz_direct_discovery_delta,
    report_json,
)


def main() -> int:
    """Write a review report without modifying static delivery files."""
    parser = argparse.ArgumentParser(prog="report-musicbrainz-direct-discovery-delta")
    parser.add_argument("--custody-receipt", type=Path, required=True)
    parser.add_argument("--custody-object-store", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--certified-manifest", type=Path, required=True)
    parser.add_argument("--certified-layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_musicbrainz_direct_discovery_delta(
        custody_receipt_path=arguments.custody_receipt,
        custody_object_store=arguments.custody_object_store,
        static_discovery_path=arguments.static_discovery,
        certified_manifest_path=arguments.certified_manifest,
        certified_layout_path=arguments.certified_layout,
    )
    _write_fresh_output(arguments.output, report_json(report).encode())
    return 0


def _write_fresh_output(path: Path, payload: bytes) -> None:
    """Create one immutable review report and never replace an earlier report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"refusing to replace local review report: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
