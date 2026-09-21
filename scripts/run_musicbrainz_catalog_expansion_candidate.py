"""Run a bounded, metadata-only MusicBrainz hydration candidate with replay proof."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from opennoise.ingest.musicbrainz.release_hydration import (
    HydrationBatchResult,
    HydrationSettings,
    MusicBrainzReleaseHydrationArtifact,
    MusicBrainzReleaseTrackHydrationAdapter,
    artifact_counts,
    load_representative_artifact,
    write_hydration_artifact,
)
from opennoise.storage import LocalObjectStore


@dataclass(frozen=True, slots=True)
class _CandidateSettings:
    representatives: Path
    cache_directory: Path
    user_agent: str
    max_genres: int
    max_releases_per_seed: int
    max_attempts: int
    timeout_seconds: float


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--representatives", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--object-store", required=True, type=Path)
    parser.add_argument("--cache-directory", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--max-genres", required=True, type=int)
    parser.add_argument("--max-releases-per-seed", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


async def _hydrate_batch(
    settings: _CandidateSettings, *, offline: bool
) -> tuple[HydrationBatchResult, int]:
    artifact, source_sha256 = load_representative_artifact(settings.representatives)
    hydration_settings = HydrationSettings(
        cache_directory=settings.cache_directory,
        max_genres=settings.max_genres,
        max_releases_per_seed=settings.max_releases_per_seed,
        max_attempts=settings.max_attempts,
        offline=offline,
    )
    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
        adapter = MusicBrainzReleaseTrackHydrationAdapter(
            client, hydration_settings, user_agent=settings.user_agent
        )
        result = await adapter.hydrate_batch(artifact, source_sha256=source_sha256)
    return result, adapter.upstream_request_count


def _load_artifact(path: Path) -> MusicBrainzReleaseHydrationArtifact:
    return MusicBrainzReleaseHydrationArtifact.model_validate_json(path.read_bytes())


def main() -> int:
    """Write a new candidate plus an offline-identical bounded coverage report."""
    arguments = _arguments()
    settings = _CandidateSettings(
        representatives=arguments.representatives,
        cache_directory=arguments.cache_directory,
        user_agent=arguments.user_agent,
        max_genres=arguments.max_genres,
        max_releases_per_seed=arguments.max_releases_per_seed,
        max_attempts=arguments.max_attempts,
        timeout_seconds=arguments.timeout_seconds,
    )
    baseline = _load_artifact(arguments.baseline)
    online, upstream_request_count = asyncio.run(_hydrate_batch(settings, offline=False))
    offline, offline_upstream_request_count = asyncio.run(_hydrate_batch(settings, offline=True))
    if offline.artifact != online.artifact or offline.failures != online.failures:
        raise RuntimeError("offline replay differs from online hydration")
    if offline_upstream_request_count:
        raise RuntimeError("offline replay made upstream requests")
    publication = write_hydration_artifact(
        online.artifact,
        output=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    baseline_releases, baseline_media, baseline_tracks = artifact_counts(baseline)
    report = {
        "revision": "musicbrainz-catalog-expansion-candidate-v1",
        "inputs": {
            "baseline": str(arguments.baseline),
            "representatives": str(arguments.representatives),
        },
        "bounds": {
            "max_genres": arguments.max_genres,
            "max_releases_per_seed": arguments.max_releases_per_seed,
        },
        "publication": publication.model_dump(mode="json"),
        "candidate_counts": {
            "releases": publication.release_count,
            "media": publication.medium_count,
            "tracks": publication.track_count,
        },
        "baseline_counts": {
            "releases": baseline_releases,
            "media": baseline_media,
            "tracks": baseline_tracks,
        },
        "delta_from_baseline": {
            "releases": publication.release_count - baseline_releases,
            "media": publication.medium_count - baseline_media,
            "tracks": publication.track_count - baseline_tracks,
        },
        "online": {
            "selected_seed_count": online.selected_seed_count,
            "failure_count": len(online.failures),
            "failures": [failure.model_dump(mode="json") for failure in online.failures],
            "upstream_request_count": upstream_request_count,
        },
        "offline_replay": {
            "artifact_matches": offline.artifact == online.artifact,
            "failures_match": offline.failures == online.failures,
            "upstream_request_count": offline_upstream_request_count,
        },
        "sealed_database_mutated": False,
    }
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(publication.artifact.sha256)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
