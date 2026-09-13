from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pydantic import HttpUrl

from opennoise.ingest.musicbrainz.release_group_evidence import (
    MusicBrainzReleaseGroupEvidenceError,
    ReleaseGroupEvidenceProgress,
    ReleaseGroupEvidenceSettings,
    build_release_group_evidence,
    build_release_group_evidence_from_seed_target_path,
    verify_release_group_evidence,
)
from opennoise.ingest.musicbrainz.seed_targets import (
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
    write_seed_target_artifact,
)
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.source_cache import SourceCacheEntry, SourceCacheReceipt
from opennoise.storage import ObjectKey


def _target() -> MusicBrainzSeedTargetArtifact:
    settings = SeedTargetExtractorSettings()
    artist = "00000000-0000-0000-0000-000000000001"
    evidence = (
        SeedTargetEvidence(
            seed_source_item_id="rock",
            seed_source_external_id="seed:rock",
            seed_name="Rock",
            seed_normalized_name="rock",
            facet="genre",
            target_namespace="musicbrainz_genre_id",
            target_identity="00000000-0000-0000-0000-000000000010",
            target_name="Rock",
            artist_id=artist,
            source_record_id=f"musicbrainz:artist:{artist}",
            source_record_ordinal=1,
            source_record_sha256="a" * 64,
            source_record_byte_length=1,
            evidence_ref="artist-direct-rock",
            positive_weight=1.0,
            match_kind="exact",
        ),
    )
    target = MusicBrainzSeedTargetArtifact(
        seed_input_sha256="b" * 64,
        seed_source_id="fixture",
        seed_source_content_sha256="c" * 64,
        seed_count=2,
        archive_sha256="d" * 64,
        settings=settings,
        settings_sha256=settings_sha256(settings),
        counters=SeedTargetExtractorCounters(
            **dict.fromkeys(SeedTargetExtractorCounters.model_fields, 0)
        ),
        coverage=(
            SeedTargetCoverage(
                seed_source_item_id="rock",
                seed_source_external_id="seed:rock",
                seed_name="Rock",
                normalized_name="rock",
                evidence_count=1,
                distinct_artist_count=1,
                distinct_target_identity_count=1,
                genre_evidence_count=1,
                tag_evidence_count=0,
            ),
            SeedTargetCoverage(
                seed_source_item_id="ambient",
                seed_source_external_id="seed:ambient",
                seed_name="Ambient",
                normalized_name="ambient",
                evidence_count=0,
                distinct_artist_count=0,
                distinct_target_identity_count=0,
                genre_evidence_count=0,
                tag_evidence_count=0,
            ),
        ),
        evidence=evidence,
        output_sha256="0" * 64,
    )
    return target.model_copy(update={"output_sha256": artifact_sha256(target)})


class ReleaseGroupEvidenceTests(unittest.TestCase):
    def test_rejects_a_cache_smaller_than_an_unflushed_batch(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_cached_memberships"):
            ReleaseGroupEvidenceSettings(max_cached_memberships=1_000, insert_batch_rows=1_001)

    def test_release_tags_are_support_not_artist_direct_and_are_capped(self) -> None:  # noqa: PLR0915
        artist = "00000000-0000-0000-0000-000000000001"
        group = {
            "id": "00000000-0000-0000-0000-000000000100",
            "title": "Fixture",
            "artist-credit": [{"artist": {"id": artist, "name": "Fixture"}}],
            "genres": [{"id": "00000000-0000-0000-0000-000000000010", "name": "Rock"}],
            "tags": [{"name": "Ambient", "count": 2}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "release-group.tar.xz"
            groups = tuple(
                group | {"id": f"00000000-0000-0000-0000-00000000010{ordinal}"}
                for ordinal in range(3)
            )
            member_payload = b"".join((json.dumps(item) + "\n").encode() for item in groups)
            with tarfile.open(archive, "w:xz") as output:
                member = tarfile.TarInfo("mbdump/release-group")
                member.size = len(member_payload)
                output.addfile(member, io.BytesIO(member_payload))
            payload = archive.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            source = DownloadSource(
                id="fixture-release-groups",
                adapter="musicbrainz_release_group_json_dump_v1",
                snapshot="fixture",
                url=HttpUrl("https://example.test/release-group.tar.xz"),
                discovery_url=HttpUrl("https://example.test/"),
                expected_content_type="application/octet-stream",
                compression="tar.xz",
                expected_bytes=len(payload),
                checksum_algorithm="sha256",
                checksum=digest,
                data_license="fixture",
                license_url="https://example.test/license",
                rights_classification="restricted_research",
                local_only=True,
                normalize=True,
                local_search=True,
                display=True,
                embed=True,
                train=True,
                export_metadata=False,
            )
            receipt = SourceCacheReceipt(
                declared_manifest_sha256="e" * 64,
                entries=(
                    SourceCacheEntry(
                        source_id=source.id,
                        adapter=source.adapter,
                        snapshot=source.snapshot,
                        original_url=str(source.url),
                        discovery_url=str(source.discovery_url),
                        expected_content_type=source.expected_content_type,
                        expected_bytes=source.expected_bytes,
                        sha256=digest,
                        data_license=source.data_license,
                        license_url=source.license_url,
                        rights_classification=source.rights_classification,
                        local_only=True,
                        portable_object_store_eligible=False,
                        object_key=ObjectKey(value=f"source-artifacts/sha256/{digest}"),
                    ),
                ),
            )
            database = root / "evidence.sqlite"
            progress: list[ReleaseGroupEvidenceProgress] = []
            progress_tables: list[set[str]] = []

            def record_progress(item: ReleaseGroupEvidenceProgress) -> None:
                progress.append(item)
                staging = database.with_suffix(".sqlite.partial")
                with closing(sqlite3.connect(staging)) as checkpoint:
                    progress_tables.append(
                        {
                            str(row[0])
                            for row in checkpoint.execute(
                                "SELECT name FROM sqlite_master WHERE type = 'table'"
                            )
                        }
                    )

            artifact = build_release_group_evidence(
                archive,
                _target(),
                source,
                receipt,
                "e" * 64,
                database,
                ReleaseGroupEvidenceSettings(max_release_groups_per_membership=1),
                progress_callback=record_progress,
            )
            verify_release_group_evidence(artifact)
            self.assertEqual([item.records_seen for item in progress], [3])
            self.assertGreaterEqual(progress[0].elapsed_seconds, 0.0)
            self.assertNotIn("build_checkpoint", progress_tables[0])
            verified_seed_path = root / "verified-seed-target.json"
            write_seed_target_artifact(verified_seed_path, _target())
            verified_artifact = build_release_group_evidence_from_seed_target_path(
                archive,
                verified_seed_path,
                source,
                receipt,
                "e" * 64,
                root / "verified-evidence.sqlite",
                ReleaseGroupEvidenceSettings(max_release_groups_per_membership=1),
            )
            self.assertEqual(verified_artifact.counters, artifact.counters)
            self.assertEqual(verified_artifact.coverage, artifact.coverage)
            tampered_seed_path = root / "tampered-seed-target.json"
            tampered_seed_path.write_text(
                _target().model_copy(update={"output_sha256": "0" * 64}).model_dump_json(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "output hash mismatch"):
                build_release_group_evidence_from_seed_target_path(
                    archive,
                    tampered_seed_path,
                    source,
                    receipt,
                    "e" * 64,
                    root / "tampered-evidence.sqlite",
                )
            with (
                closing(sqlite3.connect(database)) as ordinary,
                closing(sqlite3.connect(root / "verified-evidence.sqlite")) as verified,
            ):
                typed_counts = (
                    "SELECT evidence_kind, count(*) FROM typed_evidence "
                    "GROUP BY evidence_kind ORDER BY evidence_kind"
                )
                self.assertEqual(
                    ordinary.execute(typed_counts).fetchall(),
                    verified.execute(typed_counts).fetchall(),
                )
            self.assertEqual(artifact.coverage.support_genre_count, 2)
            self.assertEqual(artifact.coverage.direct_anchor_membership_count, 1)
            self.assertEqual(artifact.coverage.new_support_membership_count, 1)
            self.assertEqual(artifact.counters.raw_support_rows, 6)
            self.assertEqual(artifact.counters.capped_support_rows, 2)
            self.assertEqual(artifact.source_member_bytes, len(member_payload))
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    "SELECT evidence_kind, genre_id, release_group_id "
                    "FROM typed_evidence ORDER BY evidence_kind, genre_id"
                ).fetchall()
                direct_indexes = {
                    str(row[1]) for row in connection.execute("PRAGMA index_list('direct_anchor')")
                }
                support_indexes = {
                    str(row[1])
                    for row in connection.execute("PRAGMA index_list('release_group_support')")
                }
            self.assertIn("direct_anchor_artist_genre_idx", direct_indexes)
            self.assertIn("release_group_support_artist_genre_idx", support_indexes)
            self.assertEqual(rows[0], ("artist_direct", "rock", None))
            self.assertEqual(
                rows[1],
                ("release_group_support", "ambient", "00000000-0000-0000-0000-000000000100"),
            )
            self.assertEqual(
                rows[2],
                ("release_group_support", "rock", "00000000-0000-0000-0000-000000000100"),
            )
            with self.assertRaisesRegex(
                MusicBrainzReleaseGroupEvidenceError, "different manifest bytes"
            ):
                build_release_group_evidence(
                    archive,
                    _target(),
                    source,
                    receipt,
                    "f" * 64,
                    root / "substituted.sqlite",
                    ReleaseGroupEvidenceSettings(max_release_groups_per_membership=1),
                )
            with self.assertRaisesRegex(
                MusicBrainzReleaseGroupEvidenceError, "mbdump/release-group member"
            ):
                build_release_group_evidence(
                    archive,
                    _target(),
                    source,
                    receipt,
                    "e" * 64,
                    root / "oversize.sqlite",
                    ReleaseGroupEvidenceSettings(max_member_bytes=len(member_payload) - 1),
                )
            member_limited = root / "member-limited.tar.xz"
            with tarfile.open(member_limited, "w:xz") as output:
                for name in ("mbdump/release-group", "JSON_DUMPS_SCHEMA_NUMBER"):
                    item = tarfile.TarInfo(name)
                    item.size = 0
                    output.addfile(item, io.BytesIO())
            limited_payload = member_limited.read_bytes()
            limited_digest = hashlib.sha256(limited_payload).hexdigest()
            limited_source = source.model_copy(
                update={"expected_bytes": len(limited_payload), "checksum": limited_digest}
            )
            limited_receipt = receipt.model_copy(
                update={
                    "entries": (
                        receipt.entries[0].model_copy(
                            update={
                                "expected_bytes": len(limited_payload),
                                "sha256": limited_digest,
                                "object_key": ObjectKey(
                                    value=f"source-artifacts/sha256/{limited_digest}"
                                ),
                            }
                        ),
                    )
                }
            )
            limited_database = root / "member-limit.sqlite"
            limited_database.write_bytes(b"previous-final-artifact")
            with self.assertRaisesRegex(
                MusicBrainzReleaseGroupEvidenceError, "max_archive_members"
            ):
                build_release_group_evidence(
                    member_limited,
                    _target(),
                    limited_source,
                    limited_receipt,
                    "e" * 64,
                    limited_database,
                    ReleaseGroupEvidenceSettings(max_archive_members=1),
                )
            self.assertEqual(limited_database.read_bytes(), b"previous-final-artifact")
            staged = limited_database.with_suffix(".sqlite.partial")
            self.assertTrue(staged.is_file())
            with closing(sqlite3.connect(staged)) as connection:
                self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))


if __name__ == "__main__":
    unittest.main()
