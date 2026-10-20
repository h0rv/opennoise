"""Selected-key custody on explicitly synthetic qualified contracts, without model fits."""

# ruff: noqa: E501 -- Literal fixture fields retain exact type and custody bindings.

import sqlite3
import unittest
from contextlib import closing

from opennoise.catalog.entities import EntityProjector
from opennoise.db import DEFAULT_MIGRATION_PATHS
from opennoise.ml.repository import (
    PublicInputLoadError,
    PublicInputLoadSettings,
    PublicModelRepository,
    _require_identities,
)
from opennoise.models.catalog import (
    EntityProjection,
    ExternalIdentity,
    IdentifierClaim,
    NameClaim,
    RelationClaim,
)
from tests.test_embed_metadata_labels import catalog, load
from tests.test_embed_source_eligibility import catalog as hierarchy_catalog
from tests.test_public_model_repository import _listenbrainz


class EmbedSelectedIdentityTests(unittest.TestCase):
    def test_required_artist_and_genre_selected_keys_fail_on_own_veto(self) -> None:
        for entity in (10, 20):
            for kind in ("source", "provenance", "snapshot", "artifact"):
                for use in ("all", "embed"):
                    with (
                        self.subTest(entity=entity, kind=kind, use=use),
                        closing(catalog()) as c,
                        closing(_listenbrainz()) as lb,
                    ):
                        c.execute(
                            "UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=?",
                            (entity,),
                        )
                        c.execute(
                            "INSERT INTO active_suppressions VALUES(?,?,?)", (kind, "99", use)
                        )
                        for full in (False, True):
                            with self.subTest(full=full), self.assertRaises(PublicInputLoadError):
                                repo = PublicModelRepository(c, lb)
                                if full:
                                    repo.load(PublicInputLoadSettings())
                                else:
                                    repo.load_catalog_only(PublicInputLoadSettings())

    def test_optional_album_recording_keys_omit_without_changing_required_facts(self) -> None:
        for entity, kind in ((30, "release_group"), (40, "recording")):
            with self.subTest(kind=kind), closing(catalog()) as c:
                before = load(c)
                c.execute(
                    "UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=?", (entity,)
                )
                c.execute("INSERT INTO active_suppressions VALUES('source','99','embed')")
                after = load(c)
                self.assertNotIn(kind, {x.entity_kind for x in after.metadata_candidates})
                self.assertEqual(after.direct_memberships, before.direct_memberships)
                self.assertEqual(after.genres[0].genre_id, before.genres[0].genre_id)

    def test_permission_denial_is_own_and_display_only_does_not_veto_embed(self) -> None:
        with closing(catalog()) as c:
            c.execute("UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=10")
            before = load(c)
            c.execute("INSERT INTO active_suppressions VALUES('source','99','display')")
            self.assertEqual(load(c), before)
            c.execute("INSERT INTO active_rights_policy_permissions VALUES(99,'embed','deny')")
            c.execute("UPDATE provenance_records SET policy_id=99 WHERE id=99")
            with self.assertRaises(PublicInputLoadError):
                load(c)

    def test_exact_independent_observation_supports_same_key_not_an_alternate(self) -> None:
        for alternate in ("Q100", "Q101"):
            with self.subTest(alternate=alternate), closing(catalog()) as c:
                c.execute("UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=20")
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(200,20,'wikidata',?,1,1)", (alternate,)
                )
                c.execute("INSERT INTO active_suppressions VALUES('source','99','embed')")
                if alternate == "Q100":
                    self.assertEqual(load(c).genres[0].genre_id, "wikidata:genre:Q100")
                else:
                    with self.assertRaises(PublicInputLoadError):
                        load(c)

    def test_optional_alternate_public_key_cannot_rescue_selected_private_key(self) -> None:
        for entity, kind, identifier_type in ((30, "release_group", 102), (40, "recording", 103)):
            with self.subTest(kind=kind), closing(catalog()) as c:
                c.execute(
                    "UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=?", (entity,)
                )
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(200,?,'musicbrainz','aaaaaaaa-1111-4111-8111-111111111111',?,1)",
                    (entity, identifier_type),
                )
                c.execute("INSERT INTO active_suppressions VALUES('source','99','embed')")
                self.assertNotIn(kind, {x.entity_kind for x in load(c).metadata_candidates})

    def test_canonical_type_namespace_and_entity_kind_are_required_even_with_name(self) -> None:
        for sql in (
            "UPDATE entity_identifiers SET normalized_value='Q0100' WHERE entity_id=20 AND namespace='wikidata'",
            "UPDATE identifier_types SET type_key='wikidata_artist_qid' WHERE id=1",
            "UPDATE catalog_entities SET entity_kind='artist' WHERE id=20",
            "UPDATE entity_identifiers SET identifier_type_id=NULL WHERE entity_id=10",
            "UPDATE entity_identifiers SET normalized_value='ABCDEFAB-1111-4111-8111-111111111111' WHERE entity_id=10",
        ):
            with self.subTest(sql=sql), closing(catalog()) as c:
                c.execute(sql)
                with self.assertRaises(PublicInputLoadError):
                    load(c)

    def test_optional_malformed_ids_are_excluded_before_sql_bounds(self) -> None:
        with closing(catalog()) as c:
            # Exclude the original recording and add many similarly unsupported names.
            c.execute("UPDATE entity_identifiers SET normalized_value='bad' WHERE entity_id=40")
            for n in range(200, 220):
                c.execute("INSERT INTO catalog_entities VALUES(?,'recording')", (n,))
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(?,?,'musicbrainz','not-canonical',103,1)",
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

    def test_hierarchy_requires_its_exact_selected_endpoint_keys(self) -> None:
        with closing(hierarchy_catalog(sibling=True)) as c:
            c.execute("UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=22")
            with self.assertRaises(PublicInputLoadError):
                load(c)

    def test_read_only_release_restores_identical_payload(self) -> None:
        with closing(catalog()) as c:
            before = load(c)
            c.execute("UPDATE entity_identifiers SET provenance_id=99 WHERE entity_id=10")
            c.execute("INSERT INTO active_suppressions VALUES('source','99','embed')")
            with self.assertRaises(PublicInputLoadError):
                load(c)
            c.execute(
                "DELETE FROM active_suppressions WHERE target_kind='source' AND target_ref='99'"
            )
            c.execute("PRAGMA query_only=ON")
            self.assertEqual(load(c), before)

    def test_full_schema_identity_source_veto_with_independently_allowed_name(self) -> None:
        with closing(sqlite3.connect(":memory:")) as c:
            for migration in DEFAULT_MIGRATION_PATHS:
                c.executescript(migration.read_text())
            c.executescript("""
                INSERT INTO rights_policies(id,policy_key,policy_version,classification,basis)
                VALUES(1,'synthetic-selected-key-contract',1,'open_license','Synthetic test only');
                INSERT INTO rights_policy_permissions VALUES
                (1,'normalize','allow','Fixture'),(1,'embed','allow','Fixture'),
                (1,'local_search','allow','Fixture'),(1,'display','allow','Fixture');
                INSERT INTO rights_policy_seals VALUES(1,'2026-01-01T00:00:00Z');
                INSERT INTO data_sources(id,source_key,name,license_name,default_policy_id)
                VALUES(1,'wikidata_synthetic_facts','Synthetic facts','Fixture permission',1),
                (2,'wikidata_synthetic_identity','Synthetic identity','Fixture permission',1);
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
                "INSERT INTO entity_names(entity_id,name_kind,name,provenance_id,fingerprint) VALUES(?,'alias','Independent allowed genre name',1,?)",
                (genre, "e" * 64),
            )
            c.execute(
                "INSERT INTO genre_music_qualification_observations(genre_id,root_qid,path_depth,path_spec,exclusion_profile,statement_id,statement_rank,observed_at,provenance_id,policy_id,record_fingerprint) VALUES(?,'Q188451',1,'P31','P279:nondeprecated:Q25379','synthetic-only','normal','2026-01-01T00:00:00Z',1,1,?)",
                (genre, "f" * 64),
            )
            projector.persist(
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
            )
            before = load(c)
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
                    self.assertEqual(
                        c.execute(
                            "SELECT count(*) FROM entity_names WHERE entity_id=? AND provenance_id=1",
                            (genre,),
                        ).fetchone()[0],
                        1,
                    )
                    with self.assertRaises(PublicInputLoadError):
                        load(c)
                else:
                    c.execute("PRAGMA query_only=ON")
                    self.assertEqual(load(c), before)

    def test_many_direct_rows_deduplicate_validation_into_bounded_batches(self) -> None:
        with closing(catalog()) as c:
            for n in range(100, 2100):
                c.execute(
                    "INSERT INTO normalizable_artist_genre_evidence VALUES(?,10,20,'direct_source_claim',1.0,'wikidata_music_slice',?,'wikidata_p136',1,1)",
                    (n, f"synthetic-{n}"),
                )
            queries = []
            c.set_trace_callback(queries.append)
            value = load(c)
            self.assertEqual(len(value.direct_memberships), 2001)
            validations = [q for q in queries if "FROM json_each(" in q]
            self.assertEqual(len(validations), 2)  # One direct-key and one genre-key batch.

    def test_batch_chunk_boundary_retains_first_unavailable_key_order(self) -> None:
        with closing(catalog()) as c:
            identities = []
            for n in range(300, 551):
                key = f"{n:08x}-1111-4111-8111-111111111111"
                c.execute("INSERT INTO catalog_entities VALUES(?,'artist')", (n,))
                c.execute(
                    "INSERT INTO entity_identifiers VALUES(?,?,'musicbrainz',?,101,1)", (n, n, key)
                )
                identities.append((n, f"musicbrainz:artist:{key}"))
            queries = []
            c.set_trace_callback(queries.append)
            _require_identities(c, identities + identities)
            self.assertEqual(sum("FROM json_each(" in q for q in queries), 2)
            identities.extend(
                (
                    (999, "musicbrainz:artist:first-invalid"),
                    (998, "musicbrainz:artist:second-invalid"),
                )
            )
            with self.assertRaisesRegex(PublicInputLoadError, "first-invalid"):
                _require_identities(c, identities)

    def test_embedded_nul_is_rejected_for_all_four_selected_key_roles(self) -> None:
        for entity, kind in (
            (10, "artist"),
            (20, "genre"),
            (30, "release_group"),
            (40, "recording"),
        ):
            with self.subTest(kind=kind), closing(catalog()) as c:
                row = c.execute(
                    "SELECT id,normalized_value FROM entity_identifiers WHERE entity_id=? ORDER BY CASE namespace WHEN 'wikidata' THEN 0 ELSE 1 END,id LIMIT 1",
                    (entity,),
                ).fetchone()
                c.execute(
                    "UPDATE entity_identifiers SET normalized_value=? WHERE id=?",
                    (row[1] + "\x00junk", row[0]),
                )
                if entity in (10, 20):
                    with self.assertRaises(PublicInputLoadError):
                        load(c)
                else:
                    value = load(c, max_metadata_candidates=2)
                    self.assertNotIn(kind, {x.entity_kind for x in value.metadata_candidates})
                    self.assertEqual(len(value.metadata_candidates), 2)
