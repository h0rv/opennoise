"""Synthetic native metadata fixtures only; no retained-source fits or acquisition."""

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, override
from unittest.mock import patch
from uuid import UUID

from opennoise.ingest.acousticbrainz import vector_bank
from opennoise.ml import ab178_portable as portable
from opennoise.ml import recording_evaluation as engine


class PortableABTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        (self.source / "raw/sonic").mkdir(parents=True)
        self.native_bank = self.root / "bank"
        self.native_bank.mkdir()
        for path in (self.source, self.native_bank):
            (path / "receipt.json").write_bytes(b"synthetic receipt")
        self.source_pin = vector_bank.digest(self.source / "receipt.json")
        self.version = {
            "essentia": "2.1-beta2",
            "essentia_git_sha": "v2.1_beta2",
            "essentia_build_sha": "a" * 40,
            "extractor": "music 1.0",
        }
        self.analysis = {"analysis_sample_rate": 44100, "downmix": "mix", "equal_loudness": 0}
        self.contract: dict[str, Any] = {
            "revision": portable.CONTRACT_REVISION,
            "schema_sha256": portable.hash_value(vector_bank.columns()),
            "version": self.version,
            "analysis": self.analysis,
        }
        self.contract_path = self.root / "contract.json"
        self.contract_path.write_bytes(portable.encoded(self.contract))
        self.contract_pin = vector_bank.digest(self.contract_path)
        self.ids = [str(UUID(int=i)) for i in range(1, 13)]
        records: list[dict[str, Any]] = []
        for index, identity in enumerate(self.ids):
            artist = str(UUID(int=100 + max(index, 1)))
            fact = {"recording_mbid": identity, "credited_artist_mbids": [artist]}
            raw = portable.encoded(
                {"metadata": {"version": self.version, "audio_properties": self.analysis}}
            )
            (self.source / f"raw/sonic/{identity}.json").write_bytes(raw)
            records.append(
                {
                    "recording_mbid": identity,
                    "cohort_artist_mbid": str(UUID(int=999)),
                    "state": "available",
                    "identity_state": "matched",
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "exact_credit": {"fact": fact, "state": "accepted_core"},
                    "values": [float(index + 1)] * 178,
                    "missing_mask": [False] * 178,
                }
            )
        self.projected = {"columns": vector_bank.columns(), "rows": records}
        rows = portable.source_rows(self.source, self.contract, self.projected)
        ledger = engine.component_ledger(rows)
        self.fold = next(
            fold
            for fold in range(3)
            if sum(r["fold"] == fold for r in ledger["records"]) > 0
            and sum(r["fold"] != fold for r in ledger["records"])
            >= engine.POLICY["minimum_complete_training_recordings"]
        )
        self.bundle = self.root / "bundle"
        self.pin = self.export(self.bundle)

    def export(self, output: Path) -> str:
        with patch("opennoise.ml.ab178_portable.bank.verify", return_value=self.projected):
            return portable.export_bundle(
                self.source,
                self.source_pin,
                self.native_bank,
                self.source_pin,
                self.contract_path,
                self.contract_pin,
                self.fold,
                output,
            )

    def queries(self, ids: list[str], name: str = "queries") -> tuple[Path, str]:
        output = self.root / name
        with patch("opennoise.ml.ab178_portable.bank.project", return_value=self.projected):
            pin = portable.export_queries(
                self.bundle, self.pin, self.source, self.source_pin, ids, output
            )
        return output, pin

    def test_frozen_frame_self_component_exclusion_and_fit_membership(self) -> None:
        queries, pin = self.queries(self.ids)
        result = portable.infer(self.bundle, self.pin, queries, pin)
        body = portable.bundle(self.bundle, self.pin)
        metadata = {r["recording_mbid"]: r for r in body["ledger"]["records"]}
        self.assertEqual(
            metadata[self.ids[0]]["component_id"], metadata[self.ids[1]]["component_id"]
        )
        self.assertGreater(len({r["component_id"] for r in metadata.values()}), 1)
        for row in result["rows"]:
            identity = row["recording_mbid"]
            self.assertEqual(row["fit_member"], identity in body["frame"]["fitted_recordings"])
            self.assertEqual(row["outcome"], "emitted")
            for neighbor in row["neighbors"]:
                self.assertNotEqual(neighbor["recording_mbid"], identity)
                self.assertNotEqual(
                    metadata[neighbor["recording_mbid"]]["component_id"], row["component_id"]
                )

    def test_training_frame_does_not_read_heldout_values(self) -> None:
        original = portable.bundle(self.bundle, self.pin)
        heldout = {
            r["recording_mbid"] for r in original["ledger"]["records"] if r["fold"] == self.fold
        }
        for row in self.projected["rows"]:
            if row["recording_mbid"] in heldout:
                row["values"] = [99999.0] * 178
        output = self.root / "second"
        pin = self.export(output)
        second = portable.bundle(output, pin)
        self.assertEqual(original["frame"], second["frame"])
        self.assertEqual(original["candidates"], second["candidates"])

    def test_version_config_dirty_missing_and_unknown_outcomes(self) -> None:
        for identity, change in zip(self.ids[:3], ("version", "config", "dirty"), strict=True):
            path = self.source / f"raw/sonic/{identity}.json"
            raw = json.loads(path.read_bytes())
            if change == "version":
                raw["metadata"]["version"]["essentia_build_sha"] = "b" * 40
            elif change == "dirty":
                raw["metadata"]["version"]["essentia_git_sha"] += "-dirty"
            else:
                raw["metadata"]["audio_properties"]["downmix"] = "left"
            path.write_bytes(portable.encoded(raw))
        self.projected["rows"][3]["state"] = "missing_http_404"
        other = self.root / "other"
        pin = self.export(other)
        self.bundle, self.pin = other, pin
        unknown = str(UUID(int=10000))
        queries, query_pin = self.queries([*self.ids[:4], unknown])
        result = portable.infer(other, pin, queries, query_pin)
        self.assertEqual(
            [r["outcome"] for r in result["rows"]],
            [
                "extractor_version_mismatch",
                "analysis_configuration_mismatch",
                "dirty_extractor",
                "missing_http_404",
                "not_nominated",
            ],
        )
        self.assertTrue(all(not r["neighbors"] for r in result["rows"]))

    def test_contract_fields_schema_dirty_and_external_pin(self) -> None:
        for key in self.contract:
            bad = copy.deepcopy(self.contract)
            del bad[key]
            with self.assertRaises(ValueError):
                portable.contract(bad)
        for key, value in (("schema_sha256", "wrong"), ("extra", True)):
            with self.assertRaises(ValueError):
                portable.contract({**self.contract, key: value})
        bad = copy.deepcopy(self.contract)
        bad["version"]["essentia_git_sha"] += "-dirty"
        with self.assertRaises(ValueError):
            portable.contract(bad)
        with self.assertRaisesRegex(ValueError, "external pin"):
            portable.read(self.contract_path, "0" * 64)

    def test_query_tamper_even_with_new_pin_rejects_features_and_credit(self) -> None:
        queries, pin = self.queries(self.ids[:1])
        original = portable.load(queries, "queries.json", pin)
        for kind in ("value", "credit", "hash", "version", "capture"):
            bad = copy.deepcopy(original)
            if kind == "value":
                bad["rows"][0]["values"][0] += 1
            elif kind == "credit":
                bad["rows"][0]["credited_artist_mbids"] = [str(UUID(int=10000))]
            elif kind == "hash":
                bad["rows"][0]["evidence"]["source_sha256"] = "f" * 64
            elif kind == "version":
                bad["rows"][0]["version"]["extractor"] = "other"
            else:
                bad["source_receipt_sha256"] = "f" * 64
            path = queries / "queries.json"
            path.write_bytes(portable.encoded(bad))
            with self.assertRaises(ValueError):
                portable.infer(self.bundle, self.pin, queries, vector_bank.digest(path))

    def test_source_receipt_mismatch_rejects_before_native_read(self) -> None:
        with (
            patch("opennoise.ml.ab178_portable.source_rows") as scan,
            self.assertRaisesRegex(ValueError, "capture pin"),
        ):
            portable.export_queries(
                self.bundle, self.pin, self.source, "f" * 64, self.ids[:1], self.root / "bad-query"
            )
        scan.assert_not_called()

    def test_request_bounds_output_inventory_and_missing_support(self) -> None:
        for ids in ([], self.ids[:1] * 2, ["not-an-id"], [str(UUID(int=i)) for i in range(101)]):
            with self.assertRaises(ValueError):
                self.queries(ids)
        (self.bundle / "extra").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "inventory"):
            portable.bundle(self.bundle, self.pin)
        for row in self.projected["rows"]:
            row["values"] = [1.0] * 178
        with self.assertRaisesRegex(ValueError, "support"):
            self.export(self.root / "unsupported")
        self.assertFalse((self.root / "unsupported").exists())

    def test_portable_relocation_needs_no_native_paths(self) -> None:
        queries, pin = self.queries(self.ids)
        expected = portable.encoded(portable.infer(self.bundle, self.pin, queries, pin))
        moved = self.root / "moved"
        moved.mkdir()
        shutil.move(self.bundle, moved / "bundle")
        shutil.move(queries, moved / "queries")
        shutil.rmtree(self.source)
        shutil.rmtree(self.native_bank)
        self.contract_path.unlink()
        self.assertEqual(
            expected,
            portable.encoded(portable.infer(moved / "bundle", self.pin, moved / "queries", pin)),
        )
