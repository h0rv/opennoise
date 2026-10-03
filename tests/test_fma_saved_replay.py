from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from opennoise.ml.fma_saved_replay import replay_saved_pack

PACK = Path(__file__).resolve().parents[1] / "data/examples/fma-acoustic-baseline"


class SavedRankReplayTests(unittest.TestCase):
    def test_all_validation_test_rank_metrics_replay_without_raw_source_or_fit(self) -> None:
        result = replay_saved_pack(PACK)
        self.assertFalse(result["native_source_replay"])
        self.assertFalse(result["model_refit"])
        self.assertEqual(result["folds"]["validation"]["queries"], 7332)
        self.assertEqual(result["folds"]["test"]["queries"], 6468)
        self.assertTrue(result["folds"]["test"]["all_saved_metrics_match"])

    def test_changed_native_target_projection_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pack"
            shutil.copytree(PACK, output)
            targets = output / "held-out-native-targets.jsonl.zst"
            changed = bytearray(targets.read_bytes())
            changed[-1] ^= 1
            targets.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "byte binding differs"):
                replay_saved_pack(output)


if __name__ == "__main__":
    unittest.main()
