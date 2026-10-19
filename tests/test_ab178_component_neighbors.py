"""Fixed optional structural comparison; fixtures fit once, comparisons never refit."""

import copy
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar, override
from unittest.mock import patch

from opennoise.ml import ab178_component_neighbors as components
from opennoise.ml import ab178_crossfit as crossfit

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "data/recipes/ab178-component-neighbors/protocol.json"
PROTOCOL_PIN = "cfd44c8d03ef4222cc5dc0119cc3c64732e84d6a3b65be0f9625b3a6976941c8"
EVALUATION = ROOT / "data/recipes/ab178-crossfit/protocol.json"
EVALUATION_PIN = "4fefa8bfc2ac9ac7985b86e4a27db92443188031c3dcab2e455b9b08cb25dda6"
SOURCE_PIN = "13e21e5296989e148e0efc2f6956675d2d391326552fe4a1a3b67df56e1494cb"


class ComponentNeighborTests(unittest.TestCase):
    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    source: ClassVar[Path]
    source_pin: ClassVar[str]
    directory: ClassVar[Path]
    pin: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.source = root / "evaluation"
        cls.source_pin = crossfit.build(
            ROOT / "data/examples/native-sonic", SOURCE_PIN, EVALUATION, EVALUATION_PIN, cls.source
        )
        cls.directory = root / "comparison"
        with patch.object(
            crossfit.routing.engine, "fit_frame", side_effect=AssertionError("comparison refit")
        ):
            cls.pin = components.build(
                cls.source, cls.source_pin, PROTOCOL, PROTOCOL_PIN, cls.directory
            )

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_actual_baseline_and_all_abstentions_unchanged_with_reported_losses(self) -> None:
        result = components.verify(self.source, self.source_pin, self.directory, self.pin)
        original = crossfit.verify(self.source, self.source_pin)
        self.assertEqual(
            [
                {k: v for k, v in r.items() if k not in {"component_neighbors", "comparison"}}
                for r in result["recordings"]
            ],
            original["recordings"],
        )
        self.assertEqual(len(result["recordings"]), 100)
        self.assertEqual(len(result["cells"]), 18)
        summary = result["summary"]
        self.assertEqual(summary["retrieval_attempted_queries"], 11)
        self.assertEqual(summary["queries_gaining_components"], 6)
        self.assertEqual(summary["queries_losing_artists"], 4)
        self.assertEqual(
            [summary["policies"][p]["recording_edges"] for p in components.POLICIES], [55, 38]
        )
        self.assertEqual(
            [summary["policies"][p]["returned_component_count_sum"] for p in components.POLICIES],
            [32, 38],
        )
        self.assertEqual(
            [summary["policies"][p]["exact_artist_count_sum"] for p in components.POLICIES],
            [42, 42],
        )
        self.assertEqual(
            [len(summary["policies"][p]["exact_artist_union_mbids"]) for p in components.POLICIES],
            [9, 11],
        )
        for row in result["recordings"]:
            if row["outcome"] != "emitted":
                self.assertEqual(row["component_neighbors"], [])
                self.assertFalse(row["comparison"]["retrieval_attempted"])
            selected = row["comparison"]["nearest_component"]
            self.assertEqual(selected["recording_edges"], len(selected["component_ids"]))
        for cell, baseline in zip(result["cells"], original["cells"], strict=True):
            self.assertEqual(
                cell["policies"]["nearest_recording"],
                {k: baseline[k] for k in ("recordings", "artists", "counts")},
            )

    def test_exact_selected_recording_credits_and_frame_proof(self) -> None:
        result = components.verify(self.source, self.source_pin, self.directory, self.pin)
        for cell in result["cells"]:
            fold = cell["heldout_fold"]
            roster = {
                r["recording_mbid"]: r
                for r in components.portable.read(self.source / f"fold-{fold}/intake.json")["rows"]
            }
            for artist in cell["policies"]["nearest_component"]["artists"]:
                for neighbor in artist["neighbor_evidence"]["heldout"]:
                    for observation in neighbor["observations"]:
                        candidate = roster[observation["candidate_recording_mbid"]]
                        self.assertIn(neighbor["artist_mbid"], candidate["credited_artist_mbids"])
                        self.assertEqual(observation["frame_sha256"], cell["frame_sha256"])
                        self.assertEqual(observation["heldout_fold"], fold)
                        self.assertEqual(observation["contract_sha256"], cell["contract_sha256"])

    def test_ranking_ties_exclusions_representatives_and_no_component_credit_inheritance(
        self,
    ) -> None:
        metadata = {
            "query": {"component_id": "self"},
            "self-credit": {"component_id": "self"},
            "a": {"component_id": "group"},
            "b": {"component_id": "group"},
            "c": {"component_id": "other"},
        }
        query = {"recording_mbid": "query", "vector": [0.0], "fit_member": False}
        candidates = [
            {"recording_mbid": i, "vector": [1.0]} for i in ("query", "self-credit", "b", "c", "a")
        ]
        ranked = components.ranked_candidates(query, candidates, metadata)
        self.assertEqual([r["recording_mbid"] for r in ranked], ["a", "b", "c"])
        selected = components.representatives(ranked, metadata)
        self.assertEqual([r["recording_mbid"] for r in selected], ["a", "c"])
        roster = {i: {"credited_artist_mbids": [i + "-artist"]} for i in metadata}
        self.assertEqual(
            components.coverage(selected, metadata, roster)["artist_mbids"],
            ["a-artist", "c-artist"],
        )
        self.assertNotIn(
            "b-artist", components.coverage(selected, metadata, roster)["artist_mbids"]
        )
        with self.assertRaises(ValueError):
            components.ranked_candidates(
                query, [{"recording_mbid": "a", "vector": [math.nan]}], metadata
            )

    def test_baseline_disagreement_aborts_before_representative_selection(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(components, "ranked_candidates", return_value=[]),
            patch.object(components, "representatives") as select,
        ):
            output = Path(temporary) / "output"
            with self.assertRaisesRegex(ValueError, "nearest-five"):
                components.build(self.source, self.source_pin, PROTOCOL, PROTOCOL_PIN, output)
            select.assert_not_called()
            self.assertFalse(output.exists())

    def test_relocated_no_source_no_refit_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(self.source, root / "evaluation")
            shutil.copytree(self.directory, root / "comparison")
            with (
                patch.object(
                    crossfit.routing.engine, "fit_frame", side_effect=AssertionError("refit")
                ),
                patch.object(
                    components.portable.bank, "project", side_effect=AssertionError("source")
                ),
            ):
                result = components.verify(
                    root / "evaluation", self.source_pin, root / "comparison", self.pin
                )
            self.assertEqual(result["summary"]["queries"], 100)

    def test_resealed_tamper_wrong_pins_protocol_and_fresh_output_contract(self) -> None:
        for change in ("extra", "runtime", "result"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "copy"
                shutil.copytree(self.directory, target)
                manifest = components.portable.read(target / "manifest.json")
                if change == "extra":
                    crossfit.routing.write(target / "extra.json", {})
                elif change == "runtime":
                    manifest["runtime"]["comparison_sha256"] = "0" * 64
                else:
                    result = components.portable.read(target / "comparison.json")
                    result["recordings"][0]["outcome"] = "emitted"
                    crossfit.routing.write(target / "comparison.json", result)
                    manifest["files"]["comparison.json"] = components.portable.bank.digest(
                        target / "comparison.json"
                    )
                crossfit.routing.write(target / "manifest.json", manifest)
                with self.assertRaises(ValueError):
                    components.verify(
                        self.source,
                        self.source_pin,
                        target,
                        components.portable.bank.digest(target / "manifest.json"),
                    )
        for source_pin, output_pin in (("0" * 64, self.pin), (self.source_pin, "0" * 64)):
            with self.assertRaises(ValueError):
                components.verify(self.source, source_pin, self.directory, output_pin)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = copy.deepcopy(components.portable.read(PROTOCOL))
            invalid["refitting"] = True
            crossfit.routing.write(root / "protocol.json", invalid)
            with self.assertRaises(ValueError):
                components.build(
                    self.source,
                    self.source_pin,
                    root / "protocol.json",
                    components.portable.bank.digest(root / "protocol.json"),
                    root / "output",
                )
            self.assertFalse((root / "output").exists())
        with self.assertRaises(ValueError):
            components.build(self.source, self.source_pin, PROTOCOL, PROTOCOL_PIN, self.directory)
