from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from musix.common.hashing import canonical_json, sha256_file, sha256_hex, sha256_json
from musix.common.sqlite import write_atomic_bytes, write_durable_bytes


class CommonHashingTests(unittest.TestCase):
    def test_canonical_json_is_key_order_deterministic(self) -> None:
        first = canonical_json({"b": 1, "a": [2, 3]})
        self.assertEqual(first, canonical_json({"a": [2, 3], "b": 1}))
        self.assertEqual(first, b'{"a":[2,3],"b":1}')

    def test_sha256_hex_matches_hashlib(self) -> None:
        payload = b"musix-boundary-fixture"
        self.assertEqual(sha256_hex(payload), hashlib.sha256(payload).hexdigest())

    def test_sha256_file_streams_bytes(self) -> None:
        payload = b"abcd" * 700_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.bin"
            path.write_bytes(payload)
            digest, size = sha256_file(path)
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertEqual(size, len(payload))

    def test_write_atomic_bytes_round_trips_without_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.bin"
            write_atomic_bytes(path, b"\x00\xffmusix")
            self.assertEqual(path.read_bytes(), b"\x00\xffmusix")
            self.assertEqual(list(Path(tmp).glob("*.partial")), [])

    def test_sha256_json_composes_canonical_hash(self) -> None:
        value = {"b": 1, "a": [2, 3]}
        self.assertEqual(sha256_json(value), sha256_hex(canonical_json(value)))

    def test_write_durable_bytes_round_trips_without_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.bin"
            write_durable_bytes(path, b"\x00\xffmusix")
            self.assertEqual(path.read_bytes(), b"\x00\xffmusix")
            self.assertEqual(list(Path(tmp).glob(".out.bin.*")), [])


if __name__ == "__main__":
    unittest.main()
