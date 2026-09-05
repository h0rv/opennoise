from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from musix.public_artist_membership import canonical_sha256
from musix.public_artist_membership_adapter import (
    CertifiedPublicDirectSelector,
    CertifiedPublicMembershipAdapterPolicy,
    CertifiedPublicMembershipAdapterReceipt,
    adapt_certified_public_membership_input,
    verify_certified_public_membership_receipt,
)


class PublicArtistMembershipAdapterTests(unittest.TestCase):
    def _synthetic_database(self, path: Path) -> None:
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(
                """
                CREATE TABLE data_sources (id INTEGER PRIMARY KEY, source_key TEXT,
                    license_name TEXT, default_policy_id INTEGER);
                CREATE TABLE rights_policies (id INTEGER PRIMARY KEY, policy_key TEXT,
                    policy_version INTEGER, classification TEXT, local_only INTEGER);
                CREATE TABLE active_rights_policy_permissions
                    (policy_id INTEGER, use_kind TEXT, decision TEXT);
                CREATE TABLE provenance_records (id INTEGER PRIMARY KEY, source_id INTEGER,
                    policy_id INTEGER, snapshot_ref TEXT, artifact_sha256 TEXT,
                    record_fingerprint TEXT);
                CREATE TABLE source_snapshots (id INTEGER PRIMARY KEY, source_id INTEGER,
                    snapshot_ref TEXT, manifest_sha256 TEXT, policy_id INTEGER);
                CREATE TABLE source_artifacts (id INTEGER PRIMARY KEY, snapshot_id INTEGER,
                    artifact_ref TEXT, sha256 TEXT, policy_id INTEGER);
                CREATE TABLE artist_genre_evidence (id INTEGER PRIMARY KEY, artist_id INTEGER,
                    genre_id INTEGER, evidence_kind TEXT, evidence_value REAL, source_key TEXT,
                    source_record_id TEXT, method_key TEXT, provenance_id INTEGER,
                    policy_id INTEGER, record_fingerprint TEXT);
                CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
                CREATE TABLE entity_identifiers (id INTEGER PRIMARY KEY, entity_id INTEGER,
                    identifier_type_id INTEGER, normalized_value TEXT);
                CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE artist_co_listen_runs (id INTEGER PRIMARY KEY, run_ref TEXT,
                    ingest_attempt_id INTEGER, artifact_id INTEGER, window_seconds INTEGER,
                    minimum_distinct_users INTEGER, listens_seen INTEGER,
                    distinct_artists INTEGER, user_windows INTEGER, candidate_pairs INTEGER,
                    emitted_pairs INTEGER, quarantined_records INTEGER);
                CREATE TABLE ingest_attempts (id INTEGER PRIMARY KEY, snapshot_id INTEGER,
                    policy_id INTEGER);
                CREATE TABLE artist_co_listen_evidence (id INTEGER PRIMARY KEY,
                    ingest_attempt_id INTEGER, left_artist_source_id TEXT,
                    right_artist_source_id TEXT, distinct_user_count INTEGER,
                    evidence_fingerprint TEXT);
                """
            )
            connection.executemany(
                "INSERT INTO rights_policies VALUES (?, ?, 1, 'public_domain', 0)",
                ((1, "default-not-selected"), (2, "direct-exact"), (3, "aggregate-exact")),
            )
            connection.executemany(
                "INSERT INTO active_rights_policy_permissions VALUES (?, 'export', 'allow')",
                ((2,), (3,)),
            )
            connection.executemany(
                "INSERT INTO data_sources VALUES (?, ?, 'CC0-1.0', ?)",
                (
                    (1, "wikidata_phase3_artists_good", 1),
                    (2, "other-unrelated", 1),
                    (3, "listenbrainz_joint_good", 1),
                ),
            )
            connection.execute("INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id')")
            connection.execute("INSERT INTO identifier_types VALUES (2, 'wikidata_genre_qid')")
            connection.executemany(
                "INSERT INTO entity_identifiers VALUES (?, ?, ?, ?)",
                ((1, 10, 1, "artist-a"), (2, 20, 2, "Q-jazz")),
            )
            connection.execute("INSERT INTO genres VALUES (20, 'Jazz')")
            connection.execute(
                "INSERT INTO source_snapshots VALUES (1, 1, 'snapshot-direct', ?, 2)",
                ("d" * 64,),
            )
            connection.execute(
                "INSERT INTO source_artifacts VALUES (1, 1, 'direct.json', ?, 2)",
                ("a" * 64,),
            )
            connection.execute(
                "INSERT INTO provenance_records VALUES "
                "(1, 1, 2, 'snapshot-direct', ?, 'fp-direct')",
                ("a" * 64,),
            )
            connection.execute(
                "INSERT INTO artist_genre_evidence VALUES "
                "(1, 10, 20, 'direct_source_claim', 1.0, ?, 'record-1', "
                "'wikidata_p136', 1, 2, 'fp-direct')",
                ("wikidata_phase3_artists_good",),
            )
            connection.execute(
                "INSERT INTO artist_genre_evidence VALUES "
                "(2, 10, 20, 'direct_source_claim', 9.0, 'other-unrelated', "
                "'record-other', 'wikidata_p136', 1, 2, 'fp-other')"
            )
            connection.execute(
                "INSERT INTO source_snapshots VALUES (2, 3, 'snapshot-aggregate', ?, 3)",
                ("e" * 64,),
            )
            connection.execute(
                "INSERT INTO source_artifacts VALUES (2, 2, 'aggregate.json', ?, 3)",
                ("b" * 64,),
            )
            connection.execute("INSERT INTO ingest_attempts VALUES (1, 2, 3)")
            connection.execute(
                "INSERT INTO artist_co_listen_runs VALUES "
                "(1, 'run-good', 1, 2, 86400, 5, 10, 2, 1, 1, 1, 0)"
            )
            connection.execute(
                "INSERT INTO artist_co_listen_evidence VALUES "
                "(1, 1, 'artist-a', 'artist-b', 5, 'fp-pair')"
            )
            connection.execute(
                "INSERT INTO data_sources VALUES (4, 'listenbrainz_other', 'CC0-1.0', 1)"
            )
            connection.execute(
                "INSERT INTO source_snapshots VALUES (3, 4, 'snapshot-other', ?, 3)",
                ("f" * 64,),
            )
            connection.execute(
                "INSERT INTO source_artifacts VALUES (3, 3, 'other.json', ?, 3)",
                ("c" * 64,),
            )
            connection.execute("INSERT INTO ingest_attempts VALUES (2, 3, 3)")
            connection.execute(
                "INSERT INTO artist_co_listen_runs VALUES "
                "(2, 'run-other', 2, 3, 86400, 5, 10, 2, 1, 1, 1, 0)"
            )
            connection.execute(
                "INSERT INTO artist_co_listen_evidence VALUES "
                "(2, 2, 'artist-x', 'artist-y', 99, 'fp-other-pair')"
            )
            connection.commit()

    def test_synthetic_adapter_binds_exact_provenance_and_ignores_unrelated_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "public.sqlite"
            self._synthetic_database(database)
            adaptation = adapt_certified_public_membership_input(
                database,
                CertifiedPublicMembershipAdapterPolicy(
                    include_aggregate_candidates=True,
                    aggregate_source_key_prefix="listenbrainz_joint_",
                ),
            )
        self.assertEqual(adaptation.receipt.direct_row_count, 1)
        self.assertEqual(adaptation.receipt.aggregate_pair_count, 1)
        self.assertEqual(adaptation.receipt.direct_source_bindings[0].policy_key, "direct-exact")
        self.assertEqual(
            adaptation.receipt.aggregate_source_bindings[0].policy_key, "aggregate-exact"
        )

    def test_build_receipt_revalidation_rejects_database_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "public.sqlite"
            self._synthetic_database(database)
            policy = CertifiedPublicMembershipAdapterPolicy(
                include_aggregate_candidates=True,
                aggregate_source_key_prefix="listenbrainz_joint_",
            )
            adaptation = adapt_certified_public_membership_input(database, policy)
            payload = adaptation.receipt.model_dump(mode="python", exclude={"output_sha256"})
            payload["database_file_sha256"] = "0" * 64
            tampered = CertifiedPublicMembershipAdapterReceipt.model_validate(
                {**payload, "output_sha256": canonical_sha256(payload)}
            )
            with self.assertRaisesRegex(ValueError, "do not reproduce"):
                verify_certified_public_membership_receipt(
                    adaptation.approved_input, tampered, database, policy
                )

    def test_build_receipt_revalidation_rejects_forged_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "public.sqlite"
            self._synthetic_database(database)
            policy = CertifiedPublicMembershipAdapterPolicy(
                include_aggregate_candidates=True,
                aggregate_source_key_prefix="listenbrainz_joint_",
            )
            adaptation = adapt_certified_public_membership_input(database, policy)
            row = adaptation.approved_input.public_model_input.direct_memberships[0]
            forged_input = adaptation.approved_input.public_model_input.model_copy(
                update={"direct_memberships": (row.model_copy(update={"value": 2.0}),)}
            )
            forged_approved = adaptation.approved_input.model_copy(
                update={
                    "public_model_input": forged_input,
                    "public_model_input_sha256": canonical_sha256(
                        forged_input.model_dump(mode="json")
                    ),
                }
            )
            payload = adaptation.receipt.model_dump(mode="python", exclude={"output_sha256"})
            payload["approved_input_sha256"] = forged_approved.public_model_input_sha256
            forged_receipt = CertifiedPublicMembershipAdapterReceipt.model_validate(
                {**payload, "output_sha256": canonical_sha256(payload)}
            )
            with self.assertRaisesRegex(ValueError, "do not reproduce"):
                verify_certified_public_membership_receipt(
                    forged_approved, forged_receipt, database, policy
                )

    def test_synthetic_adapter_detects_database_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "public.sqlite"
            self._synthetic_database(database)
            with (
                patch(
                    "musix.public_artist_membership_adapter._file_sha256",
                    side_effect=("a" * 64, "b" * 64),
                ),
                self.assertRaisesRegex(ValueError, "changed while adapting"),
            ):
                adapt_certified_public_membership_input(
                    database,
                    CertifiedPublicMembershipAdapterPolicy(
                        include_aggregate_candidates=True,
                        aggregate_source_key_prefix="listenbrainz_joint_",
                    ),
                )

    def test_direct_source_union_is_explicitly_paired(self) -> None:
        policy = CertifiedPublicMembershipAdapterPolicy(
            direct_selectors=(
                CertifiedPublicDirectSelector(
                    source="wikidata",
                    facet="wikidata_p136",
                    source_key_prefix="wikidata_phase3_artists_",
                    method_key="wikidata_p136",
                    required_license="CC0-1.0",
                ),
                CertifiedPublicDirectSelector(
                    source="musicbrainz",
                    facet="musicbrainz_tag",
                    source_key_prefix="musicbrainz_",
                    method_key="musicbrainz_artist_tag",
                    required_license="CC0-1.0",
                ),
            )
        )
        self.assertEqual(policy.effective_direct_sources, ("wikidata", "musicbrainz"))

        with self.assertRaisesRegex(ValueError, "at least one"):
            CertifiedPublicMembershipAdapterPolicy(
                direct_selectors=(),
            )
        with self.assertRaisesRegex(ValueError, "String should match pattern"):
            CertifiedPublicMembershipAdapterPolicy(aggregate_source_key_prefix="listenbrainz_*")
        with self.assertRaisesRegex(ValueError, "require CC0-1.0"):
            CertifiedPublicMembershipAdapterPolicy(
                direct_selectors=(
                    CertifiedPublicDirectSelector(
                        source="musicbrainz",
                        facet="musicbrainz_tag",
                        source_key_prefix="musicbrainz_",
                        method_key="musicbrainz_artist_tag",
                        required_license="CC-BY-SA-3.0",
                    ),
                )
            )

    def test_musicbrainz_tag_selector_projects_tag_identity_and_facet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "public.sqlite"
            self._synthetic_database(database)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "INSERT INTO rights_policies VALUES (?, ?, 1, 'public_domain', 0)",
                    (4, "musicbrainz-direct"),
                )
                connection.execute(
                    "INSERT INTO active_rights_policy_permissions VALUES (4, 'export', 'allow')"
                )
                connection.execute(
                    "INSERT INTO data_sources VALUES (?, ?, 'CC0-1.0', ?)",
                    (5, "musicbrainz_tags_fixture", 4),
                )
                connection.execute(
                    "INSERT INTO source_snapshots VALUES (4, 5, 'snapshot-tags', ?, 4)",
                    ("7" * 64,),
                )
                connection.execute(
                    "INSERT INTO source_artifacts VALUES (4, 4, 'tags.json', ?, 4)",
                    ("8" * 64,),
                )
                connection.execute(
                    "INSERT INTO provenance_records VALUES "
                    "(4, 5, 4, 'snapshot-tags', ?, 'fp-tags')",
                    ("8" * 64,),
                )
                connection.execute(
                    "INSERT INTO identifier_types VALUES (4, 'musicbrainz_tag_name')"
                )
                connection.execute("INSERT INTO genres VALUES (30, 'Ambient')")
                connection.execute(
                    "INSERT INTO entity_identifiers VALUES (?, ?, ?, ?)",
                    (31, 30, 4, "tag:ambient"),
                )
                connection.execute(
                    "INSERT INTO artist_genre_evidence VALUES "
                    "(4, 10, 30, 'direct_source_claim', 3.0, ?, 'tag-record', "
                    "'musicbrainz_artist_tag', 4, 4, 'fp-tag-row')",
                    ("musicbrainz_tags_fixture",),
                )
                connection.commit()
            policy = CertifiedPublicMembershipAdapterPolicy(
                direct_selectors=(
                    CertifiedPublicDirectSelector(
                        source="musicbrainz",
                        facet="musicbrainz_tag",
                        source_key_prefix="musicbrainz_tags_",
                        method_key="musicbrainz_artist_tag",
                        required_license="CC0-1.0",
                    ),
                )
            )
            adaptation = adapt_certified_public_membership_input(database, policy)

        membership = adaptation.approved_input.public_model_input.direct_memberships[0]
        self.assertEqual(membership.artist_id, "musicbrainz:artist:artist-a")
        self.assertEqual(membership.genre_id, "musicbrainz:tag:tag:ambient")
        self.assertEqual(membership.facet, "musicbrainz_tag")
        self.assertEqual(
            adaptation.approved_input.public_model_input.genres[0].evidence_refs,
            ("musicbrainz:artist:tag:tag:ambient",),
        )

    def test_certified_release_counts_and_provenance_bindings(self) -> None:
        database = Path(
            "/home/h0rv/projects/musix/.cache/public-release-custody-integrated/objects/"
            "cache/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite"
        )
        if not database.exists():
            self.skipTest("certified public release is not present")
        adaptation = adapt_certified_public_membership_input(
            database,
            CertifiedPublicMembershipAdapterPolicy(include_aggregate_candidates=True),
        )
        self.assertEqual(adaptation.receipt.direct_row_count, 4948)
        self.assertEqual(adaptation.receipt.aggregate_pair_count, 13175)
        self.assertEqual(adaptation.receipt.aggregate_emitted_pairs, 30903)
        self.assertEqual(len(adaptation.receipt.direct_source_bindings), 8)
        self.assertTrue(
            all(
                item.policy_key.startswith("manifest:wikidata_phase3_artists_")
                for item in adaptation.receipt.direct_source_bindings
            )
        )
        self.assertEqual(
            adaptation.approved_input.input_file_sha256, adaptation.receipt.database_file_sha256
        )


if __name__ == "__main__":
    unittest.main()
