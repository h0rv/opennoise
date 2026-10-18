"""Real retained saved-rank lookup without source files, targets or repeated aggregation."""

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.ml import fma_recording_query_bundle as bundle
from opennoise.ml.fma_artist_evidence import export_artist_evidence
from scripts.materialize_fma_membership_example import RECIPE, materialize

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/examples/fma-acoustic-baseline"
REQUESTS = ROOT / "data/recipes/fma44-recording-artists-20261018/protocol.json"


class RecordingBundleTests(unittest.TestCase):
    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.members = cls.root / "members"
        materialize(RECIPE, cls.members)
        cls.requests = [r["track_id"] for r in json.loads(REQUESTS.read_bytes())["requests"]]
        cls.source_pin = sha256_file(SOURCE / "pack-receipt.json")[0]
        cls.members_pin = sha256_file(cls.members / "pack-receipt.json")[0]
        cls.original = cls.root / "original.json"
        cls.bundle = cls.root / "bundle"
        receipt = export_artist_evidence(
            SOURCE,
            cls.source_pin,
            cls.members,
            cls.members_pin,
            cls.original,
            rank_artists=True,
            query_track_ids=cls.requests,
            query_bundle_output=cls.bundle,
        )
        cls.pin = str(receipt["query_bundle_manifest_sha256"])
        cls.original_report = json.loads(cls.original.read_bytes())
        cls.body = json.loads((cls.bundle / "lookup.json").read_bytes())
        cls.metadata = json.loads((cls.bundle / "manifest.json").read_bytes())
        cls.metadata.pop("files")

    def test_frozen_hundred_exact_rows_and_single_duplicate_lookup(self) -> None:
        output = self.root / "hundred.json"
        bundle.lookup(self.bundle, self.pin, self.requests, output)
        result = json.loads(output.read_bytes())
        self.assertEqual(
            result["recording_artist_queries"], self.original_report["recording_artist_queries"]
        )
        self.assertEqual(result["license"], self.original_report["license"])
        self.assertEqual(result["attribution"], self.original_report["attribution"])
        self.assertEqual(result["source_provenance"], self.metadata["provenance"])
        self.assertLess(output.stat().st_size, 2_000_000)
        self.assertLess(sum(p.stat().st_size for p in self.bundle.iterdir()), 10_000_000)
        self.assertEqual(len(self.body["native"]), 109727)
        self.assertEqual(len(self.body["saved"]), 13800)
        one = self.root / "duplicates.json"
        bundle.lookup(self.bundle, self.pin, [self.requests[0]] * 2, one)
        rows = json.loads(one.read_bytes())["recording_artist_queries"]
        self.assertEqual(rows, [self.original_report["recording_artist_queries"][0]] * 2)
        self.assertEqual(
            set(self.body), {"native_columns", "native", "saved_columns", "saved", "partitions"}
        )
        for name, partition in self.body["partitions"].items():
            for actual, original in zip(
                partition["artists"],
                self.original_report["partitions"][name]["artists"],
                strict=True,
            ):
                self.assertEqual(actual, {k: original[k] for k in bundle.ARTIST_FIELDS})

    def test_relocated_lookup_denies_original_source_access(self) -> None:
        relocated = self.root / "relocated/bundle"
        shutil.copytree(self.bundle, relocated)
        original_open = Path.open
        denied = (SOURCE.resolve(), self.members.resolve(), self.original.resolve())

        def guarded(path: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - transparent test guard.
            if any(path.resolve().is_relative_to(root) for root in denied):
                raise AssertionError("Original source access forbidden")
            return original_open(path, *args, **kwargs)

        with (
            patch.object(Path, "open", guarded),
            patch(
                "opennoise.ml.fma_artist_evidence.replay_membership_pack",
                side_effect=AssertionError("no replay"),
            ),
        ):
            output = self.root / "relocated/result.json"
            bundle.lookup(relocated, self.pin, self.requests, output)
        self.assertEqual(
            json.loads(output.read_bytes())["recording_artist_queries"],
            self.original_report["recording_artist_queries"],
        )

    def test_wrong_pin_extra_symlink_and_changed_file_fail_before_output(self) -> None:
        for scenario in ("pin", "extra", "symlink", "changed"):
            root = self.root / f"bad-{scenario}"
            shutil.copytree(self.bundle, root)
            pin = self.pin
            if scenario == "pin":
                pin = "0" * 64
            elif scenario == "extra":
                (root / "extra.json").write_text("{}")
            elif scenario == "symlink":
                (root / "lookup.json").unlink()
                (root / "lookup.json").symlink_to(self.bundle / "lookup.json")
            else:
                (root / "lookup.json").write_text("{}")
            output = self.root / f"bad-{scenario}-result.json"
            with self.assertRaises(ValueError):
                bundle.lookup(root, pin, self.requests, output)
            self.assertFalse(output.exists())

    def test_resealed_schema_runtime_and_semantic_join_corruption_fail(self) -> None:  # noqa: C901, PLR0912 - explicit resealed corruption cases.
        for scenario in (
            "runtime",
            "field",
            "native_type",
            "duplicate",
            "fold",
            "rank",
            "abstention",
            "partition",
            "support",
            "weight",
            "contribution",
            "provenance",
            "license",
            "attribution",
            "source_pin",
        ):
            body = copy.deepcopy(self.body)
            metadata = copy.deepcopy(self.metadata)
            profile = body["partitions"]["calibration"]["artists"][0]
            if scenario == "runtime":
                metadata["runtime"]["versions"]["python"] = "wrong"
            elif scenario == "field":
                body["targets"] = []
            elif scenario == "native_type":
                body["native"][0][0] = True
            elif scenario == "duplicate":
                body["native"].append(body["native"][0])
            elif scenario == "fold":
                body["native"][0][4] = 2
            elif scenario == "rank":
                body["saved"][0][2] = [1, 1]
            elif scenario == "abstention":
                body["saved"][0][1] = "missing_feature_row"
            elif scenario == "partition":
                body["partitions"]["confirmation"]["artists"].append(
                    body["partitions"]["calibration"]["artists"].pop(0)
                )
            elif scenario == "support":
                profile["ranking_supported_track_count"] += 1
            elif scenario == "weight":
                profile["ranked_source_annotation_candidates"][0]["mean_reciprocal_track_rank"] = -1
            elif scenario == "contribution":
                profile["ranked_source_annotation_candidates"][0]["contributing_track_count"] = 0
            elif scenario == "license":
                metadata["provenance"]["license"] = "CC0-1.0"
            elif scenario == "attribution":
                metadata["provenance"]["attribution"] = ""
            elif scenario == "source_pin":
                metadata["provenance"]["saved_pack_receipt_sha256"] = "bad"
            else:
                metadata["provenance"]["source_path"] = "/unapproved"
            root = self.root / f"resealed-{scenario}"
            pin = bundle.publish(root, bundle.artifact.encoded(body), metadata)
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                bundle.load(root, pin)

    def test_cli_rejects_ambiguous_modes_and_output_overlap_without_writes(self) -> None:
        base = [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/replay_fma_memberships.py")]
        output = self.root / "must-not-exist.json"
        lookup = [
            "--query-bundle",
            str(self.bundle),
            "--query-bundle-sha256",
            self.pin,
            "--query-track-id",
            "213",
            "--output",
            str(output),
        ]
        for extra in (
            ["--saved-pack", str(SOURCE)],
            ["--rank-artists"],
            ["--artist-neighbors"],
            ["--membership-receipt-sha256", self.members_pin],
            ["--export-artists", str(output)],
        ):
            result = subprocess.run(  # noqa: S603 - fixed local CLI and fixture arguments.
                base + lookup + extra, check=False, capture_output=True, timeout=120
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
        for artist_output, bundle_output in (
            (self.root / "overlap", self.root / "overlap/bundle"),
            (self.root / "outer/artists.json", self.root / "outer"),
        ):
            with self.assertRaises(ValueError):
                export_artist_evidence(
                    SOURCE,
                    self.source_pin,
                    self.members,
                    self.members_pin,
                    artist_output,
                    rank_artists=True,
                    query_bundle_output=bundle_output,
                )
            self.assertFalse(artist_output.exists())
            self.assertFalse(bundle_output.exists())
        with self.assertRaises(ValueError):
            bundle.lookup(self.bundle, self.pin, [213], self.bundle / "result.json")
        self.assertFalse((self.bundle / "result.json").exists())
