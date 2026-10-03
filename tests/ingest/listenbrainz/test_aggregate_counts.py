import unittest
from pathlib import Path

from opennoise.ingest.listenbrainz.aggregate_counts import (
    _native_roster,
    build_projection,
)

ROOT = Path(__file__).resolve().parents[3]
FACTS = ROOT / "data/examples/recording-facts/recording-facts.json"
TIED_HIGHEST_INDEX = 2
SUPPRESSED_INDEX = 1


class AggregateCountPackTest(unittest.TestCase):
    def test_frozen_native_roster_verifies_from_raw_credited_facts(self) -> None:
        roster = _native_roster(FACTS)
        self.assertEqual(len(roster), 36)
        self.assertTrue(all(row["recording_mbid"] for row in roster))

    def test_rank_and_display_gate_are_local_to_available_roster(self) -> None:
        roster = _native_roster(FACTS)
        rows = [
            {
                "recording_mbid": item["recording_mbid"],
                "total_listen_count": 100 if index == TIED_HIGHEST_INDEX else index + 10,
                "total_user_count": (
                    5 if index == TIED_HIGHEST_INDEX else (4 if index == SUPPRESSED_INDEX else 1)
                ),
            }
            for index, item in enumerate(roster)
        ]
        projected = build_projection(rows, roster)
        by_id = {row["recording_mbid"]: row for row in projected["rows"]}
        self.assertFalse(by_id[roster[1]["recording_mbid"]]["public_display_eligible"])
        self.assertIsNone(by_id[roster[1]["recording_mbid"]]["bounded_example_rank"])
        self.assertEqual(by_id[roster[2]["recording_mbid"]]["bounded_example_rank"], 1)
        self.assertEqual(len(projected["rows"]), 36)

    def test_strict_replay_rejects_null_mismatch_duplicate_and_bad_count(self) -> None:
        roster = _native_roster(FACTS)
        original = [
            {
                "recording_mbid": item["recording_mbid"],
                "total_listen_count": 10,
                "total_user_count": 5,
            }
            for item in roster
        ]
        bad = [dict(row) for row in original]
        bad[0]["total_user_count"] = None
        with self.assertRaises(ValueError):
            build_projection(bad, roster)
        bad = [dict(row) for row in original]
        bad[0]["total_listen_count"] = True
        with self.assertRaises(ValueError):
            build_projection(bad, roster)
        bad = [dict(row) for row in original]
        bad[1]["recording_mbid"] = bad[0]["recording_mbid"]
        with self.assertRaises(ValueError):
            build_projection(bad, roster)


if __name__ == "__main__":
    unittest.main()
