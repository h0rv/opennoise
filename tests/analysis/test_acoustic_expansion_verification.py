from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

from opennoise.analysis.acoustic_expansion_verification import verify_expansion
from opennoise.common import sha256_file, sha256_hex
from opennoise.ingest.acousticbrainz.projection import project_low_level

ARTIST = "00000000-0000-0000-0000-000000000001"
RECORDING = "00000000-0000-0000-0000-000000000002"


class ExpansionVerificationTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.original = root / "original"
        self.corrected = root / "corrected"
        self.expansion = root / "expansion"
        for directory in (self.original, self.corrected, self.expansion):
            directory.mkdir()
        (self.expansion / "raw").mkdir()
        (self.original / "receipt.json").write_text("{}")
        self.write(
            self.corrected / "pre-reprojection-declaration.json",
            {"source_directory": str(self.original)},
        )
        search = {"recordings": [{"id": RECORDING, "artist-credit": [{"artist": {"id": ARTIST}}]}]}
        self.write(self.original / "search.json", search)
        capture = {
            "request_index": 1,
            "kind": "search",
            "requested_url": "https://musicbrainz.org/",
            "fetched_at": "2026-10-01",
            "artist_mbid": ARTIST,
            "recording_mbid": None,
            "status_code": 200,
            "response_headers": {},
            "payload_path": "search.json",
            "payload_sha256": sha256_file(self.original / "search.json")[0],
            "payload_bytes": (self.original / "search.json").stat().st_size,
            "payload_complete": True,
        }
        self.write(self.original / "source-captures.json", [capture])
        document: dict[str, object] = {
            "mbid": RECORDING,
            "lowlevel": {"average_loudness": 0.5},
            "rhythm": {"bpm": 100},
        }
        payload = json.dumps(document).encode()
        (self.expansion / "raw/000.bin").write_bytes(payload)
        (self.expansion / "executed-script.py").write_text("# frozen research capture\n")
        self.declaration: dict[str, object] = {
            "source_receipt_sha256": sha256_file(self.original / "receipt.json")[0],
            "scope": "authorized_local_research",
            "max_new_response_bytes": 10_000_000,
            "response_cap": 300_000,
            "audio_requested": False,
            "level": "low-level",
            "retries": 0,
            "rate_interval_seconds": 1.1,
            "raw_tags_consumed": False,
            "recordings": [[ARTIST, RECORDING]],
        }
        self.descriptors: list[dict[str, object]] = [
            row.model_dump(mode="json") for row in project_low_level(document)
        ]
        self.projection: dict[str, object] = {
            "scope": self.declaration,
            "outcomes": [
                {
                    "artist_id": ARTIST,
                    "recording_id": RECORDING,
                    "state": "available",
                    "status_code": 200,
                    "identity": "matched",
                    "reused": False,
                    "payload_path": "raw/000.bin",
                    "payload_sha256": sha256_hex(payload),
                    "payload_bytes": len(payload),
                    "descriptors": self.descriptors,
                }
            ],
            "new_requests": 1,
            "new_response_bytes": len(payload),
            "state_counts": {"available": 1},
            "source_license": "CC0-1.0",
            "source_attribution": "AcousticBrainz / MusicBrainz contributors",
            "product_promotion_allowed": False,
            "representative_sample": False,
        }
        self.seal()
        for name in ("verify_benchmarks", "verify_reprojection"):
            mocked = patch("opennoise.analysis.acoustic_expansion_verification." + name)
            mocked.start()
            self.addCleanup(mocked.stop)

    @staticmethod
    def write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value))

    def seal(self) -> None:
        self.write(self.expansion / "declaration.json", self.declaration)
        self.write(self.expansion / "projection.json", self.projection)
        files = {
            path.relative_to(self.expansion).as_posix(): sha256_file(path)[0]
            for path in self.expansion.rglob("*")
            if path.is_file() and path.name != "receipt.json"
        }
        self.write(self.expansion / "receipt.json", {"files": files})

    def test_valid_replay(self) -> None:
        _, audit = verify_expansion(self.expansion, self.corrected)
        self.assertTrue(audit["verified"])
        self.assertEqual(audit["available_recordings"], 1)

    def test_rehashed_descriptor_spoof_rejected(self) -> None:
        self.descriptors[0]["value"] = 999
        self.seal()
        with self.assertRaisesRegex(ValueError, "projection replay"):
            verify_expansion(self.expansion, self.corrected)

    def test_rehashed_wrong_source_rejected(self) -> None:
        self.declaration["source_receipt_sha256"] = "0" * 64
        self.seal()
        with self.assertRaisesRegex(ValueError, "source receipt"):
            verify_expansion(self.expansion, self.corrected)

    def test_rehashed_selection_spoof_rejected(self) -> None:
        self.declaration["recordings"] = [[ARTIST, ARTIST]]
        self.seal()
        with self.assertRaisesRegex(ValueError, "selection"):
            verify_expansion(self.expansion, self.corrected)

    def test_rehashed_counter_spoof_rejected(self) -> None:
        self.projection["new_requests"] = 0
        self.seal()
        with self.assertRaisesRegex(ValueError, "counters"):
            verify_expansion(self.expansion, self.corrected)

    def test_missing_raw_inventory_rejected(self) -> None:
        receipt = json.loads((self.expansion / "receipt.json").read_text())
        del receipt["files"]["raw/000.bin"]
        self.write(self.expansion / "receipt.json", receipt)
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify_expansion(self.expansion, self.corrected)

    def test_symlink_rejected(self) -> None:
        (self.expansion / "raw/000.bin").unlink()
        (self.expansion / "raw/000.bin").symlink_to(self.original / "search.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify_expansion(self.expansion, self.corrected)


if __name__ == "__main__":
    unittest.main()
