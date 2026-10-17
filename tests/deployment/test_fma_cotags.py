"""Complete direct co-tag evidence and bounded pair cohorts."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opennoise.common import sha256_file
from opennoise.deployment.fma_cotags import export_cotags
from opennoise.deployment.fma_static import _cohort, _write


def track(track_id: int, artist: int | None, tags: list[int] | None) -> dict[str, Any]:
    """Create a minimal native-ID fixture, independent of artist names."""
    return {"track_id": track_id, "artist_id": artist, "genre_ids": tags}


class FMACotagTests(unittest.TestCase):
    def test_complete_graph_exact_support_and_missing_identity(self) -> None:
        tracks = [
            track(4, None, [1, 2]),
            track(1, 10, [1, 2, 2, 3]),
            track(2, 10, [1, 2]),
            track(3, 99, [2, 3]),
            track(5, 11, [1, 3]),
            track(6, 11, None),
            track(7, 11, []),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            files: dict[str, Any] = {}
            result = export_cotags(output, tracks, {10, 11}, {1, 2, 3, 4}, files, _write, _cohort)
            self.assertEqual(result["pair_count"], 3)
            self.assertEqual(result["directed_connections"], 6)
            connections = json.loads((output / "connections/1.json").read_bytes())["connections"]
            self.assertEqual(
                connections,
                [
                    {
                        "genre_id": 2,
                        "shared_tracks": 3,
                        "known_artist_count": 1,
                        "unresolved_artist_tracks": 1,
                    },
                    {
                        "genre_id": 3,
                        "shared_tracks": 2,
                        "known_artist_count": 2,
                        "unresolved_artist_tracks": 0,
                    },
                ],
            )
            self.assertEqual(
                json.loads((output / "connections/4.json").read_bytes())["connections"], []
            )
            for left, right in [(1, 2), (1, 3), (2, 3)]:
                expected = sorted(
                    row["track_id"]
                    for row in tracks
                    if {left, right} <= set(row["genre_ids"] or [])
                )
                page = json.loads((output / f"cohorts/pair-{left}-{right}/0.json").read_bytes())
                self.assertEqual(page["track_ids"], expected)
            for path, binding in files.items():
                self.assertEqual(sha256_file(output / path), (binding["sha256"], binding["bytes"]))
                self.assertLessEqual(binding["bytes"], 200_000)

    def test_pagination_and_all_connections_not_top_six(self) -> None:
        tracks = [track(i, 1, list(range(1, 10))) for i in range(201, 0, -1)]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = export_cotags(output, tracks, {1}, set(range(1, 10)), {}, _write, _cohort)
            self.assertEqual(result["pair_count"], 36)
            self.assertEqual(
                len(json.loads((output / "connections/1.json").read_bytes())["connections"]), 8
            )
            first = json.loads((output / "cohorts/pair-1-2/0.json").read_bytes())
            second = json.loads((output / "cohorts/pair-1-2/1.json").read_bytes())
            self.assertEqual(first["track_ids"], list(range(1, 201)))
            self.assertEqual(
                second, {"cohort": "pair-1-2", "page": 1, "total": 201, "track_ids": [201]}
            )

    def test_duplicate_or_unknown_ids_fail(self) -> None:
        for tracks in [
            [track(1, 1, [1, 2]), track(1, 2, [1, 2])],
            [track(1, 1, [1, 9])],
            [track(track_id=True, artist=1, tags=[1, 2])],
        ]:
            with (
                self.subTest(tracks=tracks),
                tempfile.TemporaryDirectory() as directory,
                self.assertRaises(ValueError),
            ):
                export_cotags(Path(directory), tracks, {1}, {1, 2}, {}, _write, _cohort)
