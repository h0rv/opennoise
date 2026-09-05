"""Build one bounded, reproducible artist-backed MusicBrainz metadata expansion."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from musix.artist_backed_release_expansion import (
    ArtistBackedReleaseExpansionAdapter,
    ArtistBackedReleaseExpansionArtifact,
    ArtistBackedReleaseExpansionPublication,
    CatalogHydrationResult,
    ExpansionCoverage,
    ExpansionSettings,
    build_expansion_plan,
    materialize_expansion_catalog,
    write_expansion_artifact,
)
from musix.storage import LocalObjectStore

PREVIOUS_SERVING_RELEASE_COUNT = 20


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class DatabaseCounts(_StrictModel):
    """Count materialized catalog entities in one serving database snapshot."""

    releases: int = Field(ge=0)
    media: int = Field(ge=0)
    tracks: int = Field(ge=0)
    recordings: int = Field(ge=0)


class DatabaseReport(_StrictModel):
    """Integrity, FK, hash, and catalog-count report for one SQLite snapshot."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    integrity_check: tuple[str, ...]
    foreign_key_violations: int = Field(ge=0)
    catalog_counts: DatabaseCounts


class AcceptanceGate(_StrictModel):
    """Fail-closed acceptance result for the online build and replay."""

    passed: bool
    failures: tuple[str, ...]


class OfflineReplayReport(_StrictModel):
    """Record whether the cache-only replay made any upstream requests."""

    matches: bool
    upstream_request_count: int = Field(ge=0)


class CatalogReachability(_StrictModel):
    """Product-join counts proving evidence genres reach materialized releases."""

    reachable_genre_count: int = Field(ge=0)
    reachable_release_group_count: int = Field(ge=0)
    reachable_release_count: int = Field(ge=0)
    missing_release_link_count: int = Field(ge=0)


class ExpansionBuildReport(_StrictModel):
    """Machine-readable custody, expansion, materialization, and gate receipt."""

    revision: Literal["artist-backed-release-expansion-build-v1"] = (
        "artist-backed-release-expansion-build-v1"
    )
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication: ArtistBackedReleaseExpansionPublication
    coverage: ExpansionCoverage
    catalog: CatalogHydrationResult
    database_before: DatabaseReport
    database_after: DatabaseReport
    source_database_unchanged: bool
    materialization_replay: CatalogHydrationResult
    catalog_reachability: CatalogReachability
    upstream_request_count: int = Field(ge=0)
    offline_replay: OfflineReplayReport
    acceptance_gate: AcceptanceGate


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--cache-directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="new serving SQLite path; the source database is copied before materialization",
    )
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--max-genres", type=int, default=48)
    parser.add_argument("--max-seeds-per-genre", type=int, default=2)
    parser.add_argument("--max-releases-per-seed", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database(source: Path, destination: Path) -> None:
    """Make a fresh SQLite backup so the certified source remains untouched."""
    if destination.exists():
        raise FileExistsError(f"serving database already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source_connection,
        closing(sqlite3.connect(destination)) as destination_connection,
    ):
        source_connection.backup(destination_connection)


def _finalize_database(path: Path) -> None:
    """Checkpoint the copied serving DB and remove empty WAL sidecars."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.commit()
    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() and suffix == "-wal" and sidecar.stat().st_size != 0:
            raise RuntimeError(f"serving database left a non-empty {suffix} sidecar")
        sidecar.unlink(missing_ok=True)


def _database_report(path: Path) -> DatabaseReport:
    with closing(sqlite3.connect(path)) as connection:
        integrity = tuple(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))
        foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
        row = connection.execute(
            """
            SELECT (SELECT count(*) FROM releases),
                   (SELECT count(*) FROM media),
                   (SELECT count(*) FROM tracks),
                   (SELECT count(*) FROM recordings)
            """
        ).fetchone()
    return DatabaseReport(
        sha256=_sha256(path),
        integrity_check=integrity,
        foreign_key_violations=len(foreign_keys),
        catalog_counts=DatabaseCounts(
            releases=int(row[0]) if row else 0,
            media=int(row[1]) if row else 0,
            tracks=int(row[2]) if row else 0,
            recordings=int(row[3]) if row else 0,
        ),
    )


def _catalog_reachability(
    artifact: ArtistBackedReleaseExpansionArtifact, database: Path
) -> CatalogReachability:
    """Verify the genre → source evidence → release-group → release product join."""
    genres: set[str] = set()
    groups: set[str] = set()
    releases: set[str] = set()
    missing = 0
    with closing(sqlite3.connect(database)) as connection:
        for result in artifact.results:
            for release in result.releases:
                evidence = release.evidence
                row = connection.execute(
                    """
                    SELECT genre_identifier.normalized_value,
                           group_identifier.normalized_value,
                           release_identifier.normalized_value
                    FROM album_genre_membership_observations AS album
                    JOIN entity_identifiers AS genre_identifier
                      ON genre_identifier.entity_id = album.genre_id
                    JOIN identifier_types AS genre_type
                      ON genre_type.id = genre_identifier.identifier_type_id
                     AND genre_type.type_key = 'wikidata_genre_qid'
                    JOIN entity_identifiers AS group_identifier
                      ON group_identifier.entity_id = album.release_group_id
                    JOIN identifier_types AS group_type
                      ON group_type.id = group_identifier.identifier_type_id
                     AND group_type.type_key = 'musicbrainz_release_group_id'
                    JOIN releases AS stored_release
                      ON stored_release.release_group_id = album.release_group_id
                    JOIN entity_identifiers AS release_identifier
                      ON release_identifier.entity_id = stored_release.id
                    JOIN identifier_types AS release_type
                      ON release_type.id = release_identifier.identifier_type_id
                     AND release_type.type_key = 'musicbrainz_release_id'
                    JOIN artist_genre_evidence AS direct
                      ON direct.id = ?
                     AND direct.genre_id = album.genre_id
                     AND direct.evidence_kind = 'direct_source_claim'
                    JOIN entity_identifiers AS artist_identifier
                      ON artist_identifier.entity_id = direct.artist_id
                    JOIN identifier_types AS artist_type
                      ON artist_type.id = artist_identifier.identifier_type_id
                     AND artist_type.type_key = 'musicbrainz_artist_id'
                    WHERE album.id = ?
                      AND genre_identifier.normalized_value = ?
                      AND group_identifier.normalized_value = ?
                      AND release_identifier.normalized_value = ?
                      AND artist_identifier.normalized_value = ?
                    LIMIT 1
                    """,
                    (
                        evidence.direct_artist_evidence_id,
                        evidence.album_evidence_id,
                        evidence.genre_ref.removeprefix("wikidata:genre:"),
                        str(release.release_group_id),
                        str(release.release_id),
                        str(evidence.matching_artist_mbid),
                    ),
                ).fetchone()
                if row is None:
                    missing += 1
                    continue
                genres.add(str(row[0]))
                groups.add(str(row[1]))
                releases.add(str(row[2]))
    return CatalogReachability(
        reachable_genre_count=len(genres),
        reachable_release_group_count=len(groups),
        reachable_release_count=len(releases),
        missing_release_link_count=missing,
    )


def _acceptance_gate(  # noqa: PLR0913
    *,
    source_hash_before: str,
    source_hash_after: str,
    before: DatabaseReport,
    after: DatabaseReport,
    catalog: CatalogHydrationResult,
    replay_catalog: CatalogHydrationResult,
    reachability: CatalogReachability,
    artifact_release_count: int,
    replay_matches: bool,
) -> AcceptanceGate:
    """Fail closed when custody, materialization, or replay invariants drift."""
    failures: list[str] = []
    if source_hash_before != source_hash_after:
        failures.append("certified source database changed")
    if after.integrity_check != ("ok",):
        failures.append("serving database integrity check failed")
    if after.foreign_key_violations != 0:
        failures.append("serving database has foreign-key violations")
    before_counts = before.catalog_counts
    after_counts = after.catalog_counts
    materialized_counts = {
        "releases": catalog.releases,
        "media": catalog.media,
        "tracks": catalog.tracks,
        "recordings": catalog.recordings,
    }
    failures.extend(
        f"{field} count delta does not match materializer result"
        for field in ("releases", "media", "tracks", "recordings")
        if getattr(after_counts, field) - getattr(before_counts, field)
        != materialized_counts[field]
    )
    if not replay_matches:
        failures.append("offline replay differs from online artifact")
    if replay_catalog != CatalogHydrationResult(releases=0, media=0, tracks=0, recordings=0):
        failures.append("replaying the same artifact was not idempotent")
    inserted = any(
        value > 0
        for value in (
            catalog.releases,
            catalog.media,
            catalog.tracks,
            catalog.recordings,
        )
    )
    if inserted and before.sha256 == after.sha256:
        failures.append("serving database hash did not change despite inserted catalog rows")
    if reachability.missing_release_link_count != 0:
        failures.append("one or more expanded releases are unreachable from product evidence")
    if artifact_release_count <= PREVIOUS_SERVING_RELEASE_COUNT:
        failures.append("expansion did not exceed the previous 20-release serving slice")
    return AcceptanceGate(passed=not failures, failures=tuple(failures))


async def _run(arguments: argparse.Namespace) -> ExpansionBuildReport:
    settings = ExpansionSettings(
        max_genres=arguments.max_genres,
        max_seeds_per_genre=arguments.max_seeds_per_genre,
        max_releases_per_seed=arguments.max_releases_per_seed,
        max_attempts=arguments.max_attempts,
        cache_directory=arguments.cache_directory,
        offline=arguments.offline,
    )
    plan = build_expansion_plan(arguments.source_database, settings)
    source_hash_before = _sha256(arguments.source_database)
    async with httpx.AsyncClient(timeout=arguments.timeout_seconds) as client:
        adapter = ArtistBackedReleaseExpansionAdapter(
            client, settings, user_agent=arguments.user_agent
        )
        artifact = await adapter.hydrate(plan)
    publication = write_expansion_artifact(
        artifact, output=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    _copy_database(arguments.source_database, arguments.database)
    before_database = _database_report(arguments.database)
    catalog = materialize_expansion_catalog(
        artifact, database_path=arguments.database, artifact_sha256=publication.artifact.sha256
    )
    async with httpx.AsyncClient(timeout=arguments.timeout_seconds) as replay_client:
        replay = ArtistBackedReleaseExpansionAdapter(
            replay_client,
            settings.model_copy(update={"offline": True}),
            user_agent=arguments.user_agent,
        )
        replay_artifact = await replay.hydrate(plan)
    replay_matches = artifact == replay_artifact
    replay_catalog = materialize_expansion_catalog(
        replay_artifact,
        database_path=arguments.database,
        artifact_sha256=publication.artifact.sha256,
    )
    _finalize_database(arguments.database)
    after_database = _database_report(arguments.database)
    reachability = _catalog_reachability(artifact, arguments.database)
    source_hash_after = _sha256(arguments.source_database)
    gate = _acceptance_gate(
        source_hash_before=source_hash_before,
        source_hash_after=source_hash_after,
        before=before_database,
        after=after_database,
        catalog=catalog,
        replay_catalog=replay_catalog,
        reachability=reachability,
        artifact_release_count=artifact.coverage.unique_release_count,
        replay_matches=replay_matches,
    )
    if not gate.passed:
        raise RuntimeError(gate.model_dump_json())
    return ExpansionBuildReport(
        plan_sha256=artifact.plan_sha256,
        source_database_sha256=plan.source_database_sha256,
        publication=publication,
        coverage=artifact.coverage,
        catalog=catalog,
        database_before=before_database,
        database_after=after_database,
        source_database_unchanged=source_hash_after == source_hash_before,
        materialization_replay=replay_catalog,
        catalog_reachability=reachability,
        upstream_request_count=adapter.upstream_request_count,
        offline_replay=OfflineReplayReport(
            matches=replay_artifact == artifact,
            upstream_request_count=replay.upstream_request_count,
        ),
        acceptance_gate=gate,
    )


def main() -> int:
    """Run a one-shot bounded build and emit a machine-readable receipt."""
    arguments = _arguments()
    report = asyncio.run(_run(arguments))
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
