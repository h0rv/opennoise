"""Check new caller-profile math, context custody and training-free runtime boundaries."""

import copy
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.ml import jamendo_genre_inference as pure


def model() -> dict[str, Any]:
    """Supply a small synthetic nine-class presence/absence model."""
    return {
        "prior": (np.arange(1, 10, dtype=float) / 45).tolist(),
        "vocabulary": ["genre---rock", "instrument---drums"],
        "theta": [[0.1 + j * 0.02, 0.7 - j * 0.02] for j in range(9)],
    }


def models() -> dict[str, Any]:
    """Use identical synthetic math in five independently selected frames."""
    return {
        "classes": list(pure.CLASSES),
        "mapping": [list(t) for t in pure.MAPPING],
        "folds": [
            {
                "fold": i,
                "model": model(),
                "temperature": 4,
                "temperature_reason": None,
                "model_reason": None,
            }
            for i in range(5)
        ],
    }


def capsule() -> pure.Capsule:
    """Include two artists sharing one synthetic component, to test unobserved pairs."""
    context = pure.routing(
        {"pairs": [[1, 10, 1, pure.fold(1)], [2, 20, 1, pure.fold(1)], [3, 30, 3, pure.fold(3)]]}
    )
    return pure.Capsule({"source": {}}, "a" * 64, pure.validate_models(models()), *context)


def publish(directory: Path) -> str:
    """Create a synthetic complete-size capsule for physical/schema boundary tests."""
    pairs = sorted([[i % 713 + 1, i + 1, i % 713 + 1, pure.fold(i % 713 + 1)] for i in range(2365)])
    directory.mkdir()
    data = {"models.json": models(), "routing.json": {"pairs": pairs}}
    files = {}
    for name, body in data.items():
        raw = pure.encoded(body)
        (directory / name).write_bytes(raw)
        files[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    manifest = {
        "revision": pure.REVISION,
        "contract_sha256": pure.CONTRACT,
        "source": {
            **pure.SOURCE,
            "study_receipt_sha256": "a" * 64,
            "study_inputs": {
                "protocol": pure.SOURCE["temperature_protocol_sha256"],
                "identity_seal": "b" * 64,
                "census_seal": "c" * 64,
                "result_receipt": "d" * 64,
            },
            "inner_census_sha256": "e" * 64,
        },
        "runtime": pure.runtime(),
        "builder": {
            "jamendo_genre_capsule.py": "a" * 64,
            "jamendo_human_mood.py": (
                "9848cd3a855e8b40018c50e949d3d38b6aad533c2323f8d68a7419cd5a5002e9"
            ),
        },
        "rights": pure.RIGHTS,
        "counts": {"artists": 713, "albums": 2365, "pairs": 2365, "components": 713},
        "files": files,
    }
    (directory / "manifest.json").write_bytes(pure.encoded(manifest))
    return pure.sha(directory / "manifest.json")


def reseal(directory: Path) -> str:
    """Refresh only storage bindings to exercise semantic rejection after deliberate resealing."""
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name in pure.FILES:
        manifest["files"][name] = {
            "sha256": pure.sha(directory / name),
            "bytes": (directory / name).stat().st_size,
        }
    (directory / "manifest.json").write_bytes(pure.encoded(manifest))
    return pure.sha(directory / "manifest.json")


class GenreInferenceTests(unittest.TestCase):
    """Prove profile computation, exact identity routing and strict portable custody."""

    def test_independent_multiclass_math_and_new_profiles(self) -> None:
        m = model()
        expected = [
            math.log(m["prior"][j]) + math.log(m["theta"][j][0]) + math.log(1 - m["theta"][j][1])
            for j in range(9)
        ]
        raw = [math.exp(v) for v in expected]
        actual = pure.probabilities(m, {"genre---rock"}, 4)
        np.testing.assert_allclose(
            actual["genre_instrument_nb"], [v / sum(raw) for v in raw], rtol=1e-14
        )
        soft = [math.exp(v / 4) for v in expected]
        np.testing.assert_allclose(
            actual["temperature_nb"], [v / sum(soft) for v in soft], rtol=1e-14
        )
        self.assertEqual(actual["mapped_uploader_genre"], [0.0] * 8 + [1.0])
        changed = pure.probabilities(m, {"instrument---drums"}, 4)
        self.assertNotEqual(changed["genre_instrument_nb"], actual["genre_instrument_nb"])
        self.assertEqual(changed["training_human_prior"], actual["training_human_prior"])

    def test_empty_tags_unseen_and_literal_mapper_are_distinct(self) -> None:
        cap = capsule()
        query = {"artist_id": 1, "album_id": 10, "tags": []}
        empty = pure.infer(cap, {"profiles": [query]})["profiles"][0]
        self.assertEqual(empty["status"], "emitted")
        self.assertEqual(empty["recognized_nb_feature_count"], 0)
        query["tags"] = ["genre---blues", "instrument---neverobserved"]
        unseen = pure.infer(cap, {"profiles": [query]})["profiles"][0]
        self.assertEqual(unseen["UNSEEN_BY_NB"], sorted(query["tags"]))
        self.assertEqual(unseen["mapped_classes"], ["blues"])
        self.assertEqual(
            unseen["estimates"]["genre_instrument_nb"], empty["estimates"]["genre_instrument_nb"]
        )
        self.assertNotEqual(
            unseen["estimates"]["mapped_uploader_genre"],
            empty["estimates"]["mapped_uploader_genre"],
        )

    def test_exact_observed_context_reasons_order_and_duplicates(self) -> None:
        inputs = [
            {"artist_id": a, "album_id": b, "tags": []}
            for a, b in [(99, 99), (1, 99), (1, 30), (1, 20), (1, 10), (1, 10)]
        ]
        result = pure.infer(capsule(), {"profiles": inputs})["profiles"]
        self.assertEqual(
            [r["status"] for r in result],
            [
                "unknown_artist",
                "unknown_album",
                "conflicting_component",
                "unobserved_artist_album_pair",
                "emitted",
                "emitted",
            ],
        )
        self.assertEqual([r["query_index"] for r in result], list(range(6)))
        self.assertEqual(result[4]["estimates"], result[5]["estimates"])
        self.assertEqual(result[4]["fold"], pure.fold(1))
        self.assertTrue(all(r["estimates"] is None for r in result[:4]))

    def test_strict_ids_schema_tags_and_caps(self) -> None:
        valid = {"artist_id": 1, "album_id": 10, "tags": []}
        invalid = [{**valid, "artist_id": v} for v in (True, "1", 1.0, 0, -1, 2**32)]
        invalid += [
            {**valid, "tags": t}
            for t in (
                ["mood/theme---happy"],
                ["genre---Rock"],
                ["genre---rock "],
                ["genre---"],
                ["genre---" + "a" * 65],
                ["genre---rock"] * 2,
                [True],
                "genre---rock",
                [f"genre---x{i}" for i in range(251)],
            )
        ]
        invalid += [{**valid, "track_id": 214}, {**valid, "target": [1]}]
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(ValueError):
                pure.infer(capsule(), {"profiles": [valid, query]})
        with self.assertRaises(ValueError):
            pure.infer(capsule(), {"profiles": [valid] * 101})
        with self.assertRaises(ValueError):
            pure.infer(capsule(), {"profiles": [valid], "human_votes": []})

    def test_model_shapes_finite_weights_fallback_and_empty_vocabulary(self) -> None:
        body = models()
        for changed in (None, float("nan"), True, 0, 1):
            bad = copy.deepcopy(body)
            bad["folds"][0]["model"]["prior"][0] = changed
            with self.assertRaises(ValueError):
                pure.validate_models(bad)
        bad = copy.deepcopy(body)
        bad["folds"][0]["model"]["theta"][0].pop()
        with self.assertRaises(ValueError):
            pure.validate_models(bad)
        bad = copy.deepcopy(body)
        bad["folds"][0]["temperature_reason"] = "inner_training_class_support_failed"
        with self.assertRaises(ValueError):
            pure.validate_models(bad)
        bad["folds"][0]["temperature"] = 1
        pure.validate_models(bad)
        empty = {"prior": [0.2] + [0.1] * 8, "vocabulary": [], "theta": [[]] * 9}
        result = pure.probabilities(empty, set(), 1)
        self.assertEqual(result["temperature_nb"], empty["prior"])
        self.assertAlmostEqual(
            pure.probabilities(empty, set(), 4)["temperature_nb"][0]
            / pure.probabilities(empty, set(), 4)["temperature_nb"][1],
            2**0.25,
        )

    def test_routing_duplicate_wrong_fold_and_conflicting_joins(self) -> None:
        row = [1, 10, 1, pure.fold(1)]
        for rows in (
            [row, row],
            [[True, 10, 1, pure.fold(1)]],
            [[1, 10, 1, (pure.fold(1) + 1) % 5]],
            [row, [1, 20, 2, pure.fold(2)]],
            [row, [2, 10, 2, pure.fold(2)]],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                pure.routing({"pairs": rows})

    def test_closed_manifest_external_pins_and_resealed_semantic_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "capsule"
            pin = publish(root)
            pure.load(root, pin)
            with self.assertRaises(ValueError):
                pure.load(root, "0" * 64)
            (root / "extra").write_text("x")
            with self.assertRaises(ValueError):
                pure.load(root, pin)
            (root / "extra").unlink()
            with (root / "models.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaises(ValueError):
                pure.load(root, pin)
            body = json.loads((root / "models.json").read_bytes())
            body["folds"][0]["model"]["prior"][0] = 0
            (root / "models.json").write_bytes(pure.encoded(body))
            pin = reseal(root)
            with self.assertRaises(ValueError):
                pure.load(root, pin)

    def test_resealed_rights_runtime_provenance_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "capsule"
            publish(root)
            original = json.loads((root / "manifest.json").read_bytes())
            for field in ("rights", "runtime", "source", "builder", "counts"):
                changed = copy.deepcopy(original)
                changed[field] = {}
                (root / "manifest.json").write_bytes(pure.encoded(changed))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    pure.load(root, pure.sha(root / "manifest.json"))

    def test_resealed_physical_binding_types_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "capsule"
            publish(root)
            original = json.loads((root / "manifest.json").read_bytes())
            expected = original["files"]["models.json"]["bytes"]
            for value in (float(expected), str(expected), True, -1):
                changed = copy.deepcopy(original)
                changed["files"]["models.json"]["bytes"] = value
                (root / "manifest.json").write_bytes(pure.encoded(changed))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    pure.load(root, pure.sha(root / "manifest.json"))

    def test_duplicate_json_keys_and_atomic_invalid_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "capsule"
            pin = publish(directory)
            query = root / "queries.json"
            query.write_text('{"profiles":[],"profiles":[]}')
            output = root / "result.json"
            with self.assertRaises(ValueError):
                pure.infer_file(directory, pin, query, pure.sha(query), output)
            self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                pure.fresh(directory / "overlap", (directory,))

    def test_pure_import_does_not_load_builder_or_training(self) -> None:
        code = """import sys

forbidden = ("opennoise.ml.jamendo_human_",
             "opennoise.ml.jamendo_genre_temperature", "opennoise.ml.jamendo_genre_capsule")
def guard(event, args):
    if event == "import" and args[0].startswith(forbidden):
        raise RuntimeError("forbidden training/source/builder import")
sys.addaudithook(guard)
from opennoise.ml import jamendo_genre_inference
if any(name.startswith(forbidden) for name in sys.modules):
    raise RuntimeError("forbidden loaded module")
"""
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)  # noqa: S603
