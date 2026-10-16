"""Recording evidence, component isolation and immutable discovery custody."""

# ruff: noqa: PLR2004, FBT003 -- explicit synthetic fixture values.

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.ml import fma_recording_profiles as profiles


def fixture() -> tuple[dict[str, Any], list[dict[str, Any]], np.ndarray, dict[str, Any]]:
    """Give ten different artists one component, plus a two-recording artist."""
    tracks = [
        {"track_id": i + 1, "artist_id": i + 100, "genre_ids": [1, 2] if i == 0 else [2]}
        for i in range(12)
    ]
    tracks.append({"track_id": 13, "artist_id": 111, "genre_ids": [3]})
    roster = [
        {"track_id": row["track_id"], "component_id": 1 if i < 10 else i + 1, "fold": 0}
        for i, row in enumerate(tracks)
    ]
    roster[-1]["component_id"] = roster[-2]["component_id"]
    values = np.zeros((13, 52))
    values[:, :2] = [[1, (i + 1) / 10] for i in range(13)]
    model = {
        "center": np.zeros(52),
        "scale": np.ones(52),
        "active": np.ones(52, dtype=bool),
        "axes": np.eye(52, 2),
        "projection_usable": np.array(True),
    }
    manifest = {"tracks": tracks, "genres": [{"genre_id": i} for i in range(1, 5)]}
    return manifest, roster, values, model


class RecordingProfilesTest(unittest.TestCase):
    def test_singleton_mean_and_component_isolation(self) -> None:
        manifest, roster, values, model = fixture()
        rows = profiles.artist_rows(manifest, roster, values, model)
        self.assertEqual(len(rows), 12)
        np.testing.assert_array_equal(rows[0]["vector"], values[0])
        np.testing.assert_array_equal(rows[-1]["vector"], (values[-2] + values[-1]) / 2)
        self.assertEqual(rows[-1]["position"], ((values[-2] + values[-1]) / 2)[:2].tolist())
        self.assertEqual(rows[-1]["track_ids"], [12, 13])
        for row in rows[:10]:
            self.assertFalse(set(row["neighbors"]) & set(range(100, 110)))
        self.assertEqual(sum(i < 110 for i in rows[-1]["neighbors"]), 1)
        self.assertTrue(all(len(row["neighbors"]) <= 6 for row in rows))

    def test_tags_do_not_change_acoustic_profiles(self) -> None:
        manifest, roster, values, model = fixture()
        before = profiles.artist_rows(manifest, roster, values, model)
        changed = copy.deepcopy(manifest)
        for row in changed["tracks"]:
            row["genre_ids"] = [4]
        after = profiles.artist_rows(changed, roster, values, model)
        for left, right in zip(before, after, strict=True):
            for field in ("vector", "position", "neighbors", "neighbor_reason"):
                self.assertEqual(left[field], right[field])

    def test_invalid_member_zero_mean_and_projection_are_distinct(self) -> None:
        manifest, roster, values, model = fixture()
        for invalid in (np.zeros(52), np.full(52, 13.0)):
            changed = values.copy()
            changed[-1] = invalid
            row = profiles.artist_rows(manifest, roster, changed, model)[-1]
            self.assertIsNone(row["vector"])
            self.assertIsNone(row["position"])
            self.assertEqual(row["neighbor_reason"], "unsupported_member")
            self.assertEqual(row["projection_reason"], "unsupported_member")
            self.assertEqual(row["track_count"], 2)
        values[-1] = -values[-2]
        row = profiles.artist_rows(manifest, roster, values, model)[-1]
        self.assertEqual(row["neighbor_reason"], "zero_mean_norm")
        self.assertEqual(row["position"], [0.0, 0.0])
        self.assertIsNone(row["projection_reason"])
        model["projection_usable"] = np.array(False)
        row = profiles.artist_rows(manifest, roster, values, model)[0]
        self.assertEqual(row["projection_reason"], "projection_degenerate")
        self.assertTrue(row["neighbors"])

    def test_exact_ties_and_cross_fold_artist_rejection(self) -> None:
        manifest, roster, values, model = fixture()
        values[:] = values[0]
        rows = profiles.artist_rows(manifest, roster, values, model)
        self.assertEqual(rows[-1]["neighbors"], [100, 110])
        roster[-1]["fold"] = 2
        with self.assertRaisesRegex(ValueError, "crosses"):
            profiles.artist_rows(manifest, roster, values, model)
        with self.assertRaisesRegex(ValueError, "roster"):
            profiles.artist_rows(manifest, roster[:-1], values, model)

    def test_cotags_are_symmetric_exact_and_not_artist_unions(self) -> None:
        manifest, roster, _, _ = fixture()
        rows = profiles.source_genres(manifest, {r["track_id"]: r for r in roster})
        self.assertEqual(rows[0]["relationships"][0]["track_ids"], [1])
        self.assertEqual(rows[1]["relationships"][0]["track_ids"], [1])
        self.assertEqual(rows[2]["relationships"], [])
        self.assertEqual(rows[3]["track_count"], 0)
        for row in rows:
            self.assertNotIn(row["genre_id"], [r["genre_id"] for r in row["relationships"]])

    def test_pack_rejects_extra_files_and_rebound_view(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol = b"{}\n"
            (root / "protocol.json").write_bytes(protocol)
            profiles.waveform.write(root / "declaration.json", {})
            profiles.waveform.write(root / "discovery.json", {"expected": True})
            receipt = {
                "revision": "fma55-recording-profile-receipt-v1",
                "files": {
                    name: profiles.waveform.binding(root / name)
                    for name in ("protocol.json", "declaration.json", "discovery.json")
                },
                "waveform_inventory_sha256": profiles.SOURCE_SHA,
                "candidate_manifest_sha256": profiles.waveform.MANIFEST_SHA,
                "protocol_sha256": profiles.waveform.digest(protocol),
            }
            profiles.waveform.write(root / "receipt.json", receipt)
            profiles.waveform.write(root / "inventory.json", profiles.inventory(root))
            pin = profiles.waveform.digest((root / "inventory.json").read_bytes())
            with (
                patch.object(profiles, "PROTOCOL_SHA", profiles.waveform.digest(protocol)),
                patch.object(profiles, "check_declaration"),
                patch.object(profiles, "inputs", return_value={}),
                patch.object(profiles, "calculate", return_value={"expected": True}),
            ):
                self.assertEqual(
                    profiles.validate_discovery_pack(root, root, root, pin), {"expected": True}
                )
                (root / "extra").write_text("no")
                with self.assertRaisesRegex(ValueError, "not closed"):
                    profiles.validate_discovery_pack(root, root, root, pin)
                (root / "extra").unlink()
                (root / "discovery.json").write_text('{"unexpected":true}\n')
                receipt["files"]["discovery.json"] = profiles.waveform.binding(
                    root / "discovery.json"
                )
                (root / "receipt.json").write_text(json.dumps(receipt))
                (root / "inventory.json").write_text(json.dumps(profiles.inventory(root)))
                pin = profiles.waveform.digest((root / "inventory.json").read_bytes())
                with self.assertRaisesRegex(ValueError, "frozen replay"):
                    profiles.validate_discovery_pack(root, root, root, pin)
