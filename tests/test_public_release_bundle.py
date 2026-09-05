"""Tests for portable cache-only public release custody bundles."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from musix.pipeline.public_release_bundle import (
    PublicReleaseBundleDestinations,
    PublicReleaseBundleError,
    PublicReleaseCustodyBundleReceipt,
    export_public_release_bundle,
    restore_public_release_bundle,
    verify_public_release_bundle,
)
from musix.pipeline.public_release_custody import (
    CustodyObject,
    DatabaseCounts,
    EvidenceBinding,
    PublicReleaseCustodyReceipt,
)
from musix.storage import LocalObjectStore, ObjectKey


class PublicReleaseBundleTests(unittest.TestCase):
    def _push(self, root: Path, store: LocalObjectStore, key: str, payload: bytes) -> CustodyObject:
        source = root / f"{hashlib.sha256(payload).hexdigest()}.json"
        source.write_bytes(payload)
        written = store.push(source, ObjectKey(value=key))
        return CustodyObject(key=written.key, sha256=written.sha256, byte_size=written.byte_size)

    def _custody_receipt(self, root: Path, store: LocalObjectStore) -> Path:
        cache = self._push(root, store, "cache/sealed.sqlite", b"sealed-derived-cache")
        evidence: list[EvidenceBinding] = []
        names = (
            "public-model",
            "production-map",
            "production-map-acceptance",
            "production-map-seed-report",
            "production-map-browser",
            "production-map-report",
            "release-receipt",
            "public-model-gate",
            "metadata-representatives",
        )
        for name in names:
            bound = self._push(root, store, f"evidence/{name}.json", f"{name}-bytes".encode())
            evidence.append(EvidenceBinding(**bound.model_dump(), name=name, path=f"/{name}.json"))
        by_name = {item.name: item for item in evidence}
        counts = DatabaseCounts(
            data_sources=62,
            source_snapshots=62,
            source_artifacts=62,
            ingest_attempts=62,
            staged_records=37011,
            parser_releases=2,
        )
        receipt = PublicReleaseCustodyReceipt(
            release_id="phase3-public-20260831-qualified",
            cache=cache,
            cache_declared_byte_size=cache.byte_size,
            database_counts=counts,
            expected_database_counts=counts,
            source_objects_expected=62,
            source_objects_custodied=0,
            source_objects=(),
            source_objects_missing=(),
            source_completeness="cache_only",
            source_vault="/not-included",
            source_storage_mode="reference",
            evidence=tuple(evidence),
            objective_gate_state="present",
            objective_gate_evidence=tuple(
                by_name[name] for name in ("public-model-gate", "metadata-representatives")
            ),
            public_model_gate_sha256=by_name["public-model-gate"].sha256,
            metadata_representatives_sha256=by_name["metadata-representatives"].sha256,
            model_logical_sha256="a" * 64,
            model_file_sha256=by_name["public-model"].sha256,
            production_map_sha256=by_name["production-map"].sha256,
            browser_evidence_sha256=by_name["production-map-browser"].sha256,
            representative_items=3344,
            profile_memberships=26525,
            neighbor_rows=34348,
            rebuild_command=("release-certify",),
            python_version="test",
            code_revision="test",
            created_at="2026-09-04T00:00:00.000Z",
        )
        path = root / "custody-receipt.json"
        path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _export(
        self, root: Path
    ) -> tuple[PublicReleaseCustodyBundleReceipt, ObjectKey, LocalObjectStore]:
        custody_store = LocalObjectStore(root / "custody-store")
        custody_receipt = self._custody_receipt(root, custody_store)
        bundle_store = LocalObjectStore(root / "bundle-store")
        receipt, key = export_public_release_bundle(
            custody_receipt_path=custody_receipt,
            release_directory=Path("config/releases/phase3-public-20260831"),
            custody_store=custody_store,
            bundle_store=bundle_store,
        )
        return receipt, key, bundle_store

    def test_export_verify_and_idempotent_restore_are_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, key, store = self._export(root)
            self.assertEqual(receipt.raw_source_reingestion, "not-included")
            self.assertEqual(len([item for item in receipt.entries if item.kind == "cache"]), 1)
            self.assertEqual(len(receipt.entries), 21)
            verified = verify_public_release_bundle(store, key)
            self.assertEqual(verified, receipt)
            destinations = PublicReleaseBundleDestinations(
                cache_database=root / "restored/data/phase3-public-qualified.sqlite",
                release_directory=root / "restored/config/release",
                evidence_directory=root / "restored/evidence",
                objective_gates_directory=root / "restored/gates",
                custody_receipt=root / "restored/receipts/custody.json",
            )
            first = restore_public_release_bundle(
                store=store, receipt_key=key, destinations=destinations
            )
            first_hashes = {
                path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (root / "restored").rglob("*")
                if path.is_file()
            }
            second = restore_public_release_bundle(
                store=store, receipt_key=key, destinations=destinations
            )
            second_hashes = {
                path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (root / "restored").rglob("*")
                if path.is_file()
            }
            self.assertEqual(first, second)
            self.assertEqual(first_hashes, second_hashes)
            self.assertTrue(destinations.cache_database.is_file())
            self.assertTrue(
                (destinations.evidence_directory / "production-map-v1.browser.json").is_file()
            )

    def test_verifier_rejects_tampered_and_missing_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, key, store = self._export(root)
            cache = next(item for item in receipt.entries if item.kind == "cache")
            cache_path = root / "bundle-store" / cache.object.key.value
            cache_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(PublicReleaseBundleError, "hash or size"):
                verify_public_release_bundle(store, key)
            cache_path.unlink()
            with self.assertRaisesRegex(PublicReleaseBundleError, "missing"):
                verify_public_release_bundle(store, key)

    def test_receipt_parser_rejects_restore_path_traversal_and_omission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, _, _ = self._export(root)
            payload = receipt.model_dump(mode="json")
            payload["entries"][0]["restore_path"]["value"] = "../escape.sqlite"
            with self.assertRaises(ValidationError):
                PublicReleaseCustodyBundleReceipt.model_validate(payload)
            payload = receipt.model_dump(mode="json")
            payload["entries"] = [
                item for item in payload["entries"] if item["kind"] != "release-config"
            ]
            with self.assertRaises(ValidationError):
                PublicReleaseCustodyBundleReceipt.model_validate(payload)

    def test_verifier_rejects_evidence_binding_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _receipt, key, store = self._export(root)
            receipt_path = root / "bundle-store" / key.value
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            evidence = next(item for item in payload["entries"] if item["kind"] == "evidence")
            evidence["object"]["sha256"] = "f" * 64
            receipt_path.unlink()
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(PublicReleaseBundleError, "hash or size"):
                verify_public_release_bundle(store, key)

    def test_parser_requires_complete_optional_integrated_evidence_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt, _, _ = self._export(root)
            payload = receipt.model_dump(mode="json")
            payload["entries"].append(
                {
                    "kind": "evidence",
                    "object": {
                        "key": {"value": "bundle/hydration"},
                        "sha256": "a" * 64,
                        "byte_size": 1,
                    },
                    "restore_path": {"value": "musicbrainz-release-tracks.json"},
                }
            )
            payload["entries"] = tuple(payload["entries"])
            with self.assertRaisesRegex(ValidationError, "optional integrated evidence"):
                PublicReleaseCustodyBundleReceipt.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
