import hashlib
import io
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.analysis.lastfm_1k_feasibility import (
    LastFm1kFeasibilityError,
    LastFm1kFeasibilitySettings,
    run_lastfm_1k_feasibility_scan,
)

_ARTIST = "aaaaaaaa-0000-4000-8000-000000000001"
_TRACK = "00000000-0000-4000-8000-000000000002"


def _archive(path: Path, rows: list[bytes]) -> str:
    payload = b"".join(rows)
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("lastfm-dataset-1K/userid-timestamp-artid-artname-traid-traname.tsv")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        private = tarfile.TarInfo("lastfm-dataset-1K/private-users.tsv")
        private.size = 16
        archive.addfile(private, io.BytesIO(b"do not read this\n"))
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _archive_with_duplicate_listens_members(path: Path) -> str:
    payload = _row("2009-04-08T01:57:47Z", _ARTIST, _TRACK)
    with tarfile.open(path, "w:gz") as archive:
        for member_name in (
            "first/userid-timestamp-artid-artname-traid-traname.tsv",
            "second/userid-timestamp-artid-artname-traid-traname.tsv",
        ):
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _catalog(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.executescript(
            """CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
               CREATE TABLE entity_identifiers (identifier_type_id INTEGER, normalized_value TEXT);
               INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id');"""
        )
        database.execute("INSERT INTO entity_identifiers VALUES (1, ?)", (_ARTIST,))


def _row(timestamp: str, artist: str, track: str) -> bytes:
    return f"private-user\t{timestamp}\t{artist}\tprivate artist\t{track}\tprivate title\n".encode()


class LastFm1kFeasibilityTests(unittest.TestCase):
    def test_counts_only_valid_ids_timestamps_abstentions_and_catalog_overlap(self) -> None:
        rows = [
            _row("2009-04-08T01:57:47Z", _ARTIST, _TRACK),
            _row("bad", _ARTIST.upper(), "missing"),
            b"not\ta\tsix\tfield\trow\n",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            catalog = root / "catalog.sqlite"
            archive_md5 = _archive(archive, rows)
            _catalog(catalog)
            archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch("opennoise.analysis.lastfm_1k_feasibility._ARCHIVE_MD5", archive_md5):
                receipt = run_lastfm_1k_feasibility_scan(
                    archive_path=archive,
                    supplied_archive_sha256=archive_sha256,
                    catalog_path=catalog,
                    settings=LastFm1kFeasibilitySettings(maximum_rows=len(rows)),
                )
        self.assertEqual(receipt.raw_rows_seen, 3)
        self.assertEqual(receipt.valid_tsv_rows, 2)
        self.assertEqual(receipt.malformed_rows, 1)
        self.assertEqual(receipt.abstained_rows, 1)
        self.assertEqual(receipt.valid_canonical_artist_mbid_rows, 1)
        self.assertEqual(receipt.valid_canonical_track_mbid_rows, 1)
        self.assertEqual(receipt.valid_timestamp_rows, 1)
        self.assertEqual(receipt.valid_exact_artist_track_timestamp_rows, 1)
        self.assertEqual(receipt.catalog_exact_artist_overlap_count, 1)
        serialized = receipt.model_dump_json()
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("private artist", serialized)
        self.assertNotIn("private title", serialized)

    def test_abstains_from_invalid_iso_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            archive_md5 = _archive(archive, [_row("2009-04-08 01:57:47", _ARTIST, _TRACK)])
            archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch("opennoise.analysis.lastfm_1k_feasibility._ARCHIVE_MD5", archive_md5):
                receipt = run_lastfm_1k_feasibility_scan(
                    archive_path=archive,
                    supplied_archive_sha256=archive_sha256,
                    settings=LastFm1kFeasibilitySettings(maximum_rows=1),
                )
        self.assertEqual(receipt.valid_tsv_rows, 1)
        self.assertEqual(receipt.valid_timestamp_rows, 0)
        self.assertEqual(receipt.abstained_rows, 1)

    def test_counts_an_oversized_line_as_malformed_without_retaining_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            oversized = b"private-user\t" + b"x" * 100 + b"\n"
            archive_md5 = _archive(archive, [oversized])
            archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch("opennoise.analysis.lastfm_1k_feasibility._ARCHIVE_MD5", archive_md5):
                receipt = run_lastfm_1k_feasibility_scan(
                    archive_path=archive,
                    supplied_archive_sha256=archive_sha256,
                    settings=LastFm1kFeasibilitySettings(maximum_rows=1, maximum_line_bytes=64),
                )
        self.assertEqual(receipt.raw_rows_seen, 1)
        self.assertEqual(receipt.malformed_rows, 1)
        self.assertEqual(receipt.valid_tsv_rows, 0)

    def test_rejects_duplicate_listens_tsv_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            archive_md5 = _archive_with_duplicate_listens_members(archive)
            archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            with (
                patch("opennoise.analysis.lastfm_1k_feasibility._ARCHIVE_MD5", archive_md5),
                self.assertRaisesRegex(LastFm1kFeasibilityError, "multiple listens TSV"),
            ):
                run_lastfm_1k_feasibility_scan(
                    archive_path=archive,
                    supplied_archive_sha256=archive_sha256,
                    settings=LastFm1kFeasibilitySettings(maximum_rows=2),
                )

    def test_rejects_an_independently_pinned_sha256_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            archive_md5 = _archive(archive, [_row("2009-04-08T01:57:47Z", _ARTIST, _TRACK)])
            with (
                patch("opennoise.analysis.lastfm_1k_feasibility._ARCHIVE_MD5", archive_md5),
                self.assertRaisesRegex(LastFm1kFeasibilityError, "SHA-256"),
            ):
                run_lastfm_1k_feasibility_scan(
                    archive_path=archive,
                    supplied_archive_sha256="0" * 64,
                    settings=LastFm1kFeasibilitySettings(maximum_rows=1),
                )
