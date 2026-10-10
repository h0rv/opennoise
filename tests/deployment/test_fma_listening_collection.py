"""Offline fixture assembly; mocked decoder/source verifier do not claim genuine audio."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.deployment import fma_listening_collection as m
from opennoise.deployment import fma_playback


def row(identity: int, genres: list[int]) -> dict[str, Any]:
    """Create explicitly fake native metadata and hash-bound bytes."""
    body = f"FAKE audio {identity}".encode()
    return {
        "track_id": identity,
        "artist_id": identity + 1,
        "genre_ids": genres,
        "audio_path": f"{identity}.mp3",
        "audio_bytes": len(body),
        "audio_sha256": hashlib.sha256(body).hexdigest(),
        "source": {
            "track_title": f"Fake {identity}",
            "artist_name": "Fixture artist",
            "license_title": "Attribution 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "track_url": "https://example.invalid/fixture",
            "track_copyright_c": "",
            "track_copyright_p": "",
            "track_composer": "",
        },
    }


class ListeningCollectionTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
        """Write tiny separate captures and the old validated export."""
        baseline, new, source, old = [root / name for name in ("baseline", "new", "source", "old")]
        for directory in (baseline, new, source):
            directory.mkdir()
        (source / "source-receipt.json").write_bytes(b"fake source receipt")
        original: dict[str, Any] = {"tracks": [row(2, [10]), row(3, [11]), row(4, [11, 12])]}
        (baseline / "listening.json").write_text(json.dumps(original))
        expanded: dict[str, Any] = {
            "revision": m.fma_large32.REVISION,
            "baseline_sha256": hashlib.sha256(
                (baseline / "listening.json").read_bytes()
            ).hexdigest(),
            "tracks": [row(100, [20])],
        }
        (new / "listening.json").write_text(json.dumps(expanded))
        for directory, receipt in ((baseline, original), (new, expanded)):
            for record in receipt["tracks"]:
                (directory / record["audio_path"]).write_bytes(
                    f"FAKE audio {record['track_id']}".encode()
                )
        with (
            patch.object(fma_playback.fma_listening64, "verify", return_value=original),
            patch.object(fma_playback, "decode_duration", return_value=30.0),
        ):
            fma_playback.export_fma_playback(baseline, source, old)
        return baseline, new, source, old, expanded

    def test_all_new_preserved_old_selection_stable_and_only_new_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, new, source, old, receipt = self.fixture(root)
            before = {path.name: path.read_bytes() for path in old.iterdir()}
            with (
                patch.object(m.fma_large32, "verify", return_value=receipt),
                patch.object(fma_playback, "decode_duration", return_value=30.0) as decode,
            ):
                manifest = m.build_listening_collection(
                    new, source, baseline, old, root / "expanded"
                )
            self.assertEqual(decode.call_count, 1)
            self.assertEqual(Path(decode.call_args.args[0]).name, "100.mp3")
            self.assertEqual(manifest["revision"], m.REVISION)
            self.assertEqual(manifest["expanded_track_ids"], [100])
            self.assertEqual(manifest["original_track_ids"], [4, 2, 3])
            self.assertEqual(before, {path.name: path.read_bytes() for path in old.iterdir()})
            self.assertEqual(fma_playback.validate_playback_export(root / "expanded"), manifest)
            self.assertNotIn("source_pack_sha256", manifest)
            with self.assertRaisesRegex(ValueError, "fresh"):
                m.build_listening_collection(new, source, baseline, old, root / "expanded")
            for mutate in (
                lambda value: value["tracks"].pop("100"),
                lambda value: value["tracks"]["4"].update(title="altered"),
                lambda value: value.update(original_track_ids=[2, 4, 3]),
                lambda value: value["sources"]["expanded"].update(baseline_sha256="0" * 64),
            ):
                changed = copy.deepcopy(manifest)
                mutate(changed)
                with self.assertRaises(ValueError):
                    m.validate_collection_metadata(changed)

    def test_byte_and_count_guards_do_not_drop_new_clips(self) -> None:
        expanded = {str(i): {"audio_bytes": 1_000_000, "genre_ids": [i]} for i in range(100, 132)}
        old = {str(i): {"audio_bytes": 2_000_000, "genre_ids": [i]} for i in range(1, 33)}
        self.assertEqual(m.select_original(expanded, old), list(range(1, 17)))
        small = {str(i): {"audio_bytes": 1, "genre_ids": [i]} for i in range(1, 61)}
        self.assertEqual(
            len(m.select_original({"100": {"audio_bytes": 1, "genre_ids": []}}, small)), 32
        )
        with self.assertRaises(ValueError):
            m.select_original({"100": {"audio_bytes": 32_000_001, "genre_ids": []}}, small)
        with self.assertRaises(ValueError):
            m.select_original(expanded, {"100": old["1"]})

    def test_capture_binding_and_changed_audio_reject_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, new, source, old, receipt = self.fixture(root)
            changed = copy.deepcopy(receipt)
            changed["baseline_sha256"] = "0" * 64
            with (
                patch.object(m.fma_large32, "verify", return_value=changed),
                self.assertRaises(ValueError),
            ):
                m.build_listening_collection(new, source, baseline, old, root / "output")
            self.assertFalse((root / "output").exists())
            (new / "100.mp3").write_bytes(b"changed")
            with (
                patch.object(m.fma_large32, "verify", return_value=receipt),
                self.assertRaises(ValueError),
            ):
                m.build_listening_collection(new, source, baseline, old, root / "output")
            self.assertFalse((root / "output").exists())
