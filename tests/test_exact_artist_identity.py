"""Cross-source artist identity regression tests through ordinary catalog projectors."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import override
from uuid import UUID

from opennoise.catalog.artist_identity import ArtistIdentityError, resolve_artist
from opennoise.catalog.artists import ArtistProjector
from opennoise.catalog.entities import EntityProjector
from opennoise.catalog.musicbrainz import RecordingProjector
from opennoise.catalog.registry import CatalogProjector
from opennoise.db import Database
from opennoise.ingest.musicbrainz import artist_credit_catalog_candidate as native_credits
from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    ArtistCreditMember,
    CachedArtistCreditRelation,
)
from opennoise.models.catalog import (
    ArtistCreditMemberClaim,
    ArtistProjection,
    CatalogProjection,
    EntityProjection,
    ExternalIdentity,
    IdentifierClaim,
    NameClaim,
    ProjectionResult,
    RecordingProjection,
    RelationClaim,
)

MBID = "11111111-1111-4111-8111-111111111111"
OTHER_MBID = "22222222-2222-4222-8222-222222222222"
RECORDING = "33333333-3333-4333-8333-333333333333"


def identifier(value: str = MBID) -> IdentifierClaim:
    """Create one typed native artist identity; no name-based matching."""
    return IdentifierClaim(type_key="musicbrainz_artist_id", namespace="musicbrainz", value=value)


def artist(value: str = MBID) -> ArtistProjection:
    """One native artist row with an intentionally uninformative name."""
    return ArtistProjection(
        external_id=value,
        names=(NameClaim(kind="primary", value="same name"),),
        identifiers=(identifier(value),),
    )


def wikidata(qid: str = "Q100", value: str | None = MBID) -> EntityProjection:
    """Use a differently named exact source crosswalk and one direct P136 claim."""
    return EntityProjection(
        entity_kind="artist",
        source_identity=ExternalIdentity(namespace="wikidata", value=qid),
        names=(NameClaim(kind="primary", value="different name"),),
        identifiers=((identifier(value),) if value else ()),
        claims=(
            RelationClaim(
                property_key="genre",
                target=ExternalIdentity(namespace="wikidata", value="Q500"),
                target_kind="genre",
            ),
        ),
    )


def recording(value: str = MBID) -> RecordingProjection:
    """Keep the chosen recording's actual ordered credit separate from genre evidence."""
    return RecordingProjection(
        external_id=RECORDING,
        names=(NameClaim(kind="primary", value="recording"),),
        identifiers=(
            IdentifierClaim(
                type_key="musicbrainz_recording_id", namespace="musicbrainz", value=RECORDING
            ),
        ),
        artist_credit=(
            ArtistCreditMemberClaim(
                artist_identity=ExternalIdentity(namespace="musicbrainz", value=value),
                artist_name="credit name",
                credited_name="credited spelling",
            ),
        ),
    )


class ExactArtistIdentityTests(unittest.TestCase):
    """Prove order invariance and fail-closed ambiguity without repairing old duplicates."""

    @override
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "catalog.sqlite"
        Database(path).initialize()
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.connection.close)
        self.mb = self.provenance("musicbrainz", display=True)
        self.wd = self.provenance("wikidata", display=True)
        self.hidden = self.provenance("restricted_wikidata", display=False)
        self.connection.commit()

    def provenance(self, source: str, *, display: bool) -> tuple[int, int]:
        """Register independent source policies, never borrow credit provenance for P136."""
        c = self.connection
        policy = c.execute(
            """INSERT INTO
            rights_policies(policy_key,policy_version,classification,local_only,basis)
            VALUES(?,1,'public_domain',0,'test source policy')""",
            (source,),
        ).lastrowid
        for use in ("normalize", "local_search", "display", "embed", "train", "export"):
            c.execute(
                """INSERT INTO rights_policy_permissions(policy_id,use_kind,decision,reason)
                VALUES(?,?,?,'explicit test decision')""",
                (policy, use, "deny" if use == "display" and not display else "allow"),
            )
        c.execute(
            "INSERT INTO rights_policy_seals(policy_id,sealed_at) VALUES(?,'2026-10-19T00:00:00Z')",
            (policy,),
        )
        sid = c.execute(
            "INSERT INTO data_sources(source_key,name,default_policy_id) VALUES(?,?,?)",
            (source, source, policy),
        ).lastrowid
        prov = c.execute(
            """INSERT INTO
            provenance_records(source_id,policy_id,snapshot_ref,record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at)
            VALUES(?,?,'test',?,'test','test','2026-10-19T00:00:00Z')""",
            (sid, policy, "a" * 64),
        ).lastrowid
        if prov is None or policy is None:
            raise AssertionError("Missing source/policy fixture")
        return prov, policy

    def persist(
        self, projector: CatalogProjector, projection: CatalogProjection, source: tuple[int, int]
    ) -> ProjectionResult:
        """Use the public projector contract with independent source custody."""
        prov, policy = source
        return projector.persist(self.connection, projection, provenance_id=prov, policy_id=policy)

    def test_musicbrainz_then_wikidata_joins_claim_to_existing_credit_artist(self) -> None:
        c = self.connection
        self.persist(RecordingProjector(), recording(), self.mb)
        original = c.execute("SELECT artist_id FROM artist_credit_members").fetchone()[0]
        result = self.persist(EntityProjector(), wikidata(), self.wd)
        self.assertEqual(result.target_id, original)
        self.assertTrue(result.duplicate)
        self.assertEqual(c.execute("SELECT count(*) FROM artists").fetchone()[0], 1)
        self.assertEqual(
            c.execute(
                "SELECT artist_id,policy_id,provenance_id FROM artist_genre_evidence"
            ).fetchone(),
            (original, self.wd[1], self.wd[0]),
        )
        self.assertEqual(
            c.execute(
                "SELECT count(DISTINCT provenance_id) FROM entity_identifiers WHERE entity_id=?",
                (original,),
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            c.execute(
                "SELECT count(*) FROM entity_provenance WHERE entity_id=?", (original,)
            ).fetchone()[0],
            2,
        )

    def test_wikidata_then_native_artist_and_recording_all_reuse_subject(self) -> None:
        wd = self.persist(EntityProjector(), wikidata(), self.wd)
        mb = self.persist(ArtistProjector(), artist(), self.mb)
        self.persist(RecordingProjector(), recording(), self.mb)
        self.assertEqual(wd.target_id, mb.target_id)
        self.assertEqual(
            self.connection.execute("SELECT artist_id FROM artist_credit_members").fetchone()[0],
            wd.target_id,
        )
        self.assertEqual(self.connection.execute("SELECT count(*) FROM artists").fetchone()[0], 1)

    def test_repeated_identifier_provenance_is_not_an_ambiguous_entity(self) -> None:
        first = self.persist(EntityProjector(), wikidata(), self.wd)
        self.persist(EntityProjector(), wikidata(), self.mb)
        second = self.persist(EntityProjector(), wikidata(), self.wd)
        self.assertEqual(first.target_id, second.target_id)
        self.assertEqual(resolve_artist(self.connection, (identifier(),)), first.target_id)

    def test_claim_policy_is_not_laundered_by_open_credit_identity(self) -> None:
        wd = self.persist(EntityProjector(), wikidata(), self.hidden)
        self.persist(RecordingProjector(), recording(), self.mb)
        row = self.connection.execute(
            "SELECT artist_id,policy_id FROM artist_genre_evidence"
        ).fetchone()
        self.assertEqual(row, (wd.target_id, self.hidden[1]))
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) FROM displayable_artist_genre_evidence"
            ).fetchone()[0],
            0,
        )

    def test_subject_qid_conflict_rejected_before_mutation(self) -> None:
        self.persist(EntityProjector(), wikidata(), self.wd)
        before = self.connection.total_changes
        with self.assertRaisesRegex(ArtistIdentityError, "conflicting"):
            self.persist(EntityProjector(), wikidata("Q101"), self.wd)
        self.assertEqual(before, self.connection.total_changes)

    def test_multiple_source_mbids_and_noncanonical_values_are_rejected(self) -> None:
        for values in (
            (identifier(), identifier(OTHER_MBID)),
            (identifier("not-an-mbid"),),
            (identifier("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),),
        ):
            p = wikidata().model_copy(update={"identifiers": values})
            before = self.connection.total_changes
            with self.assertRaises(ArtistIdentityError):
                self.persist(EntityProjector(), p, self.wd)
            self.assertEqual(before, self.connection.total_changes)

    def test_first_insert_rejects_foreign_kind_identifiers_without_poisoning(self) -> None:
        for key, namespace, value in (
            ("wikidata_genre_qid", "wikidata", "Q500"),
            ("musicbrainz_recording_id", "musicbrainz", RECORDING),
        ):
            foreign = IdentifierClaim(type_key=key, namespace=namespace, value=value)
            for projector, projection in (
                (EntityProjector(), wikidata()),
                (ArtistProjector(), artist()),
            ):
                poisoned = projection.model_copy(
                    update={"identifiers": (*projection.identifiers, foreign)}
                )
                before = self.connection.total_changes
                with self.assertRaisesRegex(ArtistIdentityError, "foreign"):
                    self.persist(projector, poisoned, self.wd)
                self.assertEqual(before, self.connection.total_changes)
        legitimate = artist().model_copy(
            update={
                "identifiers": (
                    identifier(),
                    IdentifierClaim(type_key="isni", namespace="isni", value="0000000123456789"),
                )
            }
        )
        self.persist(ArtistProjector(), legitimate, self.mb)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM artists").fetchone()[0], 1)

    def test_unobserved_relation_rank_stays_null_and_preferred_is_preserved(self) -> None:
        projection = wikidata()
        for rank in (None, "preferred"):
            claim = projection.claims[0].model_copy(update={"rank": rank})
            observed = projection.model_copy(update={"claims": (claim,)})
            self.persist(EntityProjector(), observed, self.wd)
        ranks = [
            json.loads(row[0])["rank"]
            for row in self.connection.execute(
                "SELECT normalized_value_json FROM entity_claims "
                "WHERE claim_key='genre' ORDER BY id"
            )
        ]
        self.assertEqual(ranks, [None, "preferred"])
        self.assertEqual(
            RelationClaim(
                property_key="genre", target=ExternalIdentity(namespace="wikidata", value="Q501")
            ).rank,
            "normal",
        )

    def test_existing_split_entities_rejected_not_merged(self) -> None:
        self.persist(ArtistProjector(), artist(), self.mb)
        self.persist(EntityProjector(), wikidata(value=None), self.wd)
        before = self.connection.total_changes
        with self.assertRaisesRegex(ArtistIdentityError, "ambiguously"):
            self.persist(EntityProjector(), wikidata(), self.wd)
        self.assertEqual(before, self.connection.total_changes)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM artists").fetchone()[0], 2)

    def test_duplicate_native_identifier_does_not_choose_first_row(self) -> None:
        one = self.persist(ArtistProjector(), artist(), self.mb).target_id
        two = self.persist(ArtistProjector(), artist(OTHER_MBID), self.mb).target_id
        self.connection.execute(
            """INSERT INTO
            entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id)
            SELECT ?,identifier_type_id,namespace,value,normalized_value,provenance_id FROM
            entity_identifiers WHERE entity_id=?""",
            (two, one),
        )
        before = self.connection.total_changes
        with self.assertRaisesRegex(ArtistIdentityError, "ambiguously"):
            self.persist(ArtistProjector(), artist(), self.mb)
        self.assertEqual(before, self.connection.total_changes)

    def test_wrong_kind_binding_rejected_before_artist_mutation(self) -> None:
        self.persist(RecordingProjector(), recording(), self.mb)
        recording_id = self.connection.execute("SELECT id FROM recordings").fetchone()[0]
        artist_id = self.connection.execute("SELECT id FROM artists").fetchone()[0]
        self.connection.execute(
            """UPDATE entity_identifiers SET entity_id=? WHERE entity_id=? AND
            namespace='musicbrainz'""",
            (recording_id, artist_id),
        )
        before = self.connection.total_changes
        with self.assertRaisesRegex(ArtistIdentityError, "wrong entity kind"):
            self.persist(EntityProjector(), wikidata(), self.wd)
        self.assertEqual(before, self.connection.total_changes)

    def test_native_credit_materializer_reuses_wikidata_and_rejects_ambiguity(self) -> None:
        wd = self.persist(EntityProjector(), wikidata(), self.wd)
        relation = CachedArtistCreditRelation(
            entity_kind="recording",
            entity_id=UUID(RECORDING),
            source_endpoint="release/test",
            observed_response_sha256="a" * 64,
            projection_sha256="b" * 64,
            members=(
                ArtistCreditMember(
                    position=0,
                    artist_id=UUID(MBID),
                    artist_name="native",
                    credited_name="credit",
                    join_phrase="",
                ),
            ),
        )
        result = native_credits._artist(self.connection, relation, 0, self.mb[0])  # noqa: SLF001 -- existing replay path regression.
        self.assertEqual(result, wd.target_id)
        two = self.persist(ArtistProjector(), artist(OTHER_MBID), self.mb).target_id
        self.connection.execute(
            """INSERT INTO entity_identifiers
            (entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id)
            SELECT ?,identifier_type_id,namespace,value,normalized_value,provenance_id
            FROM entity_identifiers WHERE entity_id=? AND namespace='musicbrainz'""",
            (two, wd.target_id),
        )
        before = self.connection.total_changes
        with self.assertRaisesRegex(ArtistIdentityError, "ambiguously"):
            native_credits._artist(self.connection, relation, 0, self.mb[0])  # noqa: SLF001
        self.assertEqual(before, self.connection.total_changes)

    def test_credit_conflict_rolls_back_whole_projection_transaction(self) -> None:
        one = self.persist(ArtistProjector(), artist(), self.mb).target_id
        two = self.persist(ArtistProjector(), artist(OTHER_MBID), self.mb).target_id
        self.connection.execute(
            """INSERT INTO
            entity_identifiers(entity_id,identifier_type_id,namespace,value,normalized_value,provenance_id)
            SELECT ?,identifier_type_id,namespace,value,normalized_value,provenance_id FROM
            entity_identifiers WHERE entity_id=?""",
            (two, one),
        )
        self.connection.commit()
        count = self.connection.execute("SELECT count(*) FROM catalog_entities").fetchone()[0]
        with self.assertRaises(ArtistIdentityError), self.connection:
            self.persist(RecordingProjector(), recording(), self.mb)
        self.assertEqual(
            self.connection.execute("SELECT count(*) FROM catalog_entities").fetchone()[0], count
        )
        self.assertEqual(
            self.connection.execute("SELECT count(*) FROM artist_credits").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
