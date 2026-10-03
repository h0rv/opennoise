"""Independently replay native recording facts and exercise source-role rejection."""

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opennoise.serving.metadata.recording_facts import (
    REVISION,
    project_recording_fact,
    replay_recording_facts,
    verify_recording_fact_pack,
)

ARTIST = "0b0c25f4-f31c-46a5-a4fb-ccbf53d663bd"
RECORDING = "56b8e7ce-2fb2-4054-abda-d889ed41a7ac"
OTHER = "f22942a1-6f70-4f48-866e-238cb2308fbd"
PACK = Path(__file__).resolve().parents[2] / "data/examples/recording-facts"


def source_payload() -> dict[str, Any]:
    """Build only the native fields needed to establish a recording credit."""
    return {
        "id": RECORDING,
        "title": "Glasstop",
        "length": None,
        "artist-credit": [{"artist": {"id": ARTIST, "name": "Jon Hopkins"}, "joinphrase": ""}],
    }


class RecordingFactTests(unittest.TestCase):
    def test_core_metadata_credit_and_missing_duration(self) -> None:
        fact = project_recording_fact(json.dumps(source_payload()).encode(), RECORDING, ARTIST)
        self.assertEqual(fact["credited_artist_mbids"], [ARTIST])
        self.assertIsNone(fact["length_ms"])
        with self.assertRaisesRegex(ValueError, "not explicitly credited"):
            project_recording_fact(json.dumps(source_payload()).encode(), RECORDING, OTHER)
        with self.assertRaisesRegex(ValueError, "identity"):
            project_recording_fact(json.dumps(source_payload()).encode(), OTHER, ARTIST)

    def test_supplementary_and_media_fields_rejected_at_each_native_scope(self) -> None:
        for scope in ("recording", "credit", "artist"):
            with self.subTest(scope=scope):
                payload = source_payload()
                target = payload
                if scope == "credit":
                    target = payload["artist-credit"][0]
                elif scope == "artist":
                    target = payload["artist-credit"][0]["artist"]
                target["tags"] = [{"name": "electronic"}]
                with self.assertRaisesRegex(ValueError, "unapproved"):
                    project_recording_fact(json.dumps(payload).encode(), RECORDING, ARTIST)
        payload = source_payload()
        payload["audio"] = "https://example.org/music.mp3"
        with self.assertRaisesRegex(ValueError, "unapproved"):
            project_recording_fact(json.dumps(payload).encode(), RECORDING, ARTIST)

    def test_failed_requests_preserve_artists_and_requested_denominator(self) -> None:
        selection = {
            "revision": REVISION,
            "selection_method": "fixture",
            "source_projection_sha256": "a" * 64,
            "artists": [
                {"artist_mbid": ARTIST, "name": "Jon Hopkins", "recording_mbids": [RECORDING]}
            ],
        }
        captures = [
            {
                "artist_mbid": ARTIST,
                "recording_mbid": RECORDING,
                "url": f"https://musicbrainz.org/ws/2/recording/{RECORDING}?inc=artist-credits&fmt=json",
                "status_code": 404,
                "outcome": "http_status",
            }
        ]
        artifact = replay_recording_facts(Path("unused-no-source-reads"), selection, captures)
        self.assertEqual(artifact["artists"][0]["recordings"], [])
        self.assertEqual(artifact["artists"][0]["requested_recordings"], 1)
        self.assertEqual(artifact["artists"][0]["missing_recordings"], 1)
        with self.assertRaisesRegex(ValueError, "frozen selection"):
            replay_recording_facts(Path("unused-no-source-reads"), selection, [])

    def test_checked_in_pack_replays_native_credit_bytes(self) -> None:
        artifact = verify_recording_fact_pack(PACK)
        self.assertEqual(len(artifact["artists"]), 10)
        for artist in artifact["artists"]:
            with self.subTest(artist=artist["name"]):
                count = 6 if artist["name"] in {"Aphex Twin", "Four Tet"} else 3
                self.assertEqual(artist["requested_recordings"], count)
                self.assertEqual(len(artist["recordings"]) + artist["missing_recordings"], count)
                for fact in artist["recordings"]:
                    self.assertIn(artist["artist_mbid"], fact["credited_artist_mbids"])

    def test_unreferenced_raw_file_is_rejected_even_with_valid_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(PACK, directory)
            (directory / "raw/unreferenced-tags.json").write_text(
                '{"tags":[{"name":"not part of this pack"}]}\n'
            )
            with self.assertRaisesRegex(ValueError, "file set differs"):
                verify_recording_fact_pack(directory)

    def test_symlinked_raw_directory_and_file_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(PACK, directory)
            raw = directory / "raw"
            moved = directory / "raw-saved"
            raw.rename(moved)
            raw.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "regular directory"):
                verify_recording_fact_pack(directory)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(PACK, directory)
            proof = json.loads((directory / "receipt.json").read_bytes())
            capture = next(c for c in proof["captures"] if c["outcome"] == "accepted_core")
            source = directory / capture["path"]
            target = Path(temporary) / "outside.json"
            shutil.copy2(source, target)
            source.unlink()
            source.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "cannot contain symlinks"):
                verify_recording_fact_pack(directory)

    def test_noncanonical_capture_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(PACK, directory)
            receipt_path = directory / "receipt.json"
            proof = json.loads(receipt_path.read_bytes())
            capture = next(c for c in proof["captures"] if c["outcome"] == "accepted_core")
            capture["path"] = "raw/../receipt.json"
            receipt_path.write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, "noncanonical raw path"):
                verify_recording_fact_pack(directory)

    def test_matching_hash_cannot_reclassify_mixed_native_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(PACK, directory)
            proof = json.loads((directory / "receipt.json").read_bytes())
            capture = next(c for c in proof["captures"] if c["outcome"] == "accepted_core")
            path = directory / capture["path"]
            payload = json.loads(path.read_bytes())
            payload["tags"] = [{"name": "electronic"}]
            body = json.dumps(payload).encode()
            path.write_bytes(body)
            proof["response_bytes"] += len(body) - capture["bytes"]
            capture.update({"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
            (directory / "receipt.json").write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, "unapproved recording source fields"):
                verify_recording_fact_pack(directory)

    def test_native_credit_bytes_and_projected_rows_are_both_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(PACK, directory)
            proof = json.loads((directory / "receipt.json").read_bytes())
            artifact = json.loads((directory / "recording-facts.json").read_bytes())
            changed = copy.deepcopy(artifact)
            changed["artists"][0]["recordings"][0]["credited_artist_mbids"] = [OTHER]
            body = json.dumps(changed).encode()
            (directory / "recording-facts.json").write_bytes(body)
            proof["projection_sha256"] = hashlib.sha256(body).hexdigest()
            (directory / "receipt.json").write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, "native source replay"):
                verify_recording_fact_pack(directory)
