from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import override

import zstandard

from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import CoreArtistPrefixReceipt
from opennoise.ingest.musicbrainz.core_artist_identities import (
    CoreIdentityError,
    build_core_artist_identities,
)

_MBID = "00000000-0000-4000-8000-000000000001"


class CoreArtistIdentityTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "core.tar.bz2"
        columns = ["1", _MBID, r"Bj\303\266rk", "sort", *([r"\N"] * 15)]
        self.member = ("\t".join(columns) + "\n").encode()
        self._archive("mbdump/artist", self.member)

    def _archive(self, member_name: str, payload: bytes) -> None:
        with tarfile.open(self.source, "w:bz2") as archive:
            member = tarfile.TarInfo(member_name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
            # Derived content is intentionally ignored, even if present later.
            tags = tarfile.TarInfo("mbdump/artist_tag")
            tags.size = 9
            archive.addfile(tags, io.BytesIO(b"FORBIDDEN"))

    def _receipt(self) -> CoreArtistPrefixReceipt:
        raw = self.source.read_bytes()
        return CoreArtistPrefixReceipt(
            snapshot="fixture",
            archive_url="https://example.org/core.tar.bz2",
            archive_bytes=len(raw),
            archive_sha256=hashlib.sha256(raw).hexdigest(),
            prefix_bytes=len(raw),
            prefix_sha256=hashlib.sha256(raw).hexdigest(),
            artist_member_bytes=len(self.member),
            artist_member_sha256=hashlib.sha256(self.member).hexdigest(),
            artist_row_count=1,
            schema_sequence="31",
            observed_at="2026-10-02T00:00:00Z",
        )

    def test_identity_only_unicode_projection(self) -> None:
        output = self.root / "output"
        receipt = build_core_artist_identities(self.source, self._receipt(), output)
        with (
            (output / "artist-identities.jsonl.zst").open("rb") as source,
            zstandard.ZstdDecompressor().stream_reader(source) as reader,
        ):
            rows = reader.read().decode()
        self.assertEqual(json.loads(rows), {"artist_mbid": _MBID, "name": "Björk"})
        self.assertEqual(receipt["artist_count"], 1)
        self.assertEqual(receipt["derived_tables_consumed"], [])
        self.assertFalse(receipt["source_archive_sha256_verified"])

    def test_prefix_mutation_rejected_before_creating_output(self) -> None:
        receipt = self._receipt()
        with self.source.open("ab") as source:
            source.write(b"x")
        output = self.root / "output"
        with self.assertRaises(CoreIdentityError):
            build_core_artist_identities(self.source, receipt, output)
        self.assertFalse(output.exists())

    def test_member_hash_or_count_rejected_without_complete_receipt(self) -> None:
        for field, value in (("artist_member_sha256", "0" * 64), ("artist_row_count", 2)):
            with self.subTest(field=field):
                output = self.root / field
                with self.assertRaises(CoreIdentityError):
                    build_core_artist_identities(
                        self.source, replace(self._receipt(), **{field: value}), output
                    )
                self.assertFalse((output / "receipt.json").exists())

    def test_existing_output_preserved(self) -> None:
        output = self.root / "output"
        output.mkdir()
        sentinel = output / "receipt.json"
        sentinel.write_text("preserved", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            build_core_artist_identities(self.source, self._receipt(), output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserved")

    def test_unsafe_member_rejected(self) -> None:
        self._archive("../mbdump/artist", self.member)
        with self.assertRaises(CoreIdentityError):
            build_core_artist_identities(self.source, self._receipt(), self.root / "output")

    def test_unverified_license_capture_rejected_before_output(self) -> None:
        license_capture = self.root / "license.html"
        license_capture.write_text("unverified license assertion", encoding="utf-8")
        output = self.root / "output"
        with self.assertRaises(CoreIdentityError):
            build_core_artist_identities(
                self.source, self._receipt(), output, license_capture=license_capture
            )
        self.assertFalse(output.exists())
