# ruff: noqa: E501, S608
"""Exercise the v2-only credit export gate against retained local inputs when present."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from opennoise.deployment.musicbrainz_credit_static_export import (
    CreditMetadataPublicationApproval,
    MusicBrainzCreditStaticExportError,
    build_musicbrainz_credit_static_metadata,
    export_musicbrainz_credit_static_metadata,
    sha256_file,
)
from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import ArtistCreditCatalogReport

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = (
    ROOT / ".cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite"
)
REPORT = (
    ROOT / ".cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final-report.json"
)
PUBLIC = ROOT / "data/public.sqlite"
DISCOVERY = (
    ROOT
    / "dist/assets/static-discovery.4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c.json"
)
_CREDIT_ARTIFACT_SHA256 = "6454e5bfa4b4062e0bb7303629e0b5380af9997518ce386b896de69597496b7d"
_ARTIST_MBID = "10000000-0000-4000-8000-000000000001"
_RELEASE_MBID = "20000000-0000-4000-8000-000000000001"


@unittest.skipUnless(
    CANDIDATE.is_file() and REPORT.is_file() and PUBLIC.is_file() and DISCOVERY.is_file(),
    "retained local inputs are unavailable",
)
class MusicBrainzCreditStaticExportTests(unittest.TestCase):
    """The optional asset may only replay from the exact retained local candidate."""

    def test_replays_authorized_exact_id_rows_from_verified_v2_discovery(self) -> None:
        approval = CreditMetadataPublicationApproval(
            decision="approved",
            candidate_database_sha256=sha256_file(CANDIDATE),
            candidate_report_sha256=sha256_file(REPORT),
            public_database_sha256=sha256_file(PUBLIC),
            static_discovery_sha256=sha256_file(DISCOVERY),
            credit_artifact_sha256=_CREDIT_ARTIFACT_SHA256,
            approved_policy_key="musicbrainz-core-metadata-hydration",
        )
        payload = build_musicbrainz_credit_static_metadata(
            candidate_database=CANDIDATE,
            candidate_report=REPORT,
            public_database=PUBLIC,
            static_discovery=DISCOVERY,
            approval=approval,
        )
        self.assertEqual(
            (payload.visible_artist_count, payload.release_row_count, payload.recording_row_count),
            (1126, 82, 879),
        )
        self.assertEqual(len(payload.rows), 961)
        self.assertTrue(all(row.musicbrainz_artist_id for row in payload.rows))


class PortableMusicBrainzCreditStaticExportTests(unittest.TestCase):
    """Portable boundary tests independent of ignored candidates and generated assets."""

    def test_exact_id_success_and_existing_output_rejection(self) -> None:
        with (
            self._fixture() as fixture,
            patch(
                "opennoise.deployment.musicbrainz_credit_static_export._parse_discovery",
                return_value=self._discovery(fixture.public_hash, _ARTIST_MBID),
            ),
        ):
            payload, _ = export_musicbrainz_credit_static_metadata(
                candidate_database=fixture.candidate,
                candidate_report=fixture.report,
                public_database=fixture.public,
                static_discovery=fixture.discovery,
                approval=fixture.approval,
                output=fixture.output,
            )
            self.assertEqual((len(payload.rows), payload.release_row_count), (1, 1))
            with self.assertRaisesRegex(MusicBrainzCreditStaticExportError, "already exists"):
                export_musicbrainz_credit_static_metadata(
                    candidate_database=fixture.candidate,
                    candidate_report=fixture.report,
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=fixture.approval,
                    output=fixture.output,
                )

    def test_rejects_bad_approval_and_zero_exact_id_join(self) -> None:
        with self._fixture() as fixture:
            bad = fixture.approval.model_copy(update={"candidate_database_sha256": "0" * 64})
            with self.assertRaisesRegex(MusicBrainzCreditStaticExportError, "approval"):
                build_musicbrainz_credit_static_metadata(
                    candidate_database=fixture.candidate,
                    candidate_report=fixture.report,
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=bad,
                )
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_static_export._parse_discovery",
                    return_value=self._discovery(
                        fixture.public_hash, "30000000-0000-4000-8000-000000000001"
                    ),
                ),
                self.assertRaisesRegex(MusicBrainzCreditStaticExportError, "no visible rows"),
            ):
                build_musicbrainz_credit_static_metadata(
                    candidate_database=fixture.candidate,
                    candidate_report=fixture.report,
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=fixture.approval,
                )

    def test_rejects_invalid_v2_bytes_and_denied_policy(self) -> None:
        with self._fixture(policy_decision="deny") as fixture:
            with self.assertRaisesRegex(MusicBrainzCreditStaticExportError, "static discovery"):
                build_musicbrainz_credit_static_metadata(
                    candidate_database=fixture.candidate,
                    candidate_report=fixture.report,
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=fixture.approval,
                )
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_static_export._parse_discovery",
                    return_value=self._discovery(fixture.public_hash, _ARTIST_MBID),
                ),
                self.assertRaisesRegex(MusicBrainzCreditStaticExportError, "no visible rows"),
            ):
                build_musicbrainz_credit_static_metadata(
                    candidate_database=fixture.candidate,
                    candidate_report=fixture.report,
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=fixture.approval,
                )

    @staticmethod
    def _discovery(public_hash: str, artist_mbid: str) -> SimpleNamespace:
        return SimpleNamespace(
            availability="ready",
            source=SimpleNamespace(
                observation_kind="direct_source_claim", database_sha256=public_hash
            ),
            artists=(
                SimpleNamespace(
                    artist_id="artist:1",
                    musicbrainz_url=f"https://musicbrainz.org/artist/{artist_mbid}",
                ),
            ),
        )

    def _fixture(self, *, policy_decision: str = "allow") -> _CreditFixture:
        return _CreditFixture(self, policy_decision)


class _CreditFixture:
    def __init__(self, test: unittest.TestCase, policy_decision: str) -> None:
        self.test = test
        self.policy_decision = policy_decision

    def __enter__(self) -> SimpleNamespace:
        self.directory = self.test.enterContext(tempfile.TemporaryDirectory())
        root = Path(self.directory)
        candidate, public, discovery, output = (
            root / name
            for name in ("candidate.sqlite", "public.sqlite", "discovery.json", "output.json")
        )
        public.write_bytes(b"public")
        discovery.write_bytes(b"not a v2 asset")
        with sqlite3.connect(candidate) as connection:
            connection.executescript(
                f"""CREATE TABLE provenance_records (id INTEGER PRIMARY KEY, artifact_sha256 TEXT, policy_id INTEGER, record_fingerprint TEXT);
                CREATE TABLE rights_policies (id INTEGER PRIMARY KEY, policy_key TEXT, local_only INTEGER);
                CREATE TABLE active_rights_policy_permissions (policy_id INTEGER, use_kind TEXT, decision TEXT);
                CREATE TABLE catalog_entities (id INTEGER PRIMARY KEY, entity_kind TEXT);
                CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
                CREATE TABLE entity_identifiers (entity_id INTEGER, identifier_type_id INTEGER, normalized_value TEXT);
                CREATE TABLE entity_artist_credits (entity_id INTEGER, artist_credit_id INTEGER, provenance_id INTEGER);
                CREATE TABLE artist_credit_members (artist_credit_id INTEGER, position INTEGER, artist_id INTEGER, credited_name TEXT, join_phrase TEXT);
                CREATE TABLE entity_names (id INTEGER PRIMARY KEY, entity_id INTEGER, name TEXT, is_preferred INTEGER);
                INSERT INTO rights_policies VALUES (1, 'musicbrainz-core-metadata-hydration', 0);
                INSERT INTO active_rights_policy_permissions VALUES (1, 'display', '{self.policy_decision}');
                INSERT INTO active_rights_policy_permissions VALUES (1, 'export', '{self.policy_decision}');
                INSERT INTO provenance_records VALUES (1, '{_CREDIT_ARTIFACT_SHA256}', 1, '{"c" * 64}');
                INSERT INTO catalog_entities VALUES (1, 'artist'); INSERT INTO catalog_entities VALUES (2, 'release');
                INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id'); INSERT INTO identifier_types VALUES (2, 'musicbrainz_release_id');
                INSERT INTO entity_identifiers VALUES (1, 1, '{_ARTIST_MBID}'); INSERT INTO entity_identifiers VALUES (2, 2, '{_RELEASE_MBID}');
                INSERT INTO entity_artist_credits VALUES (2, 1, 1); INSERT INTO artist_credit_members VALUES (1, 0, 1, 'Artist', '');
                INSERT INTO entity_names VALUES (1, 2, 'Release', 1);"""
            )
        report = root / "report.json"
        report.write_text(
            ArtistCreditCatalogReport(
                source_hydration_sha256="b" * 64,
                source_credit_sha256=_CREDIT_ARTIFACT_SHA256,
                candidate_database_path=str(candidate),
                database_sha256=sha256_file(candidate),
                release_relations=1,
                recording_relations=0,
                ordered_credit_members=1,
                artists=1,
                verified_cache_projections=1,
                provenance_record_count=2,
                first_core_materialization={},
                idempotent_core_replay={},
                foreign_key_violations=0,
                content_policy="core_metadata_only_no_audio_preview_artwork_or_genres",
            ).model_dump_json()
        )
        approval = CreditMetadataPublicationApproval(
            decision="approved",
            candidate_database_sha256=sha256_file(candidate),
            candidate_report_sha256=sha256_file(report),
            public_database_sha256=sha256_file(public),
            static_discovery_sha256=sha256_file(discovery),
            credit_artifact_sha256=_CREDIT_ARTIFACT_SHA256,
            approved_policy_key="musicbrainz-core-metadata-hydration",
        )
        return SimpleNamespace(
            candidate=candidate,
            report=report,
            public=public,
            discovery=discovery,
            output=output,
            approval=approval,
            public_hash=sha256_file(public),
        )

    def __exit__(self, *unused: object) -> bool:
        return False
