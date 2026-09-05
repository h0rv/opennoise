# ruff: noqa: S608

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

import httpx

from musix.artist_backed_release_expansion import (
    ArtistBackedReleaseExpansionAdapter,
    ArtistBackedReleaseExpansionError,
    ArtistBackedReleaseExpansionPlan,
    DirectArtistGenreAnchor,
    ExpansionSettings,
    ReleaseGroupSeed,
    materialize_expansion_catalog,
    write_expansion_artifact,
)
from musix.musicbrainz_release_hydration import CatalogHydrationResult
from musix.storage import LocalObjectStore
from scripts.build_artist_backed_release_expansion import (
    AcceptanceGate,
    CatalogReachability,
    DatabaseCounts,
    DatabaseReport,
    _acceptance_gate,
)
from tests._test_client import PollingIsolatedAsyncioTestCase

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(sorted((ROOT / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")))
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"

GENRE_REF = "wikidata:genre:Q42"
ARTIST_ID = UUID("10000000-0000-4000-8000-000000000001")
GROUP_ID = UUID("20000000-0000-4000-8000-000000000001")
RELEASE_ID = UUID("30000000-0000-4000-8000-000000000001")
SECOND_RELEASE_ID = UUID("30000000-0000-4000-8000-000000000002")
TRACK_ID = UUID("40000000-0000-4000-8000-000000000001")
RECORDING_ID = UUID("50000000-0000-4000-8000-000000000001")


def _plan(root: Path, *, max_releases_per_seed: int = 1) -> ArtistBackedReleaseExpansionPlan:
    settings = ExpansionSettings(
        cache_directory=root / "cache",
        max_genres=21,
        max_seeds_per_genre=1,
        max_releases_per_seed=max_releases_per_seed,
        max_attempts=1,
    )
    return ArtistBackedReleaseExpansionPlan(
        source_database_sha256="a" * 64,
        settings=settings,
        anchors=(
            DirectArtistGenreAnchor(
                genre_ref=GENRE_REF,
                artist_mbid=ARTIST_ID,
                evidence_id=1,
                provenance_id=2,
                policy_id=3,
                source_key="wikidata_phase3_artists_00",
            ),
        ),
        seeds=(
            ReleaseGroupSeed(
                genre_ref=GENRE_REF,
                release_group_mbid=GROUP_ID,
                album_evidence_id=1,
                provenance_id=5,
                policy_id=6,
                source_key="wikidata_phase3_release_group_details_00",
            ),
        ),
    )


def _release(release_id: UUID) -> dict[str, object]:
    return {
        "id": str(release_id),
        "title": "Synthetic Release",
        "release-group": {"id": str(GROUP_ID), "title": "Synthetic Group"},
        "status": "Official",
        "country": "US",
        "date": "2001-02-03",
        "genres": [{"name": "must not be retained"}],
        "media": [
            {
                "position": 1,
                "format": "CD",
                "track-count": 1,
                "tracks": [
                    {
                        "id": str(TRACK_ID),
                        "position": 1,
                        "number": "1",
                        "title": "Synthetic Track",
                        "length": 1234,
                        "recording": {
                            "id": str(RECORDING_ID),
                            "title": "Synthetic Track",
                            "length": 1234,
                        },
                    }
                ],
            }
        ],
    }


class ArtistBackedReleaseExpansionTests(PollingIsolatedAsyncioTestCase):
    def test_acceptance_gate_rejects_unchanged_hash_with_inserted_rows(self) -> None:
        before = DatabaseReport(
            sha256="a" * 64,
            integrity_check=("ok",),
            foreign_key_violations=0,
            catalog_counts=DatabaseCounts(releases=0, media=0, tracks=0, recordings=0),
        )
        after = before.model_copy(
            update={"catalog_counts": DatabaseCounts(releases=1, media=1, tracks=1, recordings=1)}
        )
        gate = _acceptance_gate(
            source_hash_before="c" * 64,
            source_hash_after="c" * 64,
            before=before,
            after=after,
            catalog=CatalogHydrationResult(releases=1, media=1, tracks=1, recordings=1),
            replay_catalog=CatalogHydrationResult(releases=0, media=0, tracks=0, recordings=0),
            reachability=CatalogReachability(
                reachable_genre_count=1,
                reachable_release_group_count=1,
                reachable_release_count=1,
                missing_release_link_count=0,
            ),
            artifact_release_count=21,
            replay_matches=True,
        )
        self.assertIsInstance(gate, AcceptanceGate)
        self.assertFalse(gate.passed)
        self.assertIn("hash did not change", " ".join(gate.failures))

    async def test_hydrates_core_metadata_and_replays_offline(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith(f"release-group/{GROUP_ID}"):
                return httpx.Response(
                    200,
                    json={
                        "id": str(GROUP_ID),
                        "title": "Synthetic Group",
                        "artist-credit": [{"artist": {"id": str(ARTIST_ID), "name": "Artist"}}],
                        "releases": [
                            {
                                "id": str(RELEASE_ID),
                                "title": "Synthetic Release",
                                "date": "2001-02-03",
                            }
                        ],
                    },
                )
            if request.url.path.endswith(f"release/{RELEASE_ID}"):
                return httpx.Response(200, json=_release(RELEASE_ID))
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = ArtistBackedReleaseExpansionAdapter(
                    client,
                    plan.settings,
                    user_agent="musix/0.1 (maintainer@example.test)",
                )
                artifact = await adapter.hydrate(plan)
            self.assertEqual(len(requests), 2)
            self.assertEqual(artifact.coverage.hydrated_seed_count, 1)
            self.assertEqual(artifact.coverage.unique_release_count, 1)
            self.assertEqual(artifact.coverage.track_count, 1)
            rendered = artifact.model_dump_json()
            self.assertNotIn("must not be retained", rendered)
            self.assertIn("track_metadata_not_playable_media", rendered)

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                replay = ArtistBackedReleaseExpansionAdapter(
                    client,
                    plan.settings.model_copy(update={"offline": True}),
                    user_agent="musix/0.1 (maintainer@example.test)",
                )
                replayed = await replay.hydrate(plan)
            self.assertEqual(replayed, artifact)
            self.assertEqual(replay.upstream_request_count, 0)

            cache_entry = next((root / "cache").glob("*.json"))
            cache_payload = json.loads(cache_entry.read_text(encoding="utf-8"))
            cache_payload["payload"]["title"] = "tampered projection"
            cache_entry.write_text(json.dumps(cache_payload), encoding="utf-8")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                tampered = ArtistBackedReleaseExpansionAdapter(
                    client,
                    plan.settings.model_copy(update={"offline": True}),
                    user_agent="musix/0.1 (maintainer@example.test)",
                )
                tampered_artifact = await tampered.hydrate(plan)
            self.assertEqual(tampered_artifact.coverage.metadata_unavailable_count, 1)
            self.assertEqual(tampered_artifact.coverage.unique_release_count, 0)

            publication = write_expansion_artifact(
                artifact,
                output=root / "expansion.json",
                store=LocalObjectStore(root / "objects"),
            )
            self.assertEqual(publication.coverage.track_count, 1)
            self.assertTrue((root / "objects" / publication.artifact.key.value).is_file())

            other_root = root / "other-cache"
            other_plan = _plan(other_root)
            other_plan = other_plan.model_copy(
                update={
                    "settings": other_plan.settings.model_copy(
                        update={"max_attempts": 3, "offline": False}
                    )
                }
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                other_adapter = ArtistBackedReleaseExpansionAdapter(
                    client,
                    other_plan.settings,
                    user_agent="musix/0.1 (maintainer@example.test)",
                )
                other_artifact = await other_adapter.hydrate(other_plan)
            self.assertEqual(other_artifact, artifact)

    async def test_materializes_copied_database_with_source_linkage_and_idempotence(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(f"release-group/{GROUP_ID}"):
                return httpx.Response(
                    200,
                    json={
                        "id": str(GROUP_ID),
                        "title": "Synthetic Group",
                        "artist-credit": [{"artist": {"id": str(ARTIST_ID), "name": "Artist"}}],
                        "releases": [{"id": str(RELEASE_ID), "title": "Synthetic Release"}],
                    },
                )
            return httpx.Response(200, json=_release(RELEASE_ID))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            _create_evidence_fixture(source)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            serving = root / "serving.sqlite"
            shutil.copyfile(source, serving)
            plan = _plan(root)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = ArtistBackedReleaseExpansionAdapter(
                    client, plan.settings, user_agent="musix/0.1 (maintainer@example.test)"
                )
                artifact = await adapter.hydrate(plan)
            counts = materialize_expansion_catalog(
                artifact, database_path=serving, artifact_sha256="b" * 64
            )
            self.assertEqual(
                (counts.releases, counts.media, counts.tracks, counts.recordings), (1, 1, 1, 1)
            )
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            with sqlite3.connect(serving) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(tuple(connection.execute("PRAGMA foreign_key_check")), ())
            replay_counts = materialize_expansion_catalog(
                artifact, database_path=serving, artifact_sha256="b" * 64
            )
            self.assertEqual(
                replay_counts,
                counts.model_copy(update={"releases": 0, "media": 0, "tracks": 0, "recordings": 0}),
            )

            invalid = (
                artifact.results[0]
                .releases[0]
                .evidence.model_copy(update={"direct_artist_evidence_id": 999999})
            )
            invalid_release = (
                artifact.results[0].releases[0].model_copy(update={"evidence": invalid})
            )
            invalid_result = artifact.results[0].model_copy(update={"releases": (invalid_release,)})
            invalid_artifact = artifact.model_copy(update={"results": (invalid_result,)})
            with self.assertRaisesRegex(ArtistBackedReleaseExpansionError, "artist evidence"):
                materialize_expansion_catalog(
                    invalid_artifact, database_path=serving, artifact_sha256="c" * 64
                )

    async def test_partial_release_fetch_is_one_explicit_abstention(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(f"release-group/{GROUP_ID}"):
                return httpx.Response(
                    200,
                    json={
                        "id": str(GROUP_ID),
                        "title": "Synthetic Group",
                        "artist-credit": [{"artist": {"id": str(ARTIST_ID), "name": "Artist"}}],
                        "releases": [
                            {"id": str(RELEASE_ID), "title": "Synthetic Release"},
                            {"id": str(SECOND_RELEASE_ID), "title": "Missing Release"},
                        ],
                    },
                )
            if request.url.path.endswith(f"release/{RELEASE_ID}"):
                return httpx.Response(200, json=_release(RELEASE_ID))
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = _plan(root, max_releases_per_seed=2)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = ArtistBackedReleaseExpansionAdapter(
                    client,
                    plan.settings,
                    user_agent="musix/0.1 (maintainer@example.test)",
                )
                artifact = await adapter.hydrate(plan)
            self.assertEqual(len(artifact.results), 1)
            result = artifact.results[0]
            self.assertEqual(result.releases, ())
            self.assertEqual(result.abstention_reason, "musicbrainz_metadata_unavailable")
            self.assertEqual(artifact.coverage.hydrated_seed_count, 0)
            self.assertEqual(artifact.coverage.abstained_seed_count, 1)
            self.assertEqual(artifact.coverage.metadata_unavailable_count, 1)


if __name__ == "__main__":
    unittest.main()


def _create_evidence_fixture(path: Path) -> None:
    """Build a tiny migration fixture with the exact public evidence joins."""
    with sqlite3.connect(path) as connection:
        for migration in MIGRATIONS:
            connection.executescript(migration.read_text(encoding="utf-8"))
        connection.executescript(FIXTURE.read_text(encoding="utf-8"))
        connection.executescript(
            f"""
            INSERT INTO rights_policies
                (id, policy_key, policy_version, classification, local_only, basis)
            VALUES (3, 'wikidata-public', 1, 'public_domain', 0, 'CC0 fixture');
            INSERT INTO rights_policy_permissions (policy_id, use_kind, decision, reason)
            VALUES
                (3, 'normalize', 'allow', 'CC0 fixture'),
                (3, 'local_search', 'allow', 'CC0 fixture'),
                (3, 'display', 'allow', 'CC0 fixture'),
                (3, 'embed', 'allow', 'CC0 fixture'),
                (3, 'train', 'allow', 'CC0 fixture'),
                (3, 'export', 'allow', 'CC0 fixture');
            INSERT INTO rights_policy_seals (policy_id, sealed_at)
            VALUES (3, '2026-01-01T00:00:00Z');
            INSERT INTO data_sources (id, source_key, name, default_policy_id)
            VALUES (3, 'wikidata_phase3_release_group_details_00', 'Wikidata fixture', 3);
            INSERT INTO provenance_records
                (id, source_id, policy_id, snapshot_ref, artifact_sha256,
                 record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at)
            VALUES (3, 3, 3, 'fixture-2', '{"a" * 64}', '{"b" * 64}', 'fixture-2', 'attempt-2',
                    '2026-01-01T00:00:00Z');
            INSERT INTO data_sources (id, source_key, name, default_policy_id)
            VALUES (4, 'wikidata_phase3_artists_00', 'Wikidata artists fixture', 3);
            INSERT INTO provenance_records
                (id, source_id, policy_id, snapshot_ref, artifact_sha256,
                 record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at)
            VALUES (4, 4, 3, 'fixture-3', '{"c" * 64}', '{"d" * 64}', 'fixture-3', 'attempt-3',
                    '2026-01-01T00:00:00Z');
            INSERT INTO identifier_types (id, type_key, name) VALUES
                (2, 'wikidata_genre_qid', 'Wikidata Genre Qid'),
                (3, 'musicbrainz_release_group_id', 'MusicBrainz Release Group Id'),
                (4, 'musicbrainz_artist_id', 'MusicBrainz Artist Id');
            INSERT INTO entity_identifiers
                (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
            VALUES
                (1, 2, 'wikidata', 'Q42', 'Q42', 3),
                (5, 3, 'musicbrainz', '{GROUP_ID}', '{GROUP_ID}', 3),
                (2, 4, 'musicbrainz', '{ARTIST_ID}', '{ARTIST_ID}', 4);
            INSERT INTO album_genre_membership_observations
                (release_group_id, genre_id, evidence_kind, evidence_level, source_family,
                 source_record_id, source_genre_name, method_key, method_version, observed_at,
                 provenance_id, policy_id, record_fingerprint)
            VALUES (5, 1, 'wikidata_p136', 'release_group', 'wikidata', 'fixture:group', 'Q42',
                    'direct_source_claim', '1', '2026-01-01T00:00:00Z', 3, 3, '{"e" * 64}');
            INSERT INTO artist_genre_evidence
                (artist_id, genre_id, evidence_kind, evidence_value, source_key, source_record_id,
                 method_key, method_version, parameter_manifest_json, observed_at, provenance_id,
                 policy_id, record_fingerprint)
            VALUES (2, 1, 'direct_source_claim', 1.0,
                    'wikidata_phase3_artists_00', 'fixture:artist',
                    'direct_source_claim', '1', '{{}}', '2026-01-01T00:00:00Z', 4, 3, '{"f" * 64}');
            """
        )
