from __future__ import annotations

import unittest

from opennoise.analysis.connected_split import (
    TrackIdentity,
    audit_split,
    build_split,
    connected_components,
)


class ConnectedSplitTests(unittest.TestCase):
    def test_compilation_and_transitive_duplicate_leakage(self) -> None:
        records = (
            TrackIdentity(track_id="fma:1", artist_ids=("fma:a",), album_ids=("fma:x",)),
            TrackIdentity(track_id="fma:2", artist_ids=("fma:b",), album_ids=("fma:x",)),
            TrackIdentity(track_id="fma:3", artist_ids=("fma:b",), duplicate_ids=("fp:z",)),
            TrackIdentity(track_id="fma:4", artist_ids=("fma:c",), duplicate_ids=("fp:z",)),
            TrackIdentity(track_id="fma:5", artist_ids=("fma:d",)),
        )
        self.assertEqual(
            connected_components(records), (("fma:1", "fma:2", "fma:3", "fma:4"), ("fma:5",))
        )
        report = build_split(records, seed="sealed-before-fitting")
        self.assertEqual(report["largest_component_tracks"], 4)
        assignments = {row.track_id: "train" for row in records}
        assignments["fma:2"] = "test"
        audit = audit_split(records, assignments)
        self.assertFalse(audit["known_identity_isolation_passed"])
        self.assertEqual(
            audit["cross_partition_identities"],
            {
                "artist_ids": ["fma:b"],
                "album_ids": ["fma:x"],
                "recording_ids": [],
                "duplicate_ids": [],
            },
        )

    def test_multiple_credits_and_canonical_recordings(self) -> None:
        records = (
            TrackIdentity(track_id="fma:1", artist_ids=("mb:a", "mb:b")),
            TrackIdentity(track_id="fma:2", artist_ids=("mb:b",), recording_ids=("mb:r",)),
            TrackIdentity(track_id="other:3", recording_ids=("mb:r",)),
        )
        self.assertEqual(connected_components(records), (("fma:1", "fma:2", "other:3"),))

    def test_unknown_ids_are_not_shared_sentinels_and_namespaces_are_separate(self) -> None:
        records = (
            TrackIdentity(track_id="fma:1"),
            TrackIdentity(track_id="fma:2"),
            TrackIdentity(track_id="fma:3", artist_ids=("fma:a",)),
            TrackIdentity(track_id="fma:4", artist_ids=("other:a",)),
            TrackIdentity(track_id="fma:5", album_ids=("fma:a",)),
        )
        self.assertEqual(len(connected_components(records)), 5)
        audit = audit_split(records, dict.fromkeys((r.track_id for r in records), "train"))
        self.assertEqual(
            audit["tracks_missing_identity_kind"],
            {
                "artist_ids": 3,
                "album_ids": 4,
                "recording_ids": 5,
                "duplicate_ids": 5,
            },
        )
        self.assertFalse(audit["unknown_identity_leakage_excluded"])
        self.assertFalse(audit["all_partitions_nonempty"])

    def test_order_invariance_and_source_binding(self) -> None:
        records = tuple(
            TrackIdentity(track_id=f"fma:{i}", artist_ids=(f"artist:{i}",)) for i in range(100)
        )
        report = build_split(records, seed="frozen")
        self.assertEqual(report, build_split(tuple(reversed(records)), seed="frozen"))
        self.assertNotEqual(
            report["assignments"], build_split(records, seed="different")["assignments"]
        )
        changed = (*records[:-1], TrackIdentity(track_id="fma:99", artist_ids=("artist:new",)))
        self.assertNotEqual(
            report["normalized_records_sha256"],
            build_split(changed, seed="frozen")["normalized_records_sha256"],
        )

    def test_rejects_ambiguous_or_incomplete_inputs(self) -> None:
        row = TrackIdentity(track_id="fma:1")
        with self.assertRaises(ValueError):
            connected_components((row, row))
        with self.assertRaises(ValueError):
            connected_components(())
        with self.assertRaises(ValueError):
            TrackIdentity(track_id="unscoped")
        with self.assertRaises(ValueError):
            TrackIdentity(track_id="fma:1", album_ids=("",))
        for assignments in ({}, {"fma:1": "train", "fma:2": "test"}, {"fma:1": "other"}):
            with self.assertRaises(ValueError):
                audit_split((row,), assignments)
        with self.assertRaises(ValueError):
            build_split((row,), seed="")
        with self.assertRaises(ValueError):
            build_split((row,), seed="seed", buckets=(8, 0, 2))


if __name__ == "__main__":
    unittest.main()
