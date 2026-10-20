"""Raw ownership vetoes for explicitly synthetic qualified catalog-key contracts."""

# ruff: noqa: E501 -- Literal fixture fields expose exact family and custody bindings.

import sqlite3
import unittest
from contextlib import closing

from opennoise.catalog.entities import EntityProjector
from opennoise.db import DEFAULT_MIGRATION_PATHS
from opennoise.ml.repository import (
    PublicInputLoadError,
    PublicInputLoadSettings,
    PublicModelRepository,
)
from opennoise.models.catalog import (
    EntityProjection,
    ExternalIdentity,
    IdentifierClaim,
    NameClaim,
    RelationClaim,
    ValueClaim,
)
from tests.test_embed_metadata_labels import catalog, load
from tests.test_public_model_repository import _listenbrainz

_ROLES = (
    (10, "artist", "musicbrainz", 101),
    (20, "genre", "wikidata", 1),
    (30, "release_group", "musicbrainz", 102),
    (40, "recording", "musicbrainz", 103),
)


class EmbedIdentityOwnershipTests(unittest.TestCase):
    def test_duplicate_hidden_or_wrong_kind_owners_veto_both_apis(self) -> None:
        for entity, kind, namespace, type_id in _ROLES:
            for mode in ("duplicate", "denied", "suppressed", "wrong-kind"):
                with (
                    self.subTest(kind=kind, mode=mode),
                    closing(catalog()) as c,
                    closing(_listenbrainz()) as lb,
                ):
                    selected = c.execute(
                        "SELECT normalized_value FROM entity_identifiers WHERE entity_id=? AND namespace=? ORDER BY id LIMIT 1",
                        (entity, namespace),
                    ).fetchone()[0]
                    c.execute(
                        "INSERT INTO catalog_entities VALUES(300,?)",
                        ("artist" if kind != "artist" else "recording",)
                        if mode == "wrong-kind"
                        else (kind,),
                    )
                    c.execute(
                        "INSERT INTO entity_identifiers VALUES(200,300,?,?,?,100)",
                        (namespace, selected, type_id),
                    )
                    if mode == "denied":
                        c.execute(
                            "INSERT INTO active_rights_policy_permissions VALUES(99,'embed','deny')"
                        )
                        c.execute("UPDATE provenance_records SET policy_id=99 WHERE id=100")
                    elif mode == "suppressed":
                        c.execute("INSERT INTO active_suppressions VALUES('entity','300','embed')")
                    c.execute("PRAGMA query_only=ON")
                    for full in (False, True):
                        with self.subTest(full=full):
                            if entity in (10, 20):
                                with self.assertRaises(PublicInputLoadError):
                                    PublicModelRepository(c, lb).load(
                                        PublicInputLoadSettings()
                                    ) if full else load(c)
                            else:
                                value = (
                                    PublicModelRepository(c, lb).load(PublicInputLoadSettings())
                                    if full
                                    else load(c)
                                )
                                self.assertNotIn(
                                    kind, {x.entity_kind for x in value.metadata_candidates}
                                )

    def test_conflicting_hidden_alias_or_wrong_namespace_in_selected_family_vetoes(self) -> None:
        for entity, kind, namespace, type_id in _ROLES:
            for mode in ("different-value", "wrong-namespace", "foreign-type"):
                with self.subTest(kind=kind, mode=mode), closing(catalog()) as c:
                    selected = c.execute(
                        "SELECT normalized_value FROM entity_identifiers WHERE entity_id=? AND namespace=? ORDER BY id LIMIT 1",
                        (entity, namespace),
                    ).fetchone()[0]
                    value = (
                        (
                            "Q999999"
                            if namespace == "wikidata"
                            else "aaaaaaaa-1111-4111-8111-111111111111"
                        )
                        if mode == "different-value"
                        else selected
                    )
                    other_namespace = "unexpected" if mode == "wrong-namespace" else namespace
                    other_type = type_id
                    if mode == "foreign-type":
                        c.execute(
                            "INSERT INTO identifier_types VALUES(200,?)",
                            (
                                "wikidata_work_qid"
                                if namespace == "wikidata"
                                else "musicbrainz_work_id",
                            ),
                        )
                        other_type = 200
                    c.execute(
                        "INSERT INTO entity_identifiers VALUES(200,?,?,?,?,100)",
                        (entity, other_namespace, value, other_type),
                    )
                    c.execute("INSERT INTO active_suppressions VALUES('source','100','embed')")
                    if entity in (10, 20):
                        with self.assertRaises(PublicInputLoadError):
                            load(c)
                    else:
                        self.assertNotIn(kind, {x.entity_kind for x in load(c).metadata_candidates})

    def test_repeated_same_key_and_complementary_other_provider_do_not_veto(self) -> None:
        for entity, kind, namespace, type_id in _ROLES:
            with self.subTest(kind=kind), closing(catalog()) as c:
                before = load(c)
                selected = c.execute(
                    "SELECT normalized_value FROM entity_identifiers WHERE entity_id=? AND namespace=? ORDER BY id LIMIT 1",
                    (entity, namespace),
                ).fetchone()[0]
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(200,?,?,?,?,100)",
                    (entity, namespace, selected, type_id),
                )
                # Other-provider contradictions are deliberately outside this selected-family gate.
                c.execute(
                    "INSERT INTO identifier_types VALUES(200,?)",
                    ("musicbrainz_work_id" if namespace == "wikidata" else "wikidata_work_qid",),
                )
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(201,?,?,?,?,100)",
                    (
                        entity,
                        "musicbrainz" if namespace == "wikidata" else "wikidata",
                        "bbbbbbbb-1111-4111-8111-111111111111"
                        if namespace == "wikidata"
                        else "Q999999",
                        200,
                    ),
                )
                self.assertEqual(load(c), before)

    def test_wikidata_generic_and_foreign_typed_owner_are_global(self) -> None:
        for type_key, owner_kind in (("wikidata_qid", "genre"), ("wikidata_work_qid", "work")):
            with self.subTest(type_key=type_key), closing(catalog()) as c:
                c.execute("INSERT INTO catalog_entities VALUES(300,?)", (owner_kind,))
                c.execute("INSERT INTO identifier_types VALUES(200,?)", (type_key,))
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(200,300,'wikidata','Q100',200,100)"
                )
                with self.assertRaises(PublicInputLoadError):
                    load(c)

    def test_artist_legacy_source_id_is_scoped_and_other_mb_kinds_do_not_collide(self) -> None:
        with closing(catalog()) as c:
            before = load(c)
            c.execute("INSERT INTO identifier_types VALUES(200,'source_id')")
            c.execute("INSERT INTO catalog_entities VALUES(300,'artist')")
            # Artist legacy ID with the same UUID as a recording is a different public key.
            c.execute(
                "INSERT INTO entity_identifiers VALUES(200,300,'musicbrainz','55555555-5555-4555-8555-555555555555',200,100)"
            )
            self.assertEqual(load(c), before)
            # A matching artist legacy alias on another entity is a true ownership conflict.
            c.execute(
                "INSERT INTO entity_identifiers VALUES(201,300,'musicbrainz','11111111-1111-4111-8111-111111111111',200,100)"
            )
            with self.assertRaises(PublicInputLoadError):
                load(c)
        with closing(catalog()) as c:
            before = load(c)
            c.execute("INSERT INTO catalog_entities VALUES(300,'recording')")
            c.execute(
                "INSERT INTO entity_identifiers VALUES(200,300,'musicbrainz','11111111-1111-4111-8111-111111111111',103,100)"
            )
            self.assertEqual(load(c), before)

    def test_nonartist_legacy_source_id_is_not_an_artist_public_key(self) -> None:
        with closing(catalog()) as c:
            before = load(c)
            c.execute("INSERT INTO identifier_types VALUES(200,'source_id')")
            c.execute("INSERT INTO catalog_entities VALUES(300,'recording')")
            c.execute(
                "INSERT INTO entity_identifiers VALUES(200,300,'musicbrainz','11111111-1111-4111-8111-111111111111',200,100)"
            )
            self.assertEqual(load(c), before)

    def test_optional_ambiguous_rows_are_removed_before_bounds(self) -> None:
        with closing(catalog()) as c:
            for n in range(300, 320):
                c.execute("INSERT INTO catalog_entities VALUES(?,'recording')", (n,))
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(?,?,'musicbrainz','55555555-5555-4555-8555-555555555555',103,100)",
                    (n, n),
                )
                c.execute(
                    "INSERT INTO entity_names VALUES(?,?,?,1,1)", (n, n, f"Synthetic recording {n}")
                )
                c.execute(
                    "INSERT INTO normalizable_recording_genre_memberships VALUES(?,?,20,'wikidata_p136','wikidata',7,1,1)",
                    (n, n),
                )
            value = load(c, max_metadata_candidates=2)
            self.assertEqual(len(value.metadata_candidates), 2)
            self.assertNotIn("recording", {x.entity_kind for x in value.metadata_candidates})

    def test_owner_lookup_uses_existing_type_namespace_value_index(self) -> None:
        with closing(catalog()) as c:
            c.execute(
                "CREATE INDEX entity_identifiers_lookup_idx ON entity_identifiers(identifier_type_id,namespace,normalized_value)"
            )
            statements = []
            c.set_trace_callback(statements.append)
            load(c)
            query = next(q for q in statements if "FROM json_each(" in q)
            c.set_trace_callback(None)
            plan = [str(row[3]) for row in c.execute("EXPLAIN QUERY PLAN " + query)]
            self.assertFalse(any("SCAN owner" in item for item in plan), plan)
            self.assertTrue(
                any(
                    "SEARCH owner USING INDEX entity_identifiers_lookup_idx" in item
                    and "identifier_type_id=?" in item
                    for item in plan
                ),
                plan,
            )

    def test_full_schema_denied_duplicate_owner_cannot_be_hidden_by_suppression(self) -> None:
        with closing(sqlite3.connect(":memory:")) as c:
            for migration in DEFAULT_MIGRATION_PATHS:
                c.executescript(migration.read_text())
            c.executescript("""
                INSERT INTO rights_policies(id,policy_key,policy_version,classification,basis)
                VALUES(1,'synthetic-owner-allowed',1,'open_license','Synthetic test only'),
                (2,'synthetic-owner-denied',1,'open_license','Synthetic test only');
                INSERT INTO rights_policy_permissions VALUES
                (1,'normalize','allow','Fixture'),(1,'embed','allow','Fixture'),
                (1,'local_search','allow','Fixture'),(1,'display','allow','Fixture'),
                (2,'normalize','allow','Fixture'),(2,'embed','deny','Fixture');
                INSERT INTO rights_policy_seals VALUES(1,'2026-01-01T00:00:00Z'),(2,'2026-01-01T00:00:00Z');
                INSERT INTO data_sources(id,source_key,name,license_name,default_policy_id)
                VALUES(1,'wikidata_synthetic_facts','Synthetic facts','Fixture permission',1),
                (2,'wikidata_synthetic_denied','Synthetic duplicate owner','Fixture permission',2);
            """)
            for n in (1, 2):
                sha = str(n) * 64
                c.execute(
                    "INSERT INTO provenance_records(id,source_id,policy_id,snapshot_ref,artifact_sha256,record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at) VALUES(?,?,?,?,?,?,'synthetic','synthetic','2026-01-01T00:00:00Z')",
                    (n, n, n, f"synthetic-{n}", sha, sha),
                )
            projector = EntityProjector()
            genre = EntityProjection(
                entity_kind="genre",
                source_identity=ExternalIdentity(namespace="wikidata", value="Q80001"),
                names=(NameClaim(kind="primary", value="Synthetic genre"),),
                claims=(
                    ValueClaim(
                        property_key="music_genre_qualification",
                        value_kind="string",
                        value="Q188451|1|P31|P279:nondeprecated:Q25379",
                        statement_id=ExternalIdentity(
                            namespace="wikidata_statement", value="Q80001-synthetic"
                        ),
                    ),
                ),
            )
            projector.persist(c, genre, provenance_id=1, policy_id=1)
            artist = EntityProjection(
                entity_kind="artist",
                source_identity=ExternalIdentity(namespace="wikidata", value="Q90001"),
                names=(NameClaim(kind="primary", value="Synthetic artist"),),
                identifiers=(
                    IdentifierClaim(
                        type_key="musicbrainz_artist_id",
                        namespace="musicbrainz",
                        value="11111111-1111-4111-8111-111111111111",
                    ),
                ),
                claims=(
                    RelationClaim(
                        property_key="genre",
                        target=ExternalIdentity(namespace="wikidata", value="Q80001"),
                    ),
                ),
            )
            projector.persist(c, artist, provenance_id=1, policy_id=1)
            before = load(c)
            c.execute("SAVEPOINT ambiguous_test_fixture")
            c.execute("INSERT INTO catalog_entities(id,entity_kind) VALUES(300,'artist')")
            c.execute("INSERT INTO artists(id) VALUES(300)")
            c.execute(
                "INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id) SELECT 300,id,'musicbrainz','11111111-1111-4111-8111-111111111111','11111111-1111-4111-8111-111111111111',2 FROM identifier_types WHERE type_key='musicbrainz_artist_id'"
            )
            with self.assertRaises(PublicInputLoadError):
                load(c)
            c.execute(
                "INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,effective_at,event_fingerprint) VALUES('entity','300','all','suppress','Synthetic only','2026-01-01T00:00:00Z',?)",
                ("f" * 64,),
            )
            with self.assertRaises(PublicInputLoadError):
                load(c)
            # Roll back only counterfactual test setup: no reconciliation/repair API exists.
            c.execute("ROLLBACK TO ambiguous_test_fixture")
            c.execute("RELEASE ambiguous_test_fixture")
            c.execute("PRAGMA query_only=ON")
            self.assertEqual(load(c), before)
