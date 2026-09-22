"""Write the local-only exact-MBID direct-name frontier report."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_name_join_frontier import (
    build_musicbrainz_direct_name_join_frontier,
    report_json,
)


def main() -> int:
    """Write one fresh report and never modify static delivery."""
    parser = argparse.ArgumentParser(prog="report-musicbrainz-direct-name-join-frontier")
    parser.add_argument("--direct-custody-receipt", type=Path, required=True)
    parser.add_argument("--direct-custody-receipt-sha256", required=True)
    parser.add_argument("--direct-object-store", type=Path, required=True)
    parser.add_argument("--name-custody-receipt", type=Path, required=True)
    parser.add_argument("--name-custody-receipt-sha256", required=True)
    parser.add_argument("--name-object-store", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--certified-manifest", type=Path, required=True)
    parser.add_argument("--certified-layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_musicbrainz_direct_name_join_frontier(
        direct_custody_receipt_path=arguments.direct_custody_receipt,
        direct_custody_receipt_sha256=arguments.direct_custody_receipt_sha256,
        direct_object_store=arguments.direct_object_store,
        name_custody_receipt_path=arguments.name_custody_receipt,
        name_custody_receipt_sha256=arguments.name_custody_receipt_sha256,
        name_object_store=arguments.name_object_store,
        static_discovery_path=arguments.static_discovery,
        certified_manifest_path=arguments.certified_manifest,
        certified_layout_path=arguments.certified_layout,
    )
    _write_fresh_output(arguments.output, report_json(report).encode())
    return 0


def _write_fresh_output(path: Path, payload: bytes) -> None:
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
