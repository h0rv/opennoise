"""Run the bounded, aggregate-only ListenBrainz recording coverage experiment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_recording_co_listen import (
    RecordingCoListenExperimentError,
    load_catalog_recording_ids,
    run_recording_co_listen_experiment,
    sha256_file,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--catalog", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Write a new local-only aggregate artifact after receipt verification."""
    arguments = _arguments()
    if arguments.output.exists():
        sys.stderr.write("recording co-listen output already exists\n")
        return 2
    try:
        catalog_recording_ids = load_catalog_recording_ids(arguments.catalog)
        artifact = run_recording_co_listen_experiment(
            archive_path=arguments.archive,
            source_artifact_sha256=arguments.artifact_sha256,
            catalog_recording_ids=catalog_recording_ids,
            catalog_database_sha256=sha256_file(arguments.catalog),
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.output.with_name(f".{arguments.output.name}.tmp")
        try:
            temporary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(arguments.output)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, RecordingCoListenExperimentError, ValueError) as error:
        sys.stderr.write(f"recording co-listen experiment failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only aggregate artifact: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
