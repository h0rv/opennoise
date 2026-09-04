import unittest

from musix.historical_hierarchy_release_gate import (
    evaluate_historical_hierarchy_release_gate,
)
from musix.models.historical_signal import HistoricalSignalArtifact
from tests.test_historical_hierarchy_evaluation import _artifact


class HistoricalHierarchyReleaseGateTests(unittest.TestCase):
    def test_valid_paths_caps_and_family_spot_checks_pass(self) -> None:
        artifact = _family_artifact()

        report = evaluate_historical_hierarchy_release_gate(artifact)

        self.assertTrue(report.passed)
        self.assertTrue(report.every_genre_assigned_exactly_once)
        self.assertTrue(report.top_level_within_cap)
        self.assertTrue(report.subcommunities_within_cap)
        self.assertTrue(report.microgenres_within_cap)
        self.assertEqual(
            tuple(item.family for item in report.family_spot_checks),
            ("Electronic", "Latin", "Hip-hop", "Rock", "Metal", "Jazz", "Classical"),
        )
        self.assertEqual(report.family_spot_checks[0].matching_top_child_count, 2)

    def test_detects_parent_family_conflict_without_clustering(self) -> None:
        artifact = _family_artifact(child_label="Jazz")

        report = evaluate_historical_hierarchy_release_gate(artifact)

        self.assertFalse(report.passed)
        self.assertFalse(report.parent_lexical_conflicts_free)
        self.assertEqual(report.lexical_parent_conflicts[0].child_family, "Jazz")
        self.assertEqual(report.lexical_parent_conflicts[0].parent_family, "Electronic")

    def test_explicit_classical_head_precedes_regional_modifier(self) -> None:
        artifact = _artifact()
        hierarchy = tuple(
            item.model_copy(
                update={
                    "representative_label": (
                        "Classical"
                        if item.hierarchy_id == "u1"
                        else "latin american classical piano"
                        if item.hierarchy_id == "s2"
                        else item.representative_label
                    )
                }
            )
            for item in artifact.hierarchy
        )

        report = evaluate_historical_hierarchy_release_gate(
            artifact.model_copy(update={"hierarchy": hierarchy})
        )

        self.assertTrue(report.parent_lexical_conflicts_free)

    def test_detects_duplicate_assignments_and_large_top_without_two_children(self) -> None:
        artifact = _family_artifact()
        hierarchy = tuple(
            item.model_copy(update={"member_count": 150})
            if item.hierarchy_id in {"u1", "s2"}
            else item
            for item in artifact.hierarchy
        )
        invalid = artifact.model_copy(
            update={"nodes": (*artifact.nodes, artifact.nodes[0]), "hierarchy": hierarchy}
        )

        report = evaluate_historical_hierarchy_release_gate(invalid)

        self.assertFalse(report.every_genre_assigned_exactly_once)
        self.assertFalse(report.large_top_families_have_multiple_children)
        self.assertIn("u1", report.large_top_family_violations)


def _family_artifact(*, child_label: str = "House") -> HistoricalSignalArtifact:
    artifact = _artifact()
    labels = {
        "u0": "Electronic",
        "u1": "Latin",
        "s0": child_label,
        "s1": "Electro",
        "s2": "Samba",
    }
    hierarchy = tuple(
        item.model_copy(
            update={
                "representative_label": labels.get(item.hierarchy_id, item.representative_label)
            }
        )
        for item in artifact.hierarchy
    )
    return artifact.model_copy(update={"hierarchy": hierarchy})


if __name__ == "__main__":
    unittest.main()
