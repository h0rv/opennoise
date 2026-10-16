"""Synthetic custody tests; fake numeric packs never stand in for actual scientific evidence."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from opennoise.deployment import fma_audio_free_site as site


class AudioFreeTests(TestCase):
    def test_isolated_manifest_no_audio_and_closed_export(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            isolated = root / "isolated"
            isolated.mkdir()
            manifest = isolated / "manifest.json"
            manifest.write_text("FAKE manifest")
            model, discovery = root / "model", root / "discovery"
            for folder in (model, discovery):
                folder.mkdir()
                (folder / "inventory.json").write_text("FAKE inventory")
            (model / "features.npz").write_bytes(b"FAKE numeric values")
            (model / "layout.json").write_text("FAKE layout")
            (discovery / "discovery.json").write_text("FAKE discovery")
            pin = hashlib.sha256(b"FAKE inventory").hexdigest()
            output = root / "site"
            before = site.original.PAGE_PATH.read_bytes()
            with (
                patch.object(site.waveform, "candidate") as manifest_check,
                patch.object(site.waveform, "validate_waveform_pack") as model_check,
                patch.object(site.original, "_discovery") as discovery_check,
                patch.object(
                    site.waveform, "decode", side_effect=AssertionError("Audio decode forbidden")
                ) as decode,
            ):
                result = site.build_audio_free_site(manifest, model, discovery, output, pin, pin)
                self.assertFalse(result["audio_available"])
                self.assertEqual(manifest_check.call_count, 2)
                self.assertEqual(model_check.call_count, 2)
                self.assertEqual(discovery_check.call_count, 2)
                decode.assert_not_called()
                self.assertEqual(
                    (output / "metadata/manifest.json").read_bytes(), manifest.read_bytes()
                )
                self.assertFalse(any(p.suffix == ".mp3" for p in output.rglob("*")))
                self.assertEqual({p.name for p in isolated.iterdir()}, {"manifest.json"})
                self.assertEqual(site.original.PAGE_PATH.read_bytes(), before)
                for a, b in [("0" * 64, pin), (pin, "0" * 64)]:
                    with self.assertRaises(ValueError):
                        site.validate_audio_free_site(output, a, b)
                for name in [
                    "metadata/manifest.json",
                    "model/features.npz",
                    "discovery/discovery.json",
                    "index.html",
                ]:
                    path = output / name
                    saved = path.read_bytes()
                    path.write_bytes(saved + b"changed")
                    with self.assertRaises(ValueError):
                        site.validate_audio_free_site(output, pin, pin)
                    path.write_bytes(saved)
                (output / "metadata/extra.mp3").write_bytes(b"forbidden")
                with self.assertRaises(ValueError):
                    site.validate_audio_free_site(output, pin, pin)
                (output / "metadata/extra.mp3").unlink()
                (output / "escape").symlink_to(root)
                with self.assertRaises(ValueError):
                    site.validate_audio_free_site(output, pin, pin)

    def test_wrong_manifest_and_missing_features_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text("{}")
            with self.assertRaises(ValueError):
                site.waveform.candidate(manifest)
            model = root / "model"
            model.mkdir()
            (model / "inventory.json").write_text("FAKE")
            pin = hashlib.sha256(b"FAKE").hexdigest()
            with (
                patch.object(site.waveform, "candidate"),
                patch.object(site.original, "_discovery"),
                patch.object(
                    site.waveform,
                    "validate_waveform_pack",
                    side_effect=ValueError("missing features"),
                ),
                self.assertRaisesRegex(ValueError, "missing features"),
            ):
                site.build_audio_free_site(manifest, model, model, root / "out", pin, pin)
            self.assertFalse((root / "out").exists())

    def test_page_derivation_is_closed_and_no_player(self) -> None:
        body = site.audio_free_page().decode()
        for forbidden in (
            "<audio",
            "<video",
            "function play(row)",
            "audio.src",
            "data-play-track",
            'id="stop"',
        ):
            self.assertNotIn(forbidden, body)
        for required in (
            "No excerpt available",
            "Recording credits",
            "embedded_notices",
            "Supplied curators",
            "CC BY 4.0",
        ):
            self.assertIn(required, body)
        with patch.object(site, "BASE_PAGE_SHA256", "0" * 64), self.assertRaises(ValueError):
            site.audio_free_page()
        with self.assertRaises(ValueError):
            site._replace("not matching", "required", "replacement")
