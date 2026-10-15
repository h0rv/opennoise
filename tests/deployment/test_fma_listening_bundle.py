"""Standalone bundle corruption fails before serving; packaging preserves a closed tree."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from opennoise.deployment import fma_listening_bundle as bundle
from opennoise.deployment import local_listening_server as server


class ListeningBundleTests(unittest.TestCase):
    def test_launcher_and_archive_are_reproducible_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "source"
            site.mkdir()
            (site / "index.html").write_text("<title>synthetic site</title>")
            first, second = root / "first.zip", root / "second.zip"
            with patch.object(bundle, "_verify_site"):
                a = bundle.build_listening_bundle(site, first)
                b = bundle.build_listening_bundle(site, second)
            self.assertEqual(a["sha256"], b["sha256"])
            with self.assertRaises(FileExistsError):
                bundle.build_listening_bundle(site, first)
            with zipfile.ZipFile(first) as archive:
                archive.extractall(root / "extracted")
            extracted = root / "extracted/OpenNoise"
            command = [sys.executable, str(extracted / "serve.py"), "--check-only"]
            valid = subprocess.run(command, capture_output=True, check=False)  # noqa: S603
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertIn(b"Verified", valid.stdout)
            for mutation in ("changed", "missing", "extra", "symlink"):
                with self.subTest(mutation=mutation):
                    clone = root / mutation
                    shutil.copytree(extracted, clone)
                    target = clone / "site/index.html"
                    if mutation == "changed":
                        target.write_text("changed bytes")
                    elif mutation == "missing":
                        target.unlink()
                    elif mutation == "extra":
                        (clone / "site/extra.txt").write_text("extra")
                    else:
                        target.unlink()
                        target.symlink_to(site / "index.html")
                    failed = subprocess.run(  # noqa: S603 -- explicit test interpreter and file.
                        [sys.executable, str(clone / "serve.py"), "--check-only"],
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertIn(b"Bundle verification failed", failed.stderr)

    def test_inventory_catches_symlinks_and_bound_excess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("hello")
            with patch.object(server, "MAX_BYTES", 4), self.assertRaises(ValueError):
                server.inventory(root)
            (root / "alias").symlink_to(root / "index.html")
            with self.assertRaisesRegex(ValueError, "symbolic"):
                server.inventory(root)

    def test_manifest_scope_cannot_enable_public_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "MANIFEST.json").write_text(
                json.dumps(
                    {
                        "revision": server.REVISION,
                        "public_deployment_authorized": True,
                        "files": {},
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "scope"):
                server.verify(root)
