"""Exhaustive retained-source own-fold routing; no relevance or accuracy evaluation."""

import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar, override
from unittest.mock import patch

from opennoise.ml import ab178_crossfit as crossfit
from opennoise.ml import ab178_version_routing as routing

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "data/recipes/ab178-crossfit/protocol.json"
PROTOCOL_PIN = "4fefa8bfc2ac9ac7985b86e4a27db92443188031c3dcab2e455b9b08cb25dda6"
SOURCE_PIN = "13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb"


class CrossfitTests(unittest.TestCase):
    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    directory: ClassVar[Path]
    pin: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name) / "evaluation"
        cls.pin = crossfit.build(
            ROOT / "data/examples/native-sonic", SOURCE_PIN, PROTOCOL, PROTOCOL_PIN, cls.directory
        )

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_actual_exhaustive_own_fold_query_and_candidate_isolation(self) -> None:
        result = crossfit.verify(self.directory, self.pin)
        self.assertEqual(result["counts"]["nominated_recordings"], 100)
        self.assertEqual(result["counts"]["compatible_recordings"], 34)
        self.assertEqual(result["counts"]["cells"], 18)
        self.assertEqual(result["counts"]["fitted_cells"], 7)
        self.assertEqual(result["counts"]["emitted_by_fold"], {"0": 3, "1": 1, "2": 7})
        self.assertEqual(len({r["recording_mbid"] for r in result["recordings"]}), 100)
        meta = {
            r["recording_mbid"]: r
            for r in routing.portable.read(self.directory / "fold-0/registry.json")["ledger"]
        }
        for cell in result["cells"]:
            fold = cell["heldout_fold"]
            ids = next(
                g["recording_mbids"]
                for g in routing.portable.read(self.directory / f"plans/fold-{fold}.json")[
                    "contracts"
                ]
                if g["contract_sha256"] == cell["contract_sha256"]
            )
            for row in cell["inference_rows"]:
                self.assertFalse(row["fit_member"])
                self.assertEqual(row["fold"], fold)
                self.assertIn(row["recording_mbid"], ids)
                for neighbor in row["neighbors"]:
                    candidate = neighbor["recording_mbid"]
                    self.assertIn(candidate, ids)
                    self.assertNotEqual(meta[candidate]["fold"], fold)
                    self.assertNotEqual(meta[candidate]["component_id"], row["component_id"])
                    self.assertEqual(neighbor["frame_sha256"], cell["frame_sha256"])
            self.assertEqual(cell["counts"]["emitted_by_query_role"]["fit_member"], 0)
            for artist in cell["artists"]:
                self.assertEqual(artist["frame_sha256"], cell["frame_sha256"])
                for neighbor in artist["neighbor_evidence"]["heldout"]:
                    for observation in neighbor["observations"]:
                        self.assertEqual(observation["heldout_fold"], fold)
                        self.assertEqual(observation["contract_sha256"], cell["contract_sha256"])
        self.assertTrue(all(not r["fit_member"] for r in result["recordings"]))

    def test_missing_nonfit_and_zero_query_cells_are_retained(self) -> None:
        result = crossfit.verify(self.directory, self.pin)
        self.assertTrue(any(c["query_count"] == 0 for c in result["cells"]))
        self.assertEqual(sum(c["support"]["state"] != "fitted" for c in result["cells"]), 11)
        self.assertEqual(sum(c["query_count"] for c in result["cells"]), 34)
        self.assertEqual(result["counts"]["recording_outcomes"]["missing_http_404"], 45)
        self.assertEqual(result["counts"]["recording_outcomes"]["dirty_extractor"], 21)
        for cell in result["cells"]:
            if cell["support"]["state"] != "fitted":
                self.assertIsNone(cell["bundle_sha256"])
                self.assertIsNone(cell["frame_sha256"])
                self.assertTrue(all(not r["neighbors"] for r in cell["recordings"]))

    def test_relocated_replay_needs_no_sources_or_refit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            relocated = Path(temporary) / "copy"
            shutil.copytree(self.directory, relocated)
            with (
                patch.object(routing.engine, "fit_frame", side_effect=AssertionError("refit")),
                patch.object(
                    routing.portable.bank, "project", side_effect=AssertionError("source")
                ),
            ):
                self.assertEqual(
                    crossfit.verify(relocated, self.pin), crossfit.verify(self.directory, self.pin)
                )

    def test_fold_zero_underlying_outputs_remain_unchanged(self) -> None:
        nested = routing.portable.read(self.directory / "index.json")["runs"][0]
        baseline = routing.verify(self.directory / "fold-0", nested["manifest_sha256"])
        result = crossfit.verify(self.directory, self.pin)
        for group, cell in zip(baseline["groups"], result["cells"][:6], strict=True):
            expected = [r for r in group["recordings"] if r["fold"] == 0]
            actual = [
                {
                    k: v
                    for k, v in r.items()
                    if k not in {"contract_sha256", "heldout_fold", "bundle_sha256", "frame_sha256"}
                }
                for r in cell["recordings"]
            ]
            for row in actual:
                row["neighbors"] = [
                    {k: n[k] for k in ("recording_mbid", "distance")} for n in row["neighbors"]
                ]
            self.assertEqual(actual, expected)

    def test_resealed_inventory_runtime_route_and_result_tampering(self) -> None:
        for change in ("extra", "runtime", "route", "result"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "copy"
                shutil.copytree(self.directory, target)
                manifest = routing.portable.read(target / "manifest.json")
                if change == "extra":
                    routing.write(target / "extra/manifest.json", {})
                elif change == "runtime":
                    manifest["runtime"]["crossfit_sha256"] = "0" * 64
                elif change == "route":
                    index = routing.portable.read(target / "index.json")
                    index["runs"][0]["manifest_sha256"] = index["runs"][1]["manifest_sha256"]
                    routing.write(target / "index.json", index)
                else:
                    result = routing.portable.read(target / "evidence.json")
                    result["recordings"][0]["fit_member"] = True
                    routing.write(target / "evidence.json", result)
                manifest["files"] = crossfit.inventory(target)
                routing.write(target / "manifest.json", manifest)
                with self.assertRaises(ValueError):
                    crossfit.verify(target, routing.portable.bank.digest(target / "manifest.json"))
        with self.assertRaises(ValueError):
            crossfit.verify(self.directory, "0" * 64)

    def test_invalid_protocol_and_inner_failure_abort_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = copy.deepcopy(routing.portable.read(PROTOCOL))
            invalid["fold_plans"][1]["fold"] = 0
            routing.write(root / "protocol.json", invalid)
            with self.assertRaises(ValueError):
                crossfit.build(
                    ROOT / "data/examples/native-sonic",
                    SOURCE_PIN,
                    root / "protocol.json",
                    routing.portable.bank.digest(root / "protocol.json"),
                    root / "output",
                )
            self.assertFalse((root / "output").exists())
            with (
                patch.object(routing, "build", side_effect=ValueError("custody failure")),
                self.assertRaisesRegex(ValueError, "custody failure"),
            ):
                crossfit.build(
                    ROOT / "data/examples/native-sonic",
                    SOURCE_PIN,
                    PROTOCOL,
                    PROTOCOL_PIN,
                    root / "output",
                )
            self.assertFalse((root / "output").exists())
            self.assertEqual(list(root.glob(".ab178-crossfit-*")), [])
        with self.assertRaises(ValueError):
            crossfit.build(
                ROOT / "data/examples/native-sonic",
                SOURCE_PIN,
                PROTOCOL,
                PROTOCOL_PIN,
                self.directory,
            )
