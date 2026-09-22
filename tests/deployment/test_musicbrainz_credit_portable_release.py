"""Verify the checked-in portable MusicBrainz credit custody chain."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from opennoise.deployment.musicbrainz_credit_portable_release import (
    MusicBrainzCreditPortableReleaseError,
    PortableMusicBrainzCreditReleaseReceipt,
    PortableMusicBrainzCreditSource,
    materialize_portable_musicbrainz_credit_catalog,
    publish_portable_musicbrainz_credit_source,
    restore_portable_musicbrainz_credit_catalog,
    sha256_file,
)
from opennoise.storage import LocalObjectStore

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json"
STORE = ROOT / "data/release/musicbrainz-credit-catalog-v1/objects"


class MusicBrainzCreditPortableReleaseTests(unittest.TestCase):
    """A fresh checkout can restore byte-pinned catalog metadata without `.cache`."""

    @staticmethod
    def _receipt() -> PortableMusicBrainzCreditReleaseReceipt:
        return PortableMusicBrainzCreditReleaseReceipt.model_validate_json(RECEIPT.read_bytes())

    def test_restores_the_pinned_catalog_and_report(self) -> None:
        receipt = self._receipt()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = restore_portable_musicbrainz_credit_catalog(
                receipt,
                store=LocalObjectStore(STORE),
                candidate_database=root / "catalog.sqlite",
                candidate_report=root / "catalog-report.json",
            )
            self.assertEqual(report.database_sha256, receipt.candidate_database_sha256)
            self.assertEqual(
                sha256_file(root / "catalog.sqlite"), receipt.candidate_database_sha256
            )
            self.assertEqual((report.release_relations, report.recording_relations), (87, 1_031))
            self.assertEqual((report.ordered_credit_members, report.artists), (1_344, 352))

    def test_source_replays_without_ignored_cache_and_rejects_existing_targets(self) -> None:
        receipt = self._receipt()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = materialize_portable_musicbrainz_credit_catalog(
                receipt,
                store=LocalObjectStore(STORE),
                candidate_database=root / "replayed.sqlite",
                candidate_report=root / "replayed-report.json",
            )
            self.assertEqual(report.verified_cache_projections, receipt.source_projection_count)
            self.assertEqual((report.release_relations, report.recording_relations), (87, 1_031))
            with self.assertRaisesRegex(MusicBrainzCreditPortableReleaseError, "already exist"):
                restore_portable_musicbrainz_credit_catalog(
                    receipt,
                    store=LocalObjectStore(STORE),
                    candidate_database=root / "replayed.sqlite",
                    candidate_report=root / "second-report.json",
                )

    def test_mismatched_catalog_bytes_write_no_custody_objects(self) -> None:
        receipt = self._receipt()
        source_path = STORE.joinpath(*receipt.source.key.parts)
        source = PortableMusicBrainzCreditSource.model_validate_json(source_path.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_database = root / "wrong.sqlite"
            bad_database.write_bytes(b"not the receipt-bound catalog")
            report = root / "catalog-report.json"
            report.write_bytes(STORE.joinpath(*receipt.catalog_report.key.parts).read_bytes())
            object_root = root / "objects"
            with self.assertRaisesRegex(
                MusicBrainzCreditPortableReleaseError, "before publication"
            ):
                publish_portable_musicbrainz_credit_source(
                    source,
                    store=LocalObjectStore(object_root),
                    custody_scope=receipt.custody_scope,
                    candidate_database=bad_database,
                    candidate_report=report,
                    receipt_output=root / "receipt.json",
                )
            self.assertFalse((root / "receipt.json").exists())
            self.assertEqual(tuple(object_root.rglob("*")), ())
