"""Behavioral tests for sparse cosine genre transfer."""

from __future__ import annotations

import unittest

from opennoise.ml.sparse_genre_cosine_transfer import _scores, _strengths


class SparseGenreCosineTransferTests(unittest.TestCase):
    def test_cosine_normalization_demotes_a_high_strength_candidate(self) -> None:
        relations = {
            "source": (("hub", 4.0), ("focused", 4.0)),
            "hub": (("source", 4.0), ("other-a", 96.0)),
            "focused": (("source", 4.0),),
            "other-a": (("hub", 96.0),),
        }
        train = {"genre": ("source",)}

        raw = _scores(seed_id="genre", train=train, relations=relations, strengths=None)
        cosine = _scores(
            seed_id="genre", train=train, relations=relations, strengths=_strengths(relations)
        )

        self.assertEqual(raw["hub"], raw["focused"])
        self.assertLess(cosine["hub"], cosine["focused"])

    def test_known_train_artists_are_never_returned(self) -> None:
        relations = {"one": (("two", 3.0),), "two": (("one", 3.0),)}

        scores = _scores(
            seed_id="genre",
            train={"genre": ("one", "two")},
            relations=relations,
            strengths=_strengths(relations),
        )

        self.assertEqual(scores, {})
