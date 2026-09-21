import sqlite3
import unittest

from opennoise.ml.public_graph import _sha256 as public_input_sha256
from opennoise.ml.repository import (
    PublicInputLoadError,
    PublicInputLoadSettings,
    PublicModelRepository,
)

_WD_SHA = "a" * 64
_LB_SHA = "b" * 64
_ARTIST_A = "musicbrainz:artist:11111111-1111-4111-8111-111111111111"
_ARTIST_B = "musicbrainz:artist:22222222-2222-4222-8222-222222222222"


def _catalog() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE active_rights_policy_permissions (
          policy_id INTEGER, use_kind TEXT, decision TEXT
        );
        CREATE TABLE active_suppressions (
          target_kind TEXT, target_ref TEXT, use_kind TEXT
        );
        CREATE TABLE normalizable_artist_genre_evidence (
          id INTEGER, artist_id INTEGER, genre_id INTEGER, evidence_kind TEXT,
          evidence_value REAL, source_key TEXT, source_record_id TEXT,
          method_key TEXT, policy_id INTEGER, provenance_id INTEGER
        );
        CREATE TABLE modelable_music_genres (genre_id INTEGER PRIMARY KEY);
        CREATE TABLE normalizable_album_genre_memberships (
          id INTEGER, release_group_id INTEGER, genre_id INTEGER,
          evidence_kind TEXT, source_count INTEGER, source_family TEXT,
          policy_id INTEGER, provenance_id INTEGER
        );
        CREATE TABLE normalizable_recording_genre_memberships (
          id INTEGER, recording_id INTEGER, genre_id INTEGER,
          evidence_kind TEXT, source_family TEXT, source_count INTEGER,
          policy_id INTEGER, provenance_id INTEGER
        );
        CREATE TABLE entity_identifiers (
          id INTEGER, entity_id INTEGER, namespace TEXT, normalized_value TEXT
        );
        CREATE TABLE entity_names (
          id INTEGER, entity_id INTEGER, name TEXT, is_preferred INTEGER
        );
        CREATE TABLE genres (id INTEGER, name TEXT);
        CREATE TABLE genre_hierarchy (
          relation_id INTEGER, child_genre_id INTEGER,
          parent_genre_id INTEGER, provenance_id INTEGER
        );
        CREATE TABLE provenance_records (
          id INTEGER, source_id INTEGER, policy_id INTEGER,
          snapshot_ref TEXT, artifact_sha256 TEXT
        );
        CREATE TABLE data_sources (id INTEGER, source_key TEXT);

        INSERT INTO active_rights_policy_permissions VALUES
          (1, 'embed', 'allow'), (1, 'export', 'allow'),
          (2, 'embed', 'deny'), (2, 'export', 'deny');
        INSERT INTO data_sources VALUES (1, 'wikidata_music_slice');
        INSERT INTO provenance_records VALUES (
          1, 1, 1, 'wd-1',
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' || 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        );
        INSERT INTO entity_identifiers VALUES
          (1, 10, 'musicbrainz', '11111111-1111-4111-8111-111111111111'),
          (2, 11, 'musicbrainz', '22222222-2222-4222-8222-222222222222'),
          (3, 20, 'wikidata', 'Q100'),
          (4, 30, 'musicbrainz', '33333333-3333-4333-8333-333333333333'),
          (5, 12, 'musicbrainz', '44444444-4444-4444-8444-444444444444'),
          (6, 40, 'musicbrainz', '55555555-5555-4555-8555-555555555555'),
          (7, 20, 'musicbrainz', '66666666-6666-4666-8666-666666666666'),
          (8, 21, 'wikidata', 'Q999');
        INSERT INTO entity_names VALUES
          (1, 10, 'Allowed Artist', 1),
          (2, 11, 'Denied Artist', 1),
          (3, 30, 'Q300', 1),
          (4, 20, 'Q100', 1),
          (5, 12, 'Suppressed Artist', 1),
          (6, 40, 'Q400', 1),
          (7, 30, 'Q300 Deluxe', 1);
        INSERT INTO genres VALUES (20, 'Q100'), (21, 'Non-music Genre');
        INSERT INTO modelable_music_genres VALUES (20);
        INSERT INTO normalizable_artist_genre_evidence VALUES
          (1, 10, 20, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q10-P136-Q100', 'wikidata_p136', 1, 1),
          (2, 11, 20, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q11-P136-Q100', 'wikidata_p136', 2, 1),
          (3, 12, 20, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q12-P136-Q100', 'wikidata_p136', 1, 1),
          (4, 10, 21, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q10-P136-Q999', 'wikidata_p136', 1, 1);
        INSERT INTO normalizable_album_genre_memberships VALUES
          (1, 30, 20, 'wikidata_p136', NULL, 'wikidata', 1, 1);
        INSERT INTO normalizable_recording_genre_memberships VALUES
          (1, 40, 20, 'wikidata_p136', 'wikidata', 7, 1, 1);
        INSERT INTO active_suppressions VALUES ('entity', '12', 'embed');
        """
    )
    return connection


def _listenbrainz() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE active_rights_policy_permissions (
          policy_id INTEGER, use_kind TEXT, decision TEXT
        );
        CREATE TABLE active_suppressions (
          target_kind TEXT, target_ref TEXT, use_kind TEXT
        );
        CREATE TABLE normalizable_artist_co_listen_evidence (
          ingest_attempt_id INTEGER, left_artist_source_id TEXT,
          right_artist_source_id TEXT, distinct_user_count INTEGER,
          staged_record_id INTEGER
        );
        CREATE TABLE artist_co_listen_runs (ingest_attempt_id INTEGER, artifact_id INTEGER);
        CREATE TABLE source_artifacts (id INTEGER, policy_id INTEGER);
        CREATE TABLE provenance_records (
          id INTEGER, source_id INTEGER, policy_id INTEGER,
          snapshot_ref TEXT, artifact_sha256 TEXT
        );
        CREATE TABLE data_sources (id INTEGER, source_key TEXT);
        CREATE TABLE normalization_exports (staged_record_id INTEGER, provenance_id INTEGER);
        CREATE TABLE entity_identifiers (
          entity_id INTEGER, namespace TEXT, normalized_value TEXT
        );

        INSERT INTO active_rights_policy_permissions VALUES
          (1, 'embed', 'allow'), (1, 'export', 'allow');
        INSERT INTO data_sources VALUES (1, 'listenbrainz_incremental');
        INSERT INTO provenance_records VALUES (
          1, 1, 1, 'lb-1',
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' || 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        );
        INSERT INTO source_artifacts VALUES (1, 1);
        INSERT INTO artist_co_listen_runs VALUES (7, 1);
        INSERT INTO normalizable_artist_co_listen_evidence VALUES
          (7, 'musicbrainz:artist:11111111-1111-4111-8111-111111111111',
           'musicbrainz:artist:22222222-2222-4222-8222-222222222222', 4, 100);
        INSERT INTO normalization_exports VALUES (100, 1);
        """
    )
    return connection


def _listenbrainz_v2(
    *, joint_attempt_id: int, insert_dummy_first: bool = False
) -> sqlite3.Connection:
    """Make one joint artifact with deliberately variable SQLite surrogate IDs."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE active_rights_policy_permissions (
          policy_id INTEGER, use_kind TEXT, decision TEXT
        );
        CREATE TABLE active_suppressions (target_kind TEXT, target_ref TEXT, use_kind TEXT);
        CREATE TABLE normalizable_artist_co_listen_evidence (
          ingest_attempt_id INTEGER, left_artist_source_id TEXT,
          right_artist_source_id TEXT, distinct_user_count INTEGER, staged_record_id INTEGER
        );
        CREATE TABLE artist_co_listen_runs (ingest_attempt_id INTEGER, artifact_id INTEGER);
        CREATE TABLE source_artifacts (
          id INTEGER, snapshot_id INTEGER, policy_id INTEGER, sha256 TEXT
        );
        CREATE TABLE source_snapshots (id INTEGER, source_id INTEGER, snapshot_ref TEXT);
        CREATE TABLE provenance_records (
          id INTEGER, source_id INTEGER, policy_id INTEGER, snapshot_ref TEXT, artifact_sha256 TEXT
        );
        CREATE TABLE data_sources (id INTEGER, source_key TEXT);
        CREATE TABLE normalization_exports (staged_record_id INTEGER, provenance_id INTEGER);
        CREATE TABLE entity_identifiers (entity_id INTEGER, namespace TEXT, normalized_value TEXT);
        INSERT INTO active_rights_policy_permissions VALUES
          (1, 'embed', 'allow'), (1, 'export', 'allow');
        """
    )
    if insert_dummy_first:
        connection.execute("INSERT INTO data_sources VALUES (1, 'unrelated_source')")
    source_id = 2 if insert_dummy_first else 1
    artifact_id = 9 if insert_dummy_first else 1
    snapshot = f"listenbrainz_joint_20260824_20260830:joint:{_LB_SHA}"
    connection.executemany(
        "INSERT INTO data_sources VALUES (?, ?)",
        ((source_id, "listenbrainz_joint_20260824_20260830"),),
    )
    connection.executemany(
        "INSERT INTO source_snapshots VALUES (?, ?, ?)", ((artifact_id, source_id, snapshot),)
    )
    connection.executemany(
        "INSERT INTO source_artifacts VALUES (?, ?, ?, ?)",
        ((artifact_id, artifact_id, 1, _LB_SHA),),
    )
    connection.executemany(
        "INSERT INTO provenance_records VALUES (?, ?, ?, ?, ?)",
        ((1, source_id, 1, snapshot, _LB_SHA),),
    )
    connection.executemany(
        "INSERT INTO artist_co_listen_runs VALUES (?, ?)", ((joint_attempt_id, artifact_id),)
    )
    connection.executemany(
        "INSERT INTO normalizable_artist_co_listen_evidence VALUES (?, ?, ?, ?, ?)",
        ((joint_attempt_id, _ARTIST_A, _ARTIST_B, 4, 100),),
    )
    connection.execute("INSERT INTO normalization_exports VALUES (100, 1)")
    return connection


def _listenbrainz_v2_multi_artifact() -> sqlite3.Connection:
    connection = _listenbrainz_v2(joint_attempt_id=7)
    alpha_sha = "c" * 64
    connection.executemany("INSERT INTO data_sources VALUES (?, ?)", ((2, "listenbrainz_alpha"),))
    connection.executemany(
        "INSERT INTO source_snapshots VALUES (?, ?, ?)", ((2, 2, "alpha snapshot/one"),)
    )
    connection.executemany(
        "INSERT INTO source_artifacts VALUES (?, ?, ?, ?)", ((2, 2, 1, alpha_sha),)
    )
    connection.executemany(
        "INSERT INTO provenance_records VALUES (?, ?, ?, ?, ?)",
        ((2, 2, 1, "alpha snapshot/one", alpha_sha),),
    )
    connection.executemany("INSERT INTO artist_co_listen_runs VALUES (?, ?)", ((11, 2),))
    connection.executemany(
        "INSERT INTO normalizable_artist_co_listen_evidence VALUES (?, ?, ?, ?, ?)",
        ((11, _ARTIST_A, _ARTIST_B, 5, 101),),
    )
    connection.execute("INSERT INTO normalization_exports VALUES (101, 2)")
    return connection


def _listenbrainz_v2_over_ref_limit() -> sqlite3.Connection:
    connection = _listenbrainz_v2(joint_attempt_id=1)
    for index in range(2, 368):
        source_key = f"listenbrainz_extra_{index:03}"
        snapshot_ref = f"extra-snapshot-{index:03}"
        artifact_sha = f"{index:064x}"
        connection.execute("INSERT INTO data_sources VALUES (?, ?)", (index, source_key))
        connection.execute(
            "INSERT INTO source_snapshots VALUES (?, ?, ?)", (index, index, snapshot_ref)
        )
        connection.execute(
            "INSERT INTO source_artifacts VALUES (?, ?, ?, ?)", (index, index, 1, artifact_sha)
        )
        connection.execute(
            "INSERT INTO provenance_records VALUES (?, ?, ?, ?, ?)",
            (index, index, 1, snapshot_ref, artifact_sha),
        )
        connection.execute("INSERT INTO artist_co_listen_runs VALUES (?, ?)", (index, index))
        connection.execute(
            "INSERT INTO normalizable_artist_co_listen_evidence VALUES (?, ?, ?, ?, ?)",
            (index, _ARTIST_A, _ARTIST_B, 4, 100 + index),
        )
        connection.execute("INSERT INTO normalization_exports VALUES (?, ?)", (100 + index, index))
    return connection


class PublicModelRepositoryTests(unittest.TestCase):
    def test_loads_only_embed_allowed_public_evidence(self) -> None:
        catalog = _catalog()
        listenbrainz = _listenbrainz()
        self.addCleanup(catalog.close)
        self.addCleanup(listenbrainz.close)
        repository = PublicModelRepository(catalog, listenbrainz)

        result = repository.load(PublicInputLoadSettings())

        self.assertEqual(len(result.artifacts), 2)
        self.assertTrue(all(artifact.export_allowed for artifact in result.artifacts))
        self.assertEqual(len(result.direct_memberships), 1)
        self.assertEqual(len(result.genres), 1)
        self.assertEqual(result.genres[0].name, "Q100")
        self.assertEqual(result.direct_memberships[0].artist_id, _ARTIST_A)
        self.assertEqual(result.direct_memberships[0].genre_id, "wikidata:genre:Q100")
        self.assertEqual(len(result.artist_pairs), 1)
        self.assertEqual(result.artist_pairs[0].right_artist_id, _ARTIST_B)
        self.assertEqual(len(result.metadata_candidates), 2)
        self.assertFalse(any(item.name in {"Q300", "Q400"} for item in result.metadata_candidates))
        self.assertIn("Q300 Deluxe", {item.name for item in result.metadata_candidates})
        self.assertEqual(result.hierarchy, ())
        self.assertEqual(
            {item.entity_kind for item in result.metadata_candidates},
            {"artist", "release_group"},
        )

    def test_attempt_ids_v1_is_default_and_unchanged(self) -> None:
        catalog = _catalog()
        listenbrainz = _listenbrainz()
        self.addCleanup(catalog.close)
        self.addCleanup(listenbrainz.close)
        repository = PublicModelRepository(catalog, listenbrainz)

        default = repository.load(PublicInputLoadSettings())
        explicit = repository.load(
            PublicInputLoadSettings(artist_pair_evidence_ref_version="attempt_ids_v1")
        )

        self.assertEqual(default, explicit)
        self.assertEqual(default.artist_pairs[0].evidence_refs, ("listenbrainz:attempts:7-7",))

    def test_source_artifacts_v2_binds_exact_joint_source_snapshot_and_hash(self) -> None:
        catalog = _catalog()
        listenbrainz = _listenbrainz_v2(joint_attempt_id=62, insert_dummy_first=True)
        self.addCleanup(catalog.close)
        self.addCleanup(listenbrainz.close)

        result = PublicModelRepository(catalog, listenbrainz).load(
            PublicInputLoadSettings(artist_pair_evidence_ref_version="source_artifacts_v2")
        )

        ref = result.artist_pairs[0].evidence_refs[0]
        self.assertIn("source_key=listenbrainz_joint_20260824_20260830", ref)
        self.assertIn("snapshot_ref=listenbrainz_joint_20260824_20260830%3Ajoint%3A", ref)
        self.assertIn(f"artifact_sha256={_LB_SHA}", ref)
        self.assertNotIn("attempt", ref)

    def test_source_artifacts_v2_input_hash_is_independent_of_insertion_order(self) -> None:
        catalog = _catalog()
        early_joint = _listenbrainz_v2(joint_attempt_id=8)
        late_joint = _listenbrainz_v2(joint_attempt_id=62, insert_dummy_first=True)
        self.addCleanup(catalog.close)
        self.addCleanup(early_joint.close)
        self.addCleanup(late_joint.close)
        settings_v1 = PublicInputLoadSettings(artist_pair_evidence_ref_version="attempt_ids_v1")
        settings_v2 = PublicInputLoadSettings(
            artist_pair_evidence_ref_version="source_artifacts_v2"
        )

        early_v1 = PublicModelRepository(catalog, early_joint).load(settings_v1)
        late_v1 = PublicModelRepository(catalog, late_joint).load(settings_v1)
        early_v2 = PublicModelRepository(catalog, early_joint).load(settings_v2)
        late_v2 = PublicModelRepository(catalog, late_joint).load(settings_v2)

        self.assertNotEqual(early_v1.model_dump(mode="json"), late_v1.model_dump(mode="json"))
        self.assertEqual(early_v2.model_dump(mode="json"), late_v2.model_dump(mode="json"))
        self.assertNotEqual(public_input_sha256(early_v1), public_input_sha256(late_v1))
        self.assertEqual(public_input_sha256(early_v2), public_input_sha256(late_v2))
        self.assertEqual(
            tuple(
                (
                    pair.left_artist_id,
                    pair.right_artist_id,
                    pair.listener_day_support,
                    pair.supporting_windows,
                )
                for pair in early_v1.artist_pairs
            ),
            tuple(
                (
                    pair.left_artist_id,
                    pair.right_artist_id,
                    pair.listener_day_support,
                    pair.supporting_windows,
                )
                for pair in late_v1.artist_pairs
            ),
        )
        self.assertEqual(
            tuple(
                (
                    pair.left_artist_id,
                    pair.right_artist_id,
                    pair.listener_day_support,
                    pair.supporting_windows,
                )
                for pair in early_v1.artist_pairs
            ),
            tuple(
                (
                    pair.left_artist_id,
                    pair.right_artist_id,
                    pair.listener_day_support,
                    pair.supporting_windows,
                )
                for pair in early_v2.artist_pairs
            ),
        )

    def test_source_artifacts_v2_deduplicates_and_sorts_multiple_artifacts(self) -> None:
        catalog = _catalog()
        listenbrainz = _listenbrainz_v2_multi_artifact()
        self.addCleanup(catalog.close)
        self.addCleanup(listenbrainz.close)

        pair = (
            PublicModelRepository(catalog, listenbrainz)
            .load(PublicInputLoadSettings(artist_pair_evidence_ref_version="source_artifacts_v2"))
            .artist_pairs[0]
        )

        self.assertEqual((pair.listener_day_support, pair.supporting_windows), (9, 2))
        self.assertEqual(len(pair.evidence_refs), 2)
        self.assertEqual(tuple(sorted(pair.evidence_refs)), pair.evidence_refs)
        self.assertIn("source_key=listenbrainz_alpha", pair.evidence_refs[0])
        self.assertIn("snapshot_ref=alpha%20snapshot%2Fone", pair.evidence_refs[0])

    def test_source_artifacts_v2_rejects_more_than_366_refs_while_streaming(self) -> None:
        catalog = _catalog()
        listenbrainz = _listenbrainz_v2_over_ref_limit()
        self.addCleanup(catalog.close)
        self.addCleanup(listenbrainz.close)

        with self.assertRaisesRegex(PublicInputLoadError, "references exceed declared limit 366"):
            PublicModelRepository(catalog, listenbrainz).load(
                PublicInputLoadSettings(artist_pair_evidence_ref_version="source_artifacts_v2")
            )

    def test_source_artifacts_v2_retains_embed_rights_and_suppression_filters(self) -> None:
        catalog = _catalog()
        denied = _listenbrainz_v2(joint_attempt_id=7)
        suppressed = _listenbrainz_v2(joint_attempt_id=7)
        self.addCleanup(catalog.close)
        self.addCleanup(denied.close)
        self.addCleanup(suppressed.close)
        denied.execute(
            "DELETE FROM active_rights_policy_permissions "
            "WHERE policy_id = 1 AND use_kind = 'embed'"
        )
        suppressed.execute("INSERT INTO active_suppressions VALUES ('source', '1', 'embed')")
        settings = PublicInputLoadSettings(artist_pair_evidence_ref_version="source_artifacts_v2")

        self.assertEqual(PublicModelRepository(catalog, denied).load(settings).artist_pairs, ())
        self.assertEqual(PublicModelRepository(catalog, suppressed).load(settings).artist_pairs, ())


if __name__ == "__main__":
    unittest.main()
