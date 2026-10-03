"""Graph signal exclusions, cold denominators and supported layout reproducibility."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from opennoise.analysis.taxonomy_neighborhoods import (
    _adjacency,
    _canonical_axes,
    _neighbors,
    build_taxonomy_neighborhoods,
    edge_fold,
    evaluate_graph,
    graph_layout,
    selected_p279_edges,
)


class TaxonomyGraphTests(unittest.TestCase):
    def test_type_anchors_external_parents_and_self_edges_do_not_link_genres(self) -> None:
        projection = {
            "entities": [{"qid": "Q1"}, {"qid": "Q2"}],
            "claims": [
                {"genre_qid": "Q1", "property_id": "P31", "value_qid": "Q2"},
                {"genre_qid": "Q1", "property_id": "P279", "value_qid": "Q188451"},
                {"genre_qid": "Q1", "property_id": "P279", "value_qid": "Q1"},
            ],
        }
        self.assertEqual(selected_p279_edges(projection), ())
        projection["claims"].append({"genre_qid": "Q2", "property_id": "P279", "value_qid": "Q1"})
        self.assertEqual(selected_p279_edges(projection), (("Q1", "Q2"),))

    def test_disconnected_nodes_have_no_neighbors_or_positions(self) -> None:
        nodes = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6")
        adjacency = _adjacency(nodes, (("Q1", "Q2"), ("Q2", "Q3"), ("Q3", "Q4")))
        neighbors = _neighbors(nodes, adjacency)
        self.assertEqual(neighbors["Q5"], [])
        self.assertTrue(all(row["genre_id"] not in {"Q5", "Q6"} for row in neighbors["Q1"]))
        first = graph_layout(nodes, adjacency)
        self.assertEqual(first, graph_layout(nodes, adjacency))
        self.assertEqual(len(first["coordinates"]), 4)
        self.assertEqual({row["genre_id"] for row in first["abstentions"]}, {"Q5", "Q6"})
        self.assertFalse(first["across_component_semantics"])

    def test_holdout_retains_all_cold_nodes_and_zero_signal(self) -> None:
        nodes = ("Q1", "Q2", "Q3")
        edges = (("Q1", "Q2"),)
        result = evaluate_graph(nodes, edges)
        self.assertEqual(result["all_node_fold_denominator"], 15)
        self.assertEqual(result["micro_recall_at_10"], 0)
        fold = result["folds"][edge_fold(edges[0])]
        self.assertEqual(fold["directed_target_count"], 2)
        self.assertEqual(fold["cold_training_nodes"], 3)
        self.assertEqual(fold["nodes_without_heldout_targets"], 1)
        self.assertFalse(result["independent_musical_validity"])
        self.assertEqual(result["cold_query_directed_targets"], 2)
        self.assertEqual(result["disconnected_directed_targets"], 2)

    def test_pair_fold_is_orientation_invariant(self) -> None:
        self.assertEqual(edge_fold(("Q2", "Q1")), edge_fold(("Q1", "Q2")))

    def test_repeated_axes_are_basis_invariant_or_abstain(self) -> None:
        vectors = np.eye(4)
        rotated = vectors.copy()
        angle = 0.71
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        rotated[:, 1:3] = vectors[:, 1:3] @ rotation
        values = np.array([0.0, 1.0, 1.0, 2.0])
        np.testing.assert_allclose(
            _canonical_axes(vectors, values), _canonical_axes(rotated, values), atol=1e-12
        )
        nodes = ("Q1", "Q2", "Q3", "Q4", "Q5")
        layout = graph_layout(nodes, _adjacency(nodes, tuple(("Q1", node) for node in nodes[1:])))
        self.assertEqual(layout["coordinates"], [])
        self.assertTrue(
            all(
                row["reason"] == "spectral_boundary_not_identifiable"
                for row in layout["abstentions"]
            )
        )

    def test_protocol_edits_fail_before_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            protocol = Path(temporary) / "protocol.json"
            protocol.write_text(json.dumps({"seed": 20261002}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "protocol bytes differ"):
                build_taxonomy_neighborhoods(
                    {"seed": 20261002},
                    projection_path=protocol,
                    source_receipt_path=protocol,
                    protocol_path=protocol,
                )

    def test_common_path_recovers_triangle_edges_without_dropping_cold_node(self) -> None:
        nodes = ("Q1", "Q2", "Q3", "Q4")
        edges = (("Q1", "Q2"), ("Q1", "Q3"), ("Q2", "Q3"))
        self.assertEqual(len({edge_fold(edge) for edge in edges}), 3)
        result = evaluate_graph(nodes, edges)
        self.assertEqual(result["directed_target_count"], 6)
        self.assertEqual(sum(row["hits_at_10"] for row in result["folds"]), 6)
        self.assertEqual(result["all_node_fold_denominator"], 20)
        self.assertAlmostEqual(result["all_node_macro_recall_at_10"], 0.3)
        self.assertAlmostEqual(result["all_node_neighbor_jaccard"], 0.75)


if __name__ == "__main__":
    unittest.main()
