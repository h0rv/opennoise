"""Synthetic portable inference contracts; no retained-data fitting or export."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

import numpy as np

from opennoise.ml import fma_encoder_bundle as portable
from opennoise.ml.fma_encoder_export import fresh_destination, import_queries
from opennoise.ml.fma_fixed_nonlinear import FixedEncoder, transform


class PortableEncoderTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        active = np.zeros(518, dtype=bool)
        active[:2] = True
        self.model = FixedEncoder(
            np.zeros(518),
            np.ones(518),
            active,
            np.zeros((2, 0)),
            np.zeros(0),
            np.asarray(0.0),
            np.zeros(2),
            np.ones(2, dtype=bool),
            np.zeros(2),
            np.eye(2),
            np.ones(2),
            np.eye(2),
        )
        values = np.zeros((3, 518), dtype=np.float32)
        values[:, :2] = [[1, 0], [1, 0], [0, 1]]
        vectors, _ = transform(self.model, values)
        np.savez(self.bundle / "model.npz", **asdict(self.model))
        np.savez(
            self.bundle / "candidates.npz",
            ids=np.array([2, 3, 4]),
            components=np.array([10, 20, 30]),
            features=values,
            vectors=vectors,
            labels=np.array([7, 9]),
            targets=np.array([[1, 0], [0, 1], [1, 0]], dtype=bool),
        )
        np.savez(
            self.bundle / "roster.npz",
            ids=np.array([2, 3, 4, 5]),
            components=np.array([10, 20, 30, 40]),
            artist_known=np.ones(4, dtype=bool),
            outer_fold=np.array([0, 0, 0, 1]),
            fit_member=np.array([1, 1, 1, 0], dtype=bool),
        )
        self.metadata = {
            "revision": portable.BUNDLE_REVISION,
            "namespace": "FMA/native-track-id",
            "arm": "linear518",
            "fold": 0,
            "columns": portable.schema("linear518"),
            "versions": portable.versions(),
            "runtime_code": portable.runtime_code(),
            "max_standardized_offset": 12,
            "musical_relevance_established": False,
            "promoted": False,
            "bank_receipt_sha256": "a" * 64,
            "native_observed_sha256": "d" * 64,
            "license": "CC0 synthetic fixture",
            "attribution": "Synthetic test",
        }
        self.pin = portable.write_manifest(self.bundle, self.metadata, portable.BUNDLE_BYTES)

    def external(self, rows: list[dict[str, Any]], name: str = "queries") -> tuple[Path, str]:
        source = self.root / (name + ".json")
        source.write_bytes(
            portable.encoded(
                {
                    "revision": "fma-compatible-external-rows-v1",
                    "namespace": "synthetic/example",
                    "columns": portable.schema("linear518"),
                    "extractor": "synthetic fixture, not audio",
                    "source_manifest_sha256": "b" * 64,
                    "license": "CC0 synthetic fixture",
                    "attribution": "Generated test data",
                    "rows": rows,
                }
            )
        )
        output = self.root / name
        pin = import_queries(self.bundle, self.pin, source, portable.sha(source), output)
        return output, pin

    def row(self, identity: int, component: int | None, value: float = 1.0) -> dict[str, Any]:
        return {
            "id": identity,
            "features": [value, *([0.0] * 517)],
            "fma_component_id": component,
            "identity_evidence_sha256": "c" * 64 if component is not None else None,
        }

    def test_external_namespace_collision_and_unverified_identity(self) -> None:
        queries, pin = self.external([self.row(2, 30), self.row(8, None)])
        results = portable.infer(self.bundle, self.pin, queries, pin)
        self.assertEqual(results[0]["neighbor_ids"], [2, 3])
        self.assertEqual(results[0]["ranked_source_genre_ids"], [7, 9])
        self.assertEqual(results[0]["identity_status"], "caller_declared_component")
        self.assertIsNone(results[0]["model_fit_member"])
        self.assertEqual(results[1]["vector"], [1.0, 0.0])
        self.assertEqual(results[1]["neighbor_reason"], "neighbor_identity_unverified")
        self.assertIsNone(results[1]["embedding_reason"])
        self.assertEqual(results[1]["neighbor_ids"], [])

    def test_explicit_unverified_retrieval_does_not_invent_identity(self) -> None:
        queries, pin = self.external([self.row(2, None)])
        result = portable.infer(
            self.bundle, self.pin, queries, pin, allow_unverified_neighbors=True
        )[0]
        self.assertEqual(result["neighbor_ids"], [2, 3, 4])
        self.assertEqual(result["identity_status"], "unverified")
        self.assertFalse(result["component_exclusion_verified"])
        self.assertIsNone(result["original_outer_fold"])
        self.assertIsNone(result["model_fit_member"])
        self.assertTrue(result["provenance"]["allow_unverified_neighbors"])
        default = portable.infer(self.bundle, self.pin, queries, pin)[0]
        self.assertNotEqual(portable.encoded(result), portable.encoded(default))
        self.assertEqual(default["neighbor_ids"], [])

    def test_native_self_component_and_fit_role(self) -> None:
        queries = self.root / "native"
        queries.mkdir()
        values = np.zeros((2, 518), dtype=np.float32)
        values[:, 0] = 1
        np.savez(
            queries / "queries.npz",
            ids=np.array([2, 5]),
            features=values,
            feature_present=np.ones(2, dtype=bool),
        )
        pin = portable.write_manifest(
            queries,
            {
                "revision": portable.QUERY_REVISION,
                "mode": "native-bank",
                "namespace": self.metadata["namespace"],
                "columns": self.metadata["columns"],
                "bank_receipt_sha256": "a" * 64,
                "bundle_sha256": self.pin,
                "rows": 2,
                "query_labels_consumed": False,
            },
            portable.QUERY_BYTES,
        )
        results = portable.infer(self.bundle, self.pin, queries, pin)
        self.assertEqual(results[0]["neighbor_ids"], [3, 4])
        self.assertTrue(results[0]["model_fit_member"])
        self.assertFalse(results[1]["model_fit_member"])
        self.assertEqual(results[1]["original_outer_fold"], 1)
        self.assertEqual(results[1]["neighbor_ids"], [2, 3, 4])

    def test_missing_unsupported_zero_and_boundary(self) -> None:
        missing = self.row(1, 30)
        missing["features"] = [None] * 518
        queries, pin = self.external(
            [missing, self.row(2, 30, 13.0), self.row(3, 30, 0.0), self.row(4, 30, 12.0)]
        )
        results = portable.infer(self.bundle, self.pin, queries, pin)
        self.assertEqual(
            [r["embedding_reason"] for r in results],
            ["nonfinite_descriptors", "outside_training_support", "zero_encoded_norm", None],
        )
        self.assertTrue(all(not row["neighbor_ids"] for row in results[:3]))

    def test_external_provenance_rechecked_at_consumption(self) -> None:
        queries, _pin = self.external([self.row(2, 30)])
        manifest = queries / "manifest.json"
        original = json.loads(manifest.read_text())
        mutations = [
            lambda m: m.pop("source_file_sha256"),
            lambda m: m.update(identity_evidence_sha256=[None]),
            lambda m: m.update(identity_claims_independently_verified=True),
        ]
        for mutate in mutations:
            body = original.copy()
            mutate(body)
            manifest.write_bytes(portable.encoded(body))
            with self.assertRaises(ValueError):
                portable.infer(self.bundle, self.pin, queries, portable.sha(manifest))

    def test_duplicate_id_unknown_component_and_schema_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.external([self.row(1, 30), self.row(1, 30)])
        with self.assertRaisesRegex(ValueError, "component"):
            self.external([self.row(1, 999)], "badcomponent")
        bad = self.row(1, None)
        bad["features"] = [0.0] * 178
        with self.assertRaisesRegex(ValueError, "features"):
            self.external([bad], "ab178")

    def test_native_source_inference_and_provenance_rejection(self) -> None:
        queries = self.root / "source-queries"
        queries.mkdir()
        values = np.zeros((1, 518), dtype=np.float32)
        values[0, 0] = 1
        np.savez(
            queries / "queries.npz",
            ids=np.array([2]),
            features=values,
            feature_present=np.ones(1, dtype=bool),
        )
        metadata = {
            "revision": portable.QUERY_REVISION,
            "mode": "native-source",
            "namespace": self.metadata["namespace"],
            "columns": self.metadata["columns"],
            "bundle_sha256": self.pin,
            "rows": 1,
            "query_labels_consumed": False,
            "native_observed_sha256": "d" * 64,
            "source_receipt_sha256": "e" * 64,
            "native_uncompressed_bytes": 951117185,
            "native_zip_crc32_verified": "e8eb7a19",
            "native_rows": 106574,
            "audio_downloaded": False,
            "full_archive_sha1_verified": False,
            "license": self.metadata["license"],
            "attribution": self.metadata["attribution"],
        }
        pin = portable.write_manifest(queries, metadata, portable.QUERY_BYTES)
        result = portable.infer(self.bundle, self.pin, queries, pin)[0]
        self.assertEqual(result["neighbor_ids"], [3, 4])
        self.assertTrue(result["model_fit_member"])
        for key, value in (
            ("native_observed_sha256", "f" * 64),
            ("source_receipt_sha256", ""),
            ("native_zip_crc32_verified", "wrong"),
            ("bank_receipt_sha256", "a" * 64),
        ):
            (queries / "manifest.json").unlink()
            pin = portable.write_manifest(queries, {**metadata, key: value}, portable.QUERY_BYTES)
            with self.assertRaisesRegex(ValueError, "provenance"):
                portable.infer(self.bundle, self.pin, queries, pin)

    def test_relocation_has_no_original_path_reads_and_tamper_fails(self) -> None:
        queries, pin = self.external([self.row(2, 30)])
        expected = portable.infer(self.bundle, self.pin, queries, pin)
        moved = self.root / "relocated"
        moved.mkdir()
        shutil.move(str(self.bundle), moved / "bundle")
        shutil.move(str(queries), moved / "queries")
        original_open = Path.open

        def guarded(path: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - Path.open wrapper.
            if path.is_relative_to(self.bundle) or path.is_relative_to(queries):
                raise AssertionError("Inference read an original scratch path")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            actual = portable.infer(moved / "bundle", self.pin, moved / "queries", pin)
        self.assertEqual(actual, expected)
        with (moved / "queries/queries.npz").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            portable.infer(moved / "bundle", self.pin, moved / "queries", pin)

    def test_cli_inference_replay_and_policy_pin(self) -> None:
        queries, pin = self.external([self.row(2, None)])
        repo = Path(__file__).resolve().parents[1]
        output = self.root / "result.json"
        base = [sys.executable, str(repo / "scripts/run_fma_portable_encoder.py")]
        common = [
            "--bundle",
            str(self.bundle),
            "--bundle-sha256",
            self.pin,
            "--queries",
            str(queries),
            "--query-sha256",
            pin,
        ]
        environment = {**os.environ, "PYTHONPATH": str(repo / "src")}
        done = subprocess.run(  # noqa: S603 - fixed local CLI and synthetic paths.
            [*base, "infer", *common, "--output", str(output), "--allow-unverified-neighbors"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        result_pin = json.loads(done.stdout)["sha256"]
        replay = [*base, "replay", *common, "--result", str(output), "--result-sha256", result_pin]
        wrong = subprocess.run(  # noqa: S603 - fixed local CLI and synthetic paths.
            replay, env=environment, capture_output=True, text=True, timeout=15, check=False
        )
        self.assertNotEqual(wrong.returncode, 0)
        correct = subprocess.run(  # noqa: S603 - fixed local CLI and synthetic paths.
            [*replay, "--allow-unverified-neighbors"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(correct.returncode, 0, correct.stderr)

    def test_candidate_vector_tamper_cannot_pass_rehashed_manifest(self) -> None:
        path = self.bundle / "candidates.npz"
        data = portable.arrays(path, portable.BUNDLE_BYTES)
        data["vectors"][0, 0] = -1
        np.savez(
            path,
            ids=data["ids"],
            components=data["components"],
            features=data["features"],
            vectors=data["vectors"],
            labels=data["labels"],
            targets=data["targets"],
        )
        manifest = self.bundle / "manifest.json"
        body = json.loads(manifest.read_text())
        body["files"][path.name] = {"sha256": portable.sha(path), "bytes": path.stat().st_size}
        manifest.write_bytes(portable.encoded(body))
        with self.assertRaisesRegex(ValueError, "vectors"):
            portable.load_bundle(self.bundle, portable.sha(manifest))

    def test_forged_npy_shape_rejected_before_numpy_load(self) -> None:
        payload = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            payload, {"descr": "<f8", "fortran_order": False, "shape": (10**12,)}
        )
        path = self.root / "forged.npz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("values.npy", payload.getvalue())
        with (
            patch.object(np, "load", side_effect=AssertionError("must not allocate")),
            self.assertRaisesRegex(ValueError, "shape"),
        ):
            portable.arrays(path, portable.BUNDLE_BYTES)

    def test_fresh_destination_and_pending_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            fresh_destination(self.bundle / "new", (self.bundle,))
        link = self.root / "link"
        link.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "regular"):
            fresh_destination(link / "new", (self.bundle,))
        (self.bundle / "manifest.json").rename(self.bundle / "manifest.pending")
        with self.assertRaisesRegex(ValueError, "inventory"):
            portable.load_bundle(self.bundle, self.pin)
        portable.load_bundle(self.bundle, self.pin, pending=True)


if __name__ == "__main__":
    unittest.main()
