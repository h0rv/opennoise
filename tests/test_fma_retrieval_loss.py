"""Synthetic loss attribution and frozen artifact custody; no corpus outcomes."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import zstandard

from opennoise.ml import fma_retrieval_loss as loss
from opennoise.ml import fma_retrieval_loss_custody as custody


def fixture(root: Path) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    """Two held-out components and two eligible, component-distinct candidates."""
    roster: dict[int, dict[str, Any]] = {
        1: {"component_id": 1, "inner_fold": 1, "targets": {1}},
        2: {"component_id": 2, "inner_fold": 1, "targets": set()},
        3: {"component_id": 3, "inner_fold": 0, "targets": {1, 3}},
        4: {"component_id": 4, "inner_fold": 0, "targets": set()},
    }
    candidates = {
        "nominated_ids": [1, 2],
        "joint_ids": [1, 2],
        "intrinsic_descriptor_ids": [1, 2],
        "intrinsic_raw_ids": [1, 2],
        "intrinsic_embedding_ids": [1, 2],
        "candidate_label_union": [1],
    }
    (root / "candidates.json").write_bytes(custody.encoded(candidates))
    records = []
    values = np.zeros((2, 5, 14))
    for q, track in enumerate((3, 4)):
        labeled = bool(roster[track]["targets"])
        arms: dict[str, Any] = {}
        for index, arm in enumerate(loss.ARMS):
            missing = arm == "ridge8_neighbors"
            arms[arm] = {
                "ranking": [] if missing else [1],
                "reason": "missing_descriptors" if missing else None,
                "descriptor_available": not missing,
            }
            neighbors = index == 0
            if index < loss.NEIGHBOR_ARM_COUNT:
                arms[arm].update(
                    neighbor_ids=[1, 2] if neighbors else [],
                    cosine_distances=[0.1, 0.2] if neighbors else [],
                )
            values[q, index, [0, 1, 2, 3, 6, 7, 10, 11, 12]] = [
                1,
                labeled,
                2 * labeled,
                labeled and not missing,
                not missing,
                2 * labeled * (not missing),
                labeled and not missing,
                not missing,
                neighbors,
            ]
        records.append(
            {
                "track_id": track,
                "component_id": track,
                "inner_fold": 0,
                "targets": sorted(roster[track]["targets"]),
                "arms": arms,
            }
        )
    np.savez(root / "statistics.npz", components=np.array([3, 4]), values=values)
    receipt = {
        "columns": loss.STAT_COLUMNS,
        "heldout_queries": 2,
        "components": 2,
        "arms": loss.ARMS,
        "abstentions": {
            arm: {"missing_descriptors": 2} if arm == "ridge8_neighbors" else {}
            for arm in loss.ARMS
        },
    }
    (root / "receipt.json").write_bytes(custody.encoded(receipt))
    write_records(root, records)
    return roster, records


def write_records(root: Path, records: list[dict[str, Any]]) -> None:
    """Write synthetic saved predictions without invoking a producer."""
    with zstandard.open(root / "ranks.jsonl.zst", "wt") as stream:
        for row in records:
            stream.write(json.dumps(row) + "\n")


class RetrievalLossTests(unittest.TestCase):
    def test_ordered_buckets_conserve_and_abstention_precedes_other_losses(self) -> None:
        self.assertEqual(
            loss.loss_buckets({1, 2, 3, 4}, {2, 3, 4}, {3, 4}, [4, *range(10, 19), 3], None),
            [0, 1, 1, 1, 1],
        )
        self.assertEqual(
            loss.loss_buckets({1, 2}, set(), set(), [], "missing_descriptors"), [2, 0, 0, 0, 0]
        )
        self.assertEqual(loss.loss_buckets(set(), set(), set(), [], None), [0] * 5)

    def test_vote_ties_and_unlabeled_neighbors(self) -> None:
        self.assertEqual(loss.vote_ranking([1, 2, 3], {1: {3, 2}, 2: {1}, 3: {3}}), [3, 1, 2])
        roster = {1: {"component_id": 1, "inner_fold": 1, "targets": set()}}
        prediction = {
            "ranking": [],
            "reason": None,
            "descriptor_available": True,
            "neighbor_ids": [1],
            "cosine_distances": [0.5],
        }
        self.assertEqual(
            loss.validate_prediction(
                prediction,
                loss.ARMS[0],
                {"component_id": 9, "inner_fold": 0},
                {1},
                {1: set()},
                roster,
                {3},
                [],
            ),
            ([], set()),
        )
        self.assertEqual(loss.loss_buckets({3}, {3}, set(), [], None), [0, 0, 1, 0, 0])

    def test_exact_synthetic_stream_and_equal_component_denominators(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster, _ = fixture(root)
            components = loss.analyze_fold(root, 0, roster, {1, 3})
            result = loss.summarize(components)
            self.assertEqual(result["queries"], 2)
            self.assertEqual(result["positive_components"], 1)
            self.assertEqual(result["positives"], 2)
            self.assertEqual(
                result["arms"][loss.ARMS[0]]["positive_fractions"], [0, 0.5, 0, 0, 0.5]
            )
            self.assertEqual(result["arms"][loss.ARMS[1]]["positive_fractions"], [1, 0, 0, 0, 0])
            self.assertEqual(result["arms"][loss.ARMS[0]]["coverage"]["neighbor_queries"], 2)
            empty = loss.summarize([components[1]])
            self.assertIsNone(empty["arms"][loss.ARMS[0]]["recall10"])
            self.assertIsNone(empty["arms"][loss.ARMS[0]]["component_equal_fractions"])
            self.assertEqual(empty["queries"], 1)

    def test_duplicate_omitted_and_wrong_target_queries_fail(self) -> None:
        for mutation in ("duplicate", "omit", "target", "fold"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                roster, records = fixture(root)
                if mutation == "duplicate":
                    records.append(records[0])
                elif mutation == "omit":
                    records.pop()
                elif mutation == "target":
                    records[0]["targets"] = [1]
                else:
                    records[0]["inner_fold"] = 1
                write_records(root, records)
                with self.assertRaises(ValueError):
                    loss.analyze_fold(root, 0, roster, {1, 3})

    def test_leakage_false_votes_partial_neighbors_and_reasons_fail(self) -> None:
        for mutation in (
            "candidate_fold",
            "component",
            "vote",
            "partial",
            "reason",
            "popularity",
            "stat",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                roster, records = fixture(root)
                if mutation == "candidate_fold":
                    roster[1]["inner_fold"] = 0
                elif mutation == "component":
                    roster[2]["component_id"] = 1
                elif mutation == "vote":
                    records[0]["arms"][loss.ARMS[0]]["ranking"] = [3]
                elif mutation == "partial":
                    records[0]["arms"][loss.ARMS[0]]["neighbor_ids"] = [1]
                elif mutation == "reason":
                    records[0]["arms"][loss.ARMS[0]]["reason"] = "missing_descriptors"
                elif mutation == "popularity":
                    records[0]["arms"][loss.ARMS[4]]["ranking"] = [3, 1]
                else:
                    np.savez(
                        root / "statistics.npz",
                        components=np.array([3, 4]),
                        values=np.zeros((2, 5, 14)),
                    )
                write_records(root, records)
                with self.assertRaises(ValueError):
                    loss.analyze_fold(root, 0, roster, {1, 3})

    def test_candidate_union_recomputed_from_source_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roster, _ = fixture(root)
            payload = json.loads((root / "candidates.json").read_bytes())
            payload["candidate_label_union"] = [1, 3]
            with self.assertRaises(ValueError):
                loss.candidate_pool(payload, 0, roster)

    def test_equal_components_not_recording_weighted(self) -> None:
        small = loss._component(1, 0)  # noqa: SLF001 - controlled sufficient-statistic fixture.
        small.update(
            queries=1, labeled_queries=1, positives=1, buckets=[[0, 0, 0, 0, 1]] * 2, hits10=[1] * 5
        )
        large = loss._component(2, 1)  # noqa: SLF001 - controlled sufficient-statistic fixture.
        large.update(
            queries=100, labeled_queries=100, positives=100, buckets=[[0, 100, 0, 0, 0]] * 2
        )
        result = loss.summarize([small, large])["arms"][loss.ARMS[0]]
        self.assertEqual(result["component_equal_recall10"], 0.5)
        self.assertEqual(result["recall10"], 1 / 101)
        self.assertEqual(sum(result["component_equal_fractions"]), 1)

    def test_output_bound_freshness_and_replay_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            with (
                patch.object(custody, "MAX_OUTPUT_BYTES", 3),
                self.assertRaisesRegex(ValueError, "10 MB"),
            ):
                custody.write_outputs(output, {"results.json": {"long": "value"}})
            self.assertFalse(output.exists())
            seal = root / "seal.json"
            seal.write_text("{}")
            expected = {"results.json": {"fixed": 1}, "components.json": {"components": []}}
            with patch.object(loss, "compute", side_effect=lambda _: copy.deepcopy(expected)):
                loss.run(seal, output)
                loss.replay(seal, output)
                with self.assertRaises(FileExistsError):
                    loss.run(seal, output)
                receipt = json.loads((output / "receipt.json").read_bytes())
                receipt["deploy_authorized"] = True
                (output / "receipt.json").write_bytes(custody.encoded(receipt))
                with self.assertRaisesRegex(ValueError, "claims"):
                    loss.replay(seal, output)
                receipt["deploy_authorized"] = False
                (output / "results.json").write_bytes(custody.encoded({"fixed": 2}))
                receipt["files"]["results.json"] = custody.inventory(output)["results.json"]
                (output / "receipt.json").write_bytes(custody.encoded(receipt))
                with self.assertRaisesRegex(ValueError, "Numerical"):
                    loss.replay(seal, output)

    def test_symlink_input_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "alias").symlink_to(root / "data", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlink"):
                custody.inventory(root / "alias")

    def test_freeze_protocol_bytes_and_changed_inventory_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            # Non-alphabetical key order must survive canonical seal serialization.
            protocol.write_text('{"z":1,"a":2}\n')
            original = root / "original.json"
            original.write_text("{}")
            seal = root / "seal.json"
            bindings = {"source": {"input": {"sha256": "a", "bytes": 1}}, "run": {}}
            with (
                patch.object(custody, "PROTOCOL_SHA256", custody.digest(protocol)),
                patch.object(custody, "validate_original", return_value=bindings),
            ):
                custody.freeze(protocol, original, root, root, seal)
                custody.verify_seal(seal)
                with (
                    patch.object(custody, "validate_original", return_value={"changed": True}),
                    self.assertRaisesRegex(ValueError, "bindings"),
                ):
                    custody.verify_seal(seal)
                data = json.loads(seal.read_bytes())
                data["protocol"]["a"] = 3
                seal.write_bytes(custody.encoded(data))
                with self.assertRaisesRegex(ValueError, "policy"):
                    custody.verify_seal(seal)

    def test_original_pin_prevents_rehashed_fold_receipt_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, run = root / "source", root / "run"
            source.mkdir()
            run.mkdir()
            manifest = source / "MANIFEST.json"
            manifest.write_bytes(custody.encoded({"files": {}}))
            original = root / "original.json"
            original.write_bytes(custody.encoded({"versions": custody.versions(), "code": {}}))
            original_sha = custody.digest(original)
            fold_receipts = {}
            for fold in range(5):
                folder = run / f"fold-{fold}"
                folder.mkdir()
                for name in custody.FOLD_FILES:
                    (folder / name).write_text("synthetic")
                receipt = {
                    "fold": fold,
                    "seal_sha256": original_sha,
                    "files": custody.inventory(folder),
                }
                (folder / "receipt.json").write_bytes(custody.encoded(receipt))
                fold_receipts[str(fold)] = custody.digest(folder / "receipt.json")
            summary = run / "summary"
            summary.mkdir()
            result = summary / "results.json"
            result.write_bytes(custody.encoded({"fold_receipts": fold_receipts}))
            summary_sha = custody.digest(result)
            (summary / "receipt.json").write_bytes(
                custody.encoded({"seal_sha256": original_sha, "files": custody.inventory(summary)})
            )
            with (
                patch.object(custody, "MANIFEST_SHA256", custody.digest(manifest)),
                patch.object(custody, "ORIGINAL_SEAL_SHA256", original_sha),
                patch.object(custody, "ORIGINAL_SUMMARY_SHA256", summary_sha),
            ):
                custody.validate_original(original, source, run)
                rank = run / "fold-0/ranks.jsonl.zst"
                rank.write_text("changed")
                receipt_path = run / "fold-0/receipt.json"
                receipt = json.loads(receipt_path.read_bytes())
                receipt["files"]["ranks.jsonl.zst"] = {
                    "bytes": rank.stat().st_size,
                    "sha256": custody.digest(rank),
                }
                receipt_path.write_bytes(custody.encoded(receipt))
                with self.assertRaisesRegex(ValueError, "pinned summary"):
                    custody.validate_original(original, source, run)
