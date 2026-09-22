"""Synthetic source-first recovery tests; these never read the large dump."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    _build_direct_artist_name_recovery,
    _collect_variants,
    _source_limits,
    build_direct_artist_name_recovery,
    iter_verified_unique_recovered_names,
    receipt_sha256,
    verify_direct_artist_name_recovery,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    build_direct_canonical_artist_name_custody,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    build_portable_direct_proper_genre_custody,
)
from opennoise.models.pipeline import SourceLimits
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    ArtistMetadataCounters,
    ArtistMetadataSettings,
    artist_metadata_artifact_sha256,
)
from opennoise.sources.musicbrainz import iter_artist_archive_raw_records

_ARTISTS = tuple(f"{index:08x}-1111-4111-8111-{index:012x}" for index in range(1, 8))
_ARTIST_A, _ARTIST_B, _ARTIST_C, _ARTIST_D, _ARTIST_E, _ARTIST_F, _ARTIST_G = _ARTISTS
_GENRE = "99999999-9999-4999-8999-999999999999"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(artist_id: str, name: object = "Artist") -> bytes:
    return json.dumps({"id": artist_id, "name": name}, separators=(",", ":")).encode()


def _write_artist_archive(path: Path, rows: tuple[bytes, ...]) -> None:
    with tarfile.open(path, mode="w:xz") as archive:
        schema = b"1\n"
        schema_info = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema_info.size = len(schema)
        archive.addfile(schema_info, io.BytesIO(schema))
        payload = b"\n".join(rows) + b"\n"
        member = tarfile.TarInfo("mbdump/artist")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


class DirectArtistNameRecoveryTests(unittest.TestCase):
    def _custody_inputs(self, directory: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
        seed_target = directory / "seed-target.json"
        evidence = [
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
            for index, artist in enumerate(_ARTISTS[:6], start=1)
        ]
        seed_target.write_text(json.dumps({"evidence": evidence, "output_sha256": "a" * 64}))
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
        direct_receipt = directory / "direct-receipt.json"
        build_portable_direct_proper_genre_custody(
            seed_target=seed_target,
            seed_target_byte_sha256=_sha256(seed_target),
            seed_target_output_sha256="a" * 64,
            reconciliation=reconciliation,
            object_store=direct_store,
            receipt_output=direct_receipt,
        )

        metadata_database = directory / "metadata.sqlite"
        with sqlite3.connect(metadata_database) as connection:
            connection.execute(
                """CREATE TABLE artist_summary (
                    artist_mbid TEXT PRIMARY KEY NOT NULL,
                    canonical_name TEXT,
                    canonical_name_variant_count INTEGER NOT NULL
                ) WITHOUT ROWID"""
            )
            connection.execute(
                "INSERT INTO artist_summary VALUES (?, ?, ?)", (_ARTIST_A, "Prior name", 1)
            )
        metadata = ArtistMetadataArtifact(
            source_archive_sha256="c" * 64,
            source_archive_bytes=1,
            source_snapshot="synthetic",
            evidence_output_sha256="d" * 64,
            evidence_database_sha256="e" * 64,
            evidence_database_bytes=1,
            metadata_database_sha256=_sha256(metadata_database),
            metadata_database_bytes=metadata_database.stat().st_size,
            target_artist_count=1,
            observed_artist_count=1,
            conflicting_artist_count=0,
            counters=ArtistMetadataCounters(
                records_seen=1,
                records_parsed=1,
                rejected_records=0,
                target_credit_observations=1,
            ),
            settings=ArtistMetadataSettings(),
            output_sha256="0" * 64,
        )
        metadata = metadata.model_copy(
            update={"output_sha256": artist_metadata_artifact_sha256(metadata)}
        )
        metadata_path = directory / "metadata-artifact.json"
        metadata_path.write_text(metadata.model_dump_json() + "\n")
        name_store = directory / "name-objects"
        name_receipt = directory / "name-receipt.json"
        build_direct_canonical_artist_name_custody(
            direct_custody_receipt=direct_receipt,
            direct_object_store=direct_store,
            metadata_artifact=metadata_path,
            metadata_database=metadata_database,
            object_store=name_store,
            receipt_output=name_receipt,
        )
        return seed_target, reconciliation, direct_store, direct_receipt, name_store, name_receipt

    def test_raw_archive_iterator_preserves_ordinal_and_record_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "artist.tar.xz"
            payload = _record(_ARTIST_A, "Source name")
            _write_artist_archive(archive, (payload,))
            rows = tuple(iter_artist_archive_raw_records(archive, SourceLimits()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ordinal, 0)
        self.assertEqual(rows[0].content_sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(rows[0].payload, payload)

    def test_recovery_partitions_targets_and_excludes_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, _, direct_store, direct_receipt, name_store, name_receipt = self._custody_inputs(
                directory
            )
            archive = directory / "artist.tar.xz"
            _write_artist_archive(
                archive,
                (
                    _record(_ARTIST_B, "Recovered B"),
                    _record(_ARTIST_B, "Recovered B"),
                    _record(_ARTIST_C, "Conflicting C one"),
                    _record(_ARTIST_C, "Conflicting C two"),
                    _record(_ARTIST_D, "   "),
                    _record(_ARTIST_E, 42),
                    _record(_ARTIST_G, "Not a target"),
                    b"{malformed-json",
                ),
            )
            receipt_path = directory / "recovery-receipt.json"
            object_store = directory / "recovery-objects"
            receipt = _build_direct_artist_name_recovery(
                direct_custody_receipt=direct_receipt,
                direct_object_store=direct_store,
                direct_custody_receipt_sha256=_sha256(direct_receipt),
                name_custody_receipt=name_receipt,
                name_object_store=name_store,
                name_custody_receipt_sha256=_sha256(name_receipt),
                source_archive=archive,
                expected_source_archive_sha256=_sha256(archive),
                expected_source_archive_bytes=archive.stat().st_size,
                source_archive_snapshot="synthetic-fixture",
                object_store=object_store,
                receipt_output=receipt_path,
            )
            verify_direct_artist_name_recovery(receipt, object_store=object_store)
            unique_rows = tuple(
                iter_verified_unique_recovered_names(receipt, object_store=object_store)
            )
            object_path = object_store / receipt.recovery_object_key
            with (
                object_path.open("rb") as compressed,
                zstandard.ZstdDecompressor().stream_reader(compressed) as reader,
            ):
                rows = tuple(json.loads(line) for line in reader.read().splitlines())

        self.assertEqual(receipt.recovery_target_count, 5)
        self.assertEqual(
            receipt.recovered_unique_mbid_count
            + receipt.conflicting_mbid_count
            + receipt.missing_mbid_count
            + receipt.invalid_name_only_mbid_count,
            5,
        )
        self.assertEqual(receipt.recovered_unique_mbid_count, 1)
        self.assertEqual(receipt.conflicting_mbid_count, 1)
        self.assertEqual(receipt.conflicting_name_variant_count, 2)
        self.assertEqual(receipt.invalid_name_only_mbid_count, 2)
        self.assertEqual(receipt.missing_mbid_count, 1)
        self.assertEqual(receipt.duplicate_same_name_observation_count, 1)
        self.assertEqual(receipt.malformed_source_record_count, 1)
        self.assertEqual(receipt.targeted_source_observation_count, 6)
        canonical_rows = [row for row in rows if row["name_status"] == "unique_canonical_name"]
        self.assertEqual([row["artist_mbid"] for row in canonical_rows], [_ARTIST_B])
        self.assertEqual([row.artist_mbid for row in unique_rows], [_ARTIST_B])
        self.assertNotIn(_ARTIST_C, {row["artist_mbid"] for row in canonical_rows})
        self.assertEqual(
            {
                row["artist_mbid"]
                for row in rows
                if row["name_status"] == "conflicting_name_variant"
            },
            {_ARTIST_C},
        )
        self.assertFalse(receipt.public_export_authorized)
        self.assertFalse(receipt.serving_authorized)
        self.assertFalse(receipt.membership_claims_authorized)

    def test_verifier_rejects_rehashed_false_conflict_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, _, direct_store, direct_receipt, name_store, name_receipt = self._custody_inputs(
                directory
            )
            archive = directory / "artist.tar.xz"
            _write_artist_archive(
                archive,
                (
                    _record(_ARTIST_B, "Recovered B"),
                    _record(_ARTIST_C, "Conflicting C one"),
                    _record(_ARTIST_C, "Conflicting C two"),
                ),
            )
            object_store = directory / "recovery-objects"
            receipt = _build_direct_artist_name_recovery(
                direct_custody_receipt=direct_receipt,
                direct_object_store=direct_store,
                direct_custody_receipt_sha256=_sha256(direct_receipt),
                name_custody_receipt=name_receipt,
                name_object_store=name_store,
                name_custody_receipt_sha256=_sha256(name_receipt),
                source_archive=archive,
                expected_source_archive_sha256=_sha256(archive),
                expected_source_archive_bytes=archive.stat().st_size,
                source_archive_snapshot="synthetic-fixture",
                object_store=object_store,
                receipt_output=directory / "recovery-receipt.json",
            )
            forged = receipt.model_copy(
                update={
                    "conflicting_mbid_count": 0,
                    "missing_mbid_count": receipt.missing_mbid_count + 1,
                    "output_sha256": "0" * 64,
                }
            )
            forged = forged.model_copy(update={"output_sha256": receipt_sha256(forged)})
            with self.assertRaisesRegex(RuntimeError, "rows do not match receipt accounting"):
                verify_direct_artist_name_recovery(forged, object_store=object_store)

    def test_name_source_with_invalid_id_is_counted_as_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "artist.tar.xz"
            _write_artist_archive(archive, (b'{"id":"not-a-uuid","name":"Bad id"}',))
            variants, invalid_ids, total, targeted, invalid_names, oversized, malformed = (
                _collect_variants(
                    archive=archive,
                    target_ids={_ARTIST_A},
                    limits=_source_limits(),
                )
            )
        self.assertEqual(variants, {})
        self.assertEqual(invalid_ids, set())
        self.assertEqual(total, 1)
        self.assertEqual(targeted, 0)
        self.assertEqual(invalid_names, 0)
        self.assertEqual(oversized, 0)
        self.assertEqual(malformed, 1)

    def test_recovery_receipt_output_is_no_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, _, direct_store, direct_receipt, name_store, name_receipt = self._custody_inputs(
                directory
            )
            receipt_path = directory / "already-there.json"
            receipt_path.write_text("kept")
            with self.assertRaises(FileExistsError):
                build_direct_artist_name_recovery(
                    direct_custody_receipt=direct_receipt,
                    direct_object_store=direct_store,
                    direct_custody_receipt_sha256=_sha256(direct_receipt),
                    name_custody_receipt=name_receipt,
                    name_object_store=name_store,
                    name_custody_receipt_sha256=_sha256(name_receipt),
                    source_archive=directory / "not-read.tar.xz",
                    object_store=directory / "recovery-objects",
                    receipt_output=receipt_path,
                )
            self.assertEqual(receipt_path.read_text(), "kept")


if __name__ == "__main__":
    unittest.main()
