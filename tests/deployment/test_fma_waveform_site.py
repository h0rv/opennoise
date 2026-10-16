"""Synthetic custody fixtures: no actual audio, extraction, fitting, or rights review."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from opennoise.deployment import fma_waveform_site as site


class WaveformSiteTests(TestCase):
    def test_closed_copy_and_tamper_rejection(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            candidate, pack, output = root / "candidate", root / "pack", root / "output"
            candidate.mkdir()
            pack.mkdir()
            (candidate / "manifest.json").write_text("synthetic metadata")
            (candidate / "index.html").write_text("synthetic prior page")
            (candidate / "audio.mp3").write_bytes(b"FAKE: not audio")
            layout = {
                "candidate_manifest_sha256": site.REVIEWED_MANIFEST_SHA256,
                "tracks": [{"track_id": i} for i in range(1, 56)],
            }
            (pack / "layout.json").write_text(json.dumps(layout))
            (pack / "inventory.json").write_text("synthetic inventory")
            pin = hashlib.sha256((pack / "inventory.json").read_bytes()).hexdigest()
            with (
                patch.object(site, "validate_candidate", return_value=layout) as candidate_check,
                patch.object(site, "_validate_model", return_value=layout) as model_check,
            ):
                receipt = site.build_waveform_site(candidate, pack, output, pin)
                self.assertEqual(candidate_check.call_count, 2)
                self.assertEqual(model_check.call_count, 2)
                self.assertFalse(receipt["public_deployment_authorized"])
                self.assertEqual(
                    (output / "candidate" / "audio.mp3").read_bytes(), b"FAKE: not audio"
                )
                site.validate_waveform_site(output, pin)
                with self.assertRaises(ValueError):
                    site.validate_waveform_site(output, "0" * 64)
                with self.assertRaises(ValueError):
                    site.build_waveform_site(candidate, pack, root / "wrong-pin", "0" * 64)
                self.assertFalse((root / "wrong-pin").exists())
                for target in ["index.html", "model/layout.json", "candidate/audio.mp3"]:
                    path = output / target
                    saved = path.read_bytes()
                    path.write_bytes(saved + b"tamper")
                    with self.assertRaises(ValueError):
                        site.validate_waveform_site(output, pin)
                    path.write_bytes(saved)
                (output / "extra").write_text("unexpected")
                with self.assertRaises(ValueError):
                    site.validate_waveform_site(output, pin)
                (output / "extra").unlink()
                (output / "escape").symlink_to(candidate)
                with self.assertRaises(ValueError):
                    site.validate_waveform_site(output, pin)

    def test_candidate_or_model_failure_precedes_output(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output"
            (root / "inventory.json").write_text("synthetic inventory")
            pin = hashlib.sha256((root / "inventory.json").read_bytes()).hexdigest()
            with (
                patch.object(site, "validate_candidate", side_effect=ValueError("bad pin")),
                self.assertRaisesRegex(ValueError, "bad pin"),
            ):
                site.build_waveform_site(root, root, output, pin)
            self.assertFalse(output.exists())
            with (
                patch.object(site, "validate_candidate", return_value={}),
                patch.object(site, "_validate_model", side_effect=ValueError("bad model")),
                self.assertRaisesRegex(ValueError, "bad model"),
            ):
                site.build_waveform_site(root, root, output, pin)
            self.assertFalse(output.exists())
