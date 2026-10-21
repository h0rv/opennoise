"""Synthetic alignment signals only; no real annotations or per-track outputs."""

# ruff: noqa: SLF001, PLR2004 -- Native primitive regression and explicit boundary fixtures.
import copy
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

import numpy as np

from opennoise.ml import medley_melody as native
from opennoise.ml import transposed_melody as melody
from tests import test_medley_melody as fixture

ROOT = Path(__file__).resolve().parents[1]


def contour(hz: list[float] | np.ndarray, *, query: bool) -> native.Contour:
    """Create non-melodic synthetic samples on the declared native grid."""
    return native.contour(np.arange(len(hz)) * native.HOP, hz, query=query)


class TransposedMelodyTests(unittest.TestCase):
    """Separate bounded alignment and unchanged absolute-pitch source compatibility."""

    @override
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pack = self.root / "pack"
        self.pin, _ = fixture.build(self.root, self.pack)
        self.source = native.load_source(self.pack, self.pin)
        self.request = {
            "times_seconds": (np.arange(173) * native.HOP).tolist(),
            "f0_hz": [440.0] * 173,
        }

    def test_fixed_shifts_offset_sign_bounds_and_positive_residual_cost(self) -> None:
        source = contour([440.0] * 173, query=False)
        for shift in (-13, -12, -3, 0, 3, 12, 13):
            with self.subTest(shift=shift):
                query = contour([440 * 2 ** (shift / 12)] * 173, query=True)
                match = melody._best(source, query)
                assert match is not None
                offset = max(-12, min(12, -shift))
                self.assertAlmostEqual(match["source_minus_query_semitones"], offset, places=11)
                expected = max(abs(shift) - 12, 0) ** 2
                self.assertEqual(match["distance_ticks"], round(expected / native.TICK))
                self.assertAlmostEqual(match["mean_squared_midi_distance"], expected, places=11)

    def test_independent_scalar_per_window_offset_and_cost_oracle(self) -> None:
        rng = np.random.default_rng(917)
        hz = rng.choice([0.0, 220.0, 440.0, 660.0], 310, p=[0.1, 0.3, 0.3, 0.3])
        q = rng.choice([0.0, 330.0, 440.0], 173, p=[0.1, 0.45, 0.45])
        expected = []
        for start in range(len(hz) - len(q) + 1):
            differences = [
                12 * (math.log2(float(x)) - math.log2(float(y)))
                for x, y in zip(hz[start : start + len(q)], q, strict=True)
                if x > 0 and y > 0
            ]
            if len(differences) * 4 < int((q > 0).sum()) * 3:
                continue
            offset = max(-12.0, min(12.0, math.fsum(differences) / len(differences)))
            costs = []
            for x, y in zip(hz[start : start + len(q)], q, strict=True):
                if x > 0 and y > 0:
                    costs.append((12 * (math.log2(float(x)) - math.log2(float(y))) - offset) ** 2)
                else:
                    costs.append(144.0 if (x > 0) != (y > 0) else 0.0)
            cost = math.fsum(costs) / len(q)
            expected.append((round(cost / native.TICK), start, cost, offset))
        match = melody._best(contour(hz, query=False), contour(q, query=True))
        assert match is not None
        target = min(expected)
        self.assertEqual((match["distance_ticks"], match["start_frame"]), target[:2])
        self.assertAlmostEqual(match["mean_squared_midi_distance"], target[2], places=10)
        self.assertAlmostEqual(match["source_minus_query_semitones"], target[3], places=10)

    def test_joint_only_mean_voicing_boundary_and_all_frame_denominator(self) -> None:
        query = contour([440.0] * 44 + [0.0] * 129, query=True)
        for count in (32, 33):
            match = melody._best(
                contour([880.0] * count + [0.0] * (173 - count), query=False), query
            )
            if count == 32:
                self.assertIsNone(match)
            else:
                assert match is not None
                self.assertAlmostEqual(match["source_minus_query_semitones"], 12, places=11)
                self.assertEqual(match["distance_ticks"], round((11 * 144 / 173) / native.TICK))
        unsupported = melody.search_contour(
            self.source, {**self.request, "f0_hz": [440.0] * 43 + [0.0] * 130}
        )
        self.assertEqual(unsupported["status"], "query_insufficient_voicing")
        self.assertEqual(unsupported["results"], [])
        self.assertEqual(len(unsupported["nominations"]), 3)

    def test_offset_never_breaks_earliest_or_global_ties(self) -> None:
        query = contour([440.0] * 173, query=True)
        source = contour([880.0] * 173 + [440.0] * 173, query=False)
        match = melody._best(source, query)
        assert match is not None
        self.assertEqual((match["distance_ticks"], match["start_frame"]), (0, 0))
        self.assertAlmostEqual(match["source_minus_query_semitones"], 12)
        result = melody.search_contour(self.source, {**self.request, "f0_hz": [880.0] * 173})
        self.assertEqual(
            [r["native_track_id"] for r in result["results"]], ["Synthetic_Alpha", "Synthetic_Beta"]
        )
        self.assertAlmostEqual(result["results"][0]["source_minus_query_semitones"], -12)

    def test_quantized_tiny_positive_cost_beats_later_exact_zero(self) -> None:
        epsilon = math.sqrt(4e-9)
        jitter = [440 * 2 ** ((epsilon if i % 2 else -epsilon) / 12) for i in range(172)]
        source = contour(jitter + [440.0] * 174, query=False)
        match = melody._best(source, contour([440.0] * 173, query=True))
        assert match is not None
        self.assertEqual((match["distance_ticks"], match["start_frame"]), (0, 0))
        self.assertGreater(match["mean_squared_midi_distance"], 0)

    def test_new_caller_coordinates_ndarray_parity_no_mutation_and_bindings(self) -> None:
        arrays = {name: np.asarray(values) for name, values in self.request.items()}
        before = {name: value.copy() for name, value in arrays.items()}
        result = melody.search_contour(self.source, arrays)
        self.assertEqual(result, melody.search_contour(self.source, self.request))
        for name, value in arrays.items():
            np.testing.assert_array_equal(value, before[name])
            self.assertTrue(value.flags.writeable)
        changed = melody.search_contour(self.source, {**self.request, "f0_hz": [1760.0] * 173})
        self.assertEqual(changed["results"][0]["native_track_id"], "Synthetic_Beta")
        self.assertNotEqual(result["query"]["sha256"], changed["query"]["sha256"])
        self.assertNotEqual(result["revision"], native.REVISION)
        self.assertEqual(result["source_manifest_sha256"], self.pin)
        self.assertEqual(result["runtime"], melody.runtime())
        self.assertEqual(result["rights"], self.source.pilot["rights"])

    def test_subnormal_upper_bound_and_strict_schema_grid(self) -> None:
        tiny = float(np.nextafter(0.0, 1.0))
        match = melody._best(
            contour([20000.0] * 173, query=False), contour([tiny] * 173, query=True)
        )
        assert match is not None
        self.assertTrue(math.isfinite(match["mean_squared_midi_distance"]))
        self.assertEqual(match["source_minus_query_semitones"], 12.0)
        for value in (True, "440", float("nan"), float("inf"), -1, 20001):
            request = copy.deepcopy(self.request)
            request["f0_hz"][0] = value  # ty: ignore[invalid-assignment] -- Intentional invalid input.
            with self.assertRaises(ValueError):
                melody.search_contour(self.source, request)
        for request in (
            {**self.request, "artist": "not-accepted"},
            {"times_seconds": [0.0] * 173, "f0_hz": [440.0] * 173},
        ):
            with self.assertRaises(ValueError):
                melody.search_contour(self.source, request)
        with self.assertRaises(ValueError):
            melody.search_contour(self.source, self.request, limit=True)
        with self.assertRaises(ValueError):
            melody.search_contour(self.source, self.request, limit=25)

    def test_frozen_baseline_loader_and_results_remain_unchanged(self) -> None:
        before = native.encoded(native.search_contour(self.source, self.request))
        melody.search_contour(self.source, self.request)
        self.assertEqual(before, native.encoded(native.search_contour(self.source, self.request)))
        for name, digest in melody.BASELINE_FILES.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        with (
            patch.object(melody, "BASELINE_FILES", {"src/opennoise/ml/medley_melody.py": "0" * 64}),
            self.assertRaises(ValueError),
        ):
            melody.search_contour(self.source, self.request)

    def test_chunk_bound_and_new_standalone_cli_physical_pins(self) -> None:
        observed = []
        square = np.square

        def checked(values: np.ndarray) -> np.ndarray:
            observed.append(values.shape)
            return square(values)

        with patch.object(melody.np, "square", side_effect=checked):
            melody.search_contour(self.source, self.request)
        self.assertTrue(observed)
        self.assertTrue(all(shape[0] <= native.CHUNK and shape[1] == 173 for shape in observed))
        query = self.root / "query.json"
        query.write_bytes(native.encoded(self.request))
        output = self.root / "result.json"
        command = [
            sys.executable,
            str(ROOT / "scripts/query_transposed_melody_contour.py"),
            "--source",
            str(self.pack),
            "--source-sha256",
            self.pin,
            "--query",
            str(query),
            "--query-sha256",
            fixture.digest(query),
            "--output",
            str(output),
        ]
        done = subprocess.run(command, capture_output=True, text=True, check=True)  # noqa: S603
        self.assertEqual(json.loads(done.stdout)["result_sha256"], fixture.digest(output))
        self.assertEqual(json.loads(output.read_bytes())["revision"], melody.REVISION)
        unchanged = output.read_bytes()
        self.assertNotEqual(subprocess.run(command, capture_output=True, check=False).returncode, 0)  # noqa: S603
        self.assertEqual(output.read_bytes(), unchanged)
        altered = command.copy()
        altered[altered.index("--query-sha256") + 1] = "0" * 64
        self.assertNotEqual(subprocess.run(altered, capture_output=True, check=False).returncode, 0)  # noqa: S603
