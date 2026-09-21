from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter

from opennoise.pipeline.source_vault_replay import (
    SourceVaultReplayError,
    SourceVaultReplayReport,
    load_report,
    restore_source_vault,
    verify_source_vault,
    write_report,
)
from opennoise.storage import LocalObjectStore


class SourceVaultReplayTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, list[bytes]]:
        vault = root / "vault"
        raw = vault / "raw" / "sha256"
        raw.mkdir(parents=True)
        payloads = [b"first source\n", b"second source\n"]
        inputs = []
        for index, payload in enumerate(payloads):
            digest = hashlib.sha256(payload).hexdigest()
            (raw / digest).write_bytes(payload)
            inputs.append(
                {
                    "source_key": f"source_{index}",
                    "artifact_sha256": digest,
                    "byte_size": len(payload),
                }
            )
        manifest = root / "release-manifest.json"
        manifest.write_text(
            json.dumps({"release_id": "test-release", "inputs": inputs}), encoding="utf-8"
        )
        return manifest, vault, payloads

    def _manifest_payload(self, manifest: Path) -> dict[str, object]:
        return TypeAdapter(dict[str, object]).validate_json(manifest.read_bytes())

    def test_verify_binds_manifest_and_publishes_then_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, payloads = self._fixture(root)
            store = LocalObjectStore(root / "objects")
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                report = verify_source_vault(manifest, vault, object_store=store)
            self.assertTrue(report.complete)
            self.assertEqual(report.object_count, 2)
            report_path = root / "report.json"
            write_report(report, report_path)
            loaded = load_report(report_path)
            self.assertEqual(
                loaded.manifest_sha256, hashlib.sha256(manifest.read_bytes()).hexdigest()
            )
            destination = root / "restored"
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                restore_source_vault(loaded, store, destination, manifest_path=manifest)
            restored = [
                (destination / item.object_key.value).read_bytes() for item in loaded.objects
            ]
            self.assertEqual(restored, payloads)

    def test_verify_rejects_wrong_size_or_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            item = next((vault / "raw" / "sha256").iterdir())
            item.write_bytes(b"tampered")
            with (
                patch(
                    "opennoise.pipeline.source_vault_replay.load_release_manifest",
                    return_value=self._manifest_payload(manifest),
                ),
                self.assertRaises(SourceVaultReplayError),
            ):
                verify_source_vault(manifest, vault)

    def test_restore_requires_fresh_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            store = LocalObjectStore(root / "objects")
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                report = verify_source_vault(manifest, vault, object_store=store)
            destination = root / "restored"
            destination.mkdir()
            with self.assertRaises(SourceVaultReplayError):
                restore_source_vault(report, store, destination, manifest_path=manifest)

    def test_verify_rejects_manifest_subset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            with self.assertRaises(SourceVaultReplayError):
                verify_source_vault(manifest, vault)

    def test_verify_rejects_noncanonical_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            alias = root / "alias.json"
            alias.write_bytes(manifest.read_bytes())
            with self.assertRaises(SourceVaultReplayError):
                verify_source_vault(alias, vault)

    def test_report_rejects_forged_object_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, vault, _ = self._fixture(root)
            with patch(
                "opennoise.pipeline.source_vault_replay.load_release_manifest",
                return_value=self._manifest_payload(manifest),
            ):
                report = verify_source_vault(manifest, vault)
            forged = report.model_dump(mode="json")
            forged["objects"][0]["object_key"]["value"] = "raw/sha256/not-the-artifact"
            with self.assertRaises(ValueError):
                SourceVaultReplayReport.model_validate(forged)
