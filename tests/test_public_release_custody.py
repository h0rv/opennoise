"""Tests for the cache and source custody boundary."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from musix.pipeline.public_release import PublicReleaseResult
from musix.pipeline.public_release_custody import (
    DatabaseCounts,
    PublicReleaseCustodyError,
    PublicReleaseCustodySettings,
    custody_public_release,
)


class PublicReleaseCustodyTests(unittest.TestCase):
    def _settings(
        self, root: Path, cache: Path, evidence: Path, source_vault: Path
    ) -> PublicReleaseCustodySettings:
        return PublicReleaseCustodySettings(
            release_directory=Path("config/releases/phase3-public-20260831"),
            cache_database=cache,
            source_vault=source_vault,
            evidence_directory=evidence,
            output_directory=root / "custody",
            expected_cache_sha256="a" * 64,
            expected_cache_byte_size=4,
        )

    def test_rejects_a_cache_with_the_wrong_declared_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "qualified.sqlite"
            cache.write_bytes(b"cache")
            settings = self._settings(root, cache, root / "evidence", root / "vault")
            with self.assertRaisesRegex(PublicReleaseCustodyError, "hash or byte size"):
                custody_public_release(settings)

    def test_missing_sources_produce_truthful_cache_only_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "qualified.sqlite"
            cache.write_bytes(b"cache")
            evidence = root / "evidence"
            evidence.mkdir()
            source_vault = root / "vault"
            source_vault.mkdir()
            settings = self._settings(root, cache, evidence, source_vault)
            evidence_payloads = {
                "public-model.json": '{"model":"model"}',
                "production-map-v1.json": '{"map":"map"}',
                "production-map-v1.acceptance.json": '{"accepted":true}',
                "production-map-v1.seed-report.json": '{"seed":1}',
                "production-map-v1.browser.json": '{"browser":true}',
                "production-map-v1.report.json": '{"report":true}',
                "receipt.json": '{"receipt":true}',
            }
            for filename, payload in evidence_payloads.items():
                (evidence / filename).write_text(payload)
            model_hash = hashlib.sha256(evidence_payloads["public-model.json"].encode()).hexdigest()
            expected_counts = DatabaseCounts(
                data_sources=1,
                source_snapshots=1,
                source_artifacts=1,
                ingest_attempts=1,
                staged_records=1,
                parser_releases=1,
            )
            release_receipt = PublicReleaseResult(
                release_id="test",
                cache_sha256=hashlib.sha256(b"cache").hexdigest(),
                cache_schema_version=10,
                serving_schema_version=12,
                model_logical_sha256="b" * 64,
                model_file_sha256=model_hash,
                recorded_model_file_sha256="c" * 64,
                model_input_sha256="d" * 64,
                model_settings_sha256="e" * 64,
                input_artifacts=62,
                representative_items=3344,
                profile_memberships=26525,
                neighbor_rows=34348,
            )
            with (
                patch(
                    "musix.pipeline.public_release_custody._verify_cache",
                    return_value=(hashlib.sha256(b"cache").hexdigest(), 5, expected_counts),
                ),
                patch(
                    "musix.pipeline.public_release_custody._load_release_receipt",
                    return_value=release_receipt,
                ),
                patch(
                    "musix.pipeline.public_release_custody._source_rows",
                    return_value=iter([("test-source", "f" * 64, 12, "f" * 64)]),
                ),
            ):
                settings = settings.model_copy(update={"expected_cache_byte_size": 5})
                receipt = custody_public_release(settings, code_revision="test-revision")

            self.assertEqual(receipt.source_completeness, "cache_only")
            self.assertEqual(receipt.source_objects_custodied, 0)
            self.assertEqual(len(receipt.source_objects_missing), 1)
            self.assertEqual(receipt.code_revision, "test-revision")
            self.assertTrue(
                (settings.output_directory / "public-release-custody-receipt.json").is_file()
            )


if __name__ == "__main__":
    unittest.main()
