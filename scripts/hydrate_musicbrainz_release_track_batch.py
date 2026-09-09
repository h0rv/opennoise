"""Run and verify one resumable bounded MusicBrainz core-metadata publication batch."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

from musix.ingest.musicbrainz.musicbrainz_release_hydration import (
    HydrationSettings,
    MusicBrainzReleaseTrackHydrationAdapter,
    load_representative_artifact,
    materialize_hydration_catalog,
    write_hydration_artifact,
)
from musix.storage import LocalObjectStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _checks(path: Path) -> dict[str, object]:
    with sqlite3.connect(path) as connection:
        integrity = tuple(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))
        foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
        counts = connection.execute(
            """SELECT (SELECT count(*) FROM releases), (SELECT count(*) FROM media),
                      (SELECT count(*) FROM tracks), (SELECT count(*) FROM recordings)"""
        ).fetchone()
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "catalog_counts": tuple(int(value) for value in counts or ()),
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    representatives, source_sha256 = load_representative_artifact(args.representatives)
    settings = HydrationSettings(
        cache_directory=args.cache_directory,
        max_genres=args.max_genres,
        max_releases_per_seed=args.max_releases_per_seed,
        max_attempts=args.max_attempts,
    )
    async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
        adapter = MusicBrainzReleaseTrackHydrationAdapter(
            client, settings, user_agent=args.user_agent
        )
        started = time.monotonic()
        batch = await adapter.hydrate_batch(representatives, source_sha256=source_sha256)
        elapsed = time.monotonic() - started
    publication = write_hydration_artifact(
        batch.artifact, output=args.output, store=LocalObjectStore(args.object_store)
    )
    async with httpx.AsyncClient() as replay_client:
        replay = MusicBrainzReleaseTrackHydrationAdapter(
            replay_client,
            settings.model_copy(update={"offline": True}),
            user_agent=args.user_agent,
        )
        replay_batch = await replay.hydrate_batch(representatives, source_sha256=source_sha256)
    catalog_status: dict[str, object]
    replay_catalog: dict[str, object] | None = None
    try:
        if not args.database.exists():
            args.database.parent.mkdir(parents=True, exist_ok=True)
            source_url = f"file:{args.source_database.resolve()}?mode=ro"
            with (
                sqlite3.connect(source_url, uri=True) as source,
                sqlite3.connect(args.database) as destination,
            ):
                source.backup(destination)
        catalog = materialize_hydration_catalog(
            batch.artifact, database_path=args.database, artifact_sha256=publication.artifact.sha256
        )
        replay_result = materialize_hydration_catalog(
            replay_batch.artifact,
            database_path=args.database,
            artifact_sha256=publication.artifact.sha256,
        )
        replay_catalog = {
            "releases": replay_result.releases,
            "media": replay_result.media,
            "tracks": replay_result.tracks,
            "recordings": replay_result.recordings,
        }
        catalog_status = {
            "status": "materialized",
            "releases": catalog.releases,
            "media": catalog.media,
            "tracks": catalog.tracks,
            "recordings": catalog.recordings,
        }
    except sqlite3.Error as error:
        catalog_status = {
            "status": "blocked",
            "error_type": type(error).__name__,
            "message": str(error),
        }
    return {
        "revision": "musicbrainz-release-track-hydration-batch-v1",
        "representative_artifact_sha256": source_sha256,
        "database_before_sha256": _sha256(args.source_database),
        "database_after_sha256": (
            _sha256(args.database) if catalog_status["status"] == "materialized" else None
        ),
        "publication": publication.model_dump(mode="json"),
        "selected_seed_count": batch.selected_seed_count,
        "successful_release_count": len(batch.artifact.releases),
        "failure_count": len(batch.failures),
        "abstention_count": len(batch.failures),
        "failures": [failure.model_dump(mode="json") for failure in batch.failures],
        "runtime_seconds": round(elapsed, 3),
        "upstream_request_count": adapter.upstream_request_count,
        "catalog_materialization": catalog_status,
        "replay_proof": {
            "offline_artifact_matches": replay_batch.artifact == batch.artifact,
            "offline_failure_matches": replay_batch.failures == batch.failures,
            "offline_upstream_request_count": replay.upstream_request_count,
            "replay_catalog_materialization": replay_catalog,
        },
        "database_checks": (
            _checks(args.database) if catalog_status["status"] == "materialized" else None
        ),
    }


def main() -> int:
    """Run the bounded publication and emit its machine-readable verification report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--representatives", type=Path, required=True)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--cache-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--max-genres", type=int, default=20)
    parser.add_argument("--max-releases-per-seed", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    report = asyncio.run(_run(args))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
