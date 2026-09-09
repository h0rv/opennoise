from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.peers.local_release_group_neighbor_comparison import (
    _frozen_metadata,
    _frozen_neighbors,
    _memberships,
    _neighbors,
    _shared,
)


class LocalReleaseGroupNeighborComparisonTests(unittest.TestCase):
    def test_frozen_control_uses_direct_score_and_requires_local_only_metadata(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "peer.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    """CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                       CREATE TABLE peer_edge (
                           source_genre_id TEXT, target_genre_id TEXT, score REAL,
                           direct_score REAL, aggregate_score REAL,
                           shared_direct_artist_count INTEGER);"""
                )
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?)",
                    [
                        ("non_production_candidate", "true"),
                        ("all_inputs_export_allowed", "false"),
                        ("artifact_output_sha256", "a" * 64),
                    ],
                )
                connection.execute(
                    "INSERT INTO peer_edge VALUES ('q', 'candidate', 0.9, 0.25, 0.65, 3)"
                )
            with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
                self.assertEqual(_frozen_metadata(connection), "a" * 64)
                self.assertEqual(
                    _frozen_neighbors(connection, "q", limit=10),
                    [
                        {
                            "seed_id": "candidate",
                            "direct_score": 0.25,
                            "shared_direct_artist_count": 3,
                        }
                    ],
                )

    def test_support_collapses_facets_and_reports_distinct_group_diagnostic(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "evidence.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    """CREATE TABLE direct_anchor (
                           genre_id TEXT, artist_id TEXT, facet TEXT, evidence_ref TEXT);
                       CREATE TABLE release_group_support (
                           genre_id TEXT, artist_id TEXT, facet TEXT,
                           release_group_id TEXT, evidence_ref TEXT);"""
                )
                connection.executemany(
                    "INSERT INTO direct_anchor VALUES (?, ?, 'genre', 'direct')",
                    [("q", "a"), ("q", "b"), ("direct", "a")],
                )
                connection.executemany(
                    "INSERT INTO release_group_support VALUES (?, ?, ?, ?, 'support')",
                    [
                        ("q", "a", "genre", "rg1"),
                        ("q", "a", "tag", "rg1"),
                        ("q", "a", "genre", "rg2"),
                        ("q", "b", "genre", "rg3"),
                        ("support", "a", "genre", "rg4"),
                        ("support", "a", "tag", "rg4"),
                        ("support", "b", "genre", "rg4"),
                    ],
                )
            with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
                direct_counts, direct_artists, direct_counts_by_artist = _memberships(
                    connection, "direct_anchor", frozenset({"q"})
                )
                direct_shared, _ = _shared(
                    connection, "direct_anchor", direct_artists, direct_counts_by_artist
                )
                support_counts, support_artists, support_counts_by_artist = _memberships(
                    connection, "release_group_support", frozenset({"q"})
                )
                support_shared, support_groups = _shared(
                    connection, "release_group_support", support_artists, support_counts_by_artist
                )

        self.assertEqual(direct_counts, {"direct": 1, "q": 2})
        self.assertEqual(support_counts, {"q": 2, "support": 2})
        self.assertEqual(support_counts_by_artist[("q", "a")], 2)
        self.assertEqual(support_counts_by_artist[("q", "b")], 1)
        self.assertEqual(
            _neighbors("q", direct_counts, direct_shared, {}, limit=10),
            [
                {
                    "seed_id": "direct",
                    "score": 0.5,
                    "shared_artist_count": 1,
                    "shared_artist_release_group_minimum_sum": 0,
                }
            ],
        )
        self.assertEqual(
            _neighbors("q", support_counts, support_shared, support_groups, limit=10),
            [
                {
                    "seed_id": "support",
                    "score": 1.0,
                    "shared_artist_count": 2,
                    # `rg4` supports both candidate artists. The diagnostic is a
                    # sum of per-artist minima, not a pair-level distinct-group count.
                    "shared_artist_release_group_minimum_sum": 2,
                }
            ],
        )
