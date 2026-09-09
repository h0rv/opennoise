from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.peers.peer_similarity_h3_bridge import _historical_jaccard_neighbors, _load_positives


class BridgePeerNeighborhoodTests(unittest.TestCase):
    def test_sparse_binary_jaccard_uses_stable_ties(self) -> None:
        positives = {
            "item1": {"artist-a", "artist-b"},
            "item2": {"artist-a", "artist-c"},
            "item3": {"artist-b", "artist-c"},
            "item4": {"artist-z"},
        }

        neighborhoods = _historical_jaccard_neighbors(positives, k=2)

        self.assertEqual(neighborhoods["item1"], ("item2", "item3"))
        self.assertEqual(neighborhoods["item2"], ("item1", "item3"))
        self.assertEqual(neighborhoods["item3"], ("item1", "item2"))
        self.assertNotIn("item4", neighborhoods)

    def test_positive_loader_partitions_and_deduplicates_exact_bridge_ids(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "h3.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                    CREATE TABLE historical_genre_artist_observations (
                      genre_id INTEGER NOT NULL, source_artist_id TEXT,
                      observation_role TEXT NOT NULL
                    );
                    INSERT INTO genres VALUES (1, 'IDM'), (2, 'unknown genre');
                    INSERT INTO historical_genre_artist_observations VALUES
                      (1, 'spotify-a', 'genre_page_member'),
                      (1, 'spotify-a', 'genre_page_member'),
                      (1, 'spotify-conflict', 'genre_page_member'),
                      (1, 'spotify-missing', 'genre_page_member'),
                      (2, 'spotify-a', 'genre_page_member'),
                      (1, NULL, 'genre_page_member'),
                      (1, 'spotify-a', 'other');
                    """
                )
            positives, counters = _load_positives(
                database,
                seed_by_name={"idm": "item887"},
                spotify_to_mbid={"spotify-a": "mbid-a"},
                conflicted=frozenset({"spotify-conflict"}),
                maximum_observations=10,
            )

        self.assertEqual(positives, {"item887": {"mbid-a"}})
        self.assertEqual(counters["h3_observation_count"], 5)
        self.assertEqual(counters["h3_mapped_positive_count"], 2)
        self.assertEqual(counters["h3_conflicted_artist_observation_count"], 1)
        self.assertEqual(counters["h3_unbridged_artist_observation_count"], 1)
        self.assertEqual(counters["h3_unmapped_genre_observation_count"], 1)
