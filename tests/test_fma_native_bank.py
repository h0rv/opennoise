from __future__ import annotations

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

from opennoise.common import canonical_json, sha256_file
from opennoise.ingest.fma_features import (
    MAX_PROJECTION_BYTES,
    MAX_ROWS,
    MEMBER_NAME,
    SELECTED_COLUMNS,
    _project_features,
    project_feature_stream,
)
from opennoise.ingest.fma_native_bank import (
    COLUMNS,
    MAX_BANK_BYTES,
    REVISION,
    STAGE_LIMITS,
    project_native_bank,
    verify_native_bank,
)


class NativeBankTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[dict[str, Any], Path]:
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerows(
            [
                [label, *[column[i] for column in COLUMNS]]
                for i, label in enumerate(("feature", "statistics", "number"))
            ]
        )
        writer.writerow(["track_id", *([""] * len(COLUMNS))])
        cells = [str(index / 10) for index in range(len(COLUMNS))]
        cells[1] = ""
        cells[2] = "inf"
        writer.writerows([[7, *cells], [9, *cells]])
        native = text.getvalue().encode()
        source = {
            "member": {
                "payload_path": "native.range",
                "payload_prefix_bytes": len(MEMBER_NAME),
                "uncompressed_bytes": len(native),
                "crc32": zlib.crc32(native),
            },
            "declaration_sha256": "original",
            "attribution": "FMA",
        }
        (root / "native.range").write_bytes(MEMBER_NAME.encode() + bz2.compress(native))
        (root / "source-receipt.json").write_bytes(canonical_json(source))
        declaration = root / "declaration.json"
        declaration.write_bytes(
            canonical_json(
                {
                    "revision": REVISION,
                    "max_bank_bytes": MAX_BANK_BYTES,
                    "max_rows": MAX_ROWS,
                    "stage_limits": STAGE_LIMITS,
                    "columns": COLUMNS,
                    "source_receipt_sha256": sha256_file(root / "source-receipt.json")[0],
                    "native_observed_sha256": hashlib.sha256(native).hexdigest(),
                }
            )
        )
        return source, declaration

    def test_full_bank_values_missingness_duplicates_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, declaration = self.fixture(root)
            with patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source):
                receipt = project_native_bank(root, root / "bank", declaration)
            with patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source):
                original = project_feature_stream(root, root / "original44")
            full = np.fromfile(root / "bank/features.float32", dtype="<f4").reshape(2, 518)
            selected = full[:, [COLUMNS.index(column) for column in SELECTED_COLUMNS]]
            self.assertEqual(
                selected.tobytes(), (root / "original44/features.float32").read_bytes()
            )
            self.assertEqual(original["columns"], SELECTED_COLUMNS)
            self.assertEqual(len(COLUMNS), 518)
            self.assertEqual(MAX_PROJECTION_BYTES, 20_000_000)
            self.assertEqual(verify_native_bank(root / "bank"), json.loads(canonical_json(receipt)))
            values = np.fromfile(root / "bank/features.float32", dtype="<f4").reshape(2, 518)
            np.testing.assert_allclose(values[:, 3], 0.3)
            self.assertTrue(np.isnan(values[:, 1:3]).all())
            self.assertEqual(receipt["missing_cells"][str(COLUMNS[1])], 2)
            self.assertEqual(
                json.loads((root / "bank/duplicate-native-feature-cells.json").read_bytes()),
                [[7, 9]],
            )
            np.testing.assert_array_equal(
                np.fromfile(root / "bank/track_ids.uint32", dtype="<u4"), [7, 9]
            )
            with (root / "bank/features.float32").open("r+b") as stream:
                stream.write(b"BAD!")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_native_bank(root / "bank")

    def test_prior_digest_mismatch_has_no_completion_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, declaration = self.fixture(root)
            body = json.loads(declaration.read_bytes())
            body["native_observed_sha256"] = "0" * 64
            declaration.write_bytes(canonical_json(body))
            with (
                patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source),
                self.assertRaisesRegex(ValueError, "prior verified"),
            ):
                project_native_bank(root, root / "bank", declaration)
            self.assertFalse((root / "bank/projection-receipt.json").exists())

    def test_wrong_budget_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, declaration = self.fixture(root)
            body = json.loads(declaration.read_bytes())
            body["max_bank_bytes"] += 1
            declaration.write_bytes(canonical_json(body))
            with self.assertRaisesRegex(ValueError, "frozen declaration"):
                project_native_bank(root, root / "bank", declaration)
            self.assertFalse((root / "bank").exists())

    def test_byte_guard_prevents_first_row_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, _ = self.fixture(root)
            with (
                patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source),
                self.assertRaisesRegex(ValueError, "budget"),
            ):
                _project_features(root, root / "small", selected=COLUMNS, max_bytes=100)
            self.assertEqual((root / "small/features.float32").stat().st_size, 0)
            self.assertFalse((root / "small/projection-receipt.json").exists())

    def test_extra_file_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, declaration = self.fixture(root)
            with patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source):
                project_native_bank(root, root / "bank", declaration)
            (root / "bank/extra").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "inventory"):
                verify_native_bank(root / "bank")
