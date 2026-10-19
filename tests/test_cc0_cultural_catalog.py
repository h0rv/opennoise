"""Real retained complete-cohort ingestion, identity missingness and public source navigation."""

# ruff: noqa: SLF001 -- exercise read-only custody gates and existing navigation APIs directly.
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any, ClassVar, override
from unittest.mock import patch

from opennoise.db import Database
from opennoise.models.catalog import EntityProjection, ExternalIdentity, NameClaim
from opennoise.pipeline.cultural_catalog import (
    CORE_SHA,
    PACKS,
    _hash,
    _persist_projection,
    _source,
    build,
    ingest_pack,
    load_pack,
)
from opennoise.serving.public.artist_membership_adapter import (
    CertifiedPublicMembershipAdapterPolicy,
    adapt_certified_public_membership_input,
    source_policy_for_adapter,
)
from opennoise.serving.public.artist_navigation_store import (
    PublicArtistNavigationStore,
    PublicArtistNavigationStoreError,
)

ROOT = Path(__file__).resolve().parents[1]
CORE = (
    ROOT
    / "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256"
    / f"{CORE_SHA}.json"
)
CULTURAL = ROOT / "data/examples/cultural-context"
INDEPENDENT = ROOT / "data/examples/independent-cultural-context"
NAMELESS = {"Q7613062": 5, "Q12786712": 3, "Q247237": 12}


def _suppress(c: sqlite3.Connection, kind: str, ref: int, use: str) -> None:
    c.execute(
        """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,
                 reason,effective_at,event_fingerprint) VALUES(?,?,?,'suppress',
                 'Explicit source-boundary fixture','2026-01-01T00:00:00Z',?)""",
        (kind, str(ref), use, hashlib.sha256(f"{kind}:{ref}:{use}".encode()).hexdigest()),
    )
    c.commit()


class CompleteCulturalCatalogTests(unittest.TestCase):
    """The retained raw files are checked-in CC0 inputs; no downloads or model fits."""

    temp: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]
    report: ClassVar[dict[str, Any]]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / "complete"
        cls.report = build(
            CORE, CORE_SHA, CULTURAL, PACKS[0][1], INDEPENDENT, PACKS[1][1], cls.output
        )

    @override
    def setUp(self) -> None:
        self.path = Path(self.temp.name) / (self._testMethodName + ".sqlite")
        with (
            closing(sqlite3.connect(self.output / "musicbrainz-first.sqlite")) as a,
            closing(sqlite3.connect(self.path)) as b,
        ):
            a.backup(b)
        self.c = sqlite3.connect(self.path)
        self.c.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.c.close)
        self.pack = load_pack(CULTURAL, *PACKS[0])
        self.policy = CertifiedPublicMembershipAdapterPolicy.model_validate_json(
            (self.output / "adapter-policy.json").read_bytes()
        )

    def test_all_source_and_native_denominators_both_orders(self) -> None:
        self.assertEqual(
            self.report["source"],
            {
                "unique_requested_artists": 150,
                "source_nominations": 152,
                "matched_artists": 88,
                "missingness": {
                    "no_exact_source_match": 62,
                    "matched_with_p136": 78,
                    "matched_without_observed_p136": 10,
                },
                "source_p136_observations": 287,
                "unique_p136_facts": 278,
                "genre_qids": 151,
            },
        )
        for order in self.report["orders"].values():
            self.assertTrue(order["projection_idempotent"])
            self.assertEqual(
                {
                    k: order["counts"][k]
                    for k in (
                        "artists",
                        "release_groups",
                        "recordings",
                        "entity_claims",
                        "artist_genre_evidence",
                    )
                },
                {
                    "artists": 433,
                    "release_groups": 87,
                    "recordings": 1031,
                    "entity_claims": 287,
                    "artist_genre_evidence": 278,
                },
            )
            self.assertEqual(order["adapter"]["direct_rows"], 278)
            self.assertEqual(order["adapter"]["genres"], 151)
            self.assertEqual(order["consumer_source_families"], ["wikidata"])
            self.assertEqual(order["consumer_source_facets"], ["wikidata_p136"])
            neighbors = order["neighbors"]
            self.assertEqual(len(neighbors), 433)
            self.assertEqual(sum(bool(r["neighbors"]) for r in neighbors.values()), 72)
            self.assertEqual(sum(r["neighbor_count"] for r in neighbors.values()), 580)
        self.assertEqual(
            self.report["orders"]["musicbrainz-first"]["graph"],
            self.report["orders"]["wikidata-first"]["graph"],
        )
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM artist_credit_members m JOIN entity_artist_credits e ON "
                "e.artist_credit_id=m.artist_credit_id"
            ).fetchone()[0],
            1344,
        )
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM source_artifacts a JOIN source_snapshots s ON "
                "s.id=a.snapshot_id JOIN data_sources d ON d.id=s.source_id WHERE "
                "d.source_key GLOB 'wikidata_*'"
            ).fetchone()[0],
            4,
        )
        for (payload,) in self.c.execute("SELECT normalized_value_json FROM entity_claims"):
            value = json.loads(payload)
            self.assertIsNone(value["rank"])
            self.assertIsNone(value["statement_id"])
            self.assertEqual(value["references"], [])

    def test_missing_names_are_not_name_or_search_claims_and_remain_navigable(self) -> None:
        store = PublicArtistNavigationStore(self.path)
        for qid, count in NAMELESS.items():
            entity = self.c.execute(
                """SELECT DISTINCT i.entity_id FROM entity_identifiers i
                 JOIN identifier_types t ON t.id=i.identifier_type_id
                 WHERE t.type_key='wikidata_artist_qid' AND i.normalized_value=?""",
                (qid,),
            ).fetchone()[0]
            self.assertEqual(
                self.c.execute(
                    "SELECT count(*) FROM entity_names WHERE entity_id=?", (entity,)
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                self.c.execute(
                    "SELECT count(*) FROM search_documents WHERE entity_id=?", (entity,)
                ).fetchone()[0],
                0,
            )
            response = store._related_artists_sync(entity, 0, 50)
            self.assertEqual(response.artist.name, qid)
            self.assertEqual(response.artist.name_status, "source_identifier")
            self.assertEqual(len(response.related), count)
            neighbor = response.related[0].artist.entity_id
            reverse = store._related_artists_sync(neighbor, 0, 50)
            found = next(r.artist for r in reverse.related if r.artist.entity_id == entity)
            self.assertEqual(found.name_status, "source_identifier")
        named = self.c.execute(
            "SELECT n.entity_id FROM displayable_entity_names n JOIN artists a ON "
            "a.id=n.entity_id ORDER BY n.id LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(
            store._related_artists_sync(named, 0, 50).artist.name_status, "source_name"
        )

    def test_explicit_empty_names_only_for_artist_and_still_required_field(self) -> None:
        value = EntityProjection(
            entity_kind="artist",
            source_identity=ExternalIdentity(namespace="wikidata", value="Q123"),
            names=(),
        )
        self.assertEqual(value.names, ())
        for kind in ("genre", "recording", "release_group", "work"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Only artist"):
                EntityProjection.model_validate(
                    {"entity_kind": kind, "source_identity": value.source_identity, "names": ()}
                )
        with self.assertRaises(ValueError):
            EntityProjection.model_validate(
                {"entity_kind": "artist", "source_identity": value.source_identity}
            )

    def test_all150_identity_missingness_and150_observed_genre_labels(self) -> None:
        missing = json.loads((self.output / "missingness.json").read_bytes())
        self.assertEqual(len({r["musicbrainz_artist_id"] for r in missing}), 150)
        self.assertEqual(sum(r["wikidata_artist_id"] is None for r in missing), 62)
        self.assertEqual(sum(len(r["source_observations"]) for r in missing), 152)
        approved = json.loads((self.output / "musicbrainz-first.approved-input.json").read_bytes())[
            "public_model_input"
        ]
        genres = approved["genres"]
        self.assertEqual(sum(g["name"] == g["genre_id"].rsplit(":", 1)[1] for g in genres), 1)
        self.assertEqual(
            next(g["name"] for g in genres if g["genre_id"].endswith(":Q3071")), "Q3071"
        )
        self.assertEqual(
            self.c.execute(
                "SELECT count(DISTINCT n.entity_id) FROM entity_names n JOIN genres g ON "
                "g.id=n.entity_id"
            ).fetchone()[0],
            150,
        )
        self.assertEqual(
            source_policy_for_adapter(self.policy).allowed_direct_sources, frozenset({"wikidata"})
        )

    def test_repeated_capture_claims_retained_without_fact_votes_or_fallback(self) -> None:
        repeat = self.c.execute("""SELECT c.entity_id,
             json_extract(c.normalized_value_json,'$.target.value')
             FROM entity_claims c GROUP BY 1,2 HAVING count(*)=2 LIMIT 1""").fetchone()
        self.assertIsNotNone(repeat)
        artist, qid = repeat
        direct = self.c.execute(
            """SELECT e.source_key FROM artist_genre_evidence e
             JOIN entity_identifiers i ON i.entity_id=e.genre_id
             JOIN identifier_types t ON t.id=i.identifier_type_id
             WHERE e.artist_id=? AND t.type_key='wikidata_genre_qid' AND i.normalized_value=?
             LIMIT 1""",
            (artist, qid),
        ).fetchone()[0]
        self.assertEqual(direct, PACKS[0][0])
        source = self.c.execute(
            "SELECT id FROM data_sources WHERE source_key=?", (direct,)
        ).fetchone()[0]
        _suppress(self.c, "source", source, "export")
        adapted = adapt_certified_public_membership_input(self.path, self.policy)
        self.assertEqual(adapted.receipt.direct_row_count, 170)
        artist_qid = self.c.execute(
            "SELECT i.normalized_value FROM entity_identifiers i "
            "JOIN identifier_types t ON t.id=i.identifier_type_id "
            "WHERE i.entity_id=? AND t.type_key='wikidata_artist_qid' LIMIT 1",
            (artist,),
        ).fetchone()[0]
        self.assertNotIn(
            (f"wikidata:artist:{artist_qid}", f"wikidata:genre:{qid}"),
            {
                (r.artist_id, r.genre_id)
                for r in adapted.approved_input.public_model_input.direct_memberships
            },
        )
        self.assertEqual(self.c.execute("SELECT count(*) FROM entity_claims").fetchone()[0], 287)
        before = self.c.total_changes
        ingest_pack(self.c, self.pack)  # export-only suppression does not revoke normalization.
        self.assertEqual(self.c.total_changes, before)

    def test_registered_source_normalization_suppression_rejects_before_mutation(self) -> None:
        source = self.c.execute(
            "SELECT id FROM data_sources WHERE source_key=?", (PACKS[0][0],)
        ).fetchone()[0]
        _suppress(self.c, "source", source, "normalize")
        before = self.c.total_changes
        with self.assertRaisesRegex(ValueError, "suppressed for normalization"):
            ingest_pack(self.c, self.pack)
        self.assertEqual(self.c.total_changes, before)

    def test_nameless_display_fallback_respects_entity_source_provenance_artifact(self) -> None:
        entity = self.c.execute(
            "SELECT DISTINCT i.entity_id FROM entity_identifiers i JOIN identifier_types "
            "t ON t.id=i.identifier_type_id WHERE t.type_key='wikidata_artist_qid' AND "
            "i.normalized_value='Q7613062'"
        ).fetchone()[0]
        source, prov, snapshot, artifact = self.c.execute(
            """SELECT p.source_id,p.id,s.id,a.id FROM entity_identifiers i
             JOIN provenance_records p ON p.id=i.provenance_id
             JOIN source_snapshots s ON s.source_id=p.source_id
             AND s.snapshot_ref=p.snapshot_ref
             JOIN source_artifacts a ON a.snapshot_id=s.id AND a.sha256=p.artifact_sha256
             WHERE i.entity_id=? LIMIT 1""",
            (entity,),
        ).fetchone()
        for kind, ref in (
            ("entity", entity),
            ("source", source),
            ("snapshot", snapshot),
            ("artifact", artifact),
            ("provenance", prov),
        ):
            with self.subTest(kind=kind):
                self.c.execute("SAVEPOINT display_gate")
                # No commit: use the public helper on this transaction's exact metadata state.
                self.c.execute(
                    """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,
                    reason,effective_at,event_fingerprint)
                    VALUES(?,?,'display','suppress','Fixture',
                    '2026-01-01T00:00:00Z',?)""",
                    (kind, str(ref), hashlib.sha256(kind.encode()).hexdigest()),
                )
                with self.assertRaises(PublicArtistNavigationStoreError):
                    PublicArtistNavigationStore(self.path)._artist(self.c, entity)
                self.c.execute("ROLLBACK TO display_gate")
                self.c.execute("RELEASE display_gate")

    def test_closed_source_inventory_and_symlinks_fail_before_publication(self) -> None:
        copy = Path(self.temp.name) / "extra-pack"
        shutil.copytree(CULTURAL, copy)
        (copy / "nested").mkdir()
        (copy / "nested/receipt.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            load_pack(copy, *PACKS[0])
        link = Path(self.temp.name) / "source-link"
        link.symlink_to(CULTURAL, target_is_directory=True)
        with (
            patch(
                "opennoise.pipeline.cultural_catalog.digest",
                side_effect=AssertionError("must not read symlink"),
            ),
            self.assertRaisesRegex(ValueError, "symlinks"),
        ):
            load_pack(link, *PACKS[0])
        output = Path(self.temp.name) / "wrong-pin"
        with self.assertRaises(ValueError):
            build(CORE, CORE_SHA, CULTURAL, "0" * 64, INDEPENDENT, PACKS[1][1], output)
        self.assertFalse(output.exists())

    def test_suppressed_subject_or_target_rejected_before_any_pack_mutation(self) -> None:
        for kind in ("artist", "genre"):
            entity = self.c.execute(
                "SELECT e.id FROM catalog_entities e JOIN entity_identifiers i ON i.entity_id=e.id "
                "WHERE e.entity_kind=? AND i.namespace='wikidata' ORDER BY e.id DESC LIMIT 1",
                (kind,),
            ).fetchone()[0]
            self.c.execute("SAVEPOINT veto")
            self.c.execute(
                """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,
                reason,effective_at,event_fingerprint) VALUES('entity',?,'normalize','suppress',
                'Target veto','2026-01-01T00:00:00Z',?)""",
                (str(entity), hashlib.sha256(kind.encode()).hexdigest()),
            )
            before = self.c.total_changes
            # Use both packs, because the last inserted subject/genre may belong to either.
            with self.assertRaisesRegex(ValueError, "entity is suppressed"):
                for directory, spec in ((CULTURAL, PACKS[0]), (INDEPENDENT, PACKS[1])):
                    ingest_pack(self.c, load_pack(directory, *spec))
            self.assertEqual(self.c.total_changes, before)
            self.c.execute("ROLLBACK TO veto")
            self.c.execute("RELEASE veto")

    def test_existing_incompatible_source_is_not_upgraded(self) -> None:
        path = Path(self.temp.name) / "incompatible.sqlite"
        Database(path).initialize()
        with closing(sqlite3.connect(path)) as c:
            policy = c.execute(
                """INSERT INTO rights_policies(policy_key,policy_version,classification,
                local_only,basis)
                VALUES('private',1,'restricted_research',1,'Explicit restriction')"""
            ).lastrowid
            c.execute(
                "INSERT INTO data_sources(source_key,name,license_name,default_policy_id) "
                "VALUES(?,'Conflicting source','Restricted',?)",
                (PACKS[0][0], policy),
            )
            before = c.total_changes
            with self.assertRaisesRegex(ValueError, "incompatible license or policy"):
                ingest_pack(c, self.pack)
            self.assertEqual(c.total_changes, before)

    def test_replay_implementation_includes_normalized_graph_dependency(self) -> None:
        relative = "src/opennoise/pipeline/artist_identity_replay.py"
        self.assertEqual(
            self.report["implementation_sha256"][relative],
            hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
        )

    def test_atomic_staged_failure_does_not_publish(self) -> None:
        output = Path(self.temp.name) / "failed-build"
        with (
            patch("opennoise.pipeline.cultural_catalog._neighbors", side_effect=ValueError("veto")),
            self.assertRaisesRegex(ValueError, "veto"),
        ):
            build(CORE, CORE_SHA, CULTURAL, PACKS[0][1], INDEPENDENT, PACKS[1][1], output)
        self.assertFalse(output.exists())

    def test_reused_provenance_custody_mismatch_rejects_before_projection(self) -> None:
        batch = self.pack.manifest["batches"][0]
        projection = EntityProjection(
            entity_kind="genre",
            source_identity=ExternalIdentity(namespace="wikidata", value="Q123456789"),
            names=(NameClaim(kind="primary", value="Observed test label"),),
        )
        for field in ("observed_at", "ingest_attempt_ref"):
            path = Path(self.temp.name) / (field + ".sqlite")
            Database(path).initialize()
            with closing(sqlite3.connect(path)) as c:
                source, policy = _source(c, self.pack)
                c.execute(
                    """INSERT INTO provenance_records(source_id,policy_id,snapshot_ref,
                    artifact_sha256,record_fingerprint,parser_release_ref,ingest_attempt_ref,
                    observed_at) VALUES(?,?,?,?,?,'verified-cultural-catalog-v1',?,?)""",
                    (
                        source,
                        policy,
                        f"retained:{self.pack.source_key}:{self.pack.manifest['acquired_utc']}",
                        batch["response_sha256"],
                        _hash(
                            {
                                "projection": projection.model_dump(mode="json"),
                                "raw_response_sha256": batch["response_sha256"],
                            }
                        ),
                        "wrong"
                        if field == "ingest_attempt_ref"
                        else "offline-cc0-cultural-catalog",
                        "2020-01-01T00:00:00Z"
                        if field == "observed_at"
                        else self.pack.manifest["acquired_utc"],
                    ),
                )
                before = c.total_changes
                with self.assertRaisesRegex(ValueError, "provenance custody differs"):
                    _persist_projection(c, self.pack, batch, projection)
                self.assertEqual(c.total_changes, before)

    def test_late_provenance_veto_rolls_back_earlier_projection_writes(self) -> None:
        row = min(self.pack.artists, key=lambda item: item["musicbrainz_artist_id"])
        early = self.c.execute(
            "SELECT i.entity_id FROM entity_identifiers i JOIN identifier_types t "
            "ON t.id=i.identifier_type_id WHERE t.type_key='wikidata_artist_qid' "
            "AND i.normalized_value=?",
            (row["wikidata_artist_id"],),
        ).fetchone()[0]
        self.c.execute("DELETE FROM entity_names WHERE entity_id=?", (early,))
        late = self.c.execute(
            "SELECT max(p.id) FROM provenance_records p JOIN data_sources s ON s.id=p.source_id "
            "WHERE s.source_key=?",
            (PACKS[0][0],),
        ).fetchone()[0]
        _suppress(self.c, "provenance", late, "normalize")
        before = tuple(self.c.execute("SELECT count(*) FROM entity_names").fetchone())
        with self.assertRaisesRegex(ValueError, "provenance is suppressed"):
            ingest_pack(self.c, self.pack)
        self.assertEqual(
            tuple(self.c.execute("SELECT count(*) FROM entity_names").fetchone()), before
        )
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM entity_names WHERE entity_id=?", (early,)
            ).fetchone()[0],
            0,
        )
        self.assertTrue(self.c.in_transaction)
