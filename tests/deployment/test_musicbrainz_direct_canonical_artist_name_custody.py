"""Coverage for the custody-only direct MusicBrainz canonical-name projection."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    CanonicalArtistName,
    DirectCanonicalArtistNameCustodyError,
    build_direct_canonical_artist_name_custody,
    receipt_sha256,
    verify_direct_canonical_artist_name_custody,
    verify_direct_canonical_artist_name_custody_from_inputs,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    build_portable_direct_proper_genre_custody,
)
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    ArtistMetadataCounters,
    ArtistMetadataSettings,
    artist_metadata_artifact_sha256,
)

_ARTIST_A = "11111111-1111-4111-8111-111111111111"
_ARTIST_B = "22222222-2222-4222-8222-222222222222"
_GENRE = "33333333-3333-4333-8333-333333333333"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DirectCanonicalArtistNameCustodyTests(unittest.TestCase):
    def _direct_inputs(self, directory: Path) -> tuple[Path, Path, Path, Path]:
        seed_target = directory / "seed-target.json"
        source_rows = [
            {
                "seed_source_item_id": "seed:one",
                "seed_name": "one",
                "artist_id": artist,
                "facet": "genre",
                "match_kind": "exact",
                "target_identity": _GENRE,
                "target_name": "one",
                "target_namespace": "musicbrainz_genre_id",
                "source_record_id": f"musicbrainz:artist:{artist}",
                "source_record_sha256": f"{index:x}" * 64,
                "evidence_ref": f"source:{index}",
            }
            for index, artist in enumerate((_ARTIST_A, _ARTIST_B), start=1)
        ]
        seed_target.write_text(json.dumps({"evidence": source_rows, "output_sha256": "a" * 64}))
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
                    "output_sha256": "b" * 64,
                }
            )
        )
        direct_store = directory / "direct-objects"
        direct_receipt_path = directory / "direct-receipt.json"
        build_portable_direct_proper_genre_custody(
            seed_target=seed_target,
            seed_target_byte_sha256=_sha256(seed_target),
            seed_target_output_sha256="a" * 64,
            reconciliation=reconciliation,
            object_store=direct_store,
            receipt_output=direct_receipt_path,
        )
        return seed_target, reconciliation, direct_store, direct_receipt_path

    def _metadata_inputs(self, directory: Path) -> tuple[Path, Path]:
        database = directory / "metadata.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute(
                """CREATE TABLE artist_summary (
                    artist_mbid TEXT PRIMARY KEY NOT NULL,
                    canonical_name TEXT,
                    canonical_name_variant_count INTEGER NOT NULL
                ) WITHOUT ROWID"""
            )
            connection.executemany(
                "INSERT INTO artist_summary VALUES (?, ?, ?)",
                [(_ARTIST_A, "Canonical A", 1), (_ARTIST_B, "Canonical B", 2)],
            )
        artifact_base = ArtistMetadataArtifact(
            source_archive_sha256="c" * 64,
            source_archive_bytes=1,
            source_snapshot="test",
            evidence_output_sha256="d" * 64,
            evidence_database_sha256="e" * 64,
            evidence_database_bytes=1,
            metadata_database_sha256=_sha256(database),
            metadata_database_bytes=database.stat().st_size,
            target_artist_count=2,
            observed_artist_count=2,
            conflicting_artist_count=1,
            counters=ArtistMetadataCounters(
                records_seen=1,
                records_parsed=1,
                rejected_records=0,
                target_credit_observations=2,
            ),
            settings=ArtistMetadataSettings(),
            output_sha256="0" * 64,
        )
        artifact = artifact_base.model_copy(
            update={"output_sha256": artist_metadata_artifact_sha256(artifact_base)}
        )
        artifact_path = directory / "metadata-artifact.json"
        artifact_path.write_text(artifact.model_dump_json() + "\n")
        return database, artifact_path

    def test_builds_exact_name_facts_and_excludes_ambiguous_names(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, _, direct_store, direct_receipt_path = self._direct_inputs(directory)
            database, artifact_path = self._metadata_inputs(directory)
            store = directory / "name-objects"
            receipt = build_direct_canonical_artist_name_custody(
                direct_custody_receipt=direct_receipt_path,
                direct_object_store=direct_store,
                metadata_artifact=artifact_path,
                metadata_database=database,
                object_store=store,
                receipt_output=directory / "name-receipt.json",
            )
            self.assertEqual(
                (receipt.direct_artist_mbid_count, receipt.canonical_name_count), (2, 1)
            )
            self.assertEqual(receipt.absent_direct_artist_mbid_count, 1)
            self.assertFalse(receipt.credited_as_fallback_used)
            self.assertFalse(receipt.public_export_authorized)
            self.assertFalse(receipt.serving_authorized)
            verify_direct_canonical_artist_name_custody(receipt, object_store=store)
            verify_direct_canonical_artist_name_custody_from_inputs(
                receipt,
                object_store=store,
                direct_custody_receipt=direct_receipt_path,
                direct_object_store=direct_store,
                metadata_artifact=artifact_path,
                metadata_database=database,
            )

    def test_rejects_changed_metadata_database(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, _, direct_store, direct_receipt_path = self._direct_inputs(directory)
            database, artifact_path = self._metadata_inputs(directory)
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE artist_summary SET canonical_name = 'Changed'")
            with self.assertRaisesRegex(DirectCanonicalArtistNameCustodyError, "does not match"):
                build_direct_canonical_artist_name_custody(
                    direct_custody_receipt=direct_receipt_path,
                    direct_object_store=direct_store,
                    metadata_artifact=artifact_path,
                    metadata_database=database,
                    object_store=directory / "name-objects",
                    receipt_output=directory / "name-receipt.json",
                )

    def test_rejects_metadata_artifact_with_an_invalid_embedded_hash(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, _, direct_store, direct_receipt_path = self._direct_inputs(directory)
            database, artifact_path = self._metadata_inputs(directory)
            payload = json.loads(artifact_path.read_text())
            payload["output_sha256"] = "0" * 64
            artifact_path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(
                DirectCanonicalArtistNameCustodyError, "artifact is invalid"
            ):
                build_direct_canonical_artist_name_custody(
                    direct_custody_receipt=direct_receipt_path,
                    direct_object_store=direct_store,
                    metadata_artifact=artifact_path,
                    metadata_database=database,
                    object_store=directory / "name-objects",
                    receipt_output=directory / "name-receipt.json",
                )

    def test_rejects_name_object_byte_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, _, direct_store, direct_receipt_path = self._direct_inputs(directory)
            database, artifact_path = self._metadata_inputs(directory)
            store = directory / "name-objects"
            receipt = build_direct_canonical_artist_name_custody(
                direct_custody_receipt=direct_receipt_path,
                direct_object_store=direct_store,
                metadata_artifact=artifact_path,
                metadata_database=database,
                object_store=store,
                receipt_output=directory / "name-receipt.json",
            )
            object_path = store / receipt.names_object_key
            object_path.write_bytes(object_path.read_bytes() + b"changed")
            with self.assertRaises(DirectCanonicalArtistNameCustodyError):
                verify_direct_canonical_artist_name_custody(receipt, object_store=store)

    def test_source_replay_rejects_a_self_consistent_altered_name_object(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, _, direct_store, direct_receipt_path = self._direct_inputs(directory)
            database, artifact_path = self._metadata_inputs(directory)
            store = directory / "name-objects"
            receipt = build_direct_canonical_artist_name_custody(
                direct_custody_receipt=direct_receipt_path,
                direct_object_store=direct_store,
                metadata_artifact=artifact_path,
                metadata_database=database,
                object_store=store,
                receipt_output=directory / "name-receipt.json",
            )
            altered_name = CanonicalArtistName(
                artist_mbid=_ARTIST_A,
                canonical_name="Altered A",
            )
            altered_line = altered_name.model_dump_json(exclude_none=True).encode() + b"\n"
            altered_object = directory / "altered.jsonl.zst"
            with (
                altered_object.open("wb") as compressed,
                zstandard.ZstdCompressor(level=6, threads=0, write_checksum=True).stream_writer(
                    compressed, closefd=False
                ) as writer,
            ):
                writer.write(altered_line)
            object_sha256 = _sha256(altered_object)
            object_key = (
                f"musicbrainz-direct-canonical-artist-name-custody/sha256/{object_sha256}.jsonl.zst"
            )
            object_path = store / object_key
            object_path.parent.mkdir(parents=True, exist_ok=True)
            object_path.write_bytes(altered_object.read_bytes())
            altered_base = receipt.model_copy(
                update={
                    "names_object_key": object_key,
                    "names_object_sha256": object_sha256,
                    "names_object_byte_size": altered_object.stat().st_size,
                    "names_uncompressed_sha256": hashlib.sha256(altered_line).hexdigest(),
                    "output_sha256": "0" * 64,
                }
            )
            altered_receipt = altered_base.model_copy(
                update={"output_sha256": receipt_sha256(altered_base)}
            )
            verify_direct_canonical_artist_name_custody(altered_receipt, object_store=store)
            with self.assertRaisesRegex(
                DirectCanonicalArtistNameCustodyError, "name facts do not replay"
            ):
                verify_direct_canonical_artist_name_custody_from_inputs(
                    altered_receipt,
                    object_store=store,
                    direct_custody_receipt=direct_receipt_path,
                    direct_object_store=direct_store,
                    metadata_artifact=artifact_path,
                    metadata_database=database,
                )


if __name__ == "__main__":
    unittest.main()
