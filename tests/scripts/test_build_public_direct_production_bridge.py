from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_public_direct_production_bridge import (
    _require_pinned_declaration,
    _write_fresh_receipt,
)


class BuildPublicDirectProductionBridgeTests(unittest.TestCase):
    def test_fresh_receipt_writer_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bridge.json"
            _write_fresh_receipt(output, b"first\n")

            with self.assertRaises(FileExistsError):
                _write_fresh_receipt(output, b"second\n")

            self.assertEqual(output.read_bytes(), b"first\n")

    def test_declared_candidate_pin_must_match_the_contract_pin(self) -> None:
        with self.assertRaisesRegex(ValueError, "production bridge pin"):
            _require_pinned_declaration("0" * 64, "1" * 64, "candidate selection")


if __name__ == "__main__":
    unittest.main()
