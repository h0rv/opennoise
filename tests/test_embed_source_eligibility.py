"""Explicitly synthetic qualified contracts for public-input use eligibility; no model fits."""

# ruff: noqa: E501 -- Literal fixture rows expose their exact source and policy bindings.

import hashlib
import sqlite3
import unittest
from contextlib import closing
from typing import Literal

from opennoise.catalog.entities import EntityProjector
from opennoise.db import DEFAULT_MIGRATION_PATHS
from opennoise.ml.repository import PublicInputLoadSettings, PublicModelRepository
from opennoise.models.catalog import (
    EntityProjection,
    ExternalIdentity,
    IdentifierClaim,
    NameClaim,
    RelationClaim,
    ValueClaim,
)
from tests.test_public_model_repository import (
    _catalog,
    _listenbrainz,
    _listenbrainz_v2,
    _listenbrainz_v2_multi_artifact,
)

PairVersion = Literal["attempt_ids_v1", "source_artifacts_v2", "source_artifacts_v3"]
BASELINE: dict[PairVersion, str] = {
    "attempt_ids_v1": "f7a316a4ea93a518bd538843d53a946b2a758150778f66495b51ba3737b1e6ed",
    "source_artifacts_v2": "7840f09cf709e5298a2986588f66015d4ebce0bc836a24692da4d39a9adb2840",
    "source_artifacts_v3": "3c8f59f330d45921a9b07151333857efbd314716210788e0de5022ff2fc76728",
}


def catalog(*, sibling: bool = False, anchor: bool = False) -> sqlite3.Connection:
    """Qualify synthetic hierarchy endpoints and label every synthetic facet explicitly."""
    c = _catalog()
    c.executescript("""
        DELETE FROM normalizable_artist_genre_evidence WHERE id<>1;
        UPDATE entity_names SET name='Synthetic Album' WHERE entity_id=30;
        UPDATE entity_names SET name='Synthetic Recording' WHERE entity_id=40;
        INSERT INTO genres VALUES(22,'Synthetic Parent');
        INSERT INTO modelable_music_genres VALUES(22);
        INSERT INTO genre_music_qualification_observations VALUES(22,1,1);
        INSERT INTO entity_identifiers VALUES(9,22,'wikidata','Q101',1);
        INSERT INTO genre_hierarchy VALUES(1,20,22,1);
    """)
    if sibling:
        c.executescript("""
            INSERT INTO provenance_records VALUES(2,1,1,'wd-2',
              'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc');
            INSERT INTO source_snapshots VALUES(2,1,'wd-2',1);
            INSERT INTO genre_music_qualification_observations VALUES(20,2,1),(22,2,1);
            INSERT INTO source_artifacts VALUES(2,2,
              'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',1);
            INSERT INTO normalizable_artist_genre_evidence VALUES(5,10,20,'direct_source_claim',
              2.0,'wikidata_music_slice','synthetic-sibling','wikidata_p136',1,2);
            INSERT INTO normalizable_album_genre_memberships VALUES(2,30,20,'wikidata_p136',3,'wikidata',1,2);
            INSERT INTO normalizable_recording_genre_memberships VALUES(2,40,20,'wikidata_p136','wikidata',4,1,2);
            INSERT INTO genre_hierarchy VALUES(2,20,22,2);
            INSERT INTO entity_claims VALUES(2,10,2,1,'wikidata_relation','genre',
              '{"target":{"namespace":"wikidata","value":"Q100"},"target_kind":"unresolved"}');
        """)
    if anchor:
        c.executescript("""
            INSERT INTO data_sources VALUES(3,'wikidata_allowed_anchor');
            INSERT INTO provenance_records VALUES(3,3,1,'wd-3',
              'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd');
            INSERT INTO source_snapshots VALUES(3,3,'wd-3',1);
            INSERT INTO source_artifacts VALUES(3,3,
              'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',1);
            INSERT INTO genres VALUES(23,'Synthetic Allowed Anchor');
            INSERT INTO modelable_music_genres VALUES(23);
            INSERT INTO genre_music_qualification_observations VALUES(23,3,1);
            INSERT INTO entity_identifiers VALUES(10,23,'wikidata','Q102',1);
            INSERT INTO entity_identifiers VALUES(11,13,'musicbrainz',
              '77777777-7777-4777-8777-777777777777',NULL);
            INSERT INTO entity_names VALUES(8,13,'Synthetic Allowed Artist',1);
            INSERT INTO normalizable_artist_genre_evidence VALUES(6,13,23,'direct_source_claim',
              1.0,'wikidata_allowed_anchor','synthetic-anchor','wikidata_p136',1,3);
        """)
    return c


class EmbedSourceEligibilityTests(unittest.TestCase):
    def test_no_event_default_payload_bytes_are_unchanged_for_all_pair_refs(self) -> None:
        for version, expected in BASELINE.items():
            with (
                closing(_catalog()) as c,
                closing(
                    _listenbrainz()
                    if version == "attempt_ids_v1"
                    else _listenbrainz_v2(joint_attempt_id=7)
                ) as lb,
            ):
                value = PublicModelRepository(c, lb).load(
                    PublicInputLoadSettings(artist_pair_evidence_ref_version=version)
                )
                self.assertEqual(
                    hashlib.sha256(value.model_dump_json().encode()).hexdigest(), expected
                )

    def test_snapshot_and_artifact_veto_remove_every_catalog_facet_and_own_declaration(
        self,
    ) -> None:
        for kind in ("snapshot", "artifact"):
            for use in ("embed", "all", "display", "normalize", "train", "export"):
                with self.subTest(kind=kind, use=use), closing(catalog(anchor=True)) as c:
                    before = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
                    self.assertTrue(
                        before.direct_memberships and before.genres and before.hierarchy
                    )
                    self.assertEqual(
                        {x.entity_kind for x in before.metadata_candidates},
                        {"artist", "release_group", "recording"},
                    )
                    c.execute("INSERT INTO active_suppressions VALUES(?, '1', ?)", (kind, use))
                    after = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
                    if use in ("embed", "all"):
                        self.assertEqual(
                            [r.genre_id for r in after.direct_memberships], ["wikidata:genre:Q102"]
                        )
                        self.assertEqual(
                            [r.genre_id for r in after.genres], ["wikidata:genre:Q102"]
                        )
                        self.assertEqual(
                            [r.name for r in after.metadata_candidates],
                            ["Synthetic Allowed Artist"],
                        )
                        self.assertEqual(after.hierarchy, ())
                        self.assertEqual([r.content_sha256 for r in after.artifacts], ["d" * 64])
                    else:
                        # Isolated loader contracts preserve use-specific normalization semantics.
                        self.assertEqual(after.model_dump_json(), before.model_dump_json())

    def test_allowed_sibling_artifact_retains_each_facet_and_aggregation(self) -> None:
        with closing(catalog(sibling=True)) as c:
            c.execute("INSERT INTO active_suppressions VALUES('artifact','1','embed')")
            value = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
            self.assertEqual([r.value for r in value.direct_memberships], [2.0])
            self.assertEqual(len(value.genres), 2)
            self.assertEqual(len(value.hierarchy), 1)
            self.assertEqual(
                {r.entity_kind: r.direct_evidence_value for r in value.metadata_candidates},
                {"artist": 2.0, "release_group": 3.0, "recording": 4.0},
            )
            self.assertEqual([r.content_sha256 for r in value.artifacts], ["c" * 64])

    def test_exact_direct_claim_refs_do_not_hide_other_facets_or_sibling_capture(self) -> None:
        for ref in ("artist_genre_evidence:1", "entity_claims:1"):
            with self.subTest(ref=ref), closing(catalog(sibling=True)) as c:
                c.execute("INSERT INTO active_suppressions VALUES('claim',?,'embed')", (ref,))
                value = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
                self.assertEqual([r.value for r in value.direct_memberships], [2.0])
                self.assertEqual(len(value.metadata_candidates), 3)
                self.assertEqual(len(value.genres), 2)
                self.assertEqual(len(value.hierarchy), 1)
                self.assertEqual(len(value.artifacts), 2)

    def test_claim_mask_precedes_direct_bounds_and_genre_nomination(self) -> None:
        for ref in ("artist_genre_evidence:1", "entity_claims:1"):
            with closing(catalog(sibling=True)) as c:
                c.executescript(
                    "DELETE FROM normalizable_album_genre_memberships; DELETE FROM normalizable_recording_genre_memberships; DELETE FROM genre_hierarchy;"
                )
                c.execute("INSERT INTO active_suppressions VALUES('claim',?,'embed')", (ref,))
                value = PublicModelRepository(c).load_catalog_only(
                    PublicInputLoadSettings(max_direct_memberships=1, max_metadata_candidates=1)
                )
                self.assertEqual([r.value for r in value.direct_memberships], [2.0])
                self.assertEqual(len(value.genres), 1)
                self.assertEqual(
                    [r.direct_evidence_value for r in value.metadata_candidates], [2.0]
                )

    def test_qualification_support_cannot_survive_sole_suppressed_artifact(self) -> None:
        with closing(catalog(sibling=True, anchor=True)) as c:
            # Keep the allowed direct2 source; remove ONLY its synthetic qualification support.
            c.execute("DELETE FROM genre_music_qualification_observations WHERE provenance_id=2")
            c.execute("INSERT INTO active_suppressions VALUES('artifact','1','embed')")
            value = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
            self.assertEqual(
                [r.genre_id for r in value.direct_memberships], ["wikidata:genre:Q102"]
            )
            self.assertEqual([r.genre_id for r in value.genres], ["wikidata:genre:Q102"])
            self.assertEqual(len(value.metadata_candidates), 1)
            self.assertEqual(value.hierarchy, ())
            # A denied qualifier is not rescued by the cached qualified-ID contract table.
            c.execute("INSERT INTO genre_music_qualification_observations VALUES(20,2,2)")
            self.assertEqual(
                PublicModelRepository(c)
                .load_catalog_only(PublicInputLoadSettings())
                .model_dump_json(),
                value.model_dump_json(),
            )
            c.execute("INSERT INTO genre_music_qualification_observations VALUES(20,2,1),(22,2,1)")
            restored = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
            self.assertEqual(len(restored.direct_memberships), 2)
            self.assertEqual(len(restored.hierarchy), 1)

    def test_ordinary_migrated_schema_projects_and_releases_explicit_synthetic_claims(self) -> None:
        with closing(sqlite3.connect(":memory:")) as c:
            for migration in DEFAULT_MIGRATION_PATHS:
                c.executescript(migration.read_text())
            c.executescript("""
                INSERT INTO rights_policies(id,policy_key,policy_version,classification,basis)
                    VALUES(1,'explicit-synthetic-embed-contract',1,'open_license','Synthetic test only');
                INSERT INTO rights_policy_permissions VALUES
                    (1,'normalize','allow','Fixture'),(1,'local_search','allow','Fixture'),
                    (1,'embed','allow','Fixture'),
                    (1,'display','allow','Fixture'),(1,'export','allow','Fixture');
                INSERT INTO rights_policy_seals VALUES(1,'2026-01-01T00:00:00Z');
                INSERT INTO data_sources(id,source_key,name,license_name,default_policy_id)
                    VALUES(1,'wikidata_synthetic_embed_contract','Synthetic test only','Fixture permission',1);
            """)
            artists = []
            for n in (1, 2):
                sha = str(n) * 64
                c.execute(
                    "INSERT INTO source_snapshots(id,source_id,snapshot_ref,manifest_sha256,snapshot_kind,acquired_at,policy_id) VALUES(?,1,?,?,'single_artifact','2026-01-01T00:00:00Z',1)",
                    (n, f"synthetic-{n}", sha),
                )
                c.execute(
                    "INSERT INTO source_artifacts(id,snapshot_id,artifact_ref,logical_name,media_type,byte_size,sha256,vault_key,policy_id) VALUES(?,?,?,'Synthetic test only','application/json',0,?,?,1)",
                    (n, n, f"synthetic-{n}", sha, sha),
                )
                c.execute(
                    "INSERT INTO provenance_records(id,source_id,policy_id,snapshot_ref,artifact_sha256,record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at) VALUES(?,1,1,?,?,?,'synthetic','synthetic','2026-01-01T00:00:00Z')",
                    (n, f"synthetic-{n}", sha, sha),
                )
                qid = f"Q{80000 + n}"
                genre = EntityProjection(
                    entity_kind="genre",
                    source_identity=ExternalIdentity(namespace="wikidata", value=qid),
                    names=(NameClaim(kind="primary", value=f"Synthetic Genre {n}"),),
                    claims=(
                        ValueClaim(
                            property_key="music_genre_qualification",
                            value_kind="string",
                            value="Q188451|1|P31|P279:nondeprecated:Q25379",
                            statement_id=ExternalIdentity(
                                namespace="wikidata_statement", value=f"{qid}-synthetic"
                            ),
                        ),
                    ),
                )
                EntityProjector().persist(c, genre, provenance_id=n, policy_id=1)
                artist = EntityProjection(
                    entity_kind="artist",
                    source_identity=ExternalIdentity(namespace="wikidata", value=f"Q{90000 + n}"),
                    names=(NameClaim(kind="primary", value=f"Synthetic Artist {n}"),),
                    identifiers=(
                        IdentifierClaim(
                            type_key="musicbrainz_artist_id",
                            namespace="musicbrainz",
                            value=f"{n:08x}-1111-4111-8111-111111111111",
                        ),
                    ),
                    claims=(
                        RelationClaim(
                            property_key="genre",
                            target=ExternalIdentity(namespace="wikidata", value=qid),
                        ),
                    ),
                )
                artists.append(
                    EntityProjector().persist(c, artist, provenance_id=n, policy_id=1).target_id
                )
            repo = PublicModelRepository(c)
            baseline = repo.load_catalog_only(PublicInputLoadSettings())
            self.assertEqual(len(baseline.direct_memberships), 2)
            claim = c.execute(
                "SELECT id FROM entity_claims WHERE entity_id=? AND claim_key='genre'",
                (artists[0],),
            ).fetchone()[0]
            for action in ("suppress", "release"):
                c.execute(
                    "INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,effective_at,event_fingerprint) VALUES('claim',?,'embed',?,'Synthetic contract only','2026-01-01T00:00:00Z',?)",
                    (f"entity_claims:{claim}", action, hashlib.sha256(action.encode()).hexdigest()),
                )
                value = repo.load_catalog_only(PublicInputLoadSettings())
                self.assertEqual(len(value.direct_memberships), 1 if action == "suppress" else 2)
                self.assertEqual(len(value.metadata_candidates), 1 if action == "suppress" else 2)
                self.assertEqual(len(value.genres), 1 if action == "suppress" else 2)
                self.assertEqual(
                    c.execute("SELECT count(*) FROM normalizable_artist_genre_evidence").fetchone()[
                        0
                    ],
                    2,
                )
            self.assertEqual(value.model_dump_json(), baseline.model_dump_json())
            c.execute(
                "INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,effective_at,event_fingerprint) VALUES('artifact','1','embed','suppress','Synthetic contract only','2026-01-01T00:00:00Z',?)",
                (hashlib.sha256(b"artifact").hexdigest(),),
            )
            c.execute("PRAGMA query_only=ON")
            value = repo.load_catalog_only(PublicInputLoadSettings())
            self.assertEqual(len(value.direct_memberships), 1)
            self.assertEqual([a.content_sha256 for a in value.artifacts], ["2" * 64])

    def test_wrong_typed_target_or_capture_and_unknown_refs_are_not_guessed(self) -> None:
        for column, value in (
            ("claim_type", "value"),
            ("claim_key", "subclass_of"),
            ("provenance_id", 999),
            ("policy_id", 999),
            ("entity_id", 999),
            ("normalized_value_json", '{"target":{"namespace":"other","value":"Q100"}}'),
            ("normalized_value_json", '{"target":{"namespace":"wikidata","value":"Q999999"}}'),
        ):
            with closing(catalog()) as c:
                c.execute(f"UPDATE entity_claims SET {column}=? WHERE id=1", (value,))  # noqa: S608 -- Fixed column cases above.
                c.execute(
                    "INSERT INTO active_suppressions VALUES('claim','entity_claims:1','embed')"
                )
                self.assertEqual(
                    len(
                        PublicModelRepository(c)
                        .load_catalog_only(PublicInputLoadSettings())
                        .direct_memberships
                    ),
                    1,
                )
        for ref in ("1", "other:1", "artist_genre_evidence:01"):
            with closing(catalog()) as c:
                c.execute("INSERT INTO active_suppressions VALUES('claim',?,'embed')", (ref,))
                self.assertEqual(
                    len(
                        PublicModelRepository(c)
                        .load_catalog_only(PublicInputLoadSettings())
                        .direct_memberships
                    ),
                    1,
                )

    def test_read_only_connection_and_missing_inventory_preserve_existing_behavior(self) -> None:
        with closing(catalog()) as c:
            c.execute("DELETE FROM source_snapshots")
            c.execute("DELETE FROM source_artifacts")
            c.execute("INSERT INTO active_suppressions VALUES('snapshot','1','embed')")
            c.execute("PRAGMA query_only=ON")
            value = PublicModelRepository(c).load_catalog_only(PublicInputLoadSettings())
            self.assertEqual(len(value.direct_memberships), 1)
            self.assertEqual(len(value.artifacts), 1)

    def test_pair_veto_filters_support_windows_and_refs_before_grouping(self) -> None:
        for version in BASELINE:
            for kind in ("snapshot", "artifact"):
                with (
                    self.subTest(version=version, kind=kind),
                    closing(catalog()) as c,
                    closing(_listenbrainz_v2_multi_artifact()) as lb,
                ):
                    settings = PublicInputLoadSettings(artist_pair_evidence_ref_version=version)
                    before = PublicModelRepository(c, lb).load(settings)
                    self.assertEqual(
                        (
                            before.artist_pairs[0].listener_day_support,
                            before.artist_pairs[0].supporting_windows,
                        ),
                        (9, 2),
                    )
                    lb.execute("INSERT INTO active_suppressions VALUES(?,'1','embed')", (kind,))
                    after = PublicModelRepository(c, lb).load(settings)
                    self.assertEqual(
                        (
                            after.artist_pairs[0].listener_day_support,
                            after.artist_pairs[0].supporting_windows,
                        ),
                        (5, 1),
                    )
                    self.assertEqual(len(after.artist_pairs[0].evidence_refs), 1)
                    self.assertEqual(
                        len(after.artifacts), 2
                    )  # Catalog and surviving ListenBrainz artifact.
                    self.assertEqual(after.direct_memberships, before.direct_memberships)
                    stricter = settings.model_copy(update={"minimum_pair_windows": 2})
                    self.assertEqual(PublicModelRepository(c, lb).load(stricter).artist_pairs, ())
