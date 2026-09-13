import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from opennoise.ml.layout_lenses import (
    build_weighted_community_spectral_coordinates,
    weighted_spectral_quality,
)
from opennoise.serving.local.research_peer_layout import (
    LocalResearchPeerLayoutSettings,
    build_local_research_peer_layout,
    local_research_peer_layout_output_sha256,
)
from scripts.local_peer_similarity import build_index


class LocalResearchPeerLayoutTests(unittest.TestCase):
    def test_community_layout_counts_filtered_edges_but_evaluates_all_source_edges(self) -> None:
        """Keep the coordinate graph and the fidelity reference graph distinct."""
        genres = ("a", "b", "c", "d", "e", "f")
        source_weights = {
            ("a", "b"): 1.0,
            ("a", "c"): 1.0,
            ("b", "c"): 1.0,
            ("d", "e"): 1.0,
            ("d", "f"): 1.0,
            ("e", "f"): 1.0,
            ("c", "d"): 0.000001,
        }
        community = build_weighted_community_spectral_coordinates(
            genres, source_weights, seed=20260831, maximum_iterations=100
        )
        quality = weighted_spectral_quality(
            community.coordinates,
            source_weights,
            neighbors_per_genre=2,
            layout_weights=community.layout_weights,
        )

        self.assertTrue(community.converged)
        self.assertLess(community.layout_edge_count, len(source_weights))
        self.assertEqual(quality.layout_graph_edges, community.layout_edge_count)
        self.assertEqual(quality.input_graph_edges, len(source_weights))

    def test_consumes_the_compact_index_builder_output(self) -> None:
        """Exercise the receipt-bound stream contract rather than a hand-made index."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "peer.json"
            gate_path = root / "peer.gate.json"
            receipt_path = root / "peer.receipt.json"
            reconciliation_path = root / "reconciliation.json"
            index_path = root / "peer.sqlite"
            artifact_path.write_text(
                """{"candidates":[{"source_genre_id":"item1","target_genre_id":"item2","score":0.8,"direct_score":0.8,"aggregate_score":0.0,"shared_direct_artist_count":2,"aggregate_listener_day_support":0,"aggregate_supporting_windows":0,"sufficiency":"direct_only","evidence_refs":["ref:1"],"components":[{"component_kind":"direct_artist_overlap","normalized_value":0.8,"configured_weight":0.7}]}]}""",
                encoding="utf-8",
            )
            gate_path.write_text(
                """{"passed":true,"all_inputs_export_allowed":false,"artifact_output_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","candidate_pair_count":1,"revision":"genre-peer-similarity-gate-v4"}""",
                encoding="utf-8",
            )
            receipt_path.write_text(
                """{"candidate_output_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","historical_inputs_used_for_construction":false}""",
                encoding="utf-8",
            )
            reconciliation_path.write_text(
                """{"dispositions":[{"source_item_id":"item1","source_external_id":"legacy:item1","seed_name":"one","disposition":"accepted"},{"source_item_id":"item2","source_external_id":"legacy:item2","seed_name":"two","disposition":"accepted"},{"source_item_id":"item3","source_external_id":"legacy:item3","seed_name":"three","disposition":"unresolved"}]}""",
                encoding="utf-8",
            )
            build_index(
                artifact=artifact_path,
                gate=gate_path,
                historical_receipt=receipt_path,
                reconciliation=reconciliation_path,
                output=index_path,
            )
            result = build_local_research_peer_layout(
                index_path,
                settings=LocalResearchPeerLayoutSettings(
                    expected_seed_count=3, neighbors_per_genre=1
                ),
            )

        self.assertEqual({item.genre_id for item in result.coordinates}, {"item1", "item2"})
        self.assertEqual([item.source_item_id for item in result.unplaced], ["item3"])
        self.assertEqual(result.coverage.retained_peer_edge_count, 1)

    def test_projects_only_evidence_connected_seeds_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peer.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE seed (
                        source_item_id TEXT PRIMARY KEY,
                        source_external_id TEXT,
                        seed_name TEXT NOT NULL,
                        disposition TEXT NOT NULL
                    );
                    CREATE TABLE peer_edge (
                        source_genre_id TEXT NOT NULL,
                        target_genre_id TEXT NOT NULL,
                        score REAL NOT NULL,
                        direct_score REAL NOT NULL,
                        aggregate_score REAL NOT NULL,
                        shared_direct_artist_count INTEGER NOT NULL,
                        aggregate_listener_day_support INTEGER NOT NULL,
                        aggregate_supporting_windows INTEGER NOT NULL,
                        sufficiency TEXT NOT NULL,
                        evidence_refs_json TEXT NOT NULL,
                        components_json TEXT NOT NULL,
                        PRIMARY KEY (source_genre_id, target_genre_id)
                    );
                    """
                )
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?)",
                    (
                        ("non_production_candidate", "true"),
                        ("all_inputs_export_allowed", "false"),
                        ("artifact_output_sha256", "a" * 64),
                    ),
                )
                connection.executemany(
                    "INSERT INTO seed VALUES (?, ?, ?, ?)",
                    (
                        ("peer:one", None, "one", "accepted"),
                        ("peer:two", None, "two", "accepted"),
                        ("peer:three", None, "three", "accepted"),
                        ("peer:four", None, "four", "unresolved"),
                    ),
                )
                connection.executemany(
                    "INSERT INTO peer_edge VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ("peer:one", "peer:two", 0.8, 0.8, 0.0, 3, 0, 0, "direct", "[]", "[]"),
                        ("peer:three", "peer:two", 0.4, 0.4, 0.0, 2, 0, 0, "direct", "[]", "[]"),
                    ),
                )
                connection.commit()
            settings = LocalResearchPeerLayoutSettings(expected_seed_count=4, neighbors_per_genre=2)
            first = build_local_research_peer_layout(path, settings=settings)
            second = build_local_research_peer_layout(path, settings=settings)

        self.assertEqual(first, second)
        self.assertEqual(first.output_sha256, local_research_peer_layout_output_sha256(first))
        self.assertFalse(first.export_allowed)
        self.assertEqual(
            {item.genre_id for item in first.coordinates}, {"peer:one", "peer:two", "peer:three"}
        )
        self.assertEqual([item.source_item_id for item in first.unplaced], ["peer:four"])
        self.assertEqual(first.coverage.retained_seed_count, 4)
        self.assertEqual(first.coverage.coordinate_count, 3)
        self.assertEqual(first.coverage.unplaced_seed_count, 1)
        self.assertEqual(first.coverage.retained_peer_edge_count, 2)
        self.assertEqual(first.settings.layout_method, "community_packed_spectral")
        self.assertGreaterEqual(first.coverage.community_count, 1)
        self.assertTrue(first.coverage.community_converged)
        self.assertGreaterEqual(first.quality.mean_knn_preservation, 0.0)

    def test_rejects_edges_outside_the_retained_seed_universe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peer.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE seed (source_item_id TEXT PRIMARY KEY);
                    CREATE TABLE peer_edge (
                        source_genre_id TEXT, target_genre_id TEXT, score REAL
                    );
                    """
                )
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?)",
                    (
                        ("non_production_candidate", "true"),
                        ("all_inputs_export_allowed", "false"),
                        ("artifact_output_sha256", "b" * 64),
                    ),
                )
                connection.executemany(
                    "INSERT INTO seed VALUES (?)", (("peer:one",), ("peer:two",))
                )
                connection.execute(
                    "INSERT INTO peer_edge VALUES (?, ?, ?)",
                    ("peer:one", "peer:other", 0.2),
                )
                connection.commit()
            artifact = build_local_research_peer_layout(
                path, settings=LocalResearchPeerLayoutSettings(expected_seed_count=2)
            )
        self.assertEqual(artifact.coverage.unmapped_peer_edge_count, 1)
        self.assertEqual(artifact.coverage.coordinate_count, 0)


if __name__ == "__main__":
    unittest.main()
