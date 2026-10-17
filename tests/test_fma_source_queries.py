"""Physical synthetic CSV streams; never scan retained FMA data here."""

import bz2
import csv
import hashlib
import io
import json
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.ingest.fma_features import MEMBER_NAME
from opennoise.ingest.fma_native_bank import COLUMNS
from opennoise.ml.fma_source_queries import export_source_queries, scan_rows, source_preflight


class SourceQueryTests(unittest.TestCase):
    def stream(
        self, root: Path, rows: list[list[Any]], *, swap: bool = False
    ) -> tuple[dict[str, Any], str]:
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        columns = list(COLUMNS)
        if swap:
            columns[0], columns[1] = columns[1], columns[0]
        for i, name in enumerate(("feature", "statistics", "number")):
            writer.writerow([name, *[column[i] for column in columns]])
        writer.writerow(["track_id", *[""] * len(columns)])
        writer.writerows(rows)
        raw = text.getvalue().encode()
        path = root / "feature-compressed.range"
        path.write_bytes(MEMBER_NAME.encode() + bz2.compress(raw))
        return (
            {
                "payload_path": path.name,
                "payload_prefix_bytes": len(MEMBER_NAME),
                "uncompressed_bytes": len(raw),
                "crc32": zlib.crc32(raw),
            },
            hashlib.sha256(raw).hexdigest(),
        )

    def test_order_missing_and_float32(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cells = ["0.123456789"] * 518
            cells[1:4] = ["", "nan", "inf"]
            member, digest = self.stream(root, [[2, *cells], [7, *["2"] * 518]])
            values, present, receipt = scan_rows(
                root, member, [7, 9, 2], [list(c) for c in COLUMNS], digest
            )
            np.testing.assert_array_equal(present, [True, False, True])
            self.assertTrue(np.isnan(values[1]).all())
            self.assertTrue(np.isnan(values[2, 1:4]).all())
            self.assertEqual(values[2, 0], np.float32("0.123456789"))
            self.assertEqual(receipt["native_rows"], 2)

    def test_tail_duplicate_width_identity_overflow_and_schema(self) -> None:
        first = [2, *["0"] * 518]
        for tail in (first, [3, "0"], [0, *["0"] * 518], [3, *["1e100"] * 518]):
            with self.subTest(tail=tail[:2]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                member, digest = self.stream(root, [first, tail])
                with self.assertRaises((ValueError, OverflowError)):
                    scan_rows(root, member, [2], [list(COLUMNS[0])], digest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            member, digest = self.stream(root, [first], swap=True)
            with self.assertRaisesRegex(ValueError, "column order"):
                scan_rows(root, member, [2], [list(COLUMNS[0])], digest)

    def test_full_hash_crc_and_truncation(self) -> None:
        for failure in ("hash", "crc", "truncate"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                member, digest = self.stream(root, [[2, *["0"] * 518]])
                if failure == "hash":
                    digest = "0" * 64
                elif failure == "crc":
                    member["crc32"] ^= 1
                else:
                    path = root / member["payload_path"]
                    path.write_bytes(path.read_bytes()[:-10])
                with self.assertRaises((ValueError, EOFError)):
                    scan_rows(root, member, [2], [list(COLUMNS[0])], digest)

    def test_failure_never_publishes_and_request_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            member, digest = self.stream(source, [[2, *["0"] * 518], [3, "bad"]])
            body = {
                "columns": [list(COLUMNS[0])],
                "native_observed_sha256": digest,
                "native_source_receipt_sha256": "pin",
            }
            with (
                patch("opennoise.ml.fma_source_queries.load_bundle", return_value=(body,)),
                patch(
                    "opennoise.ml.fma_source_queries.source_preflight",
                    return_value={"member": member},
                ),
            ):
                requests: list[list[Any]] = [[2], [2, 2], [], list(range(1, 258)), [True]]
                for ids in requests:
                    output = root / "queries"
                    with self.assertRaises(ValueError):
                        export_source_queries(root / "bundle", "pin", source, "pin", ids, output)
                    self.assertFalse(output.exists())

    def test_success_publishes_only_selected_rows_with_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            member, digest = self.stream(source, [[2, *["0.25"] * 518]])
            body = {
                "columns": [list(COLUMNS[0])],
                "native_observed_sha256": digest,
                "native_source_receipt_sha256": "a" * 64,
                "namespace": "FMA/native-track-id",
                "license": "CC-BY-4.0",
                "attribution": "Synthetic source fixture",
            }
            output = root / "queries"
            with (
                patch("opennoise.ml.fma_source_queries.load_bundle", return_value=(body,)),
                patch(
                    "opennoise.ml.fma_source_queries.source_preflight",
                    return_value={"member": member},
                ),
            ):
                export_source_queries(root / "bundle", "pin", source, "a" * 64, [9, 2], output)
            metadata = json.loads((output / "manifest.json").read_bytes())
            self.assertEqual(metadata["mode"], "native-source")
            self.assertEqual(metadata["source_receipt_sha256"], "a" * 64)
            self.assertNotIn("bank_receipt_sha256", metadata)
            with np.load(output / "queries.npz", allow_pickle=False) as arrays:
                np.testing.assert_array_equal(arrays["ids"], [9, 2])
                np.testing.assert_array_equal(arrays["feature_present"], [False, True])
                self.assertEqual(arrays["features"][1, 0], 0.25)

    def test_capture_receipt_mismatch_rejects_before_source_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "queries"
            with (
                patch(
                    "opennoise.ml.fma_source_queries.load_bundle",
                    return_value=({"native_source_receipt_sha256": "a" * 64},),
                ),
                patch("opennoise.ml.fma_source_queries.source_preflight") as preflight,
                patch("opennoise.ml.fma_source_queries.scan_rows") as scan,
                self.assertRaisesRegex(ValueError, "bundle capture pin"),
            ):
                export_source_queries(
                    root / "bundle", "pin", root / "source", "b" * 64, [2], output
                )
            preflight.assert_not_called()
            scan.assert_not_called()
            self.assertFalse(output.exists())

    def test_receipt_pin_and_payload_path_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "README.md",
                "central-directory.range",
                "declaration.json",
                "source-receipt.json",
                "feature-local-header.range",
                "feature-compressed.range",
            ):
                (root / name).write_bytes(b"synthetic")
            pin = hashlib.sha256(b"synthetic").hexdigest()
            with self.assertRaisesRegex(ValueError, "external pin"):
                source_preflight(root, "0" * 64)
            with (
                patch(
                    "opennoise.ml.fma_source_queries.verify_feature_source",
                    return_value={"member": {"payload_path": "../unverified"}},
                ),
                self.assertRaisesRegex(ValueError, "verified compressed range"),
            ):
                source_preflight(root, pin)

    def test_source_metadata_symlink_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "README.md",
                "central-directory.range",
                "declaration.json",
                "source-receipt.json",
                "feature-local-header.range",
                "feature-compressed.range",
            ):
                (root / name).write_bytes(b"x")
            (root / "README.md").unlink()
            (root / "README.md").symlink_to(root / "declaration.json")
            with self.assertRaisesRegex(ValueError, "regular"):
                source_preflight(root, "pin")
            (root / "README.md").unlink()
            (root / "README.md").write_bytes(b"x" * 200001)
            with self.assertRaisesRegex(ValueError, "regular"):
                source_preflight(root, "pin")
