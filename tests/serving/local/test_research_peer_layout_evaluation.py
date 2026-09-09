import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from musix.serving.local.research_peer_layout import (
    LocalResearchPeerLayoutSettings,
    build_local_research_peer_layout,
)
from musix.serving.local.research_peer_layout_evaluation import (
    evaluate_local_research_peer_layout,
)


def _index(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE seed (source_item_id TEXT PRIMARY KEY, peer_genre_id TEXT);
            CREATE TABLE peer_edge (
                source_genre_id TEXT, target_genre_id TEXT, score REAL,
                direct_score REAL, aggregate_score REAL, sufficiency TEXT,
                component_kinds_json TEXT
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
            "INSERT INTO seed VALUES (?, ?)",
            (("peer:one", "peer:one"), ("peer:two", "peer:two"), ("peer:three", None)),
        )
        connection.execute(
            "INSERT INTO peer_edge VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "peer:one",
                "peer:two",
                0.8,
                0.8,
                0.0,
                "direct_only",
                '["direct_artist_overlap"]',
            ),
        )
        connection.commit()


class LocalResearchPeerLayoutEvaluationTests(unittest.TestCase):
    def test_replays_score_and_projected_supported_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "peer.sqlite"
            _index(path)
            artifact = build_local_research_peer_layout(
                path,
                settings=LocalResearchPeerLayoutSettings(
                    expected_seed_count=3, neighbors_per_genre=1
                ),
            )
            report = evaluate_local_research_peer_layout(path, artifact)

        self.assertFalse(report.component_score_replay_available)
        self.assertTrue(report.canonical_positive_edge_scores)
        self.assertTrue(report.direct_only_score_equals_direct_component)
        self.assertTrue(report.layout_replay_matches)
        self.assertEqual(report.evidence_connected_seed_count, 2)
        self.assertEqual(report.unplaced_seed_count, 1)
        self.assertEqual(report.edge_direction_policy, "canonical_undirected_candidate_pairs")


if __name__ == "__main__":
    unittest.main()
