import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import (
    ARTIST_CREDIT_V2_SHA256,
    CORE_HYDRATION_SHA256,
    ArtistCreditCatalogReport,
)
from opennoise.ingest.musicbrainz.release_credit_genre_report import (
    ReleaseCreditGenreExpectedInputs,
    ReleaseCreditGenreReport,
    ReleaseCreditGenreReportError,
    _logical_sha256,
    build_release_credit_genre_report,
    verify_release_credit_genre_report,
)
from opennoise.ingest.musicbrainz.release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    artifact_sha256,
)

GROUP = "20000000-0000-4000-8000-000000000001"
RELEASE = "30000000-0000-4000-8000-000000000001"
RECORDING = "40000000-0000-4000-8000-000000000001"
ARTIST = "50000000-0000-4000-8000-000000000001"
OTHER_ARTIST = "60000000-0000-4000-8000-000000000001"
UNMATCHED_ARTIST = "70000000-0000-4000-8000-000000000001"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected(
    *, evidence: Path, artifact: Path, catalog: Path, catalog_report: Path
) -> ReleaseCreditGenreExpectedInputs:
    return ReleaseCreditGenreExpectedInputs(
        evidence_artifact_sha256=_sha256(artifact),
        evidence_database_sha256=_sha256(evidence),
        credit_catalog_report_sha256=_sha256(catalog_report),
        credit_catalog_database_sha256=_sha256(catalog),
    )


def _evidence_artifact(database: Path) -> ReleaseGroupEvidenceArtifact:
    raw = {
        "source_id": "source",
        "source_snapshot": "snapshot",
        "source_url": "local",
        "source_archive_sha256": "a" * 64,
        "source_archive_bytes": 1,
        "source_member_bytes": 1,
        "source_cache_receipt_sha256": "b" * 64,
        "seed_target_output_sha256": "c" * 64,
        "evidence_database_sha256": _sha256(database),
        "evidence_database_bytes": database.stat().st_size,
        "settings": {},
        "counters": {
            "archive_member_count": 0,
            "records_seen": 0,
            "records_parsed": 0,
            "records_over_limit": 0,
            "malformed_records": 0,
            "malformed_claims": 0,
            "release_groups_with_matched_claims": 0,
            "raw_support_rows": 0,
            "capped_support_rows": 0,
        },
        "coverage": {
            "seed_count": 1,
            "direct_anchor_genre_count": 0,
            "direct_anchor_membership_count": 0,
            "support_genre_count": 0,
            "support_membership_count": 0,
            "new_support_genre_count": 0,
            "new_support_membership_count": 0,
            "direct_anchor_recovered_count": 0,
            "heldout_direct_anchor_count": 0,
            "heldout_direct_anchor_recovered_count": 0,
            "heldout_direct_anchor_recovery": 0.0,
        },
        "output_sha256": "0" * 64,
    }
    unsealed = ReleaseGroupEvidenceArtifact.model_validate(raw)
    return unsealed.model_copy(update={"output_sha256": artifact_sha256(unsealed)})


def _prepare_evidence(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE release_group_support (release_group_id TEXT, artist_id TEXT, "
            "facet TEXT, genre_id TEXT, evidence_ref TEXT)"
        )
        connection.executemany(
            "INSERT INTO release_group_support VALUES (?, ?, ?, ?, ?)",
            [
                (GROUP, ARTIST, "musicbrainz_genre", "item1", "genre-ref"),
                (GROUP, UNMATCHED_ARTIST, "musicbrainz_tag", "item2", "tag-ref"),
            ],
        )


def _prepare_catalog(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE releases (id INTEGER, release_group_id INTEGER);
            CREATE TABLE media (id INTEGER, release_id INTEGER);
            CREATE TABLE tracks (id INTEGER, medium_id INTEGER, recording_id INTEGER);
            CREATE TABLE entity_identifiers (
                entity_id INTEGER, identifier_type_id INTEGER, normalized_value TEXT
            );
            CREATE TABLE identifier_types (id INTEGER, type_key TEXT);
            CREATE TABLE entity_names (
                entity_id INTEGER, name_kind TEXT, is_preferred INTEGER, name TEXT
            );
            CREATE TABLE entity_artist_credits (entity_id INTEGER, artist_credit_id INTEGER);
            CREATE TABLE artist_credit_members (
                artist_credit_id INTEGER, artist_id INTEGER, credited_name TEXT, position INTEGER
            );
            """
        )
        connection.executemany(
            "INSERT INTO identifier_types VALUES (?, ?)",
            [
                (1, "musicbrainz_release_group_id"),
                (2, "musicbrainz_release_id"),
                (3, "musicbrainz_recording_id"),
                (4, "musicbrainz_artist_id"),
            ],
        )
        connection.executemany(
            "INSERT INTO entity_identifiers VALUES (?, ?, ?)",
            [
                (1, 1, GROUP),
                (2, 2, RELEASE),
                (4, 3, RECORDING),
                (10, 4, ARTIST),
                (11, 4, OTHER_ARTIST),
            ],
        )
        connection.executemany(
            "INSERT INTO entity_names VALUES (?, 'primary', 1, ?)",
            [(2, "Release"), (4, "Recording"), (10, "Artist"), (11, "Other")],
        )
        connection.execute("INSERT INTO releases VALUES (2, 1)")
        connection.execute("INSERT INTO media VALUES (3, 2)")
        connection.execute("INSERT INTO tracks VALUES (5, 3, 4)")
        connection.executemany(
            "INSERT INTO entity_artist_credits VALUES (?, ?)", [(2, 20), (4, 21)]
        )
        connection.executemany(
            "INSERT INTO artist_credit_members VALUES (?, ?, ?, ?)",
            [
                (20, 10, "Artist release credit", 0),
                (21, 10, "Artist recording credit", 0),
                (21, 11, "Other", 1),
            ],
        )


class ReleaseCreditGenreReportTests(unittest.TestCase):
    def test_reports_only_exact_artist_credit_matches_as_contextual_support(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence, catalog = root / "evidence.sqlite", root / "catalog.sqlite"
            _prepare_evidence(evidence)
            _prepare_catalog(catalog)
            artifact = _evidence_artifact(evidence)
            artifact_path = root / "artifact.json"
            artifact_path.write_text(artifact.model_dump_json())
            catalog_report = ArtistCreditCatalogReport(
                source_hydration_sha256=CORE_HYDRATION_SHA256,
                source_credit_sha256=ARTIST_CREDIT_V2_SHA256,
                candidate_database_path=str(catalog),
                database_sha256=_sha256(catalog),
                release_relations=1,
                recording_relations=1,
                ordered_credit_members=3,
                artists=2,
                verified_cache_projections=1,
                provenance_record_count=2,
                first_core_materialization={},
                idempotent_core_replay={},
                foreign_key_violations=0,
                content_policy="core_metadata_only_no_audio_preview_artwork_or_genres",
            )
            catalog_report_path = root / "catalog-report.json"
            catalog_report_path.write_text(catalog_report.model_dump_json())
            expected = _expected(
                evidence=evidence,
                artifact=artifact_path,
                catalog=catalog,
                catalog_report=catalog_report_path,
            )

            report = build_release_credit_genre_report(
                evidence_database=evidence,
                evidence_artifact_path=artifact_path,
                credit_catalog_database=catalog,
                credit_catalog_report_path=catalog_report_path,
                expected_inputs=expected,
            )

            self.assertEqual((report.release_group_count, report.support_claim_count), (1, 2))
            self.assertEqual(report.exact_credit_match_count, 2)
            self.assertFalse(report.export_allowed)
            verify_release_credit_genre_report(report)
            with self.assertRaisesRegex(ReleaseCreditGenreReportError, "hash does not replay"):
                verify_release_credit_genre_report(
                    report.model_copy(update={"exact_credit_match_count": 99})
                )
            malformed = report.model_copy(
                update={"exact_credit_match_count": 99, "output_sha256": "0" * 64}
            )
            recomputed = malformed.model_copy(update={"output_sha256": _logical_sha256(malformed)})
            with self.assertRaisesRegex(ValueError, "does not equal report row count"):
                ReleaseCreditGenreReport.model_validate_json(recomputed.model_dump_json())
            self.assertTrue(all(not row.direct_artist_membership for row in report.rows))
            self.assertEqual({row.entity_kind for row in report.rows}, {"release", "recording"})
            self.assertEqual(
                {row.genre_claim_role for row in report.rows}, {"release_group_contextual_support"}
            )

    def test_rejects_catalog_that_claims_genre_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence, catalog = root / "evidence.sqlite", root / "catalog.sqlite"
            _prepare_evidence(evidence)
            _prepare_catalog(catalog)
            artifact_path = root / "artifact.json"
            artifact_path.write_text(_evidence_artifact(evidence).model_dump_json())
            report_path = root / "catalog-report.json"
            report_path.write_text(
                ArtistCreditCatalogReport(
                    source_hydration_sha256=CORE_HYDRATION_SHA256,
                    source_credit_sha256=ARTIST_CREDIT_V2_SHA256,
                    candidate_database_path=str(catalog),
                    database_sha256=_sha256(catalog),
                    release_relations=1,
                    recording_relations=1,
                    ordered_credit_members=3,
                    artists=2,
                    verified_cache_projections=1,
                    provenance_record_count=2,
                    first_core_materialization={},
                    idempotent_core_replay={},
                    foreign_key_violations=0,
                    content_policy="contains genres",
                ).model_dump_json()
            )
            expected = _expected(
                evidence=evidence,
                artifact=artifact_path,
                catalog=catalog,
                catalog_report=report_path,
            )
            with self.assertRaisesRegex(ReleaseCreditGenreReportError, "pinned core-credit role"):
                build_release_credit_genre_report(
                    evidence_database=evidence,
                    evidence_artifact_path=artifact_path,
                    credit_catalog_database=catalog,
                    credit_catalog_report_path=report_path,
                    expected_inputs=expected,
                )

    def test_rejects_valid_shaped_catalog_report_tampering_before_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence, catalog = root / "evidence.sqlite", root / "catalog.sqlite"
            _prepare_evidence(evidence)
            _prepare_catalog(catalog)
            artifact_path = root / "artifact.json"
            artifact_path.write_text(_evidence_artifact(evidence).model_dump_json())
            catalog_report_path = root / "catalog-report.json"
            report = ArtistCreditCatalogReport(
                source_hydration_sha256=CORE_HYDRATION_SHA256,
                source_credit_sha256=ARTIST_CREDIT_V2_SHA256,
                candidate_database_path=str(catalog),
                database_sha256=_sha256(catalog),
                release_relations=1,
                recording_relations=1,
                ordered_credit_members=3,
                artists=2,
                verified_cache_projections=1,
                provenance_record_count=2,
                first_core_materialization={},
                idempotent_core_replay={},
                foreign_key_violations=0,
                content_policy="core_metadata_only_no_audio_preview_artwork_or_genres",
            )
            catalog_report_path.write_text(report.model_dump_json())
            expected = _expected(
                evidence=evidence,
                artifact=artifact_path,
                catalog=catalog,
                catalog_report=catalog_report_path,
            )
            catalog_report_path.write_text(
                report.model_copy(update={"artists": 99}).model_dump_json()
            )
            with self.assertRaisesRegex(ReleaseCreditGenreReportError, "catalog report SHA-256"):
                build_release_credit_genre_report(
                    evidence_database=evidence,
                    evidence_artifact_path=artifact_path,
                    credit_catalog_database=catalog,
                    credit_catalog_report_path=catalog_report_path,
                    expected_inputs=expected,
                )
