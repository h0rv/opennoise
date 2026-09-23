"""Build one bounded local-only exact recording-ID cohort from a pinned archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_recording_co_listen import (
    RecordingCoListenExperimentError,
    build_recording_id_cohort,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Write a new receipt-bound local cohort without exposing listener data."""
    arguments = _arguments()
    if arguments.output.exists():
        sys.stderr.write("recording ID cohort output already exists\n")
        return 2
    try:
        cohort = build_recording_id_cohort(
            archive_path=arguments.archive,
            source_artifact_sha256=arguments.artifact_sha256,
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.output.with_name(f".{arguments.output.name}.tmp")
        try:
            temporary.write_text(cohort.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(arguments.output)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, RecordingCoListenExperimentError, ValueError) as error:
        sys.stderr.write(f"recording ID cohort failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only recording ID cohort: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
