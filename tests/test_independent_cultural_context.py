"""Replay checks for the curated independent Wikidata CC0 example."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.acquire_independent_cultural_context import replay

PACK = Path(__file__).parents[1] / "data/examples/independent-cultural-context"


class IndependentCulturalContextTests(unittest.TestCase):
    def test_curated_cc0_pack_replays_exact_ids_and_missingness(self) -> None:
        replay(PACK)
        manifest = json.loads((PACK / "manifest.json").read_text())
        self.assertEqual(manifest["requested_artist_count"], 42)
        self.assertEqual(manifest["matched_artist_count"], 42)
        self.assertEqual(manifest["unmatched_artist_count"], 0)
        self.assertEqual(manifest["raw_qid_conflict_row_count"], 3)
        cohort = manifest["cohort"]
        self.assertEqual(
            {artist["name"] for artist in cohort if artist["role"] == "baseline"},
            {"Aphex Twin", "Four Tet"},
        )
        self.assertTrue(all(artist["qid"] for artist in cohort))
        evidence = json.loads((PACK / "artist-evidence.json").read_text())
        claims = [claim for artist in evidence for claim in artist["claims"]]
        self.assertTrue(all(claim["license"] == "CC0" for claim in claims))
        self.assertLessEqual(
            {claim["property_id"] for claim in claims},
            {"P135", "P136", "P495", "P740"},
        )

    def test_replay_rejects_changed_raw_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "pack"
            shutil.copytree(PACK, copied)
            with (copied / "raw/batch-00.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                replay(copied)


if __name__ == "__main__":
    unittest.main()
