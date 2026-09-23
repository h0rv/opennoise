"""Assess an exact local recording cohort against named read-only SQLite catalogs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_recording_co_listen import RecordingIdCohortArtifact
from opennoise.analysis.recording_catalog_coverage import (
    LocalCatalogInput,
    RecordingCatalogCoverageError,
    assess_recording_catalog_coverage,
)


def _catalog(value: str) -> LocalCatalogInput:
    label, separator, raw_path = value.partition("=")
    if not separator or not label or not raw_path:
        raise argparse.ArgumentTypeError("catalog must be LABEL=PATH")
    try:
        return LocalCatalogInput(label=label, database_path=Path(raw_path))
    except ValueError as error:
        raise argparse.ArgumentTypeError("catalog label is invalid") from error


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--catalog", type=_catalog, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Write a new aggregate-only receipt without modifying any source catalog."""
    arguments = _arguments()
    if arguments.output.exists():
        sys.stderr.write("recording catalog coverage output already exists\n")
        return 2
    try:
        cohort = RecordingIdCohortArtifact.model_validate_json(arguments.cohort.read_bytes())
        artifact = assess_recording_catalog_coverage(cohort, tuple(arguments.catalog))
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.output.with_name(f".{arguments.output.name}.tmp")
        try:
            temporary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(arguments.output)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, RecordingCatalogCoverageError, ValueError) as error:
        sys.stderr.write(f"recording catalog coverage failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only recording catalog coverage: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
