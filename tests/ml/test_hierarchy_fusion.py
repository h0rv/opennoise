from __future__ import annotations

import unittest

from opennoise.ml.hierarchy_fusion.contracts import (
    EdgeProvenance,
    HierarchyFusionSettings,
    SourceBinding,
)
from opennoise.ml.hierarchy_fusion.inputs import LoadedHierarchyFusionInputs
from opennoise.ml.hierarchy_fusion.pipeline import (
    _calibrate,
    _project_edges,
    _Proposal,
    _seed_states,
    _split_factual,
)


def _review(score: float, *, artists: int = 10) -> EdgeProvenance:
    return EdgeProvenance(
        source_role="full_graph_containment",
        source_ref=f"fixture:{score}:{artists}",
        score=score,
        lexical_score=0.0,
        artist_containment_score=score,
        shared_artist_count=artists,
        child_artist_count=artists,
        parent_artist_count=artists * 2,
    )


class HierarchyFusionTests(unittest.TestCase):
    def test_calibration_does_not_select_using_holdout_facts(self) -> None:
        settings = HierarchyFusionSettings(
            factual_split_seed=9,
            factual_calibration_fraction=0.4,
            factual_holdout_fraction=0.4,
            review_score_thresholds=(0.25, 0.8),
            calibration_recovery_tolerance=0.0,
        )
        factual: dict[tuple[str, str], tuple[EdgeProvenance, ...]] = {
            (f"seed-{index}", f"parent-{index}"): (_review(1.0),) for index in range(200)
        }
        calibration = [edge for edge in factual if _split_factual(edge, settings) == "calibration"]
        holdout = [edge for edge in factual if _split_factual(edge, settings) == "holdout"]
        self.assertTrue(calibration)
        self.assertTrue(holdout)
        proposals = {
            edge: _Proposal(review=[_review(0.3 if edge in calibration else 1.0)])
            for edge in factual
        }
        evaluation = _calibrate(factual, proposals, settings)
        self.assertEqual(evaluation.selected_threshold, 0.25)
        self.assertEqual(evaluation.holdout_recovered_edge_count, len(holdout))

    def test_factual_cycle_is_preserved_as_source_evidence_but_excluded_from_dag(self) -> None:
        settings = HierarchyFusionSettings(review_score_thresholds=(0.8,))
        factual = _review(1.0)
        proposals = {
            ("child", "parent"): _Proposal(factual=[factual]),
            ("parent", "child"): _Proposal(factual=[factual]),
        }
        edges, parents, factual_counts, review_counts, rejected_counts = _project_edges(
            proposals, settings, 0.8
        )
        self.assertEqual(len(parents["child"]), 1)
        self.assertEqual(sum(edge.factual_source for edge in edges), 2)
        self.assertEqual(sum(edge.included_in_dag for edge in edges), 1)
        self.assertEqual(sum(edge.disposition == "cycle_rejected" for edge in edges), 1)
        binding = SourceBinding(
            role="fixture",
            locator="fixture:artifact.json",
            sha256="a" * 64,
            byte_count=1,
        )
        loaded = LoadedHierarchyFusionInputs(
            seed_names={"child": "Child", "parent": "Parent"},
            factual={},
            public_candidate_corpus={},
            full_graph={},
            unknown_reasons={},
            bindings=(binding, binding, binding, binding, binding, binding, binding, binding),
        )
        states = _seed_states(loaded, factual_counts, review_counts, rejected_counts)
        self.assertEqual({state.state for state in states}, {"observed"})

    def test_small_support_cannot_become_perfect_review_evidence(self) -> None:
        settings = HierarchyFusionSettings(
            minimum_shared_artist_count=5,
            minimum_child_artist_count=5,
            review_score_thresholds=(0.8,),
        )
        proposals = {("child", "parent"): _Proposal(review=[_review(1.0, artists=3)])}
        edges, *_ = _project_edges(proposals, settings, 0.8)
        self.assertEqual(edges[0].disposition, "abstained")


if __name__ == "__main__":
    unittest.main()
