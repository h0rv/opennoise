"""Own-label eligibility in an explicitly synthetic qualified source contract."""

# ruff: noqa: E501 -- Literal SQL fixtures keep custody bindings visible.
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
)
from opennoise.models.modeling import PublicModelInput
from tests.test_public_model_repository import _catalog


def catalog() -> sqlite3.Connection:
    """Create separate synthetic fact and label sources."""
    c = _catalog()
    c.executescript("""
        INSERT INTO data_sources VALUES(99,'wikidata_labels_a'),(100,'wikidata_labels_b');
        INSERT INTO provenance_records VALUES(99,99,1,'labels-a','dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'),(100,100,1,'labels-b','eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee');
        INSERT INTO source_snapshots VALUES(99,99,'labels-a',1),(100,100,'labels-b',1);
        INSERT INTO source_artifacts VALUES(99,99,'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',1),(100,100,'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',1);
        UPDATE entity_names SET provenance_id=99;
        UPDATE genres SET name='A genre' WHERE id=20;
        UPDATE entity_names SET name='A artist' WHERE entity_id=10;
        UPDATE entity_names SET name='A genre' WHERE entity_id=20;
        UPDATE entity_names SET name='A album' WHERE entity_id=30;
        UPDATE entity_names SET name='A recording' WHERE entity_id=40;
        INSERT INTO entity_names VALUES(101,10,'B artist',1,100),(102,20,'B genre',1,100),
            (103,30,'B album',1,100),(104,40,'B recording',1,100);
    """)
    return c


def load(c: sqlite3.Connection, *, max_metadata_candidates: int = 100_000) -> PublicModelInput:
    """Exercise the ordinary bounded catalog loader."""
    return PublicModelRepository(c).load_catalog_only(
        PublicInputLoadSettings(max_metadata_candidates=max_metadata_candidates)
    )


class EmbedMetadataLabelsTests(unittest.TestCase):
    def test_own_chain_veto_selects_independent_names_without_changing_facts(self) -> None:
        for kind in ("source", "provenance", "snapshot", "artifact"):
            for use in ("embed", "all"):
                with self.subTest(kind=kind, use=use), closing(catalog()) as c:
                    before = load(c)
                    c.execute("INSERT INTO active_suppressions VALUES(?,?,?)", (kind, "99", use))
                    after = load(c)
                    self.assertEqual(after.genres[0].name, "B genre")
                    self.assertEqual(
                        {x.name for x in after.metadata_candidates},
                        {"B artist", "B album", "B recording"},
                    )
                    self.assertEqual(after.direct_memberships, before.direct_memberships)
                    self.assertEqual(after.hierarchy, before.hierarchy)

    def test_permission_is_own_embed_permission_not_export_or_display(self) -> None:
        with closing(catalog()) as c:
            c.execute("INSERT INTO active_rights_policy_permissions VALUES(99,'embed','deny')")
            c.execute("UPDATE provenance_records SET policy_id=99 WHERE id=99")
            self.assertEqual(load(c).genres[0].name, "B genre")
        for use in ("display", "normalize", "train", "export"):
            with self.subTest(use=use), closing(catalog()) as c:
                before = load(c)
                c.execute("INSERT INTO active_suppressions VALUES(?,?,?)", ("source", "99", use))
                self.assertEqual(load(c), before)

    def test_unobserved_cache_cannot_override_eligible_name(self) -> None:
        with closing(catalog()) as c:
            c.execute("UPDATE genres SET name='Private cache' WHERE id=20")
            self.assertEqual(load(c).genres[0].name, "A genre")

    def test_no_names_omits_optional_representatives_before_bound(self) -> None:
        with closing(catalog()) as c:
            c.execute("DELETE FROM entity_names")
            value = load(c, max_metadata_candidates=1)
            self.assertEqual(value.metadata_candidates, ())
            self.assertEqual(value.genres[0].name, "wikidata:genre:Q100")
            self.assertEqual(value.genres[0].genre_id, "wikidata:genre:Q100")

    def test_required_fallback_needs_own_eligible_exact_typed_observation(self) -> None:
        for change in (
            "UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=20",
            "UPDATE entity_identifiers SET identifier_type_id=NULL WHERE entity_id=20",
            "UPDATE entity_identifiers SET normalized_value='Q0100' WHERE entity_id=20 AND namespace='wikidata'",
            "UPDATE identifier_types SET type_key='wikidata_artist_qid'",
        ):
            with self.subTest(change=change), closing(catalog()) as c:
                c.execute("DELETE FROM entity_names")
                c.execute("INSERT INTO active_suppressions VALUES('source','99','embed')")
                c.execute(change)
                with self.assertRaises(PublicInputLoadError):
                    load(c)

    def test_eligible_other_identity_cannot_relabel_selected_stable_key(self) -> None:
        with closing(catalog()) as c:
            c.execute("DELETE FROM entity_names")
            c.execute("UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=20")
            c.execute("INSERT INTO entity_identifiers VALUES(100,20,'wikidata','Q101',1,1)")
            c.execute("INSERT INTO active_suppressions VALUES('source','99','embed')")
            with self.assertRaises(PublicInputLoadError):
                load(c)

    def test_read_only_release_restores_exact_payload(self) -> None:
        with closing(catalog()) as c:
            before = load(c)
            c.execute("INSERT INTO active_suppressions VALUES('artifact','99','embed')")
            self.assertNotEqual(load(c), before)
            c.execute("DELETE FROM active_suppressions WHERE target_ref='99'")
            c.execute("PRAGMA query_only=ON")
            self.assertEqual(load(c), before)

    def test_musicbrainz_fallback_requires_exact_canonical_genre_type(self) -> None:
        with closing(catalog()) as c:
            c.execute("DELETE FROM entity_names")
            c.execute("DELETE FROM entity_identifiers WHERE entity_id=20 AND namespace='wikidata'")
            c.execute("INSERT INTO identifier_types VALUES(2,'musicbrainz_genre_id')")
            c.execute("UPDATE entity_identifiers SET identifier_type_id=2 WHERE entity_id=20")
            value = load(c)
            self.assertEqual(
                value.genres[0].name, "musicbrainz:genre:66666666-6666-4666-8666-666666666666"
            )
            c.execute(
                "UPDATE entity_identifiers SET normalized_value='not-a-uuid' WHERE entity_id=20"
            )
            with self.assertRaises(PublicInputLoadError):
                load(c)

    def test_ordinary_schema_name_source_suppression_release_preserves_facts(self) -> None:
        """Separate observed names from synthetic qualification/claim provenance."""
        with closing(sqlite3.connect(":memory:")) as c:
            for migration in DEFAULT_MIGRATION_PATHS:
                c.executescript(migration.read_text())
            c.executescript("""
                INSERT INTO rights_policies(id,policy_key,policy_version,classification,basis)
                VALUES(1,'synthetic-own-label-contract',1,'open_license','Synthetic test only');
                INSERT INTO rights_policy_permissions VALUES
                (1,'normalize','allow','Fixture'),(1,'embed','allow','Fixture'),
                (1,'local_search','allow','Fixture'),(1,'display','allow','Fixture');
                INSERT INTO rights_policy_seals VALUES(1,'2026-01-01T00:00:00Z');
                INSERT INTO data_sources(id,source_key,name,license_name,default_policy_id)
                VALUES(1,'wikidata_synthetic_facts','Synthetic facts','Fixture permission',1),
                (2,'wikidata_synthetic_names','Synthetic names','Fixture permission',1);
            """)
            for n in (1, 2):
                sha = str(n) * 64
                c.execute(
                    "INSERT INTO provenance_records(id,source_id,policy_id,snapshot_ref,artifact_sha256,record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at) VALUES(?,?,1,?,?,?,'synthetic','synthetic','2026-01-01T00:00:00Z')",
                    (n, n, f"synthetic-{n}", sha, sha),
                )
            projector = EntityProjector()
            genre = projector.persist(
                c,
                EntityProjection(
                    entity_kind="genre",
                    source_identity=ExternalIdentity(namespace="wikidata", value="Q80001"),
                    names=(NameClaim(kind="primary", value="Observed synthetic genre"),),
                ),
                provenance_id=2,
                policy_id=1,
            ).target_id
            c.execute(
                "INSERT INTO genre_music_qualification_observations(genre_id,root_qid,path_depth,path_spec,exclusion_profile,statement_id,statement_rank,observed_at,provenance_id,policy_id,record_fingerprint) VALUES(?,'Q188451',1,'P31','P279:nondeprecated:Q25379','synthetic-only','normal','2026-01-01T00:00:00Z',1,1,?)",
                (genre, "f" * 64),
            )
            artist = projector.persist(
                c,
                EntityProjection(
                    entity_kind="artist",
                    source_identity=ExternalIdentity(namespace="wikidata", value="Q90001"),
                    names=(NameClaim(kind="primary", value="Observed synthetic artist"),),
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
                ),
                provenance_id=1,
                policy_id=1,
            ).target_id
            self.assertIsNotNone(artist)
            before = load(c)
            # No mandatory inventory: absence of registered snapshots remains supported.
            for n, action in enumerate(("suppress", "release")):
                c.execute(
                    "INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,effective_at,event_fingerprint) VALUES('source','2','embed',?,'Synthetic only','2026-01-01T00:00:00Z',?)",
                    (action, str(n + 3) * 64),
                )
                if action == "suppress":
                    self.assertEqual(
                        c.execute(
                            "SELECT count(*) FROM normalizable_artist_genre_evidence"
                        ).fetchone()[0],
                        1,
                    )
                    with self.assertRaises(PublicInputLoadError):
                        load(c)
                else:
                    self.assertEqual(load(c), before)
