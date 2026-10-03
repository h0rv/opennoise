"""Adversarial HTTP, ZIP custody, and independent native metadata replay."""

import bz2
import io
import json
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

import httpx
import zstandard

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.fma_static import verified_tables
from opennoise.ingest.fma import corpus

README = (Path(__file__).resolve().parents[3] / "data/examples/fma-source/README.md").read_bytes()
GENRES = "genre_id,genre_parent_id,genre_title\n21,,Hip-Hop\n"
ARTISTS = "artist_id,artist_name\n1,AWOL\n"
TRACKS = (
    "track_id,artist_id,artist_name,track_title,track_genres,"
    "license_title,license_url,track_url,album_id,album_title\n"
    "2,1,AWOL,Food,\"[{'genre_id': '21'}]\",CC BY-NC-SA,"
    "https://cc.example/by-nc-sa,http://fma.example/food,17,Album\n"
    "3,999,Unknown,No tags,,Unknown,,,,\n"
)


def fixture_zip() -> bytes:
    """Create native compressed CSV members with an excluded proprietary trap."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_BZIP2) as archive:
        for name, payload in zip(corpus.MEMBERS, (GENRES, ARTISTS, TRACKS), strict=True):
            archive.writestr(name, payload)
        archive.writestr("fma_metadata/raw_echonest.csv", "PROPRIETARY: never fetched")
    return output.getvalue()


class CorpusTests(unittest.TestCase):
    """Test response bounds, native CRCs, exact IDs, and offline reproduction."""

    def test_range_response_rejects_full_body_etag_encoding_and_length_changes(self) -> None:
        """A successful request still needs exact native object and range agreement."""
        headers = {
            "content-range": f"bytes 10-19/{corpus.ARCHIVE_BYTES}",
            "etag": corpus.ETAG,
            "content-length": "10",
        }
        corpus.check_range(206, headers, 10, 19)
        for status, changed in [
            (200, headers),
            (206, {**headers, "etag": "changed"}),
            (206, {**headers, "content-encoding": "gzip"}),
            (206, {**headers, "content-range": "bytes 10-20/99"}),
            (206, {**headers, "content-length": "11"}),
        ]:
            with self.subTest(status=status, changed=changed), self.assertRaises(ValueError):
                corpus.check_range(status, changed, 10, 19)

    def test_native_range_rejects_truncation_and_overflow(self) -> None:
        """Declared lengths cannot substitute for counting the bytes actually read."""
        for payload in (b"short", b"too many bytes"):

            def handler(_request: httpx.Request, body: bytes = payload) -> httpx.Response:
                return httpx.Response(
                    206,
                    headers={
                        "content-range": f"bytes 10-19/{corpus.ARCHIVE_BYTES}",
                        "etag": corpus.ETAG,
                        "content-length": "10",
                    },
                    stream=httpx.ByteStream(body),
                )

            with (
                self.subTest(payload=payload),
                tempfile.TemporaryDirectory() as temporary,
                httpx.Client(transport=httpx.MockTransport(handler)) as client,
                self.assertRaises(ValueError),
            ):
                corpus.capture_range(client, Path(temporary), "bad.range", 10, 19)

    def test_stream_crc_and_uncompressed_size_are_not_only_receipt_hashes(self) -> None:
        """Corrupt CRC and decompression overflow both fail at the native stream."""
        for crc, length in [(0, 3), (zlib.crc32(b"abc"), 2), (zlib.crc32(b"abc"), 4)]:
            reader = corpus.CheckedCSV(
                bz2.BZ2File(io.BytesIO(bz2.compress(b"abc"))),
                {"crc32": crc, "uncompressed_bytes": length},
            )
            with self.subTest(crc=crc, length=length), self.assertRaises(ValueError):
                io.BufferedReader(reader).read()

    def test_native_album_identity_preserves_distinct_artists_and_missingness(self) -> None:
        """Album overlap is observable without merging artists or filling invalid IDs."""
        first = corpus.project_row("tracks", {"track_id": "1", "artist_id": "10", "album_id": "77"})
        second = corpus.project_row(
            "tracks", {"track_id": "2", "artist_id": "20", "album_id": "77"}
        )
        self.assertEqual(first["album_id"], second["album_id"])
        self.assertNotEqual(first["artist_id"], second["artist_id"])
        for value, reason in [("", "source_empty"), ("invalid", "source_invalid_native_id")]:
            with self.subTest(value=value):
                row = corpus.project_row(
                    "tracks", {"track_id": "3", "artist_id": "30", "album_id": value}
                )
                self.assertIsNone(row["album_id"])
                self.assertEqual(row["missing_fields"]["album_id"], reason)

    def test_untrusted_genre_literals_are_data_and_missingness_is_typed(self) -> None:
        """Do not evaluate code or invent absent source genres and identity bridges."""
        row = corpus.project_row(
            "tracks",
            {"track_id": "1", "artist_id": "2", "track_genres": "__import__('os').system('false')"},
        )
        self.assertIsNone(row["genre_ids"])
        self.assertEqual(row["missing_fields"]["genre_ids"], "source_unparseable_genre_list")
        self.assertNotIn("musicbrainz_id", row)
        self.assertNotIn("audio_url", row)
        with self.assertRaises(ValueError):
            corpus.project_row("artists", {"artist_id": "0", "artist_name": "Bad"})

    def test_capture_then_offline_replay_preserves_native_identity_and_license_boundaries(
        self,
    ) -> None:
        """Only allowlisted bytes enter reusable output; replay requires no network."""
        archive = fixture_zip()
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if str(request.url) == corpus.README_URL:
                return httpx.Response(200, stream=httpx.ByteStream(README))
            self.assertEqual(str(request.url), corpus.ARCHIVE_URL)
            self.assertEqual(request.headers["if-match"], corpus.ETAG)
            start, end = map(int, request.headers["range"].removeprefix("bytes=").split("-"))
            payload = archive[start : end + 1]
            return httpx.Response(
                206,
                headers={
                    "content-range": f"bytes {start}-{end}/{len(archive)}",
                    "etag": corpus.ETAG,
                    "content-length": str(len(payload)),
                },
                stream=httpx.ByteStream(payload),
            )

        transport = httpx.MockTransport(handler)
        original = httpx.Client
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(corpus, "ARCHIVE_BYTES", len(archive)),
            patch.object(corpus, "TAIL_BYTES", min(len(archive), 1500)),
            patch.object(
                corpus.httpx,
                "Client",
                side_effect=lambda **kwargs: original(transport=transport, **kwargs),
            ),
        ):
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            capture = corpus.capture_sources(source)
            self.assertEqual(len(requests), 8)
            self.assertEqual(set(capture["members"]), set(corpus.MEMBERS))
            requests.clear()
            receipt = corpus.project_corpus(source, output)
            self.assertEqual(requests, [])
            self.assertEqual(receipt["files"]["tracks"]["rows"], 2)
            self.assertEqual(receipt["metadata_license"], "CC-BY-4.0")
            self.assertEqual(receipt["files"]["tracks"]["unresolved_track_artists"], 1)
            with (
                (output / "tracks.jsonl.zst").open("rb") as stream,
                zstandard.ZstdDecompressor().stream_reader(stream) as compressed,
            ):
                rows = [json.loads(line) for line in io.TextIOWrapper(compressed)]
            self.assertEqual(rows[0]["genre_ids"], [21])
            self.assertEqual(rows[0]["album_id"], 17)
            self.assertIsNone(rows[1]["album_id"])
            self.assertEqual(rows[0]["audio_license_title"], "CC BY-NC-SA")
            self.assertIsNone(rows[1]["genre_ids"])
            replay = corpus.project_corpus(source, Path(temporary) / "replay")
            self.assertEqual(receipt, replay)
            verified_receipt, verified = verified_tables(source, output)
            self.assertEqual(verified_receipt, receipt)
            self.assertEqual(verified["tracks"], rows)
            with self.assertRaises(FileExistsError):
                corpus.capture_sources(source)
            with self.assertRaises(FileExistsError):
                corpus.project_corpus(source, output)
            # A forged projected table and matching self-reported hash still fail native replay.
            rows[0]["title"] = "Forged source title"
            tracks_path = output / "tracks.jsonl.zst"
            tracks_path.write_bytes(
                zstandard.ZstdCompressor().compress(
                    b"".join(canonical_json(row) + b"\n" for row in rows)
                )
            )
            receipt["files"]["tracks"].update(
                zip(("sha256", "bytes"), sha256_file(tracks_path), strict=True)
            )
            (output / "corpus-receipt.json").write_bytes(canonical_json(receipt))
            with self.assertRaisesRegex(ValueError, "differs from native source replay"):
                verified_tables(source, output)
            payload = source / "2-compressed.range"
            payload.write_bytes(payload.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                corpus.verify_sources(source)

    def test_local_header_and_directory_reject_malformed_archives(self) -> None:
        """Do not accept directory/local conflicts or a pickle-shaped replacement."""
        with self.assertRaises(ValueError):
            corpus.central_members(b"not a ZIP")
        member = {
            "flags": 0,
            "crc32": 0,
            "compressed_bytes": 1,
            "uncompressed_bytes": 1,
            "name": "fma_metadata/raw_genres.csv",
        }
        with self.assertRaises(ValueError):
            corpus.local_header(b"short", member)
        header = struct.pack(
            "<4s5H3L2H", b"PK\x03\x04", 46, 0, 0, 0, 0, 0, 1, 1, len(member["name"]), 0
        )
        with self.assertRaises(ValueError):
            corpus.local_header(header, member)


if __name__ == "__main__":
    unittest.main()
