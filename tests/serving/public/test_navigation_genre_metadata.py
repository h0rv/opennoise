"""Own display custody over the complete retained CC0 cohort, without new inputs."""

# ruff: noqa: SLF001 -- exercise synchronous public-store boundaries and own custody checks.
import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any, ClassVar, override

from opennoise.catalog.entities import EntityProjector
from opennoise.models.catalog import EntityProjection, ExternalIdentity, IdentifierClaim, NameClaim
from opennoise.pipeline.cultural_catalog import CORE_SHA, PACKS, build
from opennoise.serving.public.artist_navigation_store import (
    PublicArtistNavigationStore,
    PublicArtistNavigationStoreError,
)
from opennoise.serving.public.membership_export_eligibility import ExportEligibility

ROOT = Path(__file__).resolve().parents[3]
CORE = (
    ROOT
    / "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256"
    / f"{CORE_SHA}.json"
)


def suppress(c: sqlite3.Connection, kind: str, ref: int, use: str = "display") -> None:
    """Append a use-specific suppression without altering source observations."""
    c.execute(
        """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,
        reason,effective_at,event_fingerprint) VALUES(?,?,?,'suppress','Own metadata test',
        '2026-10-19T00:00:00Z',?)""",
        (kind, str(ref), use, hashlib.sha256(f"{kind}:{ref}:{use}".encode()).hexdigest()),
    )
    c.commit()


class NavigationGenreMetadataTests(unittest.TestCase):
    temp: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]
    report: ClassVar[dict[str, Any]]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / "full"
        cls.report = build(
            CORE,
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
        shutil.copyfile(self.output / "musicbrainz-first.sqlite", self.path)
        self.c = sqlite3.connect(self.path)
        self.addCleanup(self.c.close)
        self.store = PublicArtistNavigationStore(self.path)
        self.genre, self.raw_name = self.c.execute("""SELECT g.id,g.name FROM genres g
            WHERE g.name NOT GLOB 'Q[0-9]*' AND EXISTS(SELECT 1 FROM
            displayable_artist_genre_evidence e WHERE e.genre_id=g.id)
            ORDER BY g.id LIMIT 1""").fetchone()
        self.qid = self.c.execute(
            """SELECT i.normalized_value FROM entity_identifiers i
            JOIN identifier_types t ON t.id=i.identifier_type_id
            WHERE i.entity_id=? AND t.type_key='wikidata_genre_qid' LIMIT 1""",
            (self.genre,),
        ).fetchone()[0]

    def suppress_names(self, use: str = "display") -> None:
        for (prov,) in self.c.execute(
            "SELECT DISTINCT provenance_id FROM entity_names WHERE entity_id=?", (self.genre,)
        ).fetchall():
            suppress(self.c, "provenance", prov, use)

    def test_all_retained_claims_and_neighborhoods_preserved_with_source_labels(self) -> None:
        with closing(sqlite3.connect(self.path)) as c:
            rows = c.execute("SELECT id FROM genres ORDER BY id").fetchall()
            statuses = [self.store._genre(c, row[0]).name_status for row in rows]
        self.assertEqual(statuses.count("source_name"), 150)
        self.assertEqual(statuses.count("source_identifier"), 1)
        order = self.report["orders"]["musicbrainz-first"]
        self.assertEqual(order["adapter"]["direct_rows"], 278)
        self.assertEqual(sum(r["neighbor_count"] for r in order["neighbors"].values()), 580)
        self.assertEqual(self.c.execute("SELECT count(*) FROM entity_claims").fetchone()[0], 287)

    def test_own_label_suppression_uses_authorized_qid_across_navigation(self) -> None:
        before = self.c.execute(
            "SELECT count(*) FROM displayable_artist_genre_evidence WHERE genre_id=?", (self.genre,)
        ).fetchone()[0]
        self.suppress_names()
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM displayable_entity_names WHERE entity_id=?", (self.genre,)
            ).fetchone()[0],
            0,
        )
        response = self.store._genre_artists_sync(self.genre, 0, 50)
        self.assertEqual(
            (response.genre.name, response.genre.name_status), (self.qid, "source_identifier")
        )
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) FROM displayable_artist_genre_evidence WHERE genre_id=?",
                (self.genre,),
            ).fetchone()[0],
            before,
        )
        self.assertGreater(before, 0)
        artist = response.members[0].artist.entity_id
        genres = self.store._artist_genres_sync(artist, 0, 50)
        self.assertTrue(any(m.genre.name == self.qid for m in genres.genres))
        related = self.store._related_artists_sync(artist, 0, 50)
        self.assertTrue(any(g.name == self.qid for r in related.related for g in r.shared_genres))
        self.assertEqual(self.store._catalog_genre_id_for_qid_sync(self.qid), self.genre)
        self.assertEqual(
            self.store._open_node_ids_for_catalog_genres_sync((self.genre,)),
            {self.genre: f"catalog:wikidata:genre:{self.qid}"},
        )

    def test_export_suppression_does_not_deny_display(self) -> None:
        self.suppress_names("export")
        self.assertEqual(self.store._genre_artists_sync(self.genre, 0, 1).genre.name, self.raw_name)

    def test_entity_display_suppression_blocks_label_and_qid_links(self) -> None:
        suppress(self.c, "entity", self.genre)
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "display-authorized"):
            self.store._genre_artists_sync(self.genre, 0, 1)
        self.assertIsNone(self.store._catalog_genre_id_for_qid_sync(self.qid))
        self.assertEqual(self.store._open_node_ids_for_catalog_genres_sync((self.genre,)), {})

    def test_all_identifier_observations_suppressed_cannot_leak_qid(self) -> None:
        self.suppress_names()
        for (prov,) in self.c.execute(
            "SELECT DISTINCT provenance_id FROM entity_identifiers WHERE entity_id=?", (self.genre,)
        ).fetchall():
            # Some ID observations share the already-suppressed name provenance.
            if not self.c.execute(
                "SELECT 1 FROM active_suppressions WHERE target_kind='provenance' "
                "AND target_ref=? AND use_kind='display'",
                (str(prov),),
            ).fetchone():
                suppress(self.c, "provenance", prov)
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "display-authorized"):
            self.store._genre_artists_sync(self.genre, 0, 1)
        self.assertIsNone(self.store._catalog_genre_id_for_qid_sync(self.qid))

    def test_display_is_explicit_and_export_default_unchanged(self) -> None:
        self.c.row_factory = sqlite3.Row
        display = ExportEligibility(self.c, None, use_kind="display")
        self.assertIsNotNone(display.name(self.genre))
        with self.assertRaisesRegex(ValueError, "declared source families"):
            ExportEligibility(self.c, None)
        default = ExportEligibility(self.c, (("wikidata_", "wikidata"),))
        self.assertEqual(default.use_kind, "export")
        self.assertIsNotNone(default.name(self.genre))

    def test_direct_peer_labels_use_same_own_metadata_gate(self) -> None:
        # A fixture relation isolates label custody; no inferred graph is built here.
        other = self.c.execute(
            "SELECT id FROM genres WHERE id!=? ORDER BY id LIMIT 1", (self.genre,)
        ).fetchone()[0]
        self.c.executescript("""DROP VIEW displayable_public_genre_neighbors;
            CREATE TABLE displayable_public_genre_neighbors(genre_id INTEGER,
            neighbor_genre_id INTEGER,profile_kind TEXT,metric TEXT,score REAL,
            shared_artist_count INTEGER,rank INTEGER);""")
        self.c.execute(
            "INSERT INTO displayable_public_genre_neighbors VALUES(?,?,'direct',"
            "'weighted_jaccard',0.5,2,1)",
            (other, self.genre),
        )
        self.c.commit()
        self.suppress_names()
        response = self.store._genre_direct_peers_sync(other)
        self.assertEqual(len(response.peers), 1)
        self.assertEqual(
            (response.peers[0].genre.name, response.peers[0].genre.name_status),
            (self.qid, "source_identifier"),
        )
        self.assertEqual(response.peers[0].score, 0.5)
        self.assertEqual(response.peers[0].shared_artist_count, 2)

    def test_private_duplicate_qid_cannot_supply_or_silently_reconcile_a_link(self) -> None:
        other = self.c.execute(
            "SELECT id FROM genres WHERE id!=? ORDER BY id LIMIT 1", (self.genre,)
        ).fetchone()[0]
        observed = self.c.execute(
            "SELECT identifier_type_id,provenance_id FROM entity_identifiers "
            "WHERE entity_id=? AND normalized_value=? LIMIT 1",
            (self.genre, self.qid),
        ).fetchone()
        self.c.execute(
            "INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,"
            "value,normalized_value,provenance_id) VALUES(?,?,'wikidata',?,?,?)",
            (other, observed[0], self.qid, self.qid, observed[1]),
        )
        self.c.commit()
        suppress(self.c, "entity", other)
        self.assertIsNone(self.store._catalog_genre_id_for_qid_sync(self.qid))
        self.assertEqual(self.store._open_node_ids_for_catalog_genres_sync((self.genre,)), {})
        self.suppress_names()
        with self.assertRaisesRegex(PublicArtistNavigationStoreError, "display-authorized"):
            self.store._genre_artists_sync(self.genre, 0, 1)

    def test_cached_genre_names_never_supply_labels_or_ordering(self) -> None:
        before = self.store._genre_artists_sync(self.genre, 0, 50).model_dump(mode="json")
        self.c.execute("UPDATE genres SET name='Forbidden cached label' WHERE id=?", (self.genre,))
        self.c.commit()
        self.assertEqual(
            self.store._genre_artists_sync(self.genre, 0, 50).model_dump(mode="json"), before
        )

    def test_name_chain_ambiguity_is_consistent_store_error(self) -> None:
        from unittest.mock import patch  # noqa: PLC0415 -- Local fault isolates the error contract.

        with (
            patch.object(
                ExportEligibility, "name", side_effect=ValueError("ambiguous source artifacts")
            ),
            self.assertRaisesRegex(
                PublicArtistNavigationStoreError, "source metadata is ambiguous"
            ),
        ):
            self.store._genre_artists_sync(self.genre, 0, 1)

    def test_metadata_own_permission_and_artifact_custody_are_required(self) -> None:
        for index, (display, export, artifact) in enumerate(
            ((False, True, True), (True, False, True), (True, True, False))
        ):
            key = f"fixture_metadata_{index}"
            policy = self.c.execute(
                "INSERT INTO rights_policies(policy_key,policy_version,"
                "classification,local_only,basis) VALUES(?,1,'public_domain',0,'Test fixture')",
                (key,),
            ).lastrowid
            for use, allowed in (
                ("normalize", True),
                ("local_search", True),
                ("display", display),
                ("export", export),
            ):
                self.c.execute(
                    "INSERT INTO rights_policy_permissions VALUES(?,?,?,'Test fixture')",
                    (policy, use, "allow" if allowed else "deny"),
                )
            self.c.execute(
                "INSERT INTO rights_policy_seals VALUES(?,'2026-10-19T00:00:00Z')", (policy,)
            )
            source = self.c.execute(
                "INSERT INTO data_sources(source_key,name,license_name,"
                "default_policy_id) VALUES(?,?,'CC0-1.0',?)",
                (key, key, policy),
            ).lastrowid
            sha = hashlib.sha256(key.encode()).hexdigest()
            snapshot = self.c.execute(
                "INSERT INTO source_snapshots(source_id,snapshot_ref,"
                "snapshot_kind,manifest_sha256,acquired_at,policy_id) "
                "VALUES(?,?,'full',?,'2026-10-19T00:00:00Z',?)",
                (source, key, sha, policy),
            ).lastrowid
            if artifact:
                self.c.execute(
                    "INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,"
                    "media_type,byte_size,sha256,vault_key,policy_id) "
                    "VALUES(?,'fixture','Explicit synthetic observation',"
                    "'application/json',1,?,?,?)",
                    (snapshot, sha, sha, policy),
                )
            prov = self.c.execute(
                "INSERT INTO provenance_records(source_id,policy_id,snapshot_ref,"
                "artifact_sha256,record_fingerprint,parser_release_ref,"
                "ingest_attempt_ref,observed_at) "
                "VALUES(?,?,?,?,?,'fixture','fixture','2026-10-19T00:00:00Z')",
                (source, policy, key, sha, sha),
            ).lastrowid
            assert policy is not None
            assert prov is not None
            qid = f"Q999900{index}"
            result = EntityProjector().persist(
                self.c,
                EntityProjection(
                    entity_kind="genre",
                    source_identity=ExternalIdentity(namespace="wikidata", value=qid),
                    names=(NameClaim(kind="primary", value="Own observation"),),
                    identifiers=(
                        IdentifierClaim(
                            type_key="wikidata_genre_qid", namespace="wikidata", value=qid
                        ),
                    ),
                ),
                provenance_id=prov,
                policy_id=policy,
            )
            self.c.commit()
            entity = int(result.target_id)
            self.c.row_factory = sqlite3.Row
            self.assertEqual(
                ExportEligibility(self.c, None, use_kind="display").name(entity) is not None,
                display and artifact,
            )
            self.assertEqual(
                ExportEligibility(self.c, (("fixture_metadata_", "wikidata"),)).name(entity)
                is not None,
                export and artifact,
            )
            if not display or not artifact:
                with self.assertRaisesRegex(PublicArtistNavigationStoreError, "display-authorized"):
                    self.store._genre_artists_sync(entity, 0, 1)
                self.assertIsNone(self.store._catalog_genre_id_for_qid_sync(qid))
