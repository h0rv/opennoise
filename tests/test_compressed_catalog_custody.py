from __future__ import annotations

import hashlib
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, cast, override

import zstandard

from opennoise.ingest.musicbrainz.compressed_catalog_custody import (
    compress_stream,
    replay_and_verify,
)


class CountingStream(BytesIO):
    def __init__(self, value: bytes) -> None:
        """Record requested read sizes."""
        super().__init__(value)
        self.requests: list[int] = []

    @override
    def read(self, size: int | None = -1) -> bytes:
        self.requests.append(-1 if size is None else size)
        return super().read(size)


class BrokenStream:
    def __init__(self) -> None:
        """Raise after returning one source chunk."""
        self.calls = 0

    def read(self, size: int) -> bytes:  # noqa: ARG002
        self.calls += 1
        if self.calls == 1:
            return b"prefix"
        raise OSError("connection broke")


class CompressedCatalogCustodyTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    @override
    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_exact_boundary_with_expected_length_is_complete(self) -> None:
        body = b'{"release-groups":[]}'
        stream = CountingStream(body)
        path = self.root / "catalog.zst"
        result = compress_stream(
            stream, path, max_decoded_bytes=len(body), expected_length=len(body)
        )
        self.assertTrue(result["complete_body"])
        self.assertEqual(result["decoded_bytes"], len(body))
        self.assertLessEqual(max(stream.requests), len(body))
        self.assertTrue(replay_and_verify(path, result)["complete_body"])

    def test_one_byte_over_cap_is_retained_as_partial(self) -> None:
        body = b"abcdef"
        path = self.root / "partial.zst"
        result = compress_stream(BytesIO(body), path, max_decoded_bytes=5)
        self.assertFalse(result["complete_body"])
        self.assertEqual(result["decoded_bytes"], 5)
        self.assertEqual(result["outcome"], "decoded_limit")
        self.assertEqual(
            zstandard.ZstdDecompressor().decompress(path.read_bytes(), max_output_size=100),
            body[:5],
        )
        self.assertFalse(replay_and_verify(path, result)["complete_body"])

    def test_stream_exception_preserves_compressed_prefix(self) -> None:
        path = self.root / "broken.zst"
        result = compress_stream(cast("BinaryIO", BrokenStream()), path, max_decoded_bytes=100)
        self.assertTrue(path.exists())
        self.assertFalse(result["complete_body"])
        self.assertEqual(result["outcome"], "stream_error")
        self.assertEqual(
            zstandard.ZstdDecompressor().decompress(path.read_bytes(), max_output_size=100),
            b"prefix",
        )

    def test_tiny_encoded_budget_refuses_before_reading(self) -> None:
        stream = CountingStream(b"payload")
        path = self.root / "refused.zst"
        result = compress_stream(stream, path, max_encoded_bytes=10)
        self.assertEqual(result["outcome"], "encoded_budget_refused")
        self.assertEqual(stream.requests, [])
        self.assertFalse(path.exists())

    def test_encoded_budget_boundary_keeps_full_frame_within_limit(self) -> None:
        body = b"a" * 150_000
        path = self.root / "bounded.zst"
        result = compress_stream(
            BytesIO(body), path, max_decoded_bytes=len(body), max_encoded_bytes=70_000
        )
        encoded_bytes = result["encoded_bytes"]
        decoded_bytes = result["decoded_bytes"]
        assert isinstance(encoded_bytes, int)
        assert isinstance(decoded_bytes, int)
        self.assertLessEqual(encoded_bytes, 70_000)
        self.assertEqual(
            zstandard.ZstdDecompressor().decompress(path.read_bytes(), max_output_size=len(body)),
            body[:decoded_bytes],
        )
        self.assertTrue(
            replay_and_verify(path, result)["decoded_sha256"] == result["decoded_sha256"]
        )

    def test_replay_detects_encoded_tampering(self) -> None:
        path = self.root / "body.zst"
        result = compress_stream(BytesIO(b"source bytes"), path)
        path.write_bytes(path.read_bytes() + b"x")
        with self.assertRaisesRegex(ValueError, "encoded artifact"):
            replay_and_verify(path, result)

    def test_existing_output_is_never_overwritten(self) -> None:
        path = self.root / "existing.zst"
        path.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            compress_stream(BytesIO(b"new"), path)
        self.assertEqual(path.read_bytes(), b"keep")

    def test_metadata_hash_matches_original_bytes(self) -> None:
        body = b'{"catalog":"original"}'
        result = compress_stream(BytesIO(body), self.root / "hash.zst")
        self.assertEqual(result["decoded_sha256"], hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    unittest.main()
