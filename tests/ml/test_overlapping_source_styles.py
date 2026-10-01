"""Check canonical isolation, rare support, source authority, and replay contracts."""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from opennoise.ml.artist_style_associations import StyleProfiles
from opennoise.ml.overlapping_source_styles import fit_overlapping_styles
from scripts.evaluate_overlapping_source_styles import outcomes, partition


def fixture() -> StyleProfiles:
    """Create two rare supports, one singleton, and observed/cold queries."""
    music = {
        "a": ("cue", "rare"),
        "b": ("cue", "rare"),
        "c": ("cue", "singleton"),
        "query": ("cue",),
        "cold": (),
    }
    return StyleProfiles(
        music,
        music,
        music,
        dict.fromkeys(music, ()),
        {artist: dict.fromkeys(values, 0.8) for artist, values in music.items()},
        "fixture",
    )


class OverlappingSourceStylesTests(unittest.TestCase):
    def test_rare_without_proper_anchor_and_singleton_abstention(self) -> None:
        profiles = fixture()
        model = fit_overlapping_styles(profiles, rarity_power=0.15)
        ranked = model.rank_batch(profiles, ("query", "cold", "a"))
        self.assertEqual(ranked["query"], ("rare",))
        self.assertEqual(ranked["cold"], ())
        self.assertNotIn("rare", ranked["a"])
        self.assertNotIn("cue", ranked["a"])

    def test_release_authority_cannot_duplicate_primary_weight(self) -> None:
        primary = fixture()
        auxiliary = fixture()
        auxiliary.authority["a"]["rare"] = 0.2
        high = fit_overlapping_styles(primary, rarity_power=0.15)
        low = fit_overlapping_styles(auxiliary, rarity_power=0.15)
        cue, rare = high.vocabulary.index("cue"), high.vocabulary.index("rare")
        self.assertGreater(high.associations[cue, rare], low.associations[cue, rare])
        self.assertTrue(np.isfinite(high.associations.data).all())

    def test_only_frozen_candidates_allowed(self) -> None:
        with self.assertRaisesRegex(ValueError, "preregistered"):
            fit_overlapping_styles(fixture(), rarity_power=0.9)

    def test_confirmation_targets_are_disjoint(self) -> None:
        rows = [
            {
                "artist_mbid": f"artist-{index}",
                "features": [
                    {
                        "namespace": "artist_tag",
                        "value": "ambient",
                        "evidence_refs": [f"tag/{index}"],
                    }
                ],
            }
            for index in range(100)
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            source.write_text("\n".join(map(json.dumps, rows)))
            _, exploratory, _, _ = partition(source)
            profiles, confirmation, _, _ = partition(source, confirmation=True)
        self.assertTrue(exploratory)
        self.assertTrue(confirmation)
        self.assertFalse(set(exploratory) & set(confirmation))
        self.assertTrue(all(value not in profiles.music[artist] for artist, value in confirmation))

    def test_unseen_targets_and_deterministic_outcome_replay(self) -> None:
        profiles = fixture()
        pairs = [("query", "rare"), ("cold", "unknown")]
        rankings = {"fixed": {"query": ("rare",), "cold": ()}}
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "left.gz", Path(directory) / "right.gz"
            metrics = outcomes(left, profiles, pairs, rankings, set(pairs), set())
            outcomes(right, profiles, pairs, rankings, set(pairs), set())
            self.assertEqual(left.read_bytes(), right.read_bytes())
            with gzip.open(left, "rt") as stream:
                rows = [json.loads(line) for line in stream]
        self.assertEqual(metrics["fixed"]["all"]["positives"], 2)
        self.assertEqual(metrics["fixed"]["all"]["recall_at_10"], 0.5)
        self.assertEqual(sum(bool(row["ranks"]["fixed"]) for row in rows), 1)

    def test_global_release_and_signature_facets_stay_together(self) -> None:
        release = "https://musicbrainz.org/release-group/00000000-0000-0000-0000-000000000000"
        features = [
            {"namespace": "artist_tag", "value": "rare style", "evidence_refs": ["tag/a"]},
            {"namespace": "artist_genre", "value": "rare-style", "evidence_refs": ["genre/a"]},
            {"namespace": "release_tag", "value": "rare style", "evidence_refs": [release]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            source.write_text(
                "\n".join(
                    json.dumps({"artist_mbid": artist, "features": features})
                    for artist in ("a", "b")
                )
            )
            profiles, pairs, _, _ = partition(source)
        held = set(pairs)
        self.assertEqual(("a", "rarestyle") in held, ("b", "rarestyle") in held)
        for artist in ("a", "b"):
            self.assertEqual(
                "rarestyle" in profiles.music[artist], (artist, "rarestyle") not in held
            )
            if profiles.music[artist]:
                self.assertEqual(profiles.authority[artist]["rarestyle"], 1.0)


if __name__ == "__main__":
    unittest.main()
