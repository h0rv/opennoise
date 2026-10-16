"""Synthetic export fixtures; no actual audio or model output is fabricated."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from opennoise.deployment import fma_profile_site as site


class ProfileSiteTests(TestCase):
    def test_external_pins_closed_copy_and_original_page_untouched(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            candidate, model, discovery = (
                root / name for name in ("candidate", "model", "discovery")
            )
            for directory in (candidate, model, discovery):
                directory.mkdir()
                (directory / "inventory.json").write_text("synthetic inventory")
            (candidate / "manifest.json").write_text("FAKE metadata")
            (candidate / "index.html").write_text("original fake page")
            (candidate / "audio.mp3").write_bytes(b"FAKE not audio")
            (model / "layout.json").write_text("FAKE layout")
            (discovery / "discovery.json").write_text("FAKE profiles")
            pin = hashlib.sha256(b"synthetic inventory").hexdigest()
            output = root / "site"
            with (
                patch.object(site, "validate_candidate") as candidate_check,
                patch.object(site, "validate_waveform_pack") as model_check,
                patch.object(site, "_discovery") as profile_check,
            ):
                site.build_profile_site(candidate, model, discovery, output, pin, pin)
                self.assertEqual(candidate_check.call_count, 2)
                self.assertEqual(model_check.call_count, 2)
                self.assertEqual(profile_check.call_count, 2)
                self.assertEqual((candidate / "index.html").read_text(), "original fake page")
                self.assertEqual((output / "candidate/audio.mp3").read_bytes(), b"FAKE not audio")
                site.validate_profile_site(output, pin, pin)
                for model_pin, discovery_pin in (("0" * 64, pin), (pin, "0" * 64)):
                    with self.assertRaises(ValueError):
                        site.validate_profile_site(output, model_pin, discovery_pin)
                for name in (
                    "candidate/audio.mp3",
                    "model/layout.json",
                    "discovery/discovery.json",
                    "index.html",
                ):
                    path = output / name
                    saved = path.read_bytes()
                    path.write_bytes(saved + b"changed")
                    with self.assertRaises(ValueError):
                        site.validate_profile_site(output, pin, pin)
                    path.write_bytes(saved)
                (output / "extra.json").write_text("not bound")
                with self.assertRaises(ValueError):
                    site.validate_profile_site(output, pin, pin)
                (output / "extra.json").unlink()
                (output / "escape").symlink_to(root)
                with self.assertRaises(ValueError):
                    site.validate_profile_site(output, pin, pin)

    def test_unknown_discovery_pin_fails_before_copy(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("model", "discovery"):
                (root / name).mkdir()
                (root / name / "inventory.json").write_text("fixture")
            pin = hashlib.sha256(b"fixture").hexdigest()
            with self.assertRaises(ValueError):
                site.build_profile_site(
                    root, root / "model", root / "discovery", root / "output", pin, "0" * 64
                )
            self.assertFalse((root / "output").exists())

    def test_combined_budget_rejects_before_output(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.mkdir()
            (source / "file").write_bytes(b"1234")
            with (
                patch.object(site, "_inputs"),
                patch.object(site, "MAX_SITE_BYTES", 10),
                self.assertRaises(ValueError),
            ):
                site.build_profile_site(source, source, source, root / "output", "x", "y")
            self.assertFalse((root / "output").exists())
