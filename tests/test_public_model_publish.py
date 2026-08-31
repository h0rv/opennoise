import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import override

from musix.db import Database
from musix.genre_entry import GenreEntryRepository
from musix.ml.public_graph import build_public_model
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
                snapshot="test",
                artifact_key="test.json",
                content_sha256="a" * 64,
                export_allowed=True,
            ),
        ),
        genres=(
            GenreIdentity(genre_id="wikidata:genre:Q100", name="IDM", evidence_refs=("wd:1",)),
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
                (("display",), ("export",)),
            )
            connection.execute(
                """INSERT INTO rights_policy_seals (policy_id, sealed_at)
                   VALUES (3, '2026-08-31T00:00:00Z')"""
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
        first = publish_public_model(
            self.database_path,
            self.artifact_path,
            policy_id=3,
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
        layouts = {item.layout_key for item in Database(self.database_path).published_layouts()}
        self.assertIn("public", layouts)
        self.assertIn("genres", layouts)

        detail = Database(self.database_path).genre_detail(1)
        self.assertIsNotNone(detail)
        assert detail is not None
        enriched = GenreEntryRepository(self.database_path)._read(detail.entity_id)  # noqa: SLF001
        self.assertEqual(enriched[1][0].name, "Representative Artist")
        self.assertEqual(enriched[2][0].name, "Defining Album")
        self.assertEqual(enriched[3][0].name, "Defining Track")
        self.assertEqual(
            enriched[2][0].href,
            f"https://musicbrainz.org/release-group/{ALBUM_ID}",
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
