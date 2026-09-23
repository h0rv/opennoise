"""Run the capped local-only exact MusicBrainz recording coverage probe."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

import httpx

from opennoise.analysis.listenbrainz_recording_co_listen import RecordingIdCohortArtifact
from opennoise.analysis.musicbrainz_recording_coverage import (
    MusicBrainzRecordingCoverageError,
    RecordingLookupSettings,
    measure_exact_recording_coverage,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--expected-cohort-file-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--response-cache-directory", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--maximum-recordings", type=int, default=24)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    cohort_bytes = arguments.cohort.read_bytes()
    cohort_file_sha256 = hashlib.sha256(cohort_bytes).hexdigest()
    if cohort_file_sha256 != arguments.expected_cohort_file_sha256:
        raise ValueError("cohort file SHA-256 does not match the required expected value")
    cohort = RecordingIdCohortArtifact.model_validate_json(cohort_bytes)
    settings = RecordingLookupSettings(
        maximum_recordings=arguments.maximum_recordings,
        timeout_seconds=arguments.timeout_seconds,
    )
    async with httpx.AsyncClient(
        timeout=settings.timeout_seconds, follow_redirects=False
    ) as client:
        artifact = await measure_exact_recording_coverage(
            cohort,
            client,
            user_agent=arguments.user_agent,
            cohort_artifact_file_sha256=cohort_file_sha256,
            settings=settings,
            response_cache_directory=arguments.response_cache_directory,
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_name(f".{arguments.output.name}.tmp")
    try:
        temporary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(arguments.output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Write one new local-only source-receipted artifact."""
    arguments = _arguments()
    if arguments.output.exists():
        sys.stderr.write("MusicBrainz recording coverage output already exists\n")
        return 2
    try:
        asyncio.run(_run(arguments))
    except (MusicBrainzRecordingCoverageError, OSError, ValueError) as error:
        sys.stderr.write(f"MusicBrainz recording coverage failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only MusicBrainz recording coverage: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
