# ruff: noqa: PLR2004 -- explicit synthetic missing/unknown/same-component IDs.
"""Synthetic descriptor fixtures, not authentic audio or musical relevance evidence."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

import numpy as np

from opennoise.ml import fma_playable_neighbors as m


class PlayableNeighborTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.audio, self.features, self.pack = (
            self.root / name for name in ("audio", "features", "pack")
        )
        for directory in (self.audio, self.features, self.pack):
            directory.mkdir()
        self.model = {
            "center": np.zeros(2),
            "scale": np.ones(2),
            "active_columns": np.ones(2, dtype=bool),
        }
        self.roles = [
            {
                "track_id": i,
                "artist_id": i,
                "artist_known": i != 6,
                "component_id": None if i == 6 else 1 if i == 2 else i,
            }
            for i in range(1, 8)
        ]
        values = np.array([[0, 0], [0, 0], [1, 0], [-1, 0], [np.nan, 0]], dtype="<f4")
        ids = np.array([1, 2, 3, 4, 7], dtype="<u4")
        arrays = {"features.float32": values.tobytes(), "track_ids.uint32": ids.tobytes()}
        receipt: dict[str, Any] = {
            "license": "CC-BY-4.0",
            "audio_downloaded": False,
            "echo_nest_consumed": False,
            "rows": 5,
            "columns": ["a", "b"],
            "files": {},
        }
        for name, body in arrays.items():
            (self.features / name).write_bytes(body)
            receipt["files"][name] = {
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        (self.features / "projection-receipt.json").write_text(json.dumps(receipt))
        self.stack.enter_context(
            patch.object(
                m,
                "FEATURE_RECEIPT_SHA256",
                hashlib.sha256(
                    (self.features / "projection-receipt.json").read_bytes()
                ).hexdigest(),
            )
        )
        self.stack.enter_context(
            patch.object(m, "FEATURE_SHA", receipt["files"]["features.float32"]["sha256"])
        )
        self.stack.enter_context(
            patch.object(m, "ID_SHA", receipt["files"]["track_ids.uint32"]["sha256"])
        )
        attached = {"tracks": {str(i): {"track_id": i, "artist_id": i} for i in range(1, 8)}}
        (self.audio / "manifest.json").write_text(json.dumps(attached))
        self.verify_audio = self.stack.enter_context(
            patch.object(m, "validate_playback_export", return_value=attached)
        )
        stream = io.BytesIO()
        np.savez(
            stream,
            center=self.model["center"],
            scale=self.model["scale"],
            active_columns=self.model["active_columns"],
        )
        self.stack.enter_context(
            patch.object(
                m.fma_related_tracks,
                "_pack",
                return_value=(
                    {},
                    {"model.npz": stream.getvalue(), "native-roles.jsonl.zst": b"fake-role-bytes"},
                    self.roles,
                ),
            )
        )
        self.declaration = self.root / "declaration.json"

    def build(self) -> tuple[Path, dict[str, Any]]:
        m.freeze_protocol(self.audio, self.pack, self.features, self.declaration)
        output = self.root / "neighbors"
        result = m.build(self.audio, self.pack, self.features, self.declaration, output)
        return output, result

    def test_roundtrip_ties_whole_component_and_abstentions(self) -> None:
        output, result = self.build()
        rows = {row["track_id"]: row for row in result["rows"]}
        self.assertEqual(rows[1]["neighbor_ids"], [3, 4])
        self.assertNotIn(2, rows[1]["neighbor_ids"])
        self.assertEqual(rows[5]["reason"], "missing_feature_row")
        self.assertEqual(rows[6]["reason"], "unresolved_artist")
        self.assertEqual(rows[7]["reason"], "outside_training_support")
        self.assertEqual(result["counts"]["queries"], 7)
        self.assertEqual(result, m.replay(self.audio, self.pack, self.features, output))
        self.assertGreaterEqual(self.verify_audio.call_count, 3)
        with self.assertRaises(FileExistsError):
            m.freeze_protocol(self.audio, self.pack, self.features, self.declaration)

    def test_single_component_and_range_gate(self) -> None:
        roles = {
            1: {"artist_known": True, "component_id": 8},
            2: {"artist_known": True, "component_id": 8},
        }
        rows = m.rank_playable([2, 1], roles, {1: np.zeros(2), 2: np.zeros(2)}, self.model)
        self.assertTrue(all(row["reason"] == "no_cross_component_candidates" for row in rows))
        rows = m.rank_playable([1, 2], roles, {1: np.array([12.01, 0]), 2: np.zeros(2)}, self.model)
        self.assertEqual(rows[0]["reason"], "outside_training_support")
        with self.assertRaises(ValueError):
            m.rank_playable([1] * 65, roles, {}, self.model)

    def test_frozen_audio_feature_and_code_tampering_rejected(self) -> None:
        m.freeze_protocol(self.audio, self.pack, self.features, self.declaration)
        original = self.declaration.read_bytes()
        frozen = json.loads(original)
        frozen["implementation"]["producer"]["sha256"] = "bad"
        self.declaration.write_text(json.dumps(frozen))
        with self.assertRaisesRegex(ValueError, "frozen declaration"):
            m.derive(self.audio, self.pack, self.features, self.declaration)
        self.declaration.write_bytes(original)
        (self.audio / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "frozen declaration"):
            m.derive(self.audio, self.pack, self.features, self.declaration)
        (self.features / "features.float32").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "descriptor bytes"):
            m.derive(self.audio, self.pack, self.features, self.declaration)

    def test_receipt_semantics_exclusion_pins_and_closed_inventory(self) -> None:
        output, result = self.build()
        with self.assertRaises(ValueError):
            m.validate_playable_neighbors(output, "wrong-audio-manifest")
        original = (output / "receipt.json").read_bytes()
        for mutate in (
            lambda row: row.update(fitted=True),
            lambda row: row["rows"][0].update(neighbor_ids=[2]),
            lambda row: row["rows"][0].update(neighbor_ids=[5]),
            lambda row: row["rows"][0].update(neighbor_ids=[3, 3]),
            lambda row: row["rows"][0].update(reason="missing_feature_row"),
        ):
            changed = json.loads(json.dumps(result))
            mutate(changed)
            body = json.dumps(changed).encode()
            (output / "manifest.json").write_bytes(body)
            receipt = json.loads(original)
            receipt["files"]["manifest.json"] = {
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            (output / "receipt.json").write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                m.validate_playable_neighbors(output)
        (output / "extra").write_bytes(b"extra")
        with self.assertRaises(ValueError):
            m.validate_playable_neighbors(output)

    def test_native_artist_mismatch_stops_freeze(self) -> None:
        self.roles[0]["artist_id"] = 999
        with self.assertRaisesRegex(ValueError, "artist differs"):
            m.freeze_protocol(self.audio, self.pack, self.features, self.declaration)
        self.assertFalse(self.declaration.exists())

    def test_projection_receipt_pin_rejects_metadata_rewrite(self) -> None:
        path = self.features / "projection-receipt.json"
        receipt = json.loads(path.read_bytes())
        receipt["columns"] = ["rewritten", "metadata"]
        path.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            m.freeze_protocol(self.audio, self.pack, self.features, self.declaration)
        self.assertFalse(self.declaration.exists())
