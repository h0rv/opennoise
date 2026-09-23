"""Write the pinned, local-only MusicBrainz release-credit genre diagnostic."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from opennoise.ingest.musicbrainz.release_credit_genre_report import (
    build_release_credit_genre_report,
    verify_release_credit_genre_report,
)

_EVIDENCE_DATABASE = Path(".cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite")
_EVIDENCE_ARTIFACT = Path(".cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json")
_CREDIT_CATALOG_DATABASE = Path(
    ".cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite"
)
_CREDIT_CATALOG_REPORT = Path(
    ".cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final-report.json"
)
_OUTPUT = Path(".cache/musicbrainz-release-credit-genre-diagnostic-v1/report.json")


def _write_atomically(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build, verify, and atomically replace the local diagnostic JSON."""
    report = build_release_credit_genre_report(
        evidence_database=_EVIDENCE_DATABASE,
        evidence_artifact_path=_EVIDENCE_ARTIFACT,
        credit_catalog_database=_CREDIT_CATALOG_DATABASE,
        credit_catalog_report_path=_CREDIT_CATALOG_REPORT,
    )
    verify_release_credit_genre_report(report)
    _write_atomically(_OUTPUT, (report.model_dump_json() + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
