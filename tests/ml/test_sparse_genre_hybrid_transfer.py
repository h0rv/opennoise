"""Behavioral tests for the fixed sparse genre rank fusion."""

from __future__ import annotations

import unittest

from opennoise.ml.sparse_genre_hybrid_transfer import _direct_scores, _fused_scores


class SparseGenreHybridTransferTests(unittest.TestCase):
    def test_fusion_uses_only_the_fixed_top_twenty_from_each_arm(self) -> None:
        direct = {f"direct-{index:02}": float(100 - index) for index in range(21)}
        cosine = {f"cosine-{index:02}": float(100 - index) for index in range(21)}

        fused = _fused_scores(direct, cosine)

        self.assertEqual(len(fused), 40)
        self.assertNotIn("direct-20", fused)
        self.assertNotIn("cosine-20", fused)
        self.assertGreater(fused["direct-00"], fused["direct-19"])

    def test_direct_peer_scores_exclude_known_train_artists(self) -> None:
        train = {"seed": ("known",), "peer": ("known", "candidate")}
        peer_rows = {"seed": (("peer", 2, 0.5),)}

        scores = _direct_scores(seed="seed", train=train, peer_rows=peer_rows)

        self.assertEqual(scores, {"candidate": 0.5})
