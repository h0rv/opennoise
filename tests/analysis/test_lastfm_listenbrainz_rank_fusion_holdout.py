"""Behavior checks for the fixed local source-rank fusion ablation."""

from __future__ import annotations

import unittest

from opennoise.analysis.lastfm_listenbrainz_rank_fusion_holdout import (
    LastFmListenBrainzRankFusionHoldout,
    RankFusionMetric,
    _finalize,
    _fused_ranks,
    _recalled,
    _union_recalled,
)


class LastFmListenBrainzRankFusionHoldoutTests(unittest.TestCase):
    """Keep the fusion rule fixed and its union comparator distinct from final ranking."""

    def test_reciprocal_rank_fusion_uses_only_pre_capped_source_ranks(self) -> None:
        fused = _fused_ranks(
            {"lastfm-first": 1, "shared": 20},
            {"shared": 1, "listenbrainz-second": 2},
        )

        self.assertEqual(fused["shared"], 1)
        self.assertEqual(fused["lastfm-first"], 2)
        self.assertEqual(fused["listenbrainz-second"], 3)

    def test_union_upper_bound_does_not_rerank_or_merge_source_candidates(self) -> None:
        targets: dict[str, tuple[str, ...]] = {"seed": ("lastfm", "listenbrainz", "missing")}
        lastfm = {"seed": {"lastfm": 20}}
        listenbrainz = {"seed": {"listenbrainz": 20}}
        fused = {"seed": {"lastfm": 1, "listenbrainz": 2}}

        self.assertEqual(_union_recalled(targets, lastfm, listenbrainz), 2)
        self.assertEqual(_recalled(targets, fused), 2)

    def test_finalization_hashes_then_validates_the_receipt(self) -> None:
        metric = RankFusionMetric(recalled_target_count=0, recall=0.0)
        placeholder = LastFmListenBrainzRankFusionHoldout.model_construct(
            direct_receipt_sha256="0" * 64,
            direct_database_sha256="1" * 64,
            lastfm_artifact_sha256="2" * 64,
            lastfm_companion_receipt_sha256="3" * 64,
            lastfm_database_sha256="4" * 64,
            listenbrainz_receipt_sha256="5" * 64,
            listenbrainz_database_sha256="6" * 64,
            common_endpoint_target_count=0,
            lastfm_top_twenty=metric,
            listenbrainz_top_twenty=metric,
            reciprocal_rank_fusion_top_twenty=metric,
            candidate_union_upper_bound_at_forty=metric,
            output_sha256="0" * 64,
        )

        report = _finalize(placeholder)

        self.assertNotEqual(report.output_sha256, "0" * 64)


if __name__ == "__main__":
    unittest.main()
