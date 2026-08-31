import sqlite3
import unittest

from musix.ml.repository import PublicInputLoadSettings, PublicModelRepository

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
          (7, 20, 'musicbrainz', '66666666-6666-4666-8666-666666666666');
        INSERT INTO entity_names VALUES
          (1, 10, 'Allowed Artist', 1),
          (2, 11, 'Denied Artist', 1),
          (3, 30, 'Q300', 1),
          (4, 20, 'Q100', 1),
          (5, 12, 'Suppressed Artist', 1),
          (6, 40, 'Q400', 1),
          (7, 30, 'Q300 Deluxe', 1);
        INSERT INTO genres VALUES (20, 'Q100');
        INSERT INTO normalizable_artist_genre_evidence VALUES
          (1, 10, 20, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q10-P136-Q100', 'wikidata_p136', 1, 1),
          (2, 11, 20, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q11-P136-Q100', 'wikidata_p136', 2, 1),
          (3, 12, 20, 'direct_source_claim', 1.0, 'wikidata_music_slice',
           'Q12-P136-Q100', 'wikidata_p136', 1, 1);
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
        self.assertFalse(
            any(item.name in {"Q300", "Q400"} for item in result.metadata_candidates)
        )
        self.assertIn("Q300 Deluxe", {item.name for item in result.metadata_candidates})
        self.assertEqual(result.hierarchy, ())
        self.assertEqual(
            {item.entity_kind for item in result.metadata_candidates},
            {"artist", "release_group"},
        )


if __name__ == "__main__":
    unittest.main()
