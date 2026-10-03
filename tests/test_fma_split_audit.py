from __future__ import annotations

import unittest

from opennoise.ml.fma_acoustic_baseline import NativeTrack
from opennoise.ml.fma_split_audit import audit_native_components


def track(identity: int, artist: int | None, album: int | None) -> NativeTrack:
    """Create an identity-only fixture with explicitly missing artist support."""
    return NativeTrack(identity, artist, artist is not None, album, (), targets_missing=False)


class NativeComponentAuditTests(unittest.TestCase):
    def test_missing_artist_album_duplicate_bridge_fails_in_both_orders(self) -> None:
        rows = [track(1, 30, 10), track(2, None, 10), track(3, 5, 11)]
        for ordered, duplicates in ((rows, [[2, 3]]), (list(reversed(rows)), [[3, 2]])):
            with (
                self.subTest(order=[row.track_id for row in ordered]),
                self.assertRaisesRegex(ValueError, "fresh split revision"),
            ):
                audit_native_components(ordered, duplicates, {5: 5, 30: 30})

    def test_overlapping_duplicate_groups_transmit_missing_artist_bridge(self) -> None:
        rows = [track(1, 30, 10), track(2, None, 10), track(3, None, None), track(4, 5, 11)]
        with self.assertRaisesRegex(ValueError, "fresh split revision"):
            audit_native_components(rows, [[2, 3], [3, 4]], {5: 5, 30: 30})
        audit_native_components(rows, [[2, 3], [3, 4]], {5: 5, 30: 5})

    def test_separate_missing_artists_do_not_create_shared_sentinel(self) -> None:
        rows = [track(1, 30, 10), track(2, None, 10), track(3, None, 11), track(4, 5, 11)]
        audit_native_components(rows, [], {5: 5, 30: 30})
        audit_native_components([track(1, None, 10), track(2, None, 10)], [[1, 2]], {})

    def test_normal_connected_fixture_keeps_historical_components(self) -> None:
        rows = [track(1, 30, 10), track(2, 20, 10), track(3, 20, 11), track(4, 40, 11)]
        components = {20: 20, 30: 20, 40: 20}
        audit_native_components(rows, [[1, 4]], components)
        self.assertEqual(components, {20: 20, 30: 20, 40: 20})

    def test_missing_artist_mapping_cannot_evade_audit(self) -> None:
        rows = [track(1, 30, 10), track(2, None, 10), track(3, 5, 11)]
        for components in ({30: 30}, {5: 5, 30: 30, 99: 99}):
            with self.assertRaisesRegex(ValueError, "every supplied artist"):
                audit_native_components(rows, [[2, 3]], components)

    def test_duplicate_track_rows_are_not_silently_overwritten(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct track IDs"):
            audit_native_components([track(1, 30, 10), track(1, 5, 11)], [], {5: 5, 30: 30})


if __name__ == "__main__":
    unittest.main()
