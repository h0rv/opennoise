"""Exact version routing over the retained native CC0 capture; no quality evaluation."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar, override
from unittest.mock import patch

from opennoise.ml import ab178_portable as portable
from opennoise.ml import ab178_version_routing as routing
from opennoise.ml import recording_evaluation as engine

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "data/recipes/ab178-version-routing/protocol.json"
PLAN_PIN = "e918bd2dc23987ef492342aaa165d2de15a23fa2d06bf3243fd18bdf2747b792"
SOURCE_PIN = "13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb"


class VersionRoutingTests(unittest.TestCase):
    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    directory: ClassVar[Path]
    pin: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name) / "registry"
        cls.pin = routing.build(
            ROOT / "data/examples/native-sonic", SOURCE_PIN, PLAN, PLAN_PIN, cls.directory
        )

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_retained_end_to_end_and_offline_no_refit(self) -> None:
        with (
            patch.object(engine, "fit_frame", side_effect=AssertionError("offline refit")),
            patch.object(portable.bank, "project", side_effect=AssertionError("source access")),
        ):
            result = routing.verify(self.directory, self.pin)
        self.assertEqual(
            result["counts"],
            {
                "nominated_recordings": 100,
                "routed_recordings": 34,
                "unrouted_outcomes": {"dirty_extractor": 21, "missing_http_404": 45},
            },
        )
        self.assertEqual(len(result["groups"]), 6)
        self.assertEqual(
            [g["support"]["training_recordings"] for g in result["groups"]], [5, 2, 4, 2, 1, 0]
        )
        self.assertEqual(
            [g["counts"]["emitted_by_query_role"]["heldout"] for g in result["groups"]],
            [3, 0, 0, 0, 0, 0],
        )
        ledger = {
            r["recording_mbid"]: r
            for r in portable.read(self.directory / "registry.json")["ledger"]
        }
        for group in result["groups"]:
            ids = {r["recording_mbid"] for r in group["inference_rows"]}
            for row in group["inference_rows"]:
                for neighbor in row["neighbors"]:
                    self.assertIn(neighbor["recording_mbid"], ids)
                    self.assertNotEqual(
                        ledger[row["recording_mbid"]]["component_id"],
                        ledger[neighbor["recording_mbid"]]["component_id"],
                    )
                    self.assertNotEqual(ledger[neighbor["recording_mbid"]]["fold"], 0)

    def test_closed_inventory_pin_runtime_and_route_tampering(self) -> None:
        for change in ("nested_manifest", "runtime", "cohort", "unfitted", "cross_contract"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "copy"
                shutil.copytree(self.directory, target)
                manifest = portable.read(target / "manifest.json")
                if change == "nested_manifest":
                    routing.write(target / "extra/manifest.json", {})
                elif change == "runtime":
                    manifest["runtime"]["python"] = "0.0.0"
                else:
                    registry = portable.read(target / "registry.json")
                    if change == "cohort":
                        registry["groups"][0]["contract_sha256"] = "0" * 64
                    elif change == "unfitted":
                        registry["groups"][1]["support"]["state"] = "fitted"
                    else:
                        first, second = registry["groups"][0], registry["groups"][2]
                        first["bundle_sha256"] = second["bundle_sha256"]
                    routing.write(target / "registry.json", registry)
                manifest["files"] = routing.inventory(target)
                routing.write(target / "manifest.json", manifest)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    routing.verify(target, portable.bank.digest(target / "manifest.json"))
        with self.assertRaises(ValueError):
            routing.verify(self.directory, "0" * 64)

    def test_invalid_source_and_plan_fail_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with self.assertRaises(ValueError):
                routing.build(ROOT / "data/examples/native-sonic", "0" * 64, PLAN, PLAN_PIN, output)
            self.assertFalse(output.exists())
            bad = portable.read(PLAN)
            bad["contracts"][1]["recording_mbids"] = bad["contracts"][0]["recording_mbids"]
            path = Path(temporary) / "plan.json"
            routing.write(path, bad)
            with self.assertRaises(ValueError):
                routing.build(
                    ROOT / "data/examples/native-sonic",
                    SOURCE_PIN,
                    path,
                    portable.bank.digest(path),
                    output,
                )
            self.assertFalse(output.exists())
            with (
                patch.object(portable, "export_bundle", side_effect=ValueError("custody failure")),
                self.assertRaisesRegex(ValueError, "custody failure"),
            ):
                routing.build(
                    ROOT / "data/examples/native-sonic", SOURCE_PIN, PLAN, PLAN_PIN, output
                )
            self.assertFalse(output.exists())

    def test_structural_insufficiency_and_contract_isolation(self) -> None:
        intake = portable.read(self.directory / "intake.json")["rows"]
        frozen_plan = routing.plan(PLAN, PLAN_PIN)
        rows = routing.contract_rows(intake, frozen_plan["contracts"][0])
        original = copy.deepcopy(rows)
        for row in rows:
            if row["join_state"] == "joined":
                row["values"] = [1.0] * len(portable.bank.columns())
        self.assertEqual(routing.support(rows, 0)["state"], "insufficient_training_support")
        rows = original
        for row in rows:
            if row["join_state"] == "joined":
                row["values"] = [None] * len(portable.bank.columns())
        self.assertEqual(routing.support(rows, 0)["state"], "insufficient_training_support")
        self.assertEqual(routing.topology(intake), routing.topology(rows))
        self.assertEqual(
            sum(
                r["join_state"] == "joined"
                for r in routing.contract_rows(intake, frozen_plan["contracts"][2])
            ),
            12,
        )

    def test_unplanned_contracts_abstain_without_fallback_or_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subset = portable.read(PLAN)
            subset["contracts"] = [subset["contracts"][1]]
            routing.write(root / "plan.json", subset)
            with patch.object(engine, "fit_frame", side_effect=AssertionError("unexpected fit")):
                pin = routing.build(
                    ROOT / "data/examples/native-sonic",
                    SOURCE_PIN,
                    root / "plan.json",
                    portable.bank.digest(root / "plan.json"),
                    root / "registry",
                )
                result = routing.verify(root / "registry", pin)
            self.assertEqual(result["counts"]["routed_recordings"], 7)
            self.assertEqual(result["counts"]["unrouted_outcomes"]["unplanned_contract"], 27)
            self.assertTrue(all(not r["neighbors"] for r in result["unrouted"]))

    def test_evidence_replay_is_byte_identical(self) -> None:
        expected = json.loads((self.directory / "evidence.json").read_bytes())
        self.assertEqual(routing.verify(self.directory, self.pin), expected)
        with self.assertRaises(ValueError):
            routing.build(
                ROOT / "data/examples/native-sonic", SOURCE_PIN, PLAN, PLAN_PIN, self.directory
            )
