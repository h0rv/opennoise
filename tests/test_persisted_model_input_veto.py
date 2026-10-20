"""Coarse persisted source-batch invalidation on the existing synthetic publish fixture."""

# ruff: noqa: E501 -- Literal SQL keeps recorded provenance and use boundaries visible.

import sqlite3
import unittest
from contextlib import closing
from typing import override
from unittest.mock import patch

from opennoise.db import DEFAULT_MIGRATION_PATHS, Database
from opennoise.ml.publish import publish_public_model
from tests import test_public_model_publish as publish_fixture


def seeded_fixture(*, schema: int = 14) -> publish_fixture.PublicModelPublishTests:
    """Publish the existing deterministic synthetic artifact, never a research fit."""
    fixture = publish_fixture.PublicModelPublishTests()
    try:
        with (
            patch("opennoise.db.SCHEMA_VERSION", schema),
            patch("opennoise.db.DEFAULT_MIGRATION_PATHS", DEFAULT_MIGRATION_PATHS[:schema]),
        ):
            fixture.setUp()
            with closing(sqlite3.connect(fixture.database_path)) as c, c:
                c.execute(
                    "INSERT INTO entity_claims(id,entity_id,claim_type,claim_key,normalized_value_json,asserted_at,provenance_id,policy_id,claim_hash) VALUES(100,2,'unused_literal','synthetic_unused','123','2026-01-01T00:00:00Z',2,3,?)",
                    ("1" * 64,),
                )
                c.execute(
                    "INSERT INTO artist_genre_evidence(id,artist_id,genre_id,evidence_kind,evidence_value,source_key,source_record_id,method_key,method_version,parameter_manifest_json,observed_at,provenance_id,policy_id,record_fingerprint) VALUES(100,2,1,'direct_source_claim',1,'wikidata-test','synthetic-direct','synthetic','1','{}','2026-01-01T00:00:00Z',2,3,?)",
                    ("2" * 64,),
                )
                c.execute(
                    "INSERT INTO album_genre_membership_observations(id,release_group_id,genre_id,evidence_kind,evidence_level,source_family,source_record_id,source_genre_name,method_key,method_version,observed_at,provenance_id,policy_id,record_fingerprint) VALUES(100,5,1,'wikidata_p136','release_group','wikidata','synthetic-album','Synthetic genre','synthetic','1','2026-01-01T00:00:00Z',2,3,?)",
                    ("3" * 64,),
                )
                c.execute(
                    "INSERT INTO artist_genre_evidence(id,artist_id,genre_id,evidence_kind,evidence_value,source_key,source_record_id,source_album_evidence_id,source_credit_provenance_id,source_credit_definition_provenance_id,method_key,method_version,parameter_manifest_json,observed_at,provenance_id,policy_id,record_fingerprint) VALUES(101,2,1,'release_group_propagation',1,'wikidata-test','synthetic-propagated',100,1,1,'synthetic','1','{}','2026-01-01T00:00:00Z',2,3,?)",
                    ("4" * 64,),
                )
            publish_public_model(fixture.database_path, fixture.artifact_path, policy_id=3)
    except Exception:
        fixture.tearDown()
        raise
    else:
        return fixture


def state(path):  # noqa: ANN001, ANN201
    """Observe central views plus ordinary database map/detail APIs."""
    with closing(sqlite3.connect(path)) as c:
        counts = tuple(
            c.execute(query).fetchone()[0]
            for query in (
                "SELECT count(*) FROM servable_public_model_runs",
                "SELECT count(*) FROM displayable_public_genre_representatives",
                "SELECT count(*) FROM displayable_map_points WHERE layout_key='public'",
                "SELECT count(*) FROM displayable_public_genre_profile_memberships",
                "SELECT count(*) FROM displayable_public_genre_neighbors",
            )
        )
    database = Database(path)
    detail = database.genre_detail(1)
    return counts, tuple(database.map_points("public")), detail


class PersistedModelInputVetoTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.fixture = seeded_fixture()
        self.addCleanup(self.fixture.tearDown)
        self.path = self.fixture.database_path
        self.events = 0
        self.baseline = state(self.path)

    def event(self, kind: str, ref: str, use: str, action: str) -> None:
        """Append one synthetic suppression/release event."""
        self.events += 1
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute(
                "INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,effective_at,event_fingerprint) VALUES(?,?,?,?, 'Synthetic only','2026-01-01T00:00:00Z',?)",
                (kind, ref, use, action, f"{self.events:064x}"),
            )

    def assert_retracted(self) -> None:
        """All dependent persisted projections use the same central run gate."""
        counts, points, detail = state(self.path)
        self.assertEqual(counts, (0, 0, 0, 0, 0))
        self.assertEqual(points, ())
        self.assertIsNone(detail)

    def test_input_embed_veto_retracts_all_views_and_apis_then_release_restores(self) -> None:
        for kind, ref in (
            ("source", "3"),
            ("provenance", "2"),
            ("snapshot", "2"),
            ("artifact", "2"),
        ):
            with self.subTest(kind=kind):
                self.event(kind, ref, "embed", "suppress")
                self.assert_retracted()
                self.event(kind, ref, "embed", "release")
                self.assertEqual(state(self.path), self.baseline)

    def test_any_recognized_same_batch_row_including_unused_and_propagated_retracts(self) -> None:
        for ref in ("artist_genre_evidence:100", "artist_genre_evidence:101", "entity_claims:100"):
            for use in ("all", "embed"):
                with self.subTest(ref=ref, use=use):
                    self.event("claim", ref, use, "suppress")
                    self.assert_retracted()
                    self.event("claim", ref, use, "release")
                    self.assertEqual(state(self.path), self.baseline)

    def test_other_claim_uses_and_unrelated_or_unrecognized_refs_are_noops(self) -> None:
        for use in ("display", "export", "normalize", "train", "local_search"):
            self.event("claim", "entity_claims:100", use, "suppress")
            self.assertEqual(state(self.path), self.baseline)
        for ref in (
            "entity_claims:1",
            "100",
            "unknown:100",
            "entity_claims:0100",
            "entity_claims:100.0",
            "entity_claims:100junk",
            "entity_claims:999999",
            "artist_genre_evidence:999999",
            "entity_claims:0",
            "entity_claims:-1",
            "entity_claims:100\x00junk",
            "entity_claims:100\n",
            "entity_claims: 100",
            "entity_claims:999999999999999999999999999999999999",
        ):
            self.event("claim", ref, "all", "suppress")
            self.assertEqual(state(self.path), self.baseline)

    def test_nonpositive_existing_claim_ids_are_not_canonical_references(self) -> None:
        with closing(sqlite3.connect(self.path)) as c, c:
            for row_id in (0, -1):
                c.execute(
                    "INSERT INTO entity_claims(id,entity_id,claim_type,claim_key,normalized_value_json,asserted_at,provenance_id,policy_id,claim_hash) VALUES(?,2,'unused_literal','nonpositive','0','2026-01-01T00:00:00Z',2,3,?)",
                    (row_id, f"{row_id + 9:064x}"),
                )
        for ref in ("entity_claims:0", "entity_claims:-1"):
            self.event("claim", ref, "all", "suppress")
            self.assertEqual(state(self.path), self.baseline)

    def test_claim_gate_resolves_rows_by_primary_key_without_catalogwide_index(self) -> None:
        with closing(sqlite3.connect(self.path)) as c:
            plan = [
                str(row[3])
                for row in c.execute("EXPLAIN QUERY PLAN SELECT * FROM servable_public_model_runs")
            ]
        for table in ("claim", "evidence"):
            self.assertTrue(
                any(f"SEARCH {table} USING INTEGER PRIMARY KEY" in p for p in plan), plan
            )
            self.assertFalse(
                any(f"SCAN {table}" in p or f"SEARCH {table} USING AUTOMATIC" in p for p in plan),
                plan,
            )

    def test_source_normalize_train_only_noop_and_existing_display_export_all_vetoes_remain(
        self,
    ) -> None:
        for use in ("normalize", "train", "local_search"):
            self.event("source", "3", use, "suppress")
            self.assertEqual(state(self.path), self.baseline)
        for use in ("all", "display", "export"):
            self.event("source", "3", use, "suppress")
            self.assert_retracted()
            self.event("source", "3", use, "release")
            self.assertEqual(state(self.path), self.baseline)

    def test_raw_runs_ledger_selections_and_persisted_output_rows_are_immutable(self) -> None:
        tables = (
            "public_model_runs",
            "public_model_input_provenance",
            "current_public_models",
            "public_genre_names",
            "public_genre_representatives",
            "public_genre_profile_memberships",
            "public_genre_neighbors",
            "public_model_layouts",
            "layout_runs",
            "layout_points",
        )

        def rows():  # noqa: ANN202
            with closing(sqlite3.connect(self.path)) as c:
                return {name: c.execute(f"SELECT * FROM {name}").fetchall() for name in tables}  # noqa: S608 -- Fixed test table names.

        before = rows()
        self.event("claim", "entity_claims:100", "embed", "suppress")
        self.assert_retracted()
        self.assertEqual(rows(), before)
        self.event("claim", "entity_claims:100", "embed", "release")
        self.assertEqual(rows(), before)
        self.assertEqual(state(self.path), self.baseline)

    def test_thirteen_upgrade_retains_rows_and_changes_only_dynamic_eligibility(self) -> None:
        old = seeded_fixture(schema=13)
        try:
            old_state = state(old.database_path)
            with closing(sqlite3.connect(old.database_path)) as c, c:
                c.execute(
                    "INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,effective_at,event_fingerprint) VALUES('claim','entity_claims:100','embed','suppress','Synthetic only','2026-01-01T00:00:00Z',?)",
                    ("f" * 64,),
                )
                raw = c.execute("SELECT * FROM public_model_runs").fetchall()
                ledger = c.execute("SELECT * FROM public_model_input_provenance").fetchall()
            self.assertEqual(state(old.database_path), old_state)
            Database(old.database_path).initialize()
            with closing(sqlite3.connect(old.database_path)) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 14)
                self.assertEqual(c.execute("SELECT * FROM public_model_runs").fetchall(), raw)
                self.assertEqual(
                    c.execute("SELECT * FROM public_model_input_provenance").fetchall(), ledger
                )
            self.assertEqual(state(old.database_path)[0], (0, 0, 0, 0, 0))
            before = old.database_path.read_bytes()
            Database(old.database_path).initialize()
            self.assertEqual(old.database_path.read_bytes(), before)
        finally:
            old.tearDown()
