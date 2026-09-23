"""Write a local, source-bound human review packet from the retained Album report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from opennoise.evidence.musicbrainz_album_review import build_musicbrainz_album_review_packet
from opennoise.ingest.musicbrainz.release_group_album_examples import (
    ReleaseGroupAlbumExamplesReport,
)


def _write_once(path: Path, payload: bytes) -> None:
    """Write bytes atomically without replacing an existing packet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build from existing local report files; never scan source archives."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(".cache/musicbrainz-release-group-album-examples-v1/report.json"),
    )
    parser.add_argument(
        "--reconciliation",
        type=Path,
        default=Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".cache/musicbrainz-album-context-review-v2/packet.json"),
    )
    arguments = parser.parse_args()
    report_bytes = arguments.report.read_bytes()
    report = ReleaseGroupAlbumExamplesReport.model_validate_json(report_bytes)
    reconciliation_bytes = arguments.reconciliation.read_bytes()
    if hashlib.sha256(reconciliation_bytes).hexdigest() != report.seed_reconciliation_sha256:
        parser.error("reconciliation bytes do not match the pinned source report")
    reconciliation = json.loads(reconciliation_bytes)
    identities = {
        row["normalized_name"]: (row["source_item_id"], row["disposition"])
        for row in reconciliation["dispositions"]
    }
    packet = build_musicbrainz_album_review_packet(
        report,
        source_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        reconciliation=identities,
    )
    _write_once(arguments.output, (packet.model_dump_json(indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
