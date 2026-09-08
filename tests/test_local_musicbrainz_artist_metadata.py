import hashlib
import io
import json
import sqlite3
import tarfile
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.local_musicbrainz_artist_metadata import (
    ArtistMetadataBuildInputs,
    ArtistMetadataSettings,
    LocalArtistMetadataSources,
    LocalMusicBrainzArtistMetadataError,
    build_artist_metadata,
    exact_canonical_names,
)
from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    ReleaseGroupEvidenceCounters,
    ReleaseGroupEvidenceCoverage,
    ReleaseGroupEvidenceSettings,
    artifact_sha256,
)

_ARTIST_A = "00000000-0000-4000-8000-000000000001"
_ARTIST_B = "00000000-0000-4000-8000-000000000002"


class LocalMusicBrainzArtistMetadataTests(unittest.TestCase):
    def test_uses_exact_nested_names_and_preserves_conflicts(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_db = _evidence_database(root / "evidence.sqlite")
            archive = _archive(root / "release-group.tar.xz")
            evidence_artifact = _evidence_artifact(evidence_db, archive)
            output_db = root / "names.sqlite"
            artifact = build_artist_metadata(
                ArtistMetadataBuildInputs(
                    archive=archive,
                    evidence_database=evidence_db,
                    evidence_artifact=evidence_artifact,
                    output_database=output_db,
                )
            )
            names = exact_canonical_names(
                LocalArtistMetadataSources(database=output_db, artifact=artifact),
                (_ARTIST_A, _ARTIST_B, "00000000-0000-4000-8000-000000000099"),
            )
            with closing(sqlite3.connect(output_db)) as connection:
                canonical = connection.execute(
                    "SELECT canonical_name, occurrence_count FROM canonical_name_variant "
                    "WHERE artist_mbid = ? ORDER BY canonical_name",
                    (_ARTIST_A,),
                ).fetchall()
                conflict = connection.execute(
                    "SELECT canonical_name, canonical_name_variant_count, sort_name, country "
                    "FROM artist_summary WHERE artist_mbid = ?",
                    (_ARTIST_B,),
                ).fetchone()
                credited = connection.execute(
                    "SELECT credited_as FROM credited_as_variant WHERE artist_mbid = ? "
                    "ORDER BY credited_as",
                    (_ARTIST_A,),
                ).fetchall()

        self.assertEqual(names, {_ARTIST_A: "Canonical A"})
        self.assertEqual(canonical, [("Canonical A", 2)])
        self.assertEqual(conflict, (None, 2, None, None))
        self.assertEqual(credited, [("Canonical A",), ("Stage A",)])
        self.assertEqual(artifact.target_artist_count, 2)
        self.assertEqual(artifact.observed_artist_count, 2)
        self.assertEqual(artifact.conflicting_artist_count, 1)
        self.assertFalse(artifact.export_allowed)
        self.assertFalse(artifact.serving_allowed)
        self.assertEqual(artifact.source_snapshot, "fixture")

    def test_rejects_more_than_the_configured_distinct_names(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_db = _evidence_database(root / "evidence.sqlite")
            archive = _archive(root / "release-group.tar.xz")
            with self.assertRaisesRegex(LocalMusicBrainzArtistMetadataError, "variant cap"):
                build_artist_metadata(
                    ArtistMetadataBuildInputs(
                        archive=archive,
                        evidence_database=evidence_db,
                        evidence_artifact=_evidence_artifact(evidence_db, archive),
                        output_database=root / "names.sqlite",
                    ),
                    ArtistMetadataSettings(max_name_variants_per_artist=1),
                )

    def test_variant_cap_allows_an_existing_canonical_name(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_db = _evidence_database(root / "evidence.sqlite")
            archive = _single_name_archive(root / "release-group.tar.xz")
            artifact = build_artist_metadata(
                ArtistMetadataBuildInputs(
                    archive=archive,
                    evidence_database=evidence_db,
                    evidence_artifact=_evidence_artifact(evidence_db, archive),
                    output_database=root / "names.sqlite",
                ),
                ArtistMetadataSettings(max_name_variants_per_artist=1),
            )
            with closing(sqlite3.connect(root / "names.sqlite")) as connection:
                occurrence_count = connection.execute(
                    "SELECT occurrence_count FROM canonical_name_variant WHERE artist_mbid = ?",
                    (_ARTIST_A,),
                ).fetchone()

        self.assertEqual(occurrence_count, (2,))
        self.assertEqual(artifact.conflicting_artist_count, 0)


def _archive(path: Path) -> Path:
    rows = (
        {
            "id": "00000000-0000-4000-8000-000000000101",
            "title": "One",
            "artist-credit": [
                {"artist": {"id": _ARTIST_A, "name": "Canonical A"}, "name": "Stage A"},
                {"artist": {"id": _ARTIST_B, "name": "Canonical B One"}, "name": "B One"},
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000102",
            "title": "Two",
            "artist-credit": [
                {"artist": {"id": _ARTIST_A, "name": "Canonical A"}, "name": "Canonical A"},
                {"artist": {"id": _ARTIST_B, "name": "Canonical B Two"}, "name": "B Two"},
            ],
        },
    )
    payload = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    with tarfile.open(path, "w:xz") as output:
        schema = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema.size = 1
        output.addfile(schema, io.BytesIO(b"1"))
        member = tarfile.TarInfo("mbdump/release-group")
        member.size = len(payload)
        output.addfile(member, io.BytesIO(payload))
    return path


def _single_name_archive(path: Path) -> Path:
    row = {
        "id": "00000000-0000-4000-8000-000000000101",
        "title": "One",
        "artist-credit": [{"artist": {"id": _ARTIST_A, "name": "Canonical A"}, "name": "Stage A"}],
    }
    payload = b"".join(
        json.dumps(row | {"title": title}).encode() + b"\n" for title in ("One", "Two")
    )
    with tarfile.open(path, "w:xz") as output:
        schema = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema.size = 1
        output.addfile(schema, io.BytesIO(b"1"))
        member = tarfile.TarInfo("mbdump/release-group")
        member.size = len(payload)
        output.addfile(member, io.BytesIO(payload))
    return path


def _evidence_database(path: Path) -> Path:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE direct_anchor (
                genre_id TEXT, artist_id TEXT, facet TEXT, evidence_ref TEXT
            );
            CREATE TABLE release_group_support (
                genre_id TEXT, artist_id TEXT, facet TEXT, release_group_id TEXT, evidence_ref TEXT
            );
            """
        )
        connection.executemany(
            "INSERT INTO direct_anchor VALUES ('item1', ?, 'musicbrainz_tag', 'ref')",
            ((_ARTIST_A,), (_ARTIST_B,)),
        )
        connection.commit()
    return path


def _evidence_artifact(database: Path, archive: Path) -> ReleaseGroupEvidenceArtifact:
    database_bytes = database.read_bytes()
    archive_bytes = archive.read_bytes()
    preliminary = ReleaseGroupEvidenceArtifact(
        source_id="fixture",
        source_snapshot="fixture",
        source_url="https://example.test/release-group",
        source_archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        source_archive_bytes=len(archive_bytes),
        source_member_bytes=1,
        source_cache_receipt_sha256="b" * 64,
        seed_target_output_sha256="c" * 64,
        settings=ReleaseGroupEvidenceSettings(),
        evidence_database_sha256=hashlib.sha256(database_bytes).hexdigest(),
        evidence_database_bytes=len(database_bytes),
        counters=ReleaseGroupEvidenceCounters(
            archive_member_count=0,
            records_seen=0,
            records_parsed=0,
            records_over_limit=0,
            malformed_records=0,
            malformed_claims=0,
            release_groups_with_matched_claims=0,
            raw_support_rows=0,
            capped_support_rows=0,
        ),
        coverage=ReleaseGroupEvidenceCoverage(
            seed_count=1,
            direct_anchor_genre_count=1,
            direct_anchor_membership_count=2,
            support_genre_count=0,
            support_membership_count=0,
            new_support_genre_count=0,
            new_support_membership_count=0,
            direct_anchor_recovered_count=0,
            heldout_direct_anchor_count=0,
            heldout_direct_anchor_recovered_count=0,
            heldout_direct_anchor_recovery=0.0,
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": artifact_sha256(preliminary)})
