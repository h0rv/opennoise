import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import override

from litestar.testing import TestClient

from musix.app import create_app
from musix.db import Database
from musix.genre_entry import GenreEntryRepository
from musix.ml.public_graph import build_public_model, public_model_output_sha256
from musix.ml.publish import PublicModelPublishError, publish_public_model
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    MetadataCandidate,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"
ARTIST_ID = "11111111-1111-4111-8111-111111111111"
ALBUM_ID = "22222222-2222-4222-8222-222222222222"
TRACK_ID = "33333333-3333-4333-8333-333333333333"


def _artifact():  # noqa: ANN202
    inputs = PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="wikidata",
                snapshot="wikidata-test-snapshot",
                artifact_key=f"wikidata-test:{'a' * 64}",
                content_sha256="a" * 64,
                export_allowed=True,
            ),
        ),
        genres=(
            GenreIdentity(
                genre_id="wikidata:genre:Q100",
                name="Public IDM",
                evidence_refs=("wd:1",),
            ),
            GenreIdentity(
                genre_id="wikidata:genre:Q200",
                name="Electronic",
                evidence_refs=("wd:2",),
            ),
        ),
        direct_memberships=(
            DirectMembershipEvidence(
                artist_id=f"musicbrainz:artist:{ARTIST_ID}",
                genre_id="wikidata:genre:Q100",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:membership:1",
            ),
            DirectMembershipEvidence(
                artist_id=f"musicbrainz:artist:{ARTIST_ID}",
                genre_id="wikidata:genre:Q200",
                facet="wikidata_p136",
                value=1,
                evidence_ref="wd:membership:2",
            ),
        ),
        metadata_candidates=(
            MetadataCandidate(
                entity_kind="artist",
                entity_id=f"musicbrainz:artist:{ARTIST_ID}",
                genre_id="wikidata:genre:Q100",
                name="Representative Artist",
                direct_evidence_value=3,
                source_count=1,
                evidence_refs=("wd:artist",),
            ),
            MetadataCandidate(
                entity_kind="release_group",
                entity_id=f"musicbrainz:release-group:{ALBUM_ID}",
                genre_id="wikidata:genre:Q100",
                name="Defining Album",
                direct_evidence_value=2,
                source_count=1,
                evidence_refs=("wd:album",),
            ),
            MetadataCandidate(
                entity_kind="recording",
                entity_id=f"musicbrainz:recording:{TRACK_ID}",
                genre_id="wikidata:genre:Q100",
                name="Defining Track",
                direct_evidence_value=1,
                source_count=1,
                evidence_refs=("wd:track",),
            ),
        ),
    )
    return build_public_model(inputs, PublicModelSettings())


class PublicModelPublishTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.database_path = root / "catalog.sqlite"
        self.artifact_path = root / "public-model.json"
        Database(self.database_path).initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.executescript(FIXTURE.read_text(encoding="utf-8"))
            connection.execute(
                """INSERT INTO rights_policies
                   (id, policy_key, policy_version, classification, basis)
                   VALUES (3, 'public-test', 1, 'open_license', 'test')"""
            )
            connection.executemany(
                """INSERT INTO rights_policy_permissions
                   (policy_id, use_kind, decision, reason) VALUES (3, ?, 'allow', 'test')""",
                (("normalize",), ("display",), ("export",)),
            )
            connection.execute(
                """INSERT INTO rights_policy_seals (policy_id, sealed_at)
                   VALUES (3, '2026-08-31T00:00:00Z')"""
            )
            connection.execute(
                """INSERT INTO data_sources
                   (id, source_key, name, acquisition_kind, default_policy_id)
                   VALUES (3, 'wikidata-test', 'Wikidata test', 'public_api', 3)"""
            )
            connection.execute(
                """INSERT INTO source_snapshots
                   (id, source_id, snapshot_ref, snapshot_kind, manifest_sha256,
                    acquired_at, policy_id)
                   VALUES (2, 3, 'wikidata-test-snapshot', 'single_artifact', ?,
                           '2026-08-31T00:00:00Z', 3)""",
                ("b" * 64,),
            )
            connection.execute(
                """INSERT INTO source_artifacts
                   (id, snapshot_id, artifact_ref, logical_name, media_type, byte_size,
                    sha256, vault_key, policy_id)
                   VALUES (2, 2, 'wikidata-test', 'wikidata.json', 'application/json',
                           1, ?, ?, 3)""",
                ("a" * 64, "a" * 64),
            )
            connection.execute(
                """INSERT INTO provenance_records
                   (id, source_id, policy_id, snapshot_ref, artifact_sha256,
                    record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at)
                   VALUES (2, 3, 3, 'wikidata-test-snapshot', ?, ?,
                           'wikidata-test-v1', 'wikidata-test-attempt',
                           '2026-08-31T00:00:00Z')""",
                ("a" * 64, "c" * 64),
            )
            connection.execute(
                """INSERT INTO identifier_types (id, type_key, name)
                   VALUES (2, 'wikidata', 'Wikidata')"""
            )
            connection.executemany(
                """INSERT INTO entity_identifiers
                   (entity_id, identifier_type_id, namespace, value, normalized_value,
                    provenance_id) VALUES (?, 2, 'wikidata', ?, ?, 1)""",
                ((1, "Q100", "Q100"), (15, "Q200", "Q200")),
            )
        self.artifact = _artifact()
        self.artifact_path.write_text(self.artifact.model_dump_json(), encoding="utf-8")

    @override
    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_publish_is_atomic_idempotent_and_queryable(self) -> None:
        self.assertEqual(GenreEntryRepository(self.database_path)._read(1)[2], ())  # noqa: SLF001
        first = publish_public_model(
            self.database_path,
            self.artifact_path,
            policy_id=3,
        )
        sentinel = "2000-01-01T00:00:00.000Z"
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE current_public_models SET selected_at = ? WHERE model_key = 'public-graph'",
                (sentinel,),
            )
            connection.execute(
                "UPDATE current_layouts SET selected_at = ? WHERE layout_key = 'public'",
                (sentinel,),
            )
        second = publish_public_model(
            self.database_path,
            self.artifact_path,
            policy_id=3,
        )

        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.coordinate_genres, 2)
        self.assertEqual(first.representative_items, 3)
        with sqlite3.connect(self.database_path) as connection:
            selections = connection.execute(
                """SELECT selected_at FROM current_public_models WHERE model_key = 'public-graph'
                   UNION ALL
                   SELECT selected_at FROM current_layouts WHERE layout_key = 'public'"""
            ).fetchall()
            map_name = connection.execute(
                """SELECT name FROM displayable_map_points
                   WHERE layout_key = 'public' AND entity_id = 1"""
            ).fetchone()
        self.assertEqual(selections, [(sentinel,), (sentinel,)])
        self.assertEqual(map_name, ("Public IDM",))
        layouts = {item.layout_key for item in Database(self.database_path).published_layouts()}
        self.assertIn("public", layouts)
        self.assertIn("genres", layouts)

        detail = Database(self.database_path).genre_detail(1)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.name, "Public IDM")
        enriched = GenreEntryRepository(self.database_path)._read(detail.entity_id)  # noqa: SLF001
        self.assertEqual(enriched[1][0].name, "Representative Artist")
        self.assertEqual(enriched[2][0].name, "Defining Album")
        self.assertEqual(enriched[3][0].name, "Defining Track")
        self.assertEqual(
            enriched[2][0].href,
            f"https://musicbrainz.org/release-group/{ALBUM_ID}",
        )

    def test_active_input_and_output_suppressions_retract_public_rows(self) -> None:
        publish_public_model(self.database_path, self.artifact_path, policy_id=3)
        with sqlite3.connect(self.database_path) as connection:
            derived_output_id = int(
                connection.execute("SELECT derived_output_id FROM public_model_runs").fetchone()[0]
            )
            targets = (
                ("source", "3"),
                ("snapshot", "2"),
                ("provenance", "2"),
                ("artifact", "2"),
                ("derived_output", str(derived_output_id)),
            )
            for index, (target_kind, target_ref) in enumerate(targets, start=1):
                connection.execute(
                    """INSERT INTO suppression_events
                       (target_kind, target_ref, use_kind, event_action, reason,
                        effective_at, event_fingerprint)
                       VALUES (?, ?, 'display', 'suppress', 'test', ?, ?)""",
                    (
                        target_kind,
                        target_ref,
                        f"2026-08-31T00:00:{index:02d}Z",
                        f"d{index:063x}",
                    ),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM displayable_public_genre_representatives"
                    ).fetchone(),
                    (0,),
                )
                connection.commit()
                self.assertIsNone(Database(self.database_path).genre_detail(1))
                if target_kind == "source":
                    with TestClient(create_app(self.database_path)) as client:
                        self.assertEqual(client.get("/api/genres/1").status_code, 404)
                        self.assertEqual(
                            client.get(
                                "/fragments/genres/1", params={"layout": "public"}
                            ).status_code,
                            404,
                        )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM displayable_map_points WHERE layout_key = 'public'"
                    ).fetchone(),
                    (0,),
                )
                connection.execute(
                    """INSERT INTO suppression_events
                       (target_kind, target_ref, use_kind, event_action, reason,
                        effective_at, event_fingerprint)
                       VALUES (?, ?, 'display', 'release', 'test', ?, ?)""",
                    (
                        target_kind,
                        target_ref,
                        f"2026-08-31T00:01:{index:02d}Z",
                        f"e{index:063x}",
                    ),
                )
                self.assertGreater(
                    int(
                        connection.execute(
                            """SELECT count(*) FROM displayable_map_points
                               WHERE layout_key = 'public'"""
                        ).fetchone()[0]
                    ),
                    0,
                )
                connection.commit()
                self.assertIsNotNone(Database(self.database_path).genre_detail(1))

    def test_invalidated_derived_output_retracts_public_rows_and_detail(self) -> None:
        publish_public_model(self.database_path, self.artifact_path, policy_id=3)
        with sqlite3.connect(self.database_path) as connection:
            derived_output_id = int(
                connection.execute("SELECT derived_output_id FROM public_model_runs").fetchone()[0]
            )
            connection.execute(
                """INSERT INTO derived_output_events
                   (derived_output_id, event_kind, event_at, reason)
                   VALUES (?, 'invalidated', '2099-08-31T01:00:00Z', 'test')""",
                (derived_output_id,),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM displayable_map_points WHERE layout_key = 'public'"
                ).fetchone(),
                (0,),
            )
            connection.commit()
        self.assertIsNone(Database(self.database_path).genre_detail(1))

    def test_rejects_an_input_with_a_false_declared_snapshot(self) -> None:
        source_artifact = self.artifact.artifacts[0].model_copy(update={"snapshot": "not-real"})
        changed = self.artifact.model_copy(update={"artifacts": (source_artifact,)})
        changed = changed.model_copy(update={"output_sha256": public_model_output_sha256(changed)})
        self.artifact_path.write_text(changed.model_dump_json(), encoding="utf-8")

        with self.assertRaisesRegex(PublicModelPublishError, "exact exportable provenance"):
            publish_public_model(self.database_path, self.artifact_path, policy_id=3)

        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM derived_outputs").fetchone(), (0,)
            )

    def test_rejects_a_changed_payload_without_writes(self) -> None:
        changed = self.artifact.model_copy(update={"output_sha256": "f" * 64})
        self.artifact_path.write_text(changed.model_dump_json(), encoding="utf-8")

        with self.assertRaisesRegex(PublicModelPublishError, "logical output hash"):
            publish_public_model(self.database_path, self.artifact_path, policy_id=3)

        with sqlite3.connect(self.database_path) as connection:
            count = connection.execute("SELECT count(*) FROM public_model_runs").fetchone()
        self.assertEqual(count, (0,))


if __name__ == "__main__":
    unittest.main()
