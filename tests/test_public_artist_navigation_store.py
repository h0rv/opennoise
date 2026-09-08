# ruff: noqa: E501  # Compact SQL fixture rows are more legible as records.

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from musix.public_artist_navigation_store import (
    PublicArtistNavigationStore,
    PublicArtistNavigationStoreError,
)
from tests._test_client import run_async


class PublicArtistNavigationStoreTests(unittest.TestCase):
    def test_direct_membership_traversal_is_bounded_and_never_infers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "navigation.sqlite"
            _fixture(path)
            store = PublicArtistNavigationStore(path)

            genre_members = run_async(store.genre_artists(10, offset=0, limit=1))
            artist_genres = run_async(store.artist_genres(1, offset=0, limit=20))
            related = run_async(store.related_artists(1, offset=0, limit=20))
            unsupported = run_async(store.genre_artists(30, offset=0, limit=20))
            open_genre = run_async(
                store.catalog_genre_id_for_open_node("catalog:wikidata:genre:Q10")
            )
            legacy_genre = run_async(store.catalog_genre_id_for_open_node("legacy:item1"))
            open_nodes = run_async(store.open_node_ids_for_catalog_genres((10, 20)))

        self.assertEqual(genre_members.genre.genre_id, "catalog:genre:10")
        self.assertEqual(len(genre_members.members), 1)
        self.assertNotIn(
            "catalog:artist:4", [item.artist.artist_id for item in genre_members.members]
        )
        self.assertEqual(genre_members.members[0].membership_kind, "direct_source_claim")
        self.assertEqual(genre_members.members[0].evidence[0].source_key, "fixture:direct")
        self.assertEqual(
            [item.genre.genre_id for item in artist_genres.genres],
            ["catalog:genre:10", "catalog:genre:20"],
        )
        self.assertEqual(related.method, "shared_direct_genre")
        self.assertEqual(related.related[0].artist.artist_id, "catalog:artist:2")
        self.assertEqual(related.related[0].shared_genre_count, 2)
        self.assertNotIn("catalog:artist:1", [item.artist.artist_id for item in related.related])
        self.assertEqual(unsupported.members, ())
        self.assertEqual(open_genre, 10)
        self.assertIsNone(legacy_genre)
        self.assertEqual(open_nodes, {10: "catalog:wikidata:genre:Q10"})

    def test_unknown_id_and_invalid_page_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "navigation.sqlite"
            _fixture(path)
            store = PublicArtistNavigationStore(path)

            with self.assertRaisesRegex(PublicArtistNavigationStoreError, "artist not found"):
                run_async(store.artist_genres(99, offset=0, limit=20))
            with self.assertRaisesRegex(PublicArtistNavigationStoreError, "pagination"):
                run_async(store.genre_artists(10, offset=-1, limit=20))
            with self.assertRaisesRegex(PublicArtistNavigationStoreError, "pagination"):
                run_async(store.genre_artists(10, offset=0, limit=51))


def _fixture(path: Path) -> None:
    # sqlite's transaction context manager commits but does not close.  Keep
    # this short-lived fixture explicit so focused validation is warning-free.
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE artists (id INTEGER PRIMARY KEY);
            CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE displayable_entity_names (
                id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, name TEXT NOT NULL,
                is_preferred INTEGER NOT NULL
            );
            CREATE TABLE displayable_artist_genre_evidence (
                id INTEGER PRIMARY KEY, artist_id INTEGER NOT NULL, genre_id INTEGER NOT NULL,
                source_key TEXT NOT NULL, source_record_id TEXT NOT NULL, method_key TEXT NOT NULL,
                method_version TEXT NOT NULL, provenance_id INTEGER NOT NULL,
                evidence_kind TEXT NOT NULL
            );
            CREATE TABLE artist_genre_evidence (
                id INTEGER PRIMARY KEY, artist_id INTEGER NOT NULL, genre_id INTEGER NOT NULL,
                evidence_kind TEXT NOT NULL
            );
            CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT NOT NULL);
            CREATE TABLE entity_identifiers (
                id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, identifier_type_id INTEGER NOT NULL,
                normalized_value TEXT NOT NULL
            );
            INSERT INTO artists VALUES (1), (2), (3), (4);
            INSERT INTO genres VALUES (10, 'Rock'), (20, 'Jazz'), (30, 'Unsupported');
            INSERT INTO displayable_entity_names VALUES
                (1, 1, 'Alpha', 1), (2, 2, 'Beta', 1), (3, 3, 'Gamma', 1), (4, 4, 'Orphan', 1);
            INSERT INTO displayable_artist_genre_evidence VALUES
                (1, 1, 10, 'fixture:direct', 'alpha-rock', 'fixture_direct', '1', 1, 'direct_source_claim'),
                (2, 1, 20, 'fixture:direct', 'alpha-jazz', 'fixture_direct', '1', 1, 'direct_source_claim'),
                (3, 2, 10, 'fixture:direct', 'beta-rock', 'fixture_direct', '1', 2, 'direct_source_claim'),
                (4, 2, 20, 'fixture:direct', 'beta-jazz', 'fixture_direct', '1', 2, 'direct_source_claim'),
                (5, 3, 10, 'fixture:direct', 'gamma-rock', 'fixture_direct', '1', 3, 'direct_source_claim'),
                (6, 4, 10, 'fixture:propagated', 'orphan-rock', 'propagated', '1', 4, 'release_group_propagation');
            INSERT INTO artist_genre_evidence VALUES (99, 4, 10, 'review_anchor');
            INSERT INTO identifier_types VALUES (1, 'wikidata_genre_qid');
            INSERT INTO entity_identifiers VALUES (1, 10, 1, 'Q10');
            """
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
