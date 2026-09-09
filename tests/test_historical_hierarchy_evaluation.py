import unittest
from typing import Literal

from musix.history.historical_hierarchy_evaluation import evaluate_historical_hierarchy
from musix.models.historical_signal import (
    HistoricalSignalArtifact,
    HistoricalSignalHierarchyNode,
    HistoricalSignalNeighbor,
    HistoricalSignalNode,
    HistoricalSignalQuality,
)


class HistoricalHierarchyEvaluationTests(unittest.TestCase):
    def test_reports_closure_sizes_retention_components_and_lexical_samples(self) -> None:
        report = evaluate_historical_hierarchy(_artifact())

        self.assertTrue(report.coverage.parent_closure)
        self.assertTrue(report.coverage.child_closure)
        self.assertTrue(report.coverage.member_count_closure)
        self.assertTrue(report.coverage.node_path_closure)
        self.assertEqual(report.umbrella_size_distribution.group_count, 2)
        self.assertEqual(report.umbrella_size_distribution.minimum_member_count, 3)
        self.assertEqual(report.umbrella_size_distribution.maximum_member_count, 4)
        self.assertEqual(report.edge_retention[0].internal_union_edge_count, 5)
        self.assertEqual(report.edge_retention[1].internal_union_edge_count, 4)
        self.assertEqual(report.edge_retention[2].internal_union_edge_count, 3)
        self.assertEqual(
            report.edge_retention[0].modularity_weight, "max_directed_weighted_jaccard"
        )
        self.assertGreater(report.edge_retention[0].weighted_modularity, 0.0)
        self.assertEqual(report.components.graph_component_count, 4)
        self.assertEqual(report.components.levels[0].disconnected_group_count, 2)
        self.assertEqual(report.lexical_cohorts[0].matched_node_count, 2)
        self.assertFalse(report.lexical_cohorts[0].names_are_ground_truth)
        self.assertTrue(report.lexical_cohorts[0].evaluation_only)

    def test_compares_current_report_to_optional_baseline(self) -> None:
        current = _artifact("b" * 64)
        baseline = _artifact("a" * 64)

        comparison = evaluate_historical_hierarchy(current, baseline=baseline).baseline_comparison

        assert comparison is not None
        self.assertEqual(comparison.current_artifact_sha256, "b" * 64)
        self.assertEqual(comparison.baseline_artifact_sha256, "a" * 64)
        self.assertEqual(comparison.node_count_delta, 0)
        self.assertEqual(comparison.hierarchy_node_count_delta, 0)
        self.assertEqual(comparison.umbrella_count_delta, 0)
        self.assertEqual(comparison.lexical_cohort_match_count_delta[0][1], 0)


def _artifact(artifact_sha256: str = "a" * 64) -> HistoricalSignalArtifact:
    nodes = (
        _node("a", "Deep House", ("u0", "s0", "m0"), 0),
        _node("b", "Electronic", ("u0", "s0", "m0"), 0),
        _node("c", "Black Metal", ("u0", "s1", "m1"), 1),
        _node("d", "Death Metal", ("u0", "s1", "m1"), 1),
        _node("e", "Jazz", ("u1", "s2", "m2"), 2),
        _node("f", "Bebop", ("u1", "s2", "m2"), 2),
        _node("g", "Classical", ("u1", "s2", "m3"), 3),
    )
    hierarchy = (
        _hierarchy("u0", 0, None, ("s0", "s1"), 4),
        _hierarchy("u1", 0, None, ("s2",), 3),
        _hierarchy("s0", 1, "u0", ("m0",), 2),
        _hierarchy("s1", 1, "u0", ("m1",), 2),
        _hierarchy("s2", 1, "u1", ("m2", "m3"), 3),
        _hierarchy("m0", 2, "s0", (), 2),
        _hierarchy("m1", 2, "s1", (), 2),
        _hierarchy("m2", 2, "s2", (), 2),
        _hierarchy("m3", 2, "s2", (), 1),
    )
    neighbors = tuple(
        _neighbor(left, right)
        for left, right in (
            ("a", "b"),
            ("b", "a"),
            ("c", "d"),
            ("d", "c"),
            ("e", "f"),
            ("f", "e"),
            ("a", "c"),
            ("e", "g"),
        )
    )
    quality = HistoricalSignalQuality(
        node_count=len(nodes),
        member_genre_count=len(nodes),
        zero_membership_genre_count=0,
        similarity_edge_count=len(neighbors),
        community_count=2,
        connected_component_count=4,
        mean_neighbor_weight=0.5,
        hierarchy_umbrella_count=2,
        hierarchy_subcommunity_count=3,
        hierarchy_microgenre_count=4,
        hierarchy_node_coverage=1.0,
        hierarchy_microgenre_internal_edge_fraction=0.6,
        hierarchy_max_microgenre_member_count=2,
        artifact_sha256=artifact_sha256,
        exact_rerun=True,
    )
    return HistoricalSignalArtifact.model_construct(
        nodes=nodes, hierarchy=hierarchy, neighbors=neighbors, quality=quality
    )


def _node(
    genre_id: str, name: str, path: tuple[str, str, str], component: int
) -> HistoricalSignalNode:
    umbrella, subcommunity, microgenre = path
    return HistoricalSignalNode(
        genre_id=genre_id,
        name=name,
        x=0.5,
        y=0.5,
        community_id=umbrella,
        umbrella_id=umbrella,
        subcommunity_id=subcommunity,
        microgenre_id=microgenre,
        component_id=component,
        membership_count=1,
        lod_min=0,
        evidence_kind="h3_genre_to_artist",
    )


def _hierarchy(
    hierarchy_id: str,
    level: Literal[0, 1, 2],
    parent_id: str | None,
    children_ids: tuple[str, ...],
    member_count: int,
) -> HistoricalSignalHierarchyNode:
    return HistoricalSignalHierarchyNode(
        hierarchy_id=hierarchy_id,
        level=level,
        parent_id=parent_id,
        children_ids=children_ids,
        member_count=member_count,
        representative_genre_id="a",
        representative_label=hierarchy_id,
        x=0.5,
        y=0.5,
    )


def _neighbor(left: str, right: str) -> HistoricalSignalNeighbor:
    return HistoricalSignalNeighbor(
        genre_id=left,
        neighbor_genre_id=right,
        rank=1,
        weighted_jaccard=0.5,
        cosine=0.5,
        idf_overlap=1.0,
        shared_artist_count=1,
    )


if __name__ == "__main__":
    unittest.main()
