from __future__ import annotations

import unittest

from opennoise.analysis.acoustic_representation import (
    RecordingDescriptors,
    aggregate_recordings,
    cultural_neighbors,
    fit_scales,
    sonic_neighbors,
)


class AcousticRepresentationTests(unittest.TestCase):
    def test_missingness_and_deduplication(self) -> None:
        row = RecordingDescriptors("a", "r1", {"bpm": 100.0, "flux": None})
        artists = aggregate_recordings([row, row], ["bpm", "flux"])
        self.assertEqual(artists[0].recording_count, 1)
        self.assertEqual(artists[0].observed_counts, {"bpm": 1, "flux": 0})
        self.assertIsNone(artists[0].values["flux"])
        with self.assertRaises(ValueError):
            aggregate_recordings([row, RecordingDescriptors("a", "r1", {"bpm": 101.0})], ["bpm"])

    def test_nonfinite_and_boolean_rejected(self) -> None:
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                aggregate_recordings([RecordingDescriptors("a", "r", {"bpm": value})], ["bpm"])

    def test_training_scales_hold_out_query_and_skip_constants(self) -> None:
        rows = aggregate_recordings(
            [
                RecordingDescriptors(str(i), str(i), {"bpm": value, "constant": 1.0})
                for i, value in enumerate((10.0, 20.0, 1000.0))
            ],
            ["bpm", "constant"],
        )
        scales = fit_scales(rows[:2], ["bpm", "constant"])
        self.assertEqual(scales, {"bpm": 5.0})
        neighbors = sonic_neighbors(rows[2], rows[:2], scales, minimum_shared=1)
        self.assertEqual(neighbors[0]["artist_id"], "1")
        self.assertEqual(neighbors[0]["shared_feature_count"], 1)
        self.assertEqual(sonic_neighbors(rows[2], rows[:2], scales), [])

    def test_cultural_overlap_is_independent(self) -> None:
        memberships = {"a": frozenset({"x", "y"}), "b": frozenset({"x"}), "c": frozenset({"z"})}
        rows = cultural_neighbors("a", memberships)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["similarity"], 0.5)
        self.assertEqual(cultural_neighbors("missing", memberships), [])


if __name__ == "__main__":
    unittest.main()
