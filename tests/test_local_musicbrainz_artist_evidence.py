import hashlib
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.local_musicbrainz_artist_evidence import (
    LocalMusicBrainzArtistEvidenceError,
    LocalMusicBrainzEvidenceSources,
    direct_artists_for_seed,
    direct_seeds_for_artist,
)
from musix.musicbrainz_model_adapter import (
    AdapterSeedCoverage,
    MusicBrainzModelAdapterReport,
    adapter_report_sha256,
)
from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    ReleaseGroupEvidenceCounters,
    ReleaseGroupEvidenceCoverage,
    ReleaseGroupEvidenceSettings,
    artifact_sha256,
)
from musix.seed_reconciliation import (
    SeedReconciliationArtifact,
    SeedReconciliationDisposition,
)

_ARTIST_A = "00000000-0000-4000-8000-000000000001"
_ARTIST_B = "00000000-0000-4000-8000-000000000002"


class LocalMusicBrainzArtistEvidenceTests(unittest.TestCase):
    def test_seed_lookup_uses_stable_id_or_existing_idm_alias(self) -> None:
        with TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite")
            response = direct_artists_for_seed(
                _sources(database),
                "idm",
                limit=25,
            )

        self.assertEqual(response.seed.source_item_id, "item887")
        self.assertEqual(response.seed.name, "intelligent dance music")
        self.assertEqual(response.total_direct_artist_count, 2)
        self.assertEqual(response.artists[0].artist_mbid, _ARTIST_A)
        self.assertEqual(response.artists[0].facets, ("musicbrainz_genre", "musicbrainz_tag"))
        self.assertFalse(response.contextual_claims_available)
        self.assertFalse(response.release_group_support_included)
        self.assertGreaterEqual(response.verification_seconds, 0.0)
        self.assertGreaterEqual(response.query_seconds, 0.0)

    def test_artist_lookup_returns_only_exact_direct_stable_seed_ids(self) -> None:
        with TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite")
            response = direct_seeds_for_artist(
                _sources(database),
                _ARTIST_A,
                limit=25,
            )

        self.assertEqual([seed.source_item_id for seed in response.seeds], ["item2", "item887"])
        self.assertEqual(response.total_direct_seed_count, 2)
        self.assertFalse(response.contextual_claims_available)

    def test_rejects_database_evidence_outside_the_all_seed_sidecar(self) -> None:
        with TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite", outside_seed=True)
            with self.assertRaisesRegex(
                LocalMusicBrainzArtistEvidenceError, "outside the reconciliation"
            ):
                direct_seeds_for_artist(
                    _sources(database),
                    _ARTIST_B,
                    limit=25,
                )

    def test_rejects_database_that_does_not_match_completed_artifact(self) -> None:
        with TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite")
            artifact = _evidence_artifact(database)
            database.write_bytes(database.read_bytes() + b"unsealed")
            with self.assertRaisesRegex(
                LocalMusicBrainzArtistEvidenceError, "does not match the completed"
            ):
                direct_artists_for_seed(
                    _sources(database, evidence_artifact=artifact), "item887", limit=25
                )

    def test_rejects_valid_sidecar_from_a_different_seed_target(self) -> None:
        with TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite")
            report = _adapter_report().model_copy(update={"seed_target_output_sha256": "9" * 64})
            report = report.model_copy(update={"output_sha256": adapter_report_sha256(report)})
            with self.assertRaisesRegex(
                LocalMusicBrainzArtistEvidenceError, "verified seed binding"
            ):
                direct_artists_for_seed(
                    _sources(database, adapter_report=report),
                    "item887",
                    limit=25,
                )


def _reconciliation() -> SeedReconciliationArtifact:
    dispositions = (
        SeedReconciliationDisposition.model_construct(
            source_item_id="item2",
            source_external_id="enao-legacy:item2",
            seed_name="rock",
            normalized_name="rock",
            disposition="reconciled",
        ),
        SeedReconciliationDisposition.model_construct(
            source_item_id="item887",
            source_external_id="enao-legacy:item887",
            seed_name="intelligent dance music",
            normalized_name="intelligent dance music",
            disposition="review_only",
        ),
    )
    return SeedReconciliationArtifact.model_construct(
        seed_count=2,
        dispositions=dispositions,
        output_sha256="d" * 64,
        seed_source_id="fixture",
        seed_source_content_sha256="e" * 64,
        seed_identity_sha256="f" * 64,
    )


def _database(path: Path, *, outside_seed: bool = False) -> Path:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """CREATE TABLE direct_anchor (
                   genre_id TEXT NOT NULL,
                   artist_id TEXT NOT NULL,
                   facet TEXT NOT NULL,
                   evidence_ref TEXT NOT NULL,
                   PRIMARY KEY (genre_id, artist_id, facet, evidence_ref)
               ) WITHOUT ROWID;"""
        )
        connection.executemany(
            "INSERT INTO direct_anchor VALUES (?, ?, ?, ?)",
            [
                ("item887", _ARTIST_A, "musicbrainz_genre", "ref:one"),
                ("item887", _ARTIST_A, "musicbrainz_tag", "ref:two"),
                ("item887", _ARTIST_B, "musicbrainz_tag", "ref:three"),
                ("item2", _ARTIST_A, "musicbrainz_genre", "ref:four"),
            ],
        )
        if outside_seed:
            connection.execute(
                "INSERT INTO direct_anchor VALUES (?, ?, ?, ?)",
                ("item999", _ARTIST_B, "musicbrainz_genre", "ref:five"),
            )
    return path


def _evidence_artifact(database: Path) -> ReleaseGroupEvidenceArtifact:
    contents = database.read_bytes()
    preliminary = ReleaseGroupEvidenceArtifact(
        source_id="fixture",
        source_snapshot="fixture",
        source_url="https://example.test/release-group",
        source_archive_sha256="a" * 64,
        source_archive_bytes=1,
        source_member_bytes=1,
        source_cache_receipt_sha256="b" * 64,
        seed_target_output_sha256="c" * 64,
        settings=ReleaseGroupEvidenceSettings(),
        evidence_database_sha256=hashlib.sha256(contents).hexdigest(),
        evidence_database_bytes=len(contents),
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
            seed_count=2,
            direct_anchor_genre_count=2,
            direct_anchor_membership_count=3,
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


def _sources(
    database: Path,
    *,
    evidence_artifact: ReleaseGroupEvidenceArtifact | None = None,
    adapter_report: MusicBrainzModelAdapterReport | None = None,
) -> LocalMusicBrainzEvidenceSources:
    return LocalMusicBrainzEvidenceSources(
        database=database,
        evidence_artifact=evidence_artifact or _evidence_artifact(database),
        reconciliation=_reconciliation(),
        adapter_report=adapter_report or _adapter_report(),
    )


def _adapter_report() -> MusicBrainzModelAdapterReport:
    coverage = (
        AdapterSeedCoverage(
            source_item_id="item2",
            seed_name="rock",
            accepted_evidence_count=1,
            rejected_evidence_count=0,
            aggregate_membership_count=1,
            genre_membership_count=1,
            tag_membership_count=0,
        ),
        AdapterSeedCoverage(
            source_item_id="item887",
            seed_name="intelligent dance music",
            accepted_evidence_count=3,
            rejected_evidence_count=0,
            aggregate_membership_count=3,
            genre_membership_count=1,
            tag_membership_count=2,
        ),
    )
    preliminary = MusicBrainzModelAdapterReport(
        seed_reconciliation_output_sha256="d" * 64,
        seed_target_output_sha256="c" * 64,
        seed_target_archive_sha256="a" * 64,
        target_seed_input_sha256="b" * 64,
        reconciliation_seed_input_sha256="b" * 64,
        seed_source_id="fixture",
        seed_source_content_sha256="e" * 64,
        seed_identity_fingerprint="f" * 64,
        policy_sha256="a" * 64,
        accepted_evidence_count=4,
        rejected_evidence_count=0,
        unattributed_rejected_evidence_count=0,
        aggregate_membership_count=4,
        seed_count=2,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": adapter_report_sha256(preliminary)})
