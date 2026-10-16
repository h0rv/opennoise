"""Physical signal, leakage and bounded full-decode tests; no actual FMA computation."""

from __future__ import annotations

# ruff: noqa: PLR2004 -- fixed protocol dimensions and synthetic physical signal values.
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.ml import fma_waveform_pipeline as pipeline


class WaveformTests(unittest.TestCase):
    def test_physical_silence_tone_amplitude_and_zero_crossings(self) -> None:
        silent = pipeline.features(np.zeros(22050))
        self.assertTrue(np.isfinite(silent).all())
        np.testing.assert_array_equal(silent[48:], 0)
        t = np.arange(22050) / 22050
        tone = np.sin(2 * np.pi * 440 * t) * 0.2
        first, doubled = pipeline.features(tone), pipeline.features(2 * tone)
        self.assertAlmostEqual(doubled[48], 2 * first[48], places=12)
        self.assertAlmostEqual(first[50], 880 / 22050, delta=0.001)
        active = first[:24] > -10
        np.testing.assert_allclose(
            doubled[:24][active] - first[:24][active], np.log10(4), atol=1e-10
        )
        low, high = (
            pipeline.features(np.sin(2 * np.pi * 220 * t)),
            pipeline.features(np.sin(2 * np.pi * 4400 * t)),
        )
        self.assertLess(np.argmax(low[:24]), np.argmax(high[:24]))

    def test_heldout_values_do_not_change_fit_and_save_load_is_exact(self) -> None:
        values = np.random.default_rng(7).normal(size=(55, 52))
        training = np.arange(55) < 47
        original = pipeline.fit(values, training)
        changed = values.copy()
        changed[47:] = 1e6
        second = pipeline.fit(changed, training)
        for key in original:
            np.testing.assert_array_equal(original[key], second[key])
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "model.npz"
            np.savez(path, allow_pickle=False, **original)
            with np.load(path, allow_pickle=False) as loaded:
                replay = dict(loaded)
            np.testing.assert_array_equal(
                pipeline.transform(values, original)[1], pipeline.transform(values, replay)[1]
            )

    def test_degenerate_projection_and_zero_support_are_explicit(self) -> None:
        values = np.zeros((55, 52))
        model = pipeline.fit(values, np.arange(55) < 47)
        self.assertFalse(model["projection_usable"])
        self.assertEqual(set(pipeline.transform(values, model)[2]), {"zero_norm"})

    def test_components_ties_and_label_permutation_do_not_change_track_geometry(self) -> None:
        values = np.random.default_rng(2).normal(size=(55, 52))
        tracks = [{"track_id": i + 1, "genre_ids": [i % 4 + 1]} for i in range(55)]
        roster = [
            {
                "track_id": i + 1,
                "component_id": i // 2 + 1,
                "fold": 0 if i < 47 else 1 if i < 49 else 2,
            }
            for i in range(55)
        ]
        model = pipeline.fit(values, np.arange(55) < 47)
        view, evaluation = pipeline.derive(values, tracks, roster, model)
        altered = [{**row, "genre_ids": [99]} for row in tracks]
        other, _ = pipeline.derive(values, altered, roster, model)
        self.assertEqual(view["tracks"], other["tracks"])
        for row in view["tracks"]:
            component_ids = [roster[i - 1]["component_id"] for i in row["neighbors"]]
            self.assertNotIn(row["component_id"], component_ids)
            self.assertEqual(len(component_ids), len(set(component_ids)))
            self.assertTrue(all(i <= 47 for i in row["neighbors"]))
        self.assertEqual(evaluation["aggregates"]["test"]["total_queries"], 6)
        order = pipeline.rank(
            0,
            np.ones((4, 52)),
            np.ones((4, 2)),
            np.array([9, 3, 1, 2]),
            np.array([1, 2, 2, 3]),
            np.array([0, 1, 2, 3]),
            "raw",
        )
        self.assertEqual(order, [2, 3])

    def test_decoder_full_completion_overflow_timeout_and_invalid_source(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "synthetic.wav"
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(22050)
                stream.writeframes(np.zeros(22050, dtype="<i2").tobytes())
            self.assertEqual(len(pipeline.decode(path)), 22050)
            with (
                patch.object(pipeline, "PCM_BYTES", 8192),
                self.assertRaisesRegex(ValueError, "bound"),
            ):
                pipeline.decode(path)
            with (
                patch.object(pipeline.time, "monotonic", side_effect=[0, 21]),
                self.assertRaisesRegex(ValueError, "timeout"),
            ):
                pipeline.decode(path)
            path.write_bytes(b"invalid audio")
            with self.assertRaisesRegex(ValueError, "failed"):
                pipeline.decode(path)

    def test_closed_pack_rejects_resealed_private_scope_and_missing_receipt_binding(self) -> None:

        from opennoise.common import canonical_json  # noqa: PLC0415

        tracks = [{"track_id": i + 1, "genre_ids": [i % 4 + 1]} for i in range(55)]
        roster = [
            {"track_id": i + 1, "component_id": i + 1, "fold": 0 if i < 47 else 1 if i < 49 else 2}
            for i in range(55)
        ]
        values = np.random.default_rng(3).normal(size=(55, 52))
        model = pipeline.fit(values, np.arange(55) < 47)
        view, evaluation = pipeline.derive(values, tracks, roster, model)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            protocol = b"synthetic protocol, never actual evidence"
            protocol_sha = pipeline.digest(protocol)
            (root / "protocol.json").write_bytes(protocol)
            pipeline.write(
                root / "declaration.json",
                {
                    "protocol_sha256": protocol_sha,
                    "candidate_manifest_sha256": pipeline.MANIFEST_SHA,
                    "roster": roster,
                },
            )
            np.savez(root / "features.npz", values=values, track_ids=np.arange(1, 56))
            np.savez(root / "model.npz", allow_pickle=False, **model)
            pipeline.write(root / "evaluation.json", evaluation)
            receipt = {
                "protocol_sha256": protocol_sha,
                "candidate_manifest_sha256": pipeline.MANIFEST_SHA,
                "columns": pipeline.COLUMNS,
                "fit_ids": list(range(1, 48)),
                "files": {
                    key: pipeline.binding(root / key)
                    for key in (
                        "protocol.json",
                        "declaration.json",
                        "features.npz",
                        "model.npz",
                        "evaluation.json",
                    )
                },
            }
            pipeline.write(root / "receipt.json", receipt)
            view.update(
                revision=pipeline.REVISION,
                candidate_manifest_sha256=pipeline.MANIFEST_SHA,
                protocol_sha256=protocol_sha,
                receipt_sha256=pipeline.digest(pipeline.read(root / "receipt.json")),
                axes=["PC1", "PC2"],
                musical_quality_validated=False,
            )
            pipeline.write(root / "layout.json", view)

            def reseal() -> None:
                (root / "inventory.json").write_bytes(
                    canonical_json({key: pipeline.binding(root / key) for key in pipeline.FILES})
                )

            reseal()
            with (
                patch.object(pipeline, "candidate", return_value={"tracks": tracks}),
                patch.object(pipeline, "PROTOCOL_SHA", protocol_sha),
                patch.object(pipeline, "ROSTER_SHA", pipeline.digest(canonical_json(roster))),
            ):
                pipeline.validate_waveform_pack(root, root / "unused")
                view["private_metadata"] = "must not leak"
                (root / "layout.json").write_bytes(canonical_json(view))
                reseal()
                with self.assertRaisesRegex(ValueError, "scope"):
                    pipeline.validate_waveform_pack(root, root / "unused")
                del view["private_metadata"]
                del receipt["files"]["evaluation.json"]
                (root / "receipt.json").write_bytes(canonical_json(receipt))
                view["receipt_sha256"] = pipeline.digest(pipeline.read(root / "receipt.json"))
                (root / "layout.json").write_bytes(canonical_json(view))
                reseal()
                with self.assertRaisesRegex(ValueError, "scope"):
                    pipeline.validate_waveform_pack(root, root / "unused")

    def test_out_of_support_abstains_shared_arms_and_unknown_tags_remain(self) -> None:
        values = np.random.default_rng(8).normal(size=(55, 52))
        values[-1] = 1e6
        tracks = [{"track_id": i + 1, "genre_ids": [1 if i < 47 else 999]} for i in range(55)]
        roster = [
            {"track_id": i + 1, "component_id": i + 1, "fold": 0 if i < 47 else 1 if i < 49 else 2}
            for i in range(55)
        ]
        model = pipeline.fit(values, np.arange(55) < 47)
        view, evaluation = pipeline.derive(values, tracks, roster, model)
        self.assertEqual(view["tracks"][-1]["neighbor_reason"], "out_of_support")
        row = evaluation["queries"][-1]
        self.assertEqual(row["rankings"], {"raw": [], "pca": [], "id": []})
        self.assertEqual(row["training_known_tags"], [])
        self.assertIsNone(row["metrics"]["raw"]["3"]["recall_known"])
        self.assertEqual(row["metrics"]["raw"]["3"]["recall_all"], 0)
        self.assertEqual(evaluation["aggregates"]["test"]["total_queries"], 6)
