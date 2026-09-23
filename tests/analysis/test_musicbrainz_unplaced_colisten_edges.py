"""Tests for the bounded source-label and sealed pair review experiment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from opennoise.analysis.musicbrainz_unplaced_colisten_edges import (
    CoListenReviewProposal,
    CoListenReviewSettings,
    _cap_proposals,
    _qualifying_proposals,
    _read_literal_tag_labels,
)


class MusicBrainzUnplacedCoListenEdgesTests(unittest.TestCase):
    """Keep source labels, distinct pairs, and proposal caps separate."""

    def test_source_scan_keeps_nonliteral_scope_but_uses_literal_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.json"
            source_path.write_text(
                """{"evidence":[
                {"facet":"tag","artist_id":"artist-a","seed_source_item_id":"u","match_kind":"exact","target_name":"u","seed_name":"u"},
                {"facet":"tag","artist_id":"artist-b","seed_source_item_id":"v","match_kind":"normalized","target_name":"v","seed_name":"V"}
                ]}""",
                encoding="utf-8",
            )
            result = _read_literal_tag_labels(
                source_path,
                frozenset({"u", "v"}),
                frozenset({"u", "v"}),
                CoListenReviewSettings(),
            )
        self.assertEqual(result.literal_labels_by_artist, {"artist-a": frozenset({"u"})})
        self.assertEqual(result.retained_source_positive_unplaced_seed_ids, frozenset({"u", "v"}))

    def test_two_distinct_pairs_are_required_and_caps_are_deterministic(self) -> None:
        routes = {
            ("u", "p"): {("a", "b"): 5, ("c", "d"): 5},
            ("v", "p"): {("e", "f"): 8, ("g", "h"): 8},
            ("w", "q"): {("i", "j"): 5},
        }
        proposals = _qualifying_proposals(
            routes,
            dict.fromkeys("abcdefghij", 1),
            CoListenReviewSettings(),
        )
        self.assertEqual({proposal.unplaced_seed_id for proposal in proposals}, {"u", "v"})
        capped = _cap_proposals(
            proposals,
            CoListenReviewSettings().model_copy(
                update={
                    "maximum_proposals_per_placed_seed": 1,
                    "maximum_proposals_per_unplaced_seed": 1,
                }
            ),
        )
        self.assertEqual(len(capped), 1)
        self.assertEqual(capped[0].unplaced_seed_id, "v")

    def test_proposals_reject_one_pair_at_model_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than or equal to 2"):
            CoListenReviewProposal(
                unplaced_seed_id="u",
                placed_seed_id="p",
                distinct_exact_artist_pair_support_count=1,
                summed_pair_user_support=5,
                score=1.0,
            )
