"""Native vector custody and explicit missingness, without model experiments."""

import hashlib
import json
import tempfile
import unittest

# ruff: noqa: PLR2004 - fixed source schema and fixture counts.
from pathlib import Path

from opennoise.ingest.acousticbrainz.vector_bank import build, columns, lookup, values, verify

SOURCE = Path(__file__).resolve().parents[1] / "data/examples/native-sonic"


class VectorBankTests(unittest.TestCase):
    """Validate source-native vector and custody boundaries."""

    def test_columns_and_literal_values(self) -> None:
        """Flatten source positions without interpreting descriptive tags."""
        assert len(columns()) == 178
        raw = {"lowlevel": {"mfcc": {"mean": list(range(13))}}}
        vector = values(raw)
        assert vector[14:27] == list(range(13))
        assert all(v is None for v in vector[:14] + vector[27:])
        assert values({"metadata": {"tags": {"genre": ["fake"]}}}) == [None] * 178

    def test_bad_vectors_rejected(self) -> None:
        """Reject malformed lengths, booleans and nonfinite source values."""
        for bad in ([1] * 12, [True] * 13, [float("nan")] * 13):
            with self.assertRaisesRegex(ValueError, "shape|numeric"):
                values({"lowlevel": {"mfcc": {"mean": bad}}})

    def test_native_build_replay_and_lookup(self) -> None:
        """All nominations and missing outcomes survive byte-identical replay."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        tmp_path = Path(temp.name)
        out = tmp_path / "bank"
        build(SOURCE, out)
        bank = verify(SOURCE, out)
        assert bank["counts"]["nominated_recordings"] == 100
        assert bank["counts"]["available_recordings"] == 55
        missing = next(r for r in bank["rows"] if r["state"] == "missing_http_404")
        assert missing["values"] == [None] * 178
        assert missing["missing_mask"] == [True] * 178
        assert missing["exact_credit"]["fact"] is None
        assert lookup(SOURCE, out, missing["recording_mbid"]) == missing
        replay = tmp_path / "replay"
        build(SOURCE, replay)
        for name in ("bank.json", "receipt.json"):
            assert (out / name).read_bytes() == (replay / name).read_bytes()
        with self.assertRaisesRegex(ValueError, "not nominated"):
            lookup(SOURCE, out, "00000000-0000-0000-0000-000000000000")

    def test_mutation_and_extra_inventory_rejected(self) -> None:
        """Source replay and closed inventory reject changed artifacts."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        tmp_path = Path(temp.name)
        out = tmp_path / "bank"
        build(SOURCE, out)
        original = (out / "bank.json").read_bytes()
        changed = json.loads(original)
        next(r for r in changed["rows"] if r["state"] == "available")["values"][14] += 1
        (out / "bank.json").write_text(json.dumps(changed))
        receipt = json.loads((out / "receipt.json").read_bytes())
        altered = (out / "bank.json").read_bytes()
        receipt["files"]["bank.json"] = {
            "sha256": hashlib.sha256(altered).hexdigest(),
            "bytes": len(altered),
        }
        (out / "receipt.json").write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "replay"):
            verify(SOURCE, out)
        (out / "bank.json").write_bytes(original)
        (out / "extra").write_text("unapproved")
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify(SOURCE, out)

    def test_malformed_branches_and_symlink_ancestors(self) -> None:
        """Neither malformed numbers nor redirected paths are treated as absence."""
        with self.assertRaisesRegex(ValueError, "Malformed"):
            values({"lowlevel": []})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            (root / "alias").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlinked"):
                build(SOURCE, root / "alias" / "bank")
            (root / "source-alias").symlink_to(SOURCE, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlinked"):
                build(root / "source-alias", root / "bank")
