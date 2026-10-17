"""Synthetic derivation checks; original source validation remains a separate mandatory gate."""

import base64
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from opennoise.deployment import fma_audio_free_standalone as standalone


def fixture(root: Path) -> None:
    """Build a tiny synthetic source, including a hostile closing-script credit."""
    for directory in ("metadata", "model", "discovery"):
        (root / directory).mkdir(parents=True)
    for name in (*standalone.DATA_FILES, *standalone.RECEIPTS):
        (root / name).write_text(
            json.dumps(
                {"source": name, "credit": "café </script><script>BAD</script>"}, ensure_ascii=False
            )
        )
    (root / "site-receipt.json").write_text('{"synthetic":true}')
    (root / "index.html").write_text(
        '<!doctype html><a href="model/receipt.json">Model</a>'
        '<a href="discovery/receipt.json">Discovery</a>\n'
        "<script>\n'use strict';\n"
        "fetch('metadata/manifest.json');fetch('model/layout.json');"
        "fetch('discovery/discovery.json');\n</script>"
    )


class StandaloneTests(TestCase):
    def test_deterministic_roundtrip_and_exact_source_bindings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            fixture(source)
            before = {
                str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()
            }
            with patch.object(standalone, "validate_audio_free_site") as validate:
                first, second = root / "first.html", root / "second.html"
                result = standalone.build_standalone(source, first, "model-pin", "discovery-pin")
                standalone.build_standalone(source, second, "model-pin", "discovery-pin")
                self.assertEqual(first.read_bytes(), second.read_bytes())
                self.assertEqual(
                    result,
                    standalone.verify_standalone(source, first, "model-pin", "discovery-pin"),
                )
                validate.assert_called_with(source, "model-pin", "discovery-pin")
                text = first.read_text()
                self.assertIn("<script>\n'use strict';\nfunction embeddedResponse", text)
                self.assertNotIn("<script>BAD", text)
                blocks = re.findall(
                    r'<script type="application/json" id="([^"]+)">(.*?)</script>', text, re.DOTALL
                )
                for i, name in enumerate(standalone.DATA_FILES):
                    self.assertEqual(
                        json.loads(dict(blocks)[f"standalone-data-{i}"]),
                        json.loads((source / name).read_text()),
                    )
                provenance = json.loads(dict(blocks)["standalone-provenance"])
                self.assertFalse(provenance["public_deployment_authorized"])
                self.assertEqual(
                    provenance["source_page_sha256"],
                    hashlib.sha256(before["index.html"]).hexdigest(),
                )
                for name, binding in provenance["embedded_sources"].items():
                    self.assertEqual(binding["sha256"], hashlib.sha256(before[name]).hexdigest())
                receipts = re.findall(r'href="data:application/json;base64,([^"]+)"', text)
                self.assertEqual(
                    [base64.b64decode(v) for v in receipts],
                    [before[n] for n in standalone.RECEIPTS],
                )
            self.assertEqual(
                before,
                {
                    str(p.relative_to(source)): p.read_bytes()
                    for p in source.rglob("*")
                    if p.is_file()
                },
            )

    def test_tamper_append_and_source_change_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            fixture(source)
            output = root / "view.html"
            with patch.object(standalone, "validate_audio_free_site"):
                standalone.build_standalone(source, output, "m", "d")
                original = output.read_bytes()
                for changed in (
                    original + b"<script>bad()</script>",
                    original.replace(b"caf", b"bad", 1),
                ):
                    output.write_bytes(changed)
                    with self.assertRaisesRegex(ValueError, "content differs"):
                        standalone.verify_standalone(source, output, "m", "d")
                output.write_bytes(original)
                (source / "model/receipt.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "content differs"):
                    standalone.verify_standalone(source, output, "m", "d")
                with self.assertRaisesRegex(ValueError, "Fresh"):
                    standalone.build_standalone(source, output, "m", "d")

    def test_external_source_gate_and_budget_precede_write(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            fixture(source)
            output = root / "view.html"
            with (
                patch.object(
                    standalone, "validate_audio_free_site", side_effect=ValueError("source pin")
                ),
                self.assertRaisesRegex(ValueError, "source pin"),
            ):
                standalone.build_standalone(source, output, "wrong", "d")
            self.assertFalse(output.exists())
            with (
                patch.object(standalone, "validate_audio_free_site"),
                patch.object(standalone, "MAX_HTML_BYTES", 100),
                self.assertRaisesRegex(ValueError, "512KiB"),
            ):
                standalone.build_standalone(source, output, "m", "d")
            self.assertFalse(output.exists())

    def test_template_boundary_changes_and_symlinks_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            fixture(source)
            output = root / "view.html"
            with patch.object(standalone, "validate_audio_free_site"):
                (source / "index.html").write_text(
                    (source / "index.html").read_text().replace("'use strict';", "")
                )
                with self.assertRaisesRegex(ValueError, "boundary"):
                    standalone.build_standalone(source, output, "m", "d")
            output.symlink_to(source / "index.html")
            with self.assertRaisesRegex(ValueError, "bounded"):
                standalone.verify_standalone(source, output, "m", "d")
