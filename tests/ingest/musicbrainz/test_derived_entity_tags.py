from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from pydantic import HttpUrl

from opennoise.ingest.musicbrainz.derived_entity_tags import (
    DerivedEntityTagError,
    OfficialGenreIdentity,
    iter_derived_entity_genre_facts,
    iter_derived_entity_tag_facts,
)
from opennoise.models.sources import DownloadSource


def _archive(
    path: Path, members: dict[str, bytes] | None = None, *, unsafe_member: bool = False
) -> None:
    if members is None:
        members = {
            "tag": b"1\trock\t12\n2\tnot a genre\t7\n",
            "recording_tag": b"10\t1\t4\t2026-08-29 00:00:00+00\n",
            "release_tag": b"20\t2\t3\t2026-08-29 00:00:00+00\n",
            "release_group_tag": b"30\t1\t2\t2026-08-29 00:00:00+00\n",
        }
    with tarfile.open(path, "w:bz2") as archive:
        if unsafe_member:
            payload = b"unsafe"
            member = tarfile.TarInfo("mbdump/../tag")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        for name, payload in members.items():
            member = tarfile.TarInfo(f"mbdump/{name}")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


def _source(path: Path) -> DownloadSource:
    payload = path.read_bytes()
    return DownloadSource(
        id="fixture_derived",
        adapter="musicbrainz_postgres_derived_v1",
        snapshot="fixture",
        url=HttpUrl("https://example.test/mbdump-derived.tar.bz2"),
        discovery_url=HttpUrl("https://musicbrainz.org/"),
        expected_content_type="application/octet-stream",
        compression="tar.bz2",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="fixture",
        license_url="https://musicbrainz.org/",
        rights_classification="restricted_research",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=False,
    )


class DerivedEntityTagsTests(unittest.TestCase):
    def test_streams_positive_entity_native_tag_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(archive)
            facts = tuple(iter_derived_entity_tag_facts(archive, _source(archive)))
        self.assertEqual(
            [(fact.entity_kind, fact.entity_id, fact.tag_name, fact.count) for fact in facts],
            [
                ("recording", 10, "rock", 4),
                ("release", 20, "not a genre", 3),
                ("release_group", 30, "rock", 2),
            ],
        )

    def test_genres_require_exact_tag_id_mapping_not_label_matching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(archive)
            facts = tuple(
                iter_derived_entity_genre_facts(
                    archive, _source(archive), {1: OfficialGenreIdentity(99, "Official rock")}
                )
            )
        self.assertEqual(
            [(fact.entity_id, fact.genre_id, fact.genre_name) for fact in facts],
            [(10, 99, "Official rock"), (30, 99, "Official rock")],
        )

    def test_rejects_wrong_bytes_before_archive_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(archive)
            source = _source(archive)
            archive.write_bytes(b"not an archive")
            with self.assertRaisesRegex(DerivedEntityTagError, "byte count"):
                tuple(iter_derived_entity_tag_facts(archive, source))

    def test_rejects_wrong_sha256_before_archive_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(archive)
            source = _source(archive).model_copy(update={"checksum": "0" * 64})
            with self.assertRaisesRegex(DerivedEntityTagError, "SHA-256"):
                tuple(iter_derived_entity_tag_facts(archive, source))

    def test_rejects_missing_required_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(
                archive,
                {
                    "tag": b"1\trock\t12\n",
                    "recording_tag": b"10\t1\t4\tstamp\n",
                    "release_tag": b"20\t1\t3\tstamp\n",
                },
            )
            with self.assertRaisesRegex(DerivedEntityTagError, "release_group_tag"):
                tuple(iter_derived_entity_tag_facts(archive, _source(archive)))

    def test_rejects_unknown_tag_foreign_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(
                archive,
                {
                    "tag": b"1\trock\t12\n",
                    "recording_tag": b"10\t99\t4\tstamp\n",
                    "release_tag": b"20\t1\t3\tstamp\n",
                    "release_group_tag": b"30\t1\t2\tstamp\n",
                },
            )
            with self.assertRaisesRegex(DerivedEntityTagError, "unknown tag ID"):
                tuple(iter_derived_entity_tag_facts(archive, _source(archive)))

    def test_rejects_nonpositive_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(
                archive,
                {
                    "tag": b"1\trock\t12\n",
                    "recording_tag": b"10\t1\t0\tstamp\n",
                    "release_tag": b"20\t1\t3\tstamp\n",
                    "release_group_tag": b"30\t1\t2\tstamp\n",
                },
            )
            with self.assertRaisesRegex(DerivedEntityTagError, "non-positive"):
                tuple(iter_derived_entity_tag_facts(archive, _source(archive)))

    def test_rejects_unsafe_archive_member_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(archive, unsafe_member=True)
            with self.assertRaisesRegex(DerivedEntityTagError, "unsafe archive member path"):
                tuple(iter_derived_entity_tag_facts(archive, _source(archive)))

    def test_decodes_supported_copy_text_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(
                archive,
                {
                    "tag": b"1\telectro\\trock\t12\n",
                    "recording_tag": b"10\t1\t4\tstamp\n",
                    "release_tag": b"20\t1\t3\tstamp\n",
                    "release_group_tag": b"30\t1\t2\tstamp\n",
                },
            )
            facts = tuple(iter_derived_entity_tag_facts(archive, _source(archive)))
        self.assertEqual(facts[0].tag_name, "electro\trock")

    def test_rejects_unsupported_copy_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "derived.tar.bz2"
            _archive(
                archive,
                {
                    "tag": b"1\tbroken\\qtag\t12\n",
                    "recording_tag": b"10\t1\t4\tstamp\n",
                    "release_tag": b"20\t1\t3\tstamp\n",
                    "release_group_tag": b"30\t1\t2\tstamp\n",
                },
            )
            with self.assertRaisesRegex(DerivedEntityTagError, "unsupported COPY escape"):
                tuple(iter_derived_entity_tag_facts(archive, _source(archive)))
