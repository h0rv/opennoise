"""Reproduce the candidate with only tracked public inputs, no retained private workspace."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

from opennoise.pipeline import artist_network, wiki_artist_atlas
from opennoise.pipeline import catalog_demo as demo
from opennoise.pipeline import public_catalog_candidate as candidate

ROOT = Path(__file__).resolve().parents[1]
NEW_CODE = (
    "pyproject.toml",
    "uv.lock",
    "src/opennoise/pipeline/catalog_demo.py",
    "src/opennoise/pipeline/public_catalog_candidate.py",
    "src/opennoise/static/pipeline-demo.mjs",
    "src/opennoise/static/pipeline-demo.css",
    "scripts/build_retained_catalog_demo.py",
    "scripts/build_public_catalog_candidate.py",
    "src/opennoise/pipeline/wiki_artist_atlas.py",
    "src/opennoise/static/genre-atlas/index.html",
    "src/opennoise/static/genre-atlas/atlas.css",
    "src/opennoise/static/genre-atlas/atlas.mjs",
)


class PublicCatalogCandidateTests(unittest.TestCase):
    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    clean: ClassVar[Path]
    outputs: ClassVar[list[Path]]
    manifests: ClassVar[list[dict[str, Any]]]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        (ROOT / ".cache/test-tmp").mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache/test-tmp")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.clean = Path(cls.temporary.name) / "checkout"
        contract = candidate.inputs(ROOT)
        tracked = (
            subprocess.check_output(  # noqa: S603 -- Resolved local Git, fixed read-only arguments.
                [
                    shutil.which("git") or "/usr/bin/git",
                    "ls-files",
                    "-z",
                    "--",
                    "src",
                    "scripts",
                    "migrations",
                ],
                cwd=ROOT,
            )
            .decode()
            .split("\0")
        )
        members = {
            *filter(None, tracked),
            *NEW_CODE,
            candidate.CONTRACT,
            artist_network.CONTRACT,
            artist_network.PROMOTION,
            artist_network.SNAPSHOT,
            wiki_artist_atlas.CONTRACT,
            *(
                p.relative_to(ROOT).as_posix()
                for p in (ROOT / wiki_artist_atlas.SNAPSHOT).parent.iterdir()
                if p.is_file()
            ),
            *(name for source in contract["sources"] for name in source["files"]),
        }
        for name in sorted(members):
            destination = cls.clean / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        (cls.clean / ".cache").mkdir()
        cls.outputs = [cls.clean / ".cache" / f"build-{seed}" for seed in (1, 27)]
        runner = (
            "import runpy,socket; from unittest.mock import patch; "
            "guard=AssertionError('network forbidden in public-input build'); "
            "a=patch.object(socket.socket,'connect',side_effect=guard); "
            "b=patch.object(socket,'create_connection',side_effect=guard); "
            "a.start();b.start();runpy.run_path('scripts/build_public_catalog_candidate.py',run_name='__main__')"
        )
        for seed, output in zip((1, 27), cls.outputs, strict=True):
            env = {**os.environ, "PYTHONPATH": str(cls.clean / "src"), "PYTHONHASHSEED": str(seed)}
            subprocess.run(  # noqa: S603 -- Bounded local CLI; socket use explicitly denied.
                [
                    sys.executable,
                    "-c",
                    runner,
                    "build",
                    "--root",
                    str(cls.clean),
                    "--output",
                    str(output),
                ],
                cwd=cls.clean,
                env=env,
                capture_output=True,
                text=True,
                timeout=310,
                check=True,
            )
        cls.manifests = [demo.read(p / "payload-manifest.json") for p in cls.outputs]

    def test_clean_public_only_builds_are_byte_identical_across_hash_seeds(self) -> None:
        self.assertEqual(self.manifests[0], self.manifests[1])
        self.assertEqual(
            self.manifests[0]["payload"], candidate.inventory(self.outputs[0] / "site")
        )
        self.assertFalse((self.clean / "data/public.sqlite").exists())
        self.assertFalse((self.clean / ".cache/semantic-map-layout-v3").exists())
        self.assertFalse(self.manifests[0]["private_artifacts_consumed"])
        self.assertFalse(self.manifests[0]["publication_authorized"])
        self.assertEqual(self.manifests[0]["counts"]["catalog_artists"], 433)
        self.assertEqual(self.manifests[0]["counts"]["compatible_artists"], 13)
        self.assertEqual(self.manifests[0]["wiki_artist_atlas"]["counts"]["artists"], 86253)
        self.assertEqual(self.manifests[0]["wiki_artist_atlas"]["counts"]["genres"], 1366)

    def test_every_data_member_is_tracked_and_bound_to_explicit_rights(self) -> None:
        tracked = set(
            subprocess.check_output(  # noqa: S603 -- Resolved local Git, fixed read-only arguments.
                [shutil.which("git") or "/usr/bin/git", "ls-files", "-z"], cwd=ROOT
            )
            .decode()
            .split("\0")
        )
        for source in self.manifests[0]["input_contract"]["sources"]:
            self.assertIn(source["license"], {"CC0-1.0", "MIT"})
            for name, member in source["files"].items():
                self.assertIn(name, tracked)
                self.assertIn(member["license"], {"CC0-1.0", "MIT"})
                self.assertEqual(demo.digest(self.clean / name), member["sha256"])

    def test_source_tampering_fails_before_creating_output(self) -> None:
        path = self.clean / next(iter(self.manifests[0]["input_contract"]["sources"][0]["files"]))
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b" ")
        output = self.clean / ".cache/rejected"
        with self.assertRaisesRegex(ValueError, "source differs"):
            candidate.build(self.clean, output)
        self.assertFalse(output.exists())

    def test_verification_rejects_external_paths_and_payload_symlinks(self) -> None:
        with self.assertRaisesRegex(ValueError, "below checkout"):
            candidate.verify(self.clean, Path(self.temporary.name) / "external")
        path = self.clean / ".cache/linked-site"
        path.symlink_to(self.outputs[0] / "site", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "real directory"):
            candidate.inventory(path)

    def test_rehashed_forged_payload_still_fails_independent_source_replay(self) -> None:
        output = self.clean / ".cache/forged"
        shutil.copytree(self.outputs[0] / "site", output / "site")
        manifest = demo.read(self.outputs[0] / "payload-manifest.json")
        pipeline = demo.read(output / "site/pipeline.json")
        pipeline["artists"][0]["name"] = "Forged source name"
        demo.write(output / "site/pipeline.json", pipeline)
        manifest["payload"] = candidate.inventory(output / "site")
        demo.write(output / "payload-manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            candidate.verify(self.clean, output)


if __name__ == "__main__":
    unittest.main()
