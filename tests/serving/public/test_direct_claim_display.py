"""Ordinary CC0 direct evidence honors use-specific source/claim suppression."""

# ruff: noqa: E501 -- Dense SQL fixtures preserve their exact table/field bindings.

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, override

from opennoise.catalog.entities import EntityProjector
from opennoise.db import DEFAULT_MIGRATION_PATHS, Database
from opennoise.evidence.membership import (
    ArtistGenreRepository,
    MaterializationManifest,
    MembershipRunRequest,
)
from opennoise.models.catalog import EntityProjection, ExternalIdentity, NameClaim, RelationClaim
from opennoise.pipeline.cultural_catalog import CORE_SHA, PACKS, build
from opennoise.serving.public.artist_navigation_store import PublicArtistNavigationStore
from tests._test_client import run_async

ROOT = Path(__file__).resolve().parents[3]


def visible(c: sqlite3.Connection, use: str = "display") -> set[int]:
    """Use the ordinary shared view, not a test-side replacement query."""
    table = "displayable" if use == "display" else "normalizable"
    return {r[0] for r in c.execute(f"SELECT id FROM {table}_artist_genre_evidence")}  # noqa: S608 -- Two fixed view names.


def event(c: sqlite3.Connection, kind: str, ref: str, use: str, action: str) -> None:
    """Append real policy events and use their ordinary latest-event resolution."""
    sequence = c.execute("SELECT count(*) FROM suppression_events").fetchone()[0]
    c.execute(
        """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,
           effective_at,event_fingerprint) VALUES(?,?,?,?,'Direct display regression',
           '2026-01-01T00:00:00Z',?)""",
        (
            kind,
            ref,
            use,
            action,
            hashlib.sha256(f"{sequence}:{kind}:{ref}:{use}:{action}".encode()).hexdigest(),
        ),
    )
    c.commit()


class DirectClaimDisplayTests(unittest.TestCase):
    """Replay both complete retained CC0 cohorts once, then copy exact catalogs."""

    temp: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / "catalog"
        core = (
            ROOT
            / "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256"
            / f"{CORE_SHA}.json"
        )
        build(
            core,
            CORE_SHA,
            ROOT / "data/examples/cultural-context",
            PACKS[0][1],
            ROOT / "data/examples/independent-cultural-context",
            PACKS[1][1],
            cls.output,
        )

    @override
    def setUp(self) -> None:
        self.path = Path(self.temp.name) / f"{self._testMethodName}.sqlite"
        with (
            closing(sqlite3.connect(self.output / "musicbrainz-first.sqlite")) as src,
            closing(sqlite3.connect(self.path)) as dst,
        ):
            src.backup(dst)
        self.c = sqlite3.connect(self.path)
        self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        self.store = PublicArtistNavigationStore(self.path)
        self.rows = [
            dict(r)
            for r in self.c.execute(
                """SELECT e.*,p.source_id,s.id AS snapshot_id,a.id AS artifact_id
               FROM artist_genre_evidence e JOIN provenance_records p ON p.id=e.provenance_id
               JOIN source_snapshots s ON s.source_id=p.source_id AND s.snapshot_ref=p.snapshot_ref
                 AND s.policy_id=p.policy_id
               JOIN source_artifacts a ON a.snapshot_id=s.id AND a.sha256=p.artifact_sha256
                 AND a.policy_id=p.policy_id ORDER BY e.id"""
            )
        ]
        self.baseline = {r["id"] for r in self.rows}

    def test_full_source_baseline_and_both_ingestion_orders(self) -> None:
        self.assertEqual(len(self.rows), 278)
        self.assertEqual(visible(self.c), self.baseline)
        for name in ("musicbrainz-first", "wikidata-first"):
            with closing(sqlite3.connect(self.output / f"{name}.sqlite")) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 14)
                self.assertEqual(c.execute("SELECT count(*) FROM artists").fetchone()[0], 433)
                self.assertEqual(
                    c.execute(
                        "SELECT count(*) FROM entity_claims WHERE claim_key='genre'"
                    ).fetchone()[0],
                    287,
                )
                self.assertEqual(
                    c.execute("SELECT count(*) FROM displayable_artist_genre_evidence").fetchone()[
                        0
                    ],
                    278,
                )

    def test_every_source_boundary_suppress_release_is_use_specific(self) -> None:
        row = self.rows[0]
        targets = [
            (kind, str(row[key]), key)
            for kind, key in (
                ("source", "source_id"),
                ("snapshot", "snapshot_id"),
                ("artifact", "artifact_id"),
                ("provenance", "provenance_id"),
                ("entity", "artist_id"),
                ("entity", "genre_id"),
            )
        ]
        for kind, ref, key in targets:
            affected = {
                r["id"]
                for r in self.rows
                if str(r[key]) == ref
                or (kind == "entity" and ref in (str(r["artist_id"]), str(r["genre_id"])))
            }
            for use in ("display", "all", "normalize", "train", "export", "embed", "local_search"):
                with self.subTest(kind=kind, ref=ref, use=use):
                    event(self.c, kind, ref, use, "suppress")
                    self.assertEqual(
                        visible(self.c),
                        self.baseline - affected if use in ("display", "all") else self.baseline,
                    )
                    self.assertEqual(
                        visible(self.c, "normalize"),
                        self.baseline - affected if use in ("normalize", "all") else self.baseline,
                    )
                    event(self.c, kind, ref, use, "release")
                    self.assertEqual(visible(self.c), self.baseline)
        self.assertEqual(
            self.c.execute("SELECT count(*) FROM artist_genre_evidence").fetchone()[0], 278
        )

    def test_exact_evidence_refs_filter_before_pagination_and_shared_genre_join(self) -> None:
        row = max(self.rows, key=lambda r: sum(x["artist_id"] == r["artist_id"] for x in self.rows))
        artist = row["artist_id"]
        own = sorted({r["genre_id"] for r in self.rows if r["artist_id"] == artist})
        first = next(r for r in self.rows if r["artist_id"] == artist and r["genre_id"] == own[0])
        ref = f"artist_genre_evidence:{first['id']}"
        for use in ("display", "all"):
            event(self.c, "claim", ref, use, "suppress")
            page = run_async(self.store.artist_genres(artist, offset=0, limit=1))
            self.assertEqual([g.genre.entity_id for g in page.genres], own[1:2])
            members = run_async(self.store.genre_artists(first["genre_id"], offset=0, limit=50))
            self.assertNotIn(artist, [m.artist.entity_id for m in members.members])
            remaining = self.baseline - {first["id"]}
            own_now = {
                r["genre_id"]
                for r in self.rows
                if r["artist_id"] == artist and r["id"] in remaining
            }
            expected = {
                r["artist_id"]
                for r in self.rows
                if r["id"] in remaining and r["genre_id"] in own_now
            } - {artist}
            related = run_async(self.store.related_artists(artist, offset=0, limit=50))
            self.assertEqual({r.artist.entity_id for r in related.related}, expected)
            for peer in related.related:
                genres = {
                    r["genre_id"]
                    for r in self.rows
                    if r["artist_id"] == peer.artist.entity_id and r["id"] in remaining
                }
                self.assertEqual({g.entity_id for g in peer.shared_genres}, genres & own_now)
            event(self.c, "claim", ref, use, "release")
            self.assertEqual(
                len(run_async(self.store.artist_genres(artist, offset=0, limit=50)).genres),
                len(own),
            )
        for use in ("normalize", "train", "export"):
            event(self.c, "claim", ref, use, "suppress")
            self.assertEqual(visible(self.c), self.baseline)
            event(self.c, "claim", ref, use, "release")

    def test_ordinary_materializer_consumes_only_normalization_authorized_claims(self) -> None:
        source_keys = tuple(sorted({r["source_key"] for r in self.rows}))
        row = self.rows[0]
        ref = f"artist_genre_evidence:{row['id']}"
        repo = ArtistGenreRepository(self.c)
        for index, action in enumerate(("baseline", "suppress", "release"), start=1):
            if action != "baseline":
                event(self.c, "claim", ref, "normalize", action)
            artifact = repo.materialize(
                MembershipRunRequest(
                    run_ref=f"direct-view-regression:{index}",
                    revision=10000 + index,
                    manifest=MaterializationManifest(
                        method="direct_evidence",
                        included_evidence_kinds=("direct_source_claim",),
                        included_source_keys=source_keys,
                    ),
                    policy_id=row["policy_id"],
                    generated_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            actual = {e for item in artifact.items for e in item.evidence_ids}
            self.assertEqual(
                actual, self.baseline - {row["id"]} if action == "suppress" else self.baseline
            )
            self.assertEqual(visible(self.c), self.baseline)

    def test_default_unresolved_relation_matches_only_exact_sibling_target(self) -> None:
        row = self.rows[0]
        targets = [
            r[0]
            for r in self.c.execute(
                "SELECT DISTINCT normalized_value FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id WHERE t.type_key='wikidata_genre_qid' ORDER BY 1 LIMIT 2"
            )
        ]
        projection = EntityProjection(
            entity_kind="artist",
            source_identity=ExternalIdentity(namespace="wikidata", value="Q999999999"),
            names=(NameClaim(kind="primary", value="Synthetic suppression subject"),),
            claims=tuple(
                RelationClaim(
                    property_key="genre", target=ExternalIdentity(namespace="wikidata", value=q)
                )
                for q in targets
            ),
        )
        artist = (
            EntityProjector()
            .persist(
                self.c, projection, provenance_id=row["provenance_id"], policy_id=row["policy_id"]
            )
            .target_id
        )
        claims = self.c.execute(
            "SELECT id,normalized_value_json FROM entity_claims WHERE entity_id=? ORDER BY id",
            (artist,),
        ).fetchall()
        self.assertEqual([json.loads(c[1])["target_kind"] for c in claims], ["unresolved"] * 2)
        self.c.commit()
        self.assertEqual(
            len(run_async(self.store.artist_genres(artist, offset=0, limit=50)).genres), 2
        )
        event(self.c, "claim", f"entity_claims:{claims[0][0]}", "display", "suppress")
        actual = run_async(self.store.artist_genres(artist, offset=0, limit=50))
        self.assertEqual(len(actual.genres), 1)
        qid = self.c.execute(
            "SELECT normalized_value FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id WHERE i.entity_id=? AND t.type_key='wikidata_genre_qid'",
            (actual.genres[0].genre.entity_id,),
        ).fetchone()[0]
        self.assertEqual(qid, targets[1])
        event(self.c, "claim", f"entity_claims:{claims[0][0]}", "display", "release")
        self.assertEqual(
            len(run_async(self.store.artist_genres(artist, offset=0, limit=50)).genres), 2
        )

    def test_repeated_capture_is_not_a_canonical_suppression_fallback(self) -> None:
        repeated = self.c.execute("""SELECT entity_id,json_extract(normalized_value_json,'$.target.value') AS q
            FROM entity_claims WHERE claim_key='genre' AND claim_type='wikidata_relation'
            GROUP BY entity_id,q HAVING count(*)>1 LIMIT 1""").fetchone()
        artist, qid = repeated
        claims = self.c.execute(
            """SELECT id,provenance_id FROM entity_claims WHERE entity_id=?
            AND claim_key='genre' AND json_extract(normalized_value_json,'$.target.value')=?""",
            (artist, qid),
        ).fetchall()
        evidence = self.c.execute(
            """SELECT e.id,e.provenance_id FROM artist_genre_evidence e
            JOIN entity_identifiers i ON i.entity_id=e.genre_id JOIN identifier_types t
            ON t.id=i.identifier_type_id WHERE e.artist_id=? AND t.type_key='wikidata_genre_qid'
            AND i.normalized_value=? LIMIT 1""",
            (artist, qid),
        ).fetchone()
        canonical = next(c for c in claims if c["provenance_id"] == evidence["provenance_id"])
        other = next(c for c in claims if c["provenance_id"] != evidence["provenance_id"])
        for use in ("display", "normalize", "all"):
            event(self.c, "claim", f"entity_claims:{other['id']}", use, "suppress")
            self.assertEqual(visible(self.c), self.baseline)
            self.assertEqual(visible(self.c, "normalize"), self.baseline)
            event(self.c, "claim", f"entity_claims:{canonical['id']}", use, "suppress")
            for view_use in ("display", "normalize"):
                expected = (
                    self.baseline - {evidence["id"]} if use in (view_use, "all") else self.baseline
                )
                self.assertEqual(visible(self.c, view_use), expected)
            event(self.c, "claim", f"entity_claims:{canonical['id']}", use, "release")
            event(self.c, "claim", f"entity_claims:{other['id']}", use, "release")
            self.assertEqual(visible(self.c), self.baseline)

    def test_unbound_genre_target_does_not_guess_from_cached_name(self) -> None:
        row = self.rows[0]
        claim = self.c.execute(
            "SELECT id,normalized_value_json FROM entity_claims WHERE entity_id=? AND provenance_id=? AND claim_key='genre' LIMIT 1",
            (row["artist_id"], row["provenance_id"]),
        ).fetchone()
        qid = json.loads(claim["normalized_value_json"])["target"]["value"]
        genre = self.c.execute(
            "INSERT INTO catalog_entities(entity_kind) VALUES('genre')"
        ).lastrowid
        self.c.execute(
            "INSERT INTO genres(id,slug,name) VALUES(?, 'synthetic-unbound', ?)", (genre, qid)
        )
        self.c.execute(
            """INSERT INTO artist_genre_evidence(artist_id,genre_id,evidence_kind,evidence_value,
            source_key,source_record_id,method_key,method_version,parameter_manifest_json,observed_at,
            provenance_id,policy_id,record_fingerprint) SELECT artist_id,?,evidence_kind,evidence_value,
            source_key,'synthetic-unbound',method_key,method_version,parameter_manifest_json,observed_at,
            provenance_id,policy_id,? FROM artist_genre_evidence WHERE id=?""",
            (genre, hashlib.sha256(b"synthetic-unbound").hexdigest(), row["id"]),
        )
        new = self.c.execute("SELECT last_insert_rowid()").fetchone()[0]
        event(self.c, "claim", f"entity_claims:{claim['id']}", "all", "suppress")
        self.assertIn(new, visible(self.c))
        self.assertIn(new, visible(self.c, "normalize"))

    def test_generic_claim_matching_is_typed_not_just_a_numeric_reference(self) -> None:
        row = self.rows[0]
        original = self.c.execute(
            "SELECT normalized_value_json FROM entity_claims WHERE entity_id=? AND provenance_id=? AND claim_key='genre' LIMIT 1",
            (row["artist_id"], row["provenance_id"]),
        ).fetchone()[0]
        for index, (kind, key, namespace, target) in enumerate(
            (
                ("value", "genre", "wikidata", None),
                ("wikidata_relation", "subclass_of", "wikidata", None),
                ("wikidata_relation", "genre", "other", None),
                ("wikidata_relation", "genre", "wikidata", "Q999999998"),
            )
        ):
            value = json.loads(original)
            value["target"]["namespace"] = namespace
            if target is not None:
                value["target"]["value"] = target
            self.c.execute(
                """INSERT INTO entity_claims(entity_id,claim_type,claim_key,
                normalized_value_json,asserted_at,provenance_id,policy_id,claim_hash)
                VALUES(?,?,?,?,'synthetic regression',?,?,?)""",
                (
                    row["artist_id"],
                    kind,
                    key,
                    json.dumps(value),
                    row["provenance_id"],
                    row["policy_id"],
                    hashlib.sha256(f"typed:{index}".encode()).hexdigest(),
                ),
            )
            ref = f"entity_claims:{self.c.execute('SELECT last_insert_rowid()').fetchone()[0]}"
            event(self.c, "claim", ref, "all", "suppress")
            self.assertEqual(visible(self.c), self.baseline)
            self.assertEqual(visible(self.c, "normalize"), self.baseline)

    def test_unknown_or_bare_claim_refs_are_not_guessed_or_cast(self) -> None:
        for ref in (
            str(self.rows[0]["id"]),
            "unknown:1",
            "artist_genre_evidence:01",
            "entity_claims:01",
        ):
            event(self.c, "claim", ref, "display", "suppress")
            self.assertEqual(visible(self.c), self.baseline)

    def test_missing_inventory_retains_existing_display_behavior(self) -> None:
        # The view change honors registered vetoes; it does not invent a new inventory requirement.
        row = self.rows[0]
        # A projection under a real policy with a new unregistered snapshot is a legacy observation.
        self.c.execute(
            "INSERT INTO provenance_records(source_id,policy_id,snapshot_ref,artifact_sha256,record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at) SELECT source_id,policy_id,'legacy-no-inventory',artifact_sha256,?,parser_release_ref,ingest_attempt_ref,observed_at FROM provenance_records WHERE id=?",
            (hashlib.sha256(b"legacy-no-inventory").hexdigest(), row["provenance_id"]),
        )
        prov = self.c.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.c.execute(
            "INSERT INTO artist_genre_evidence(artist_id,genre_id,evidence_kind,evidence_value,source_key,source_record_id,method_key,method_version,parameter_manifest_json,observed_at,provenance_id,policy_id,record_fingerprint) SELECT artist_id,genre_id,evidence_kind,evidence_value,source_key,'legacy-no-inventory',method_key,method_version,parameter_manifest_json,observed_at,?,policy_id,? FROM artist_genre_evidence WHERE id=?",
            (prov, hashlib.sha256(b"legacy-no-inventory-evidence").hexdigest(), row["id"]),
        )
        new = self.c.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.assertIn(new, visible(self.c))

    def test_upgrade_twelve_preserves_facts_and_closes_existing_claim_veto(self) -> None:
        # Restore the actual old view, not a hand-authored approximation, then apply the new migration.
        old = DEFAULT_MIGRATION_PATHS[3].read_text()
        statements = []
        for name, following in (
            ("normalizable_artist_genre_evidence", "normalizable_album_genre_memberships"),
            ("displayable_artist_genre_evidence", "displayable_artist_genre_memberships"),
        ):
            statements.append(
                f"DROP VIEW {name};\n"
                + old[
                    old.index(f"CREATE VIEW {name} AS") : old.index(f"CREATE VIEW {following} AS")
                ]
            )
        old_model = (ROOT / "migrations/0007_public_model_serving.sql").read_text()
        statements.append(
            "DROP VIEW servable_public_model_runs;\n"
            + old_model[
                old_model.index("CREATE VIEW servable_public_model_runs") : old_model.index(
                    "CREATE VIEW displayable_public_genre_representatives"
                )
            ]
        )
        self.c.executescript("\n".join(statements) + "\nPRAGMA user_version=12;")
        ref = f"artist_genre_evidence:{self.rows[0]['id']}"
        event(self.c, "claim", ref, "all", "suppress")
        self.assertEqual(visible(self.c), self.baseline)
        Database(self.path).initialize()
        self.assertEqual(visible(self.c), self.baseline - {self.rows[0]["id"]})
        self.assertEqual(visible(self.c, "normalize"), self.baseline - {self.rows[0]["id"]})
        self.assertEqual(
            self.c.execute("SELECT count(*) FROM artist_genre_evidence").fetchone()[0], 278
        )
        event(self.c, "claim", ref, "all", "release")
        self.assertEqual(visible(self.c), self.baseline)
