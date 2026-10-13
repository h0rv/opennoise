"""Synthetic native-column and custody checks; no real training metrics in fixtures."""

import bz2
import csv
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from opennoise.ml import fma_temporal_experiment as temporal


class TemporalProjectionTests(unittest.TestCase):
    def test_native_order_and_missing_std(self) -> None:
        columns = list(reversed(temporal.COLUMNS))
        headers = [
            [label, *[str(column[i]) for column in columns]]
            for i, label in enumerate(("feature", "statistics", "number"))
        ]
        self.assertEqual(temporal.positions(headers), list(range(len(columns), 0, -1)))
        for header in headers:
            header.pop()
        with self.assertRaisesRegex(ValueError, "missing or duplicate"):
            temporal.positions(headers)

    def test_stream_keeps_means_and_rejects_negative_std_or_id_drift(self) -> None:
        for fault in (None, "negative", "identity", "crc"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                source = root / "feature-source"
                (source / "projection").mkdir(parents=True)
                text = io.StringIO()
                writer = csv.writer(text)
                for i, label in enumerate(("feature", "statistics", "number")):
                    writer.writerow([label, *[column[i] for column in temporal.COLUMNS]])
                writer.writerow(["track_id", *([""] * len(temporal.COLUMNS))])
                values = [1.0] * len(temporal.COLUMNS)
                if fault == "negative":
                    values[-1] = -1.0
                writer.writerow([1, *values])
                body = text.getvalue().encode()
                prefix = temporal.MEMBER_NAME.encode()
                (source / "payload").write_bytes(prefix + bz2.compress(body))
                (source / "projection/features.float32").write_bytes(
                    struct.pack("<44f", *([1.0] * 44))
                )
                (source / "projection/track_ids.uint32").write_bytes(
                    struct.pack("<I", 2 if fault == "identity" else 1)
                )
                declaration = root / "declaration.json"
                declaration.write_text("{}")
                member = {
                    "payload_path": "payload",
                    "payload_prefix_bytes": len(prefix),
                    "uncompressed_bytes": len(body),
                    "crc32": 0 if fault == "crc" else zlib.crc32(body),
                }
                with (
                    patch.object(temporal, "verify", return_value=(root, {})),
                    patch.object(
                        temporal, "verify_feature_source", return_value={"member": member}
                    ),
                ):
                    if fault is None:
                        result = temporal.project(declaration, root / "projection88")
                        self.assertEqual(result["rows"], 1)
                        self.assertEqual(result["features"]["bytes"], 352)
                    else:
                        with self.assertRaises(ValueError):
                            temporal.project(declaration, root / "projection88")

    def test_frozen_input_drift_rejected_before_projection(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source"
            source.write_bytes(b"first")
            declared = {
                "revision": temporal.REVISION,
                "columns": temporal.COLUMNS,
                "limits": temporal.LIMITS,
                "root": str(root),
                "inputs": {str(source): temporal._binding(source)},  # noqa: SLF001 -- fixture exact custody.
            }
            path = root / "declaration.json"
            path.write_text(json.dumps(declared))
            with patch.object(temporal, "_input_paths", return_value=[source]):
                self.assertEqual(temporal.verify(path)[0], root)
                source.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "input differs"):
                    temporal.verify(path)
