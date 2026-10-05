from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast, override
from unittest.mock import patch

import numpy as np
import zstandard

from opennoise.ml import (
    fma_acoustic_baseline,
    fma_inference,
    fma_memberships,
    fma_training_memberships,
)
from opennoise.ml.fma_inference import encode_jsonl, infer_tracks

UNRESOLVED_ID = 4


def binding(path: Path) -> dict[str, Any]:
    """Bind each isolated synthetic artifact for loader contract tests."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class FrozenInferenceTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack = self.root / "saved"
        self.features = self.root / "numeric"
        self.pack.mkdir()
        self.features.mkdir()
        np.savez_compressed(
            self.pack / "model.npz",
            center=np.zeros(2),
            scale=np.ones(2),
            active_columns=np.ones(2, dtype=bool),
            quadratic=np.full((2, 2), -0.5),
            linear=np.array([[1.0, 0.0], [-1.0, 0.0]]),
            intercept=np.zeros(2),
            active_labels=np.ones(2, dtype=bool),
            label_feature_support=np.array([10.0, 10.0]),
            training_rows=np.array(20),
            labels=np.array([1, 2]),
        )
        thresholds = {
            1: {
                "threshold_rank": 1,
                "positive_components": 20,
                "component_worst_positive_ranks": [1] * 20,
            },
            2: {
                "threshold_rank": None,
                "positive_components": 0,
                "component_worst_positive_ranks": [],
            },
        }
        (self.pack / "thresholds.json").write_text(json.dumps(thresholds))
        (self.pack / "declaration.json").write_text('{"fixture": true}')
        ledger = [
            {
                "track_id": i,
                "artist_known": i != UNRESOLVED_ID,
                "role": "inner_fit"
                if i == 1
                else "unresolved_artist"
                if i == UNRESOLVED_ID
                else "test_diagnostic",
            }
            for i in range(1, 8)
        ]
        data = "".join(json.dumps(row) + "\n" for row in ledger).encode()
        (self.pack / "native-roles.jsonl.zst").write_bytes(
            zstandard.ZstdCompressor().compress(data)
        )
        seal = {
            "artifacts": {
                n: binding(self.pack / n)["sha256"] for n in ("model.npz", "thresholds.json")
            }
        }
        (self.pack / "pre-diagnostic-seal.json").write_text(json.dumps(seal))
        artifacts = {n: binding(self.pack / n) for n in fma_inference.PACK_FILES}
        for module in (fma_acoustic_baseline, fma_memberships, fma_training_memberships):
            path = Path(module.__file__)
            artifacts[path.name] = binding(path)
        (self.pack / "evaluation.json").write_text(json.dumps({"artifacts": artifacts}))
        np.array([1, 2, 4, 5, 6, 7], dtype="<u4").tofile(self.features / "track_ids.uint32")
        np.array(
            [[1.0, 0.0], [-1.0, 0.0], [1.0, 0.0], [float("nan"), 0.0], [100.0, 0.0], [0.0, 0.0]],
            dtype="<f4",
        ).tofile(self.features / "features.float32")
        receipt = {
            "rows": 6,
            "columns": ["x", "y"],
            "license": "fixture",
            "attribution": "synthetic fixture",
            "files": {n: binding(self.features / n) for n in fma_inference.FEATURE_FILES},
        }
        (self.features / "projection-receipt.json").write_text(json.dumps(receipt))
        for name, path in (
            ("EVALUATION_SHA256", self.pack / "evaluation.json"),
            ("FEATURE_RECEIPT_SHA256", self.features / "projection-receipt.json"),
        ):
            patcher = patch.object(fma_inference, name, binding(path)["sha256"])
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_order_duplicates_stable_tie_and_source_distinction(self) -> None:
        result = infer_tracks(self.pack, self.features, [7, 1, 2, 1])
        self.assertEqual([r["track_id"] for r in result], [7, 1, 2, 1])
        self.assertEqual(result[1], result[3])
        self.assertEqual(result[0]["memberships"][0]["genre_id"], 1)
        self.assertEqual(result[2]["abstention"], "no_calibrated_membership")
        self.assertEqual(result[1]["namespace"], fma_training_memberships.REVISION)
        self.assertFalse(result[1]["musical_probability"])
        self.assertFalse(result[1]["direct_source_labels_inferred"])
        self.assertFalse(result[1]["provenance"]["query_source_labels_consumed"])
        self.assertEqual(
            encode_jsonl(result), encode_jsonl(infer_tracks(self.pack, self.features, [7, 1, 2, 1]))
        )

    def test_all_abstention_paths(self) -> None:
        result = infer_tracks(self.pack, self.features, [99, 4, 3, 5, 6])
        self.assertEqual(
            [r["abstention"] for r in result],
            [
                "unknown_native_track_id",
                "unresolved_artist",
                "missing_feature_row",
                "missing_descriptors",
                "outside_training_support",
            ],
        )
        self.assertTrue(all(not r["memberships"] for r in result))
        self.assertIsNone(result[0]["provenance"]["original_role"])

    def test_invalid_ids_and_query_limit_rejected_before_io(self) -> None:
        for ids in ([], [0], [-1], [True], [1.0], ["1"], [2**32], [1] * 101):
            with (
                self.subTest(ids=ids),
                patch.object(
                    fma_inference,
                    "_read_pinned",
                    side_effect=AssertionError("I/O before validation"),
                ),
                self.assertRaises(ValueError),
            ):
                infer_tracks(self.pack, self.features, cast("list[int]", ids))
        self.assertEqual(len(infer_tracks(self.pack, self.features, [1] * 100)), 100)

    def test_every_consumed_pack_and_projection_file_is_pinned(self) -> None:
        for path in [self.pack / n for n in (*fma_inference.PACK_FILES, "evaluation.json")] + [
            self.features / n for n in (*fma_inference.FEATURE_FILES, "projection-receipt.json")
        ]:
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "input"):
                    infer_tracks(self.pack, self.features, [1])
                path.write_bytes(original)

    def test_live_scoring_code_drift_rejected(self) -> None:
        fake = self.root / "fma_acoustic_baseline.py"
        fake.write_text("changed")
        with (
            patch.object(fma_acoustic_baseline, "__file__", str(fake)),
            self.assertRaisesRegex(ValueError, "input"),
        ):
            infer_tracks(self.pack, self.features, [1])

    def test_portable_minimal_pack_without_targets_ranks_or_captures(self) -> None:
        moved = self.root / "portable"
        shutil.copytree(self.pack, moved / "pack")
        shutil.copytree(self.features, moved / "features")
        before = infer_tracks(self.pack, self.features, [1, 3, 99])
        shutil.rmtree(self.pack)
        shutil.rmtree(self.features)
        with (
            patch.object(
                fma_acoustic_baseline,
                "fit_positive_gaussian",
                side_effect=AssertionError("fit prohibited"),
            ),
            patch.object(
                fma_training_memberships,
                "fit_thresholds",
                side_effect=AssertionError("calibration prohibited"),
            ),
        ):
            self.assertEqual(before, infer_tracks(moved / "pack", moved / "features", [1, 3, 99]))

    def test_symlink_rejected(self) -> None:
        path = self.pack / "model.npz"
        path.rename(self.root / "model.npz")
        path.symlink_to(self.root / "model.npz")
        with self.assertRaisesRegex(ValueError, "symlink"):
            infer_tracks(self.pack, self.features, [1])

    def test_input_output_and_cooperative_time_limits(self) -> None:
        with (
            patch.object(fma_inference, "MAX_INPUT_BYTES", 1),
            self.assertRaisesRegex(ValueError, "input byte budget"),
        ):
            infer_tracks(self.pack, self.features, [1])
        with (
            patch.object(fma_inference, "MAX_OUTPUT_BYTES", 1),
            self.assertRaisesRegex(ValueError, "output byte budget"),
        ):
            infer_tracks(self.pack, self.features, [1])
        with (
            patch.object(fma_inference.time, "monotonic", side_effect=[0, 31]),
            self.assertRaisesRegex(TimeoutError, "wall-time"),
        ):
            infer_tracks(self.pack, self.features, [1])

    def test_cli_sets_limits_and_emits_only_complete_jsonl(self) -> None:
        from scripts import infer_fma_tracks as cli  # noqa: PLC0415 - CLI side-effect boundary.

        captured = io.BytesIO()
        stdout = io.TextIOWrapper(captured, encoding="utf-8")
        args = [
            "infer_fma_tracks",
            "--pack",
            str(self.pack),
            "--features",
            str(self.features),
            "--track-id",
            "1",
            "--track-id",
            "3",
            "--track-id",
            "1",
        ]
        with (
            patch.object(sys, "argv", args),
            patch.object(sys, "stdout", stdout),
            patch.object(cli.resource, "setrlimit") as limits,
            patch.object(cli.signal, "signal"),
            patch.object(cli.signal, "alarm") as alarm,
        ):
            cli.main()
        data = captured.getvalue()
        stdout.detach()
        self.assertEqual([json.loads(line)["track_id"] for line in data.splitlines()], [1, 3, 1])
        self.assertEqual(limits.call_count, 2)
        limits.assert_any_call(cli.resource.RLIMIT_AS, (cli.MEMORY_BYTES, cli.MEMORY_BYTES))
        limits.assert_any_call(cli.resource.RLIMIT_CPU, (cli.MAX_SECONDS, cli.MAX_SECONDS))
        self.assertEqual([call.args[0] for call in alarm.call_args_list], [30, 0])

    def test_cli_validation_failure_writes_no_jsonl(self) -> None:
        from scripts import infer_fma_tracks as cli  # noqa: PLC0415 - CLI side-effect boundary.

        captured = io.BytesIO()
        stdout = io.TextIOWrapper(captured, encoding="utf-8")
        args = [
            "infer_fma_tracks",
            "--pack",
            str(self.pack),
            "--features",
            str(self.features),
            "--track-id",
            "0",
        ]
        with (
            patch.object(sys, "argv", args),
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", io.StringIO()),
            patch.object(cli.resource, "setrlimit"),
            patch.object(cli.signal, "signal"),
            patch.object(cli.signal, "alarm"),
            self.assertRaises(SystemExit) as error,
        ):
            cli.main()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(captured.getvalue(), b"")
        stdout.detach()
