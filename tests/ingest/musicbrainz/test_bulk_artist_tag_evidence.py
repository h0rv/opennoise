from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pydantic import HttpUrl, TypeAdapter

from opennoise.common import sha256_json
from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import (
    BulkArtistTagError,
    CoreArtistPrefixReceipt,
    build_bulk_artist_tag_artifact,
    iter_bulk_artist_tag_rows,
    verify_bulk_artist_tag_artifact,
)
from opennoise.ingest.musicbrainz.derived_entity_tags import DerivedEntityTagError
from opennoise.models.sources import DownloadSource

_A = "00000000-0000-4000-8000-000000000001"
_B = "00000000-0000-4000-8000-000000000002"


def _tar(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:bz2") as archive:
        for name, payload in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def _artist_row(numeric_id: int, mbid: str, name: str) -> bytes:
    columns = [
        str(numeric_id),
        mbid,
        name,
        name,
        r"\N",
        r"\N",
        r"\N",
        r"\N",
        r"\N",
        r"\N",
        r"\N",
        r"\N",
        r"\N",
        "",
        "0",
        r"\N",
        "f",
        r"\N",
        r"\N",
    ]
    return ("\t".join(columns) + "\n").encode()


def _derived_source(path: Path) -> DownloadSource:
    payload = path.read_bytes()
    return DownloadSource(
        id="fixture_musicbrainz_derived",
        adapter="musicbrainz_postgres_derived_v1",
        snapshot="fixture",
        url=HttpUrl("https://data.metabrainz.org/fixture/mbdump-derived.tar.bz2"),
        discovery_url=HttpUrl("https://musicbrainz.org/doc/MusicBrainz_Database/Download"),
        expected_content_type="application/octet-stream",
        compression="tar.bz2",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="CC-BY-NC-SA-3.0",
        license_url="https://musicbrainz.org/doc/About/Data_License",
        rights_classification="restricted_research",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=False,
    )


class BulkArtistTagEvidenceTests(unittest.TestCase):
    def _fixtures(
        self, directory: Path
    ) -> tuple[Path, DownloadSource, Path, CoreArtistPrefixReceipt, Path]:
        rows = _artist_row(100, _A, r"Test\tArtist") + _artist_row(200, _B, "No Tags")
        core = directory / "core-prefix.tar.bz2"
        _tar(core, {"mbdump/artist": rows})
        core_bytes = core.read_bytes()
        core_receipt = CoreArtistPrefixReceipt(
            snapshot="fixture",
            archive_url="https://data.metabrainz.org/fixture/mbdump.tar.bz2",
            archive_bytes=900,
            archive_sha256="a" * 64,
            prefix_bytes=len(core_bytes),
            prefix_sha256=hashlib.sha256(core_bytes).hexdigest(),
            artist_member_bytes=len(rows),
            artist_member_sha256=hashlib.sha256(rows).hexdigest(),
            artist_row_count=2,
            schema_sequence="31",
            observed_at="2026-09-30T00:00:00Z",
        )
        derived = directory / "derived.tar.bz2"
        _tar(
            derived,
            {
                "mbdump/artist_tag": (
                    b"100\t5\t2\t2026-09-30 00:00:00+00\n"
                    b"100\t6\t0\t2026-09-30 00:00:00+00\n"
                    b"100\t7\t-1\t2026-09-30 00:00:00+00\n"
                ),
                "mbdump/artist_tag_raw": b"editor-specific ignored data\n",
                "mbdump/tag": b"5\trock\t1\n6\telectro\\trock\t1\n7\tnoise\t1\n",
            },
        )
        derived_source = _derived_source(derived)
        (directory / "SHA256SUMS").write_text(
            f"{derived_source.verified_sha256()} *mbdump-derived.tar.bz2\n"
            f"{core_receipt.archive_sha256} *mbdump.tar.bz2\n",
            encoding="ascii",
        )
        (directory / "snapshot-index.html").write_text(
            "fixture/ mbdump.tar.bz2 mbdump-derived.tar.bz2", encoding="utf-8"
        )
        (directory / "license.html").write_text(
            "CC0 Attribution-NonCommercial-ShareAlike 3.0", encoding="utf-8"
        )
        selection = directory / "selection.jsonl"
        selection.write_text(
            json.dumps({"artist_mbid": _A})
            + "\n"
            + json.dumps({"artist_mbid": "00000000-0000-4000-8000-000000000003"})
            + "\n"
        )
        return derived, derived_source, core, core_receipt, selection

    def test_exact_uuid_join_preserves_nonpositive_counts_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            derived, derived_source, core, receipt, selection = self._fixtures(directory)
            output = directory / "output"
            result = build_bulk_artist_tag_artifact(
                derived_archive=derived,
                derived_source=derived_source,
                core_prefix=core,
                core_receipt=receipt,
                selection_source_path=selection,
                selection_artist_count=2,
                derived_observed_at="2026-09-30T00:00:00Z",
                output_directory=output,
            )
            rows = list(iter_bulk_artist_tag_rows(directory=output, expected_count=2))
            self.assertEqual(len(rows), 2)
            row = rows[0]
            tags = TypeAdapter(list[dict[str, object]]).validate_python(row["tags"])
            self.assertEqual(row["artist_mbid"], _A)
            self.assertEqual(row["name"], "Test\tArtist")
            self.assertEqual(
                [(tag["name"], tag["count"]) for tag in tags],
                [("rock", 2), ("electro\trock", 0), ("noise", -1)],
            )
            self.assertEqual(row["genres"], [])
            self.assertEqual(result["matched_primary_artist_count"], 1)
            self.assertEqual(
                result["absent_primary_artist_ids"], ["00000000-0000-4000-8000-000000000003"]
            )
            self.assertEqual(result["tables_excluded"], ["mbdump/artist_tag_raw"])
            counts = TypeAdapter(dict[str, int]).validate_python(result["counts"])
            self.assertEqual(counts["source_artist_tag_row_count"], 3)
            self.assertEqual(counts["primary_artist_tag_zero_row_count"], 1)
            self.assertEqual(counts["primary_artist_tag_negative_row_count"], 1)
            self.assertEqual(rows[1]["source_state"], "absent_from_current_artist_dump")
            self.assertIsNone(rows[1]["name"])
            self.assertEqual(rows[1]["tags"], [])

    def test_replay_rejects_changed_jsonl_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            derived, derived_source, core, receipt, selection = self._fixtures(directory)
            output = directory / "output"
            build_bulk_artist_tag_artifact(
                derived_archive=derived,
                derived_source=derived_source,
                core_prefix=core,
                core_receipt=receipt,
                selection_source_path=selection,
                selection_artist_count=2,
                derived_observed_at="2026-09-30T00:00:00Z",
                output_directory=output,
            )
            rows_path = output / "artist-tags.jsonl"
            rows_path.write_bytes(rows_path.read_bytes() + b"{}\n")
            with self.assertRaisesRegex(BulkArtistTagError, "does not replay"):
                verify_bulk_artist_tag_artifact(
                    derived_archive=derived,
                    derived_source=derived_source,
                    core_prefix=core,
                    core_receipt=receipt,
                    selection_source_path=selection,
                    selection_artist_count=2,
                    derived_observed_at="2026-09-30T00:00:00Z",
                    directory=output,
                )

    def test_partial_prefix_cannot_claim_whole_archive_hash_and_snapshot_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            derived, derived_source, core, receipt, selection = self._fixtures(directory)
            for changed in (
                replace(receipt, whole_archive_sha256_verified=True),
                replace(receipt, snapshot="older-snapshot"),
            ):
                with self.subTest(receipt=changed), self.assertRaises(BulkArtistTagError):
                    build_bulk_artist_tag_artifact(
                        derived_archive=derived,
                        derived_source=derived_source,
                        core_prefix=core,
                        core_receipt=changed,
                        selection_source_path=selection,
                        selection_artist_count=2,
                        derived_observed_at="2026-09-30T00:00:00Z",
                        output_directory=directory / "invalid-output",
                    )

    def test_reader_rejects_laundered_whole_archive_verification_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            derived, derived_source, core, core_receipt, selection = self._fixtures(directory)
            output = directory / "output"
            build_bulk_artist_tag_artifact(
                derived_archive=derived,
                derived_source=derived_source,
                core_prefix=core,
                core_receipt=core_receipt,
                selection_source_path=selection,
                selection_artist_count=2,
                derived_observed_at="2026-09-30T00:00:00Z",
                output_directory=output,
            )
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["core_archive_sha256_verified"] = True
            receipt["output_sha256"] = sha256_json(
                {key: value for key, value in receipt.items() if key != "output_sha256"}
            )
            receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(BulkArtistTagError, "cannot claim whole-archive"):
                list(iter_bulk_artist_tag_rows(directory=output, expected_count=2))

    def test_rejects_changed_core_prefix_and_trailing_derived_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            derived, derived_source, core, receipt, selection = self._fixtures(directory)
            core.write_bytes(core.read_bytes() + b"trailing")
            with self.assertRaisesRegex(BulkArtistTagError, "core prefix byte count"):
                build_bulk_artist_tag_artifact(
                    derived_archive=derived,
                    derived_source=derived_source,
                    core_prefix=core,
                    core_receipt=receipt,
                    selection_source_path=selection,
                    selection_artist_count=2,
                    derived_observed_at="2026-09-30T00:00:00Z",
                    output_directory=directory / "out-core",
                )
            derived.write_bytes(derived.read_bytes() + b"trailing")
            with self.assertRaisesRegex(DerivedEntityTagError, "byte count"):
                build_bulk_artist_tag_artifact(
                    derived_archive=derived,
                    derived_source=derived_source,
                    core_prefix=directory / "core-prefix.tar.bz2",
                    core_receipt=receipt,
                    selection_source_path=selection,
                    selection_artist_count=2,
                    derived_observed_at="2026-09-30T00:00:00Z",
                    output_directory=directory / "out-derived",
                )


if __name__ == "__main__":
    unittest.main()
