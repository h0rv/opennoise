"""Focused coverage for the bounded portable direct-proper-genre custody source."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyError,
    build_portable_direct_proper_genre_custody,
    receipt_sha256,
    verify_portable_direct_proper_genre_custody,
    verify_portable_direct_proper_genre_custody_from_inputs,
)

_MBID = "11111111-1111-4111-8111-111111111111"
_GENRE = "22222222-2222-4222-8222-222222222222"
_RECORD_SHA = "a" * 64


class DirectProperGenreCustodyTests(unittest.TestCase):
    def _write_inputs(self, directory: Path) -> tuple[Path, Path]:
        source = directory / "seed-target.json"
        source.write_text(
            json.dumps(
                {
                    "evidence": [
                        {
                            "seed_source_item_id": "seed:one",
                            "seed_name": "one",
                            "artist_id": _MBID,
                            "facet": "genre",
                            "match_kind": "exact",
                            "target_identity": _GENRE,
                            "target_name": "one",
                            "target_namespace": "musicbrainz_genre_id",
                            "source_record_id": f"musicbrainz:artist:{_MBID}",
                            "source_record_sha256": _RECORD_SHA,
                            "evidence_ref": "source:one",
                        },
                        {
                            "seed_source_item_id": "seed:one",
                            "seed_name": "one",
                            "artist_id": _MBID,
                            "facet": "genre",
                            "match_kind": "exact",
                            "target_identity": _GENRE,
                            "target_name": "one",
                            "target_namespace": "musicbrainz_genre_id",
                            "source_record_id": f"musicbrainz:artist:{_MBID}",
                            "source_record_sha256": _RECORD_SHA,
                            "evidence_ref": "",
                        },
                    ],
                    "output_sha256": "b" * 64,
                }
            )
        )
        reconciliation = directory / "reconciliation.json"
        reconciliation.write_text(
            json.dumps(
                {
                    "dispositions": [
                        {
                            "source_item_id": "seed:one",
                            "musicbrainz_identities": [
                                {"namespace": "musicbrainz_genre_id", "identifier": _GENRE}
                            ],
                        }
                    ],
                    "output_sha256": "c" * 64,
                }
            )
        )
        return source, reconciliation

    def test_builds_and_replays_only_nonempty_exact_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source, reconciliation = self._write_inputs(directory)
            store = directory / "objects"
            receipt = build_portable_direct_proper_genre_custody(
                seed_target=source,
                seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                seed_target_output_sha256="b" * 64,
                reconciliation=reconciliation,
                object_store=store,
                receipt_output=directory / "receipt.json",
            )
            self.assertEqual(
                (receipt.claim_count, receipt.seed_count, receipt.artist_mbid_count), (1, 1, 1)
            )
            self.assertFalse(receipt.public_export_authorized)
            verify_portable_direct_proper_genre_custody(receipt, object_store=store)
            verify_portable_direct_proper_genre_custody_from_inputs(
                receipt,
                object_store=store,
                seed_target=source,
                reconciliation=reconciliation,
            )

    def test_rejects_compressed_byte_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source, reconciliation = self._write_inputs(directory)
            store = directory / "objects"
            receipt = build_portable_direct_proper_genre_custody(
                seed_target=source,
                seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                seed_target_output_sha256="b" * 64,
                reconciliation=reconciliation,
                object_store=store,
                receipt_output=directory / "receipt.json",
            )
            object_path = store / receipt.claims_object_key
            object_path.write_bytes(object_path.read_bytes() + b"mutated")
            with self.assertRaises(DirectProperGenreCustodyError):
                verify_portable_direct_proper_genre_custody(receipt, object_store=store)

    def test_refuses_receipt_replacement_and_changed_input_replay(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source, reconciliation = self._write_inputs(directory)
            store = directory / "objects"
            receipt_path = directory / "receipt.json"
            receipt = build_portable_direct_proper_genre_custody(
                seed_target=source,
                seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                seed_target_output_sha256="b" * 64,
                reconciliation=reconciliation,
                object_store=store,
                receipt_output=receipt_path,
            )
            with self.assertRaises(FileExistsError):
                build_portable_direct_proper_genre_custody(
                    seed_target=source,
                    seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    seed_target_output_sha256="b" * 64,
                    reconciliation=reconciliation,
                    object_store=store,
                    receipt_output=receipt_path,
                )
            source.write_text(source.read_text() + " ")
            with self.assertRaisesRegex(DirectProperGenreCustodyError, "inputs differ"):
                verify_portable_direct_proper_genre_custody_from_inputs(
                    receipt,
                    object_store=store,
                    seed_target=source,
                    reconciliation=reconciliation,
                )

    def test_rejects_claim_stream_exceeding_declared_count(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source, reconciliation = self._write_inputs(directory)
            store = directory / "objects"
            receipt = build_portable_direct_proper_genre_custody(
                seed_target=source,
                seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                seed_target_output_sha256="b" * 64,
                reconciliation=reconciliation,
                object_store=store,
                receipt_output=directory / "receipt.json",
            )
            bounded = receipt.model_copy(update={"claim_count": 0, "output_sha256": "0" * 64})
            bounded = bounded.model_copy(update={"output_sha256": receipt_sha256(bounded)})
            with self.assertRaisesRegex(DirectProperGenreCustodyError, "exceeds declared"):
                verify_portable_direct_proper_genre_custody(bounded, object_store=store)

    def test_rejects_declared_source_byte_hash_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source, reconciliation = self._write_inputs(directory)
            store = directory / "objects"
            receipt_path = directory / "receipt.json"
            with self.assertRaisesRegex(DirectProperGenreCustodyError, "differs from declared"):
                build_portable_direct_proper_genre_custody(
                    seed_target=source,
                    seed_target_byte_sha256="0" * 64,
                    seed_target_output_sha256="b" * 64,
                    reconciliation=reconciliation,
                    object_store=store,
                    receipt_output=receipt_path,
                )
            self.assertFalse(store.exists())
            self.assertFalse(receipt_path.exists())

    def test_rejects_declared_source_output_hash_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source, reconciliation = self._write_inputs(directory)
            store = directory / "objects"
            receipt_path = directory / "receipt.json"
            with self.assertRaisesRegex(DirectProperGenreCustodyError, "differs from declared"):
                build_portable_direct_proper_genre_custody(
                    seed_target=source,
                    seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    seed_target_output_sha256="0" * 64,
                    reconciliation=reconciliation,
                    object_store=store,
                    receipt_output=receipt_path,
                )
            self.assertFalse(store.exists())
            self.assertFalse(receipt_path.exists())

    def test_rejects_noncanonical_musicbrainz_genre_uuid(self) -> None:
        with self.assertRaises(ValueError):
            DirectProperGenreClaim(
                seed_id="seed:one",
                artist_mbid=_MBID,
                musicbrainz_genre_id="not-a-musicbrainz-genre-uuid",
                source_record_id=f"musicbrainz:artist:{_MBID}",
                source_record_sha256=_RECORD_SHA,
                source_evidence_ref="source:one",
            )


if __name__ == "__main__":
    unittest.main()
