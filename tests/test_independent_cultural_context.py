"""Replay checks for the curated independent Wikidata CC0 example."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.acquire_independent_cultural_context import replay

PACK = Path(__file__).parents[1] / "data/examples/independent-cultural-context"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n")


def _rebind_receipt(pack: Path, paths: list[str]) -> None:
    receipt_path = pack / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    for relative in paths:
        receipt["sha256"][relative] = hashlib.sha256((pack / relative).read_bytes()).hexdigest()
    _write_json(receipt_path, receipt)


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
        self.assertTrue(all("curation_context" not in artist for artist in cohort))
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

    def test_rehashed_foreign_p434_rows_stay_out_of_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "pack"
            shutil.copytree(PACK, copied)
            manifest_path = copied / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            raw_path = copied / "raw/batch-00.json"
            raw = json.loads(raw_path.read_text())
            baseline_id = next(
                artist["artist_mbid"]
                for artist in manifest["cohort"]
                if artist["name"] == "Aphex Twin"
            )
            template = next(
                binding
                for binding in raw["results"]["bindings"]
                if binding["mbid"]["value"] == baseline_id
                and binding.get("property", {}).get("value")
                == "http://www.wikidata.org/prop/direct/P136"
            )
            injected = json.loads(json.dumps(template))
            injected["artist"] = {
                "type": "uri",
                "value": "http://www.wikidata.org/entity/Q999999999",
            }
            injected["label"] = {"xml:lang": "en", "type": "literal", "value": "Unrelated item"}
            raw["results"]["bindings"].append(injected)
            _write_json(raw_path, raw)
            body = raw_path.read_bytes()
            batch = manifest["batches"][0]
            batch["response_sha256"] = hashlib.sha256(body).hexdigest()
            batch["response_bytes"] = len(body)
            batch["returned_binding_count"] += 1
            batch["matched_artist_count"] += 1
            batch["raw_qid_conflict_rows"] += 1
            manifest["raw_qid_conflict_row_count"] += 1
            manifest["response_bytes_total"] = len(body)
            manifest["total_acquired_response_bytes"] = (
                manifest["response_bytes_total"] + manifest["discovery_response_bytes"]
            )
            _write_json(manifest_path, manifest)
            _rebind_receipt(copied, ["raw/batch-00.json", "manifest.json"])

            replay(copied)
            evidence = json.loads((copied / "artist-evidence.json").read_text())
            self.assertNotIn(
                "Q999999999",
                {artist["wikidata_artist_id"] for artist in evidence},
            )
            self.assertNotIn(
                "Q999999999",
                {claim["wikidata_artist_id"] for artist in evidence for claim in artist["claims"]},
            )

    def test_replay_requires_baseline_qids_even_with_rehashed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "pack"
            shutil.copytree(PACK, copied)
            manifest_path = copied / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            next(artist for artist in manifest["cohort"] if artist["name"] == "Four Tet").pop("qid")
            _write_json(manifest_path, manifest)
            _rebind_receipt(copied, ["manifest.json"])
            with self.assertRaisesRegex(TypeError, "requires an exact MBID and pinned QID"):
                replay(copied)

    def test_replay_rejects_foreign_projection_qid_after_hash_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "pack"
            shutil.copytree(PACK, copied)
            projection_path = copied / "artist-evidence.json"
            projection = json.loads(projection_path.read_text())
            foreign_qid = "Q999999999"
            projection[0]["wikidata_artist_id"] = foreign_qid
            for claim in projection[0]["claims"]:
                claim["wikidata_artist_id"] = foreign_qid
            _write_json(projection_path, projection)
            _rebind_receipt(copied, ["artist-evidence.json"])
            with self.assertRaisesRegex(ValueError, "projection does not replay"):
                replay(copied)


if __name__ == "__main__":
    unittest.main()
