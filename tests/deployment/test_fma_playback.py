# ruff: noqa: SIM117 -- paired mock and rejection scopes keep fixture intent explicit.
"""Fake fixture-only tests: verifier/decoder mocks are not authentic audio evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

from opennoise.deployment import fma_playback as m
from opennoise.deployment.fma_static import build_fma_static, refresh_fma_static_display
from tests.deployment.test_fma_static import tables


class FakePlaybackExportTests(unittest.TestCase):
    def test_fake_attachment_keeps_audio_separate_and_refresh_preserves_binding(self) -> None:
        self.receipt["tracks"][0]["artist_id"] = 1
        self.save_receipt()
        self.output = self.root / "audio"
        self.export_fake()
        projected = self.root / "projected"
        projected.mkdir()
        corpus = {"metadata_license": "CC-BY-4.0", "source_receipt_sha256": "a" * 64}
        (projected / "corpus-receipt.json").write_text(json.dumps(corpus))
        site = self.root / "explorer"
        with patch(
            "opennoise.deployment.fma_static.verified_tables", return_value=(corpus, tables())
        ):
            result = build_fma_static(
                source=self.source, projected=projected, output=site, playback=self.output
            )
        catalog = json.loads((site / "catalog.json").read_bytes())
        self.assertEqual(catalog["playback"]["manifest"], "../audio/manifest.json")
        self.assertEqual(catalog["playback"]["audio_bytes"], len(self.body))
        self.assertLess(result["total_bytes"], 40_000_000)
        self.assertFalse(any(site.rglob("*.mp3")))
        refresh_fma_static_display(source=site, output=self.root / "refreshed")
        with self.assertRaises(ValueError):
            refresh_fma_static_display(source=site, output=self.root / "elsewhere" / "explorer")

    @override
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="fake-playback-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pack = self.root / "fake-pack"
        self.pack.mkdir()
        self.source = self.root / "fake-metadata"
        self.source.mkdir()
        self.output = self.root / "fake-audio"
        self.body = b"FAKE: not an MP3, verifier and decoder are mocked"
        (self.pack / "2.mp3").write_bytes(self.body)
        self.receipt: dict[str, Any] = {
            "tracks": [
                {
                    "track_id": 2,
                    "artist_id": 7,
                    "audio_path": "2.mp3",
                    "audio_sha256": hashlib.sha256(self.body).hexdigest(),
                    "audio_bytes": len(self.body),
                    "source": {
                        "track_title": "Fixture",
                        "artist_name": "Fake artist",
                        "license_title": "Attribution 4.0",
                        "license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "track_url": "https://example.invalid/fake",
                        "track_copyright_c": "Fake C",
                        "track_copyright_p": "Fake P",
                        "track_composer": "Fake composer",
                    },
                }
            ]
        }
        self.save_receipt()

    def save_receipt(self) -> None:
        (self.pack / "listening.json").write_text(json.dumps(self.receipt))

    def export_fake(self, duration: float = 30.0) -> dict[str, Any]:
        with (
            patch.object(m.fma_listening64, "verify", return_value=self.receipt) as verified,
            patch.object(m, "decode_duration", return_value=duration),
        ):
            result = m.export_fma_playback(self.pack, self.source, self.output)
            verified.assert_called_once_with(self.pack, self.source)
            return result

    def test_fake_export_schema_byte_preservation_and_custody(self) -> None:
        manifest = self.export_fake()
        self.assertEqual((self.output / "2.mp3").read_bytes(), self.body)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"manifest.json", "2.mp3"})
        self.assertEqual(manifest["revision"], "fma-local-playback-v1")
        self.assertIs(manifest["test_only"], False)  # noqa: FBT003 -- exact JSON boolean.
        self.assertIs(manifest["public_deployment_authorized"], False)  # noqa: FBT003
        self.assertEqual(
            manifest["source_pack_sha256"],
            hashlib.sha256((self.pack / "listening.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["tracks"]["2"]["duration_seconds"], 30.0)
        self.assertEqual(manifest["tracks"]["2"]["copyright_p"], "Fake P")
        with self.assertRaises(ValueError):
            self.export_fake()

    def test_invalid_hash_path_license_duration_and_manifest_bound(self) -> None:
        for key, value in [
            ("audio_sha256", "bad"),
            ("audio_path", "../2.mp3"),
            ("audio_bytes", 100),
            ("track_id", True),
        ]:
            original = self.receipt["tracks"][0][key]
            self.receipt["tracks"][0][key] = value
            self.save_receipt()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.export_fake()
            self.assertFalse(self.output.exists())
            self.receipt["tracks"][0][key] = original
        self.save_receipt()
        for duration in (0.0, 31.01, float("nan")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.export_fake(duration)
        with patch.object(m, "MAX_MANIFEST_BYTES", 10), self.assertRaises(ValueError):
            self.export_fake()
        self.receipt["tracks"][0]["source"]["license_url"] = "unapproved"
        self.save_receipt()
        with self.assertRaises(ValueError):
            self.export_fake()
        self.assertFalse(self.output.exists())

    def test_duplicate_count_byte_budgets_and_symlink(self) -> None:
        self.receipt["tracks"] *= 2
        self.save_receipt()
        with self.assertRaises(ValueError):
            self.export_fake()
        self.receipt["tracks"] = self.receipt["tracks"][:1]
        self.save_receipt()
        for field in ("MAX_CLIPS", "MAX_AUDIO_BYTES", "MAX_RANGE_BYTES"):
            with patch.object(m.fma_listening64, field, 0), self.assertRaises(ValueError):
                self.export_fake()
        original = self.pack / "2.mp3"
        original.unlink()
        original.symlink_to(self.pack / "listening.json")
        with self.assertRaises(ValueError):
            self.export_fake()
        self.assertFalse(self.output.exists())

    def test_verifier_failure_and_receipt_drift_prevent_output(self) -> None:
        with patch.object(m.fma_listening64, "verify", side_effect=ValueError("invalid source")):
            with self.assertRaises(ValueError):
                m.export_fma_playback(self.pack, self.source, self.output)
        (self.pack / "listening.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.export_fake()
        self.assertFalse(self.output.exists())

    def test_fake_decoder_commands_forbid_network_and_force_mp3(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], _directory: Path, name: str) -> bytes:
            calls.append(command)
            if name == "probe":
                return (
                    b'{"streams":[{"codec_type":"audio","codec_name":"mp3"}],'
                    b'"format":{"duration":"30"}}'
                )
            Path(command[command.index("-progress") + 1]).write_text(
                "out_time_us=30000000\nprogress=end\n"
            )
            return b""

        with (
            patch.object(m.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"),
            patch.object(m, "_run", side_effect=run),
        ):
            self.assertEqual(m.decode_duration(self.pack / "2.mp3"), 30.0)
        for command in calls:
            self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
            self.assertEqual(command[command.index("-f") + 1], "mp3")
        self.assertIn("-xerror", calls[1])
        self.assertNotIn("-t", calls[1])  # Full decode, not a truncated acceptance check.

    def test_decoder_timeout_propagates(self) -> None:
        with (
            patch.object(m.shutil, "which", return_value="/usr/bin/ffprobe"),
            patch.object(m, "_run", side_effect=subprocess.TimeoutExpired("fake", 20)),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                m.decode_duration(self.pack / "2.mp3")

    def test_export_validation_rejects_fake_scope_and_receipt_tampering(self) -> None:
        manifest = self.export_fake()
        path = self.output / "manifest.json"
        self.assertEqual(m.validate_playback_export(self.output), manifest)
        for key, value in (
            ("test_only", True),
            ("public_deployment_authorized", True),
            ("source_pack_sha256", "bad"),
            ("audio_bytes", 1),
        ):
            path.write_text(json.dumps({**manifest, key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.validate_playback_export(self.output)
        changed = json.loads(json.dumps(manifest))
        changed["tracks"]["2"]["decode"]["full_decode"] = False
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            m.validate_playback_export(self.output)
        path.write_text(json.dumps(manifest))
        (self.output / "surprise.mp3").write_bytes(b"fake")
        with self.assertRaises(ValueError):
            m.validate_playback_export(self.output)
