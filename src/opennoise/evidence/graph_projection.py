"""Build an exact, source-neutral evidence graph checkpoint."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from pydantic import Field, model_validator

from opennoise.common import (
    canonical_json,
    connect_readonly,
    connect_readwrite,
    sha256_file,
    sha256_hex,
    write_atomic_bytes,
)
from opennoise.evidence.frontier import (
    AllSeedEvidenceFrontierArtifact,
    verify_all_seed_evidence_frontier,
)
from opennoise.ingest.musicbrainz.release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)
from opennoise.ingest.musicbrainz.reviewed_alias_context import (
    ReviewedAliasContextArtifact,
    verify_reviewed_alias_context_artifact,
)
from opennoise.models import FrozenModel
from opennoise.peers.support.peer import SupportPeerArtifact, logical_sha
from opennoise.taxonomy.relations.expansion import (
    TaxonomyRelationExpansionArtifact,
    taxonomy_relation_expansion_output_sha256,
)

_SEEDS: Final = 6291
_INPUT_COUNT: Final = 8
_PEER_COUNT: Final = 3

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable
    from pathlib import Path


class EvidenceGraphProjectionError(ValueError):
    """Report a malformed or unsealed graph input."""


class ArtifactInput(FrozenModel):
    """One input bound by exact bytes and its source logical digest."""

    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceGraphProjectionArtifact(FrozenModel):
    """Receipt and aggregate counts for one complete graph database."""

    revision: str = "source-neutral-evidence-graph-v2"
    inputs: tuple[ArtifactInput, ...] = Field(min_length=_INPUT_COUNT, max_length=_INPUT_COUNT)
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_bytes: int = Field(gt=0)
    identity_count: int = Field(ge=_SEEDS, le=_SEEDS)
    total_identity_count: int = Field(ge=_SEEDS)
    claim_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    factual_relation_count: int = Field(ge=0)
    candidate_relation_score_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete(self) -> EvidenceGraphProjectionArtifact:
        """Require full stable identity accounting and every declared input."""
        roles = {item.role for item in self.inputs}
        if (
            self.identity_count != _SEEDS
            or self.total_identity_count < self.identity_count
            or len(roles) != _INPUT_COUNT
        ):
            raise ValueError("receipt must bind all inputs and 6291 stable identities")
        return self


@dataclass(frozen=True, slots=True)
class EvidenceGraphProjectionInputs:
    """The sealed inputs and fresh destination for one graph projection."""

    frontier_path: Path
    musicbrainz_database: Path
    musicbrainz_artifact_path: Path
    reviewed_alias_context_path: Path
    taxonomy_relation_path: Path
    direct_peer_path: Path
    support_peer_path: Path
    filtered_support_peer_path: Path
    output_database: Path


@dataclass(frozen=True, slots=True)
class _LoadedGraphInputs:
    """Verified artifacts plus byte-bound receipts for one graph build."""

    frontier: AllSeedEvidenceFrontierArtifact
    evidence: ReleaseGroupEvidenceArtifact
    aliases: ReviewedAliasContextArtifact
    taxonomy: TaxonomyRelationExpansionArtifact
    peers: tuple[SupportPeerArtifact, SupportPeerArtifact, SupportPeerArtifact]
    receipts: tuple[ArtifactInput, ...]


def artifact_sha256(artifact: EvidenceGraphProjectionArtifact) -> str:
    """Return the canonical logical digest for a graph receipt."""
    payload = canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    return sha256_hex(payload)


def verify_evidence_graph_projection(artifact: EvidenceGraphProjectionArtifact) -> None:
    """Reject a graph receipt whose logical digest cannot be replayed."""
    if artifact_sha256(artifact) != artifact.output_sha256:
        raise EvidenceGraphProjectionError("graph receipt hash does not replay")


def _receipt(role: str, path: Path, logical: str) -> ArtifactInput:
    digest, size = sha256_file(path)
    return ArtifactInput(
        role=role, path=str(path), byte_sha256=digest, byte_count=size, logical_sha256=logical
    )


def _load(inputs: EvidenceGraphProjectionInputs) -> _LoadedGraphInputs:
    try:
        frontier = AllSeedEvidenceFrontierArtifact.model_validate_json(
            inputs.frontier_path.read_bytes()
        )
        verify_all_seed_evidence_frontier(frontier)
        evidence = ReleaseGroupEvidenceArtifact.model_validate_json(
            inputs.musicbrainz_artifact_path.read_bytes()
        )
        verify_release_group_evidence(evidence)
        aliases = ReviewedAliasContextArtifact.model_validate_json(
            inputs.reviewed_alias_context_path.read_bytes()
        )
        verify_reviewed_alias_context_artifact(aliases)
        taxonomy = TaxonomyRelationExpansionArtifact.model_validate_json(
            inputs.taxonomy_relation_path.read_bytes()
        )
        if taxonomy_relation_expansion_output_sha256(taxonomy) != taxonomy.output_sha256:
            raise EvidenceGraphProjectionError("taxonomy hash does not replay")
        peer_paths = (
            inputs.direct_peer_path,
            inputs.support_peer_path,
            inputs.filtered_support_peer_path,
        )
        peers = tuple(SupportPeerArtifact.model_validate_json(p.read_bytes()) for p in peer_paths)
    except (OSError, TypeError, ValueError) as error:
        raise EvidenceGraphProjectionError("invalid graph input") from error
    if len(peers) != _PEER_COUNT:
        raise EvidenceGraphProjectionError("invalid graph input")
    typed_peers: tuple[SupportPeerArtifact, SupportPeerArtifact, SupportPeerArtifact] = (
        peers[0],
        peers[1],
        peers[2],
    )
    database_sha, database_bytes = sha256_file(inputs.musicbrainz_database)
    if (database_sha, database_bytes) != (
        evidence.evidence_database_sha256,
        evidence.evidence_database_bytes,
    ):
        raise EvidenceGraphProjectionError("MusicBrainz database does not match artifact")
    if typed_peers[0].component_kind != "direct_artist_overlap" or any(
        peer.component_kind != "release_group_artist_overlap" for peer in typed_peers[1:]
    ):
        raise EvidenceGraphProjectionError("peer channel component mismatch")
    if any(
        logical_sha(peer.model_dump(mode="json", exclude={"output_sha256"})) != peer.output_sha256
        for peer in typed_peers
    ):
        raise EvidenceGraphProjectionError("peer artifact hash does not replay")
    receipts = (
        _receipt("sealed_frontier_v5", inputs.frontier_path, frontier.output_sha256),
        ArtifactInput(
            role="musicbrainz_database",
            path=str(inputs.musicbrainz_database),
            byte_sha256=database_sha,
            byte_count=database_bytes,
            logical_sha256=database_sha,
        ),
        _receipt("musicbrainz_artifact", inputs.musicbrainz_artifact_path, evidence.output_sha256),
        _receipt(
            "reviewed_alias_context", inputs.reviewed_alias_context_path, aliases.output_sha256
        ),
        _receipt(
            "wikidata_factual_hierarchy", inputs.taxonomy_relation_path, taxonomy.output_sha256
        ),
        _receipt("direct_peer", inputs.direct_peer_path, typed_peers[0].output_sha256),
        _receipt("support_peer", inputs.support_peer_path, typed_peers[1].output_sha256),
        _receipt(
            "filtered_support_peer",
            inputs.filtered_support_peer_path,
            typed_peers[2].output_sha256,
        ),
    )
    return _LoadedGraphInputs(
        frontier=frontier,
        evidence=evidence,
        aliases=aliases,
        taxonomy=taxonomy,
        peers=typed_peers,
        receipts=receipts,
    )


def _many(
    database: sqlite3.Connection, statement: str, values: Iterable[tuple[object, ...]]
) -> None:
    database.executemany(statement, values)


def _schema(database: sqlite3.Connection) -> None:
    database.executescript(
        """PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;
CREATE TABLE artifact_input(
role TEXT PRIMARY KEY,path TEXT NOT NULL,byte_sha256 TEXT NOT NULL,
byte_count INTEGER NOT NULL,logical_sha256 TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE identity(
namespace TEXT NOT NULL,identifier TEXT NOT NULL,label TEXT,
disposition TEXT NOT NULL,PRIMARY KEY(namespace,identifier)) WITHOUT ROWID;
CREATE TABLE claim(
subject_namespace TEXT NOT NULL,subject_identifier TEXT NOT NULL,
predicate TEXT NOT NULL,object_namespace TEXT NOT NULL,
object_identifier TEXT NOT NULL,evidence_kind TEXT NOT NULL,
source TEXT NOT NULL,facet TEXT NOT NULL,provenance_ref TEXT NOT NULL,
release_group_id TEXT NOT NULL,
PRIMARY KEY(subject_namespace,subject_identifier,predicate,
object_namespace,object_identifier,evidence_kind,source,facet,
provenance_ref,release_group_id),
FOREIGN KEY(subject_namespace,subject_identifier)
REFERENCES identity(namespace,identifier)) WITHOUT ROWID;
CREATE TABLE abstention(
namespace TEXT NOT NULL,identifier TEXT NOT NULL,reason TEXT NOT NULL,
provenance_ref TEXT NOT NULL,
PRIMARY KEY(namespace,identifier,reason,provenance_ref),
FOREIGN KEY(namespace,identifier)
REFERENCES identity(namespace,identifier)) WITHOUT ROWID;
CREATE TABLE factual_relation(
child_namespace TEXT NOT NULL,child_identifier TEXT NOT NULL,
parent_namespace TEXT NOT NULL,parent_identifier TEXT NOT NULL,
source TEXT NOT NULL,relation_kind TEXT NOT NULL,
provenance_ref TEXT NOT NULL,
PRIMARY KEY(child_namespace,child_identifier,parent_namespace,
parent_identifier,source,relation_kind,provenance_ref),
FOREIGN KEY(child_namespace,child_identifier)
REFERENCES identity(namespace,identifier),
FOREIGN KEY(parent_namespace,parent_identifier)
REFERENCES identity(namespace,identifier)) WITHOUT ROWID;
CREATE TABLE candidate_relation_score(
left_namespace TEXT NOT NULL,left_identifier TEXT NOT NULL,
right_namespace TEXT NOT NULL,right_identifier TEXT NOT NULL,
channel TEXT NOT NULL,component_kind TEXT NOT NULL,metric TEXT NOT NULL,
score REAL NOT NULL CHECK(score>0 AND score<=1),
shared_count INTEGER NOT NULL CHECK(shared_count>=1),
source_artifact_sha256 TEXT NOT NULL,
PRIMARY KEY(left_namespace,left_identifier,right_namespace,
right_identifier,channel,source_artifact_sha256),
CHECK((left_namespace,left_identifier)<(right_namespace,right_identifier)),
FOREIGN KEY(left_namespace,left_identifier)
REFERENCES identity(namespace,identifier),
FOREIGN KEY(right_namespace,right_identifier)
REFERENCES identity(namespace,identifier)) WITHOUT ROWID;"""
    )


def build_evidence_graph_projection(
    inputs: EvidenceGraphProjectionInputs,
) -> EvidenceGraphProjectionArtifact:
    """Atomically project full endpoint-bearing exact claims and separate channels."""
    if inputs.output_database.exists():
        raise EvidenceGraphProjectionError("output database already exists")
    loaded = _load(inputs)
    frontier, evidence, aliases, taxonomy = (
        loaded.frontier,
        loaded.evidence,
        loaded.aliases,
        loaded.taxonomy,
    )
    peers, receipts = loaded.peers, loaded.receipts
    temporary = inputs.output_database.with_name(
        f".{inputs.output_database.name}.{uuid4().hex}.partial"
    )
    try:
        with closing(connect_readwrite(temporary)) as database, database:
            _schema(database)
            _many(
                database,
                "INSERT INTO artifact_input VALUES (?,?,?,?,?)",
                ((r.role, r.path, r.byte_sha256, r.byte_count, r.logical_sha256) for r in receipts),
            )
            _many(
                database,
                "INSERT INTO identity VALUES ('stable_seed',?,?,?)",
                (
                    (r.source_item_id, r.seed_name, r.reconciliation_disposition)
                    for r in frontier.rows
                ),
            )
            for row in frontier.rows:
                ref = f"frontier:{frontier.output_sha256}:{row.source_item_id}"
                identities = (*row.public_identities, *row.musicbrainz_identities)
                _many(
                    database,
                    "INSERT OR IGNORE INTO identity VALUES (?,?,?,'source_identity')",
                    ((i.namespace, i.identifier, i.name) for i in identities),
                )
                _many(
                    database,
                    "INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,'')",
                    (
                        (
                            i.namespace,
                            i.identifier,
                            "identity_alias_of",
                            "stable_seed",
                            row.source_item_id,
                            "identity_alias",
                            "sealed_frontier_v5",
                            i.match_kind,
                            ref,
                        )
                        for i in identities
                    ),
                )
                _many(
                    database,
                    "INSERT INTO abstention VALUES ('stable_seed',?,?,?)",
                    ((row.source_item_id, x, ref) for x in row.missing_or_abstention_reasons),
                )
            database.execute(
                "ATTACH DATABASE ? AS evidence_source",
                (f"file:{inputs.musicbrainz_database.resolve()}?mode=ro",),
            )
            database.execute(
                "INSERT INTO identity(namespace,identifier,label,disposition) "
                "SELECT DISTINCT 'musicbrainz_artist',artist_id,NULL,'source_entity' "
                "FROM evidence_source.typed_evidence"
            )
            database.execute(
                "INSERT INTO claim(subject_namespace,subject_identifier,"
                "predicate,object_namespace,object_identifier,evidence_kind,"
                "source,facet,provenance_ref,release_group_id) "
                "SELECT 'musicbrainz_artist',artist_id,'artist_membership',"
                "'stable_seed',genre_id,'artist_direct',"
                "'musicbrainz_release_group_evidence',facet,? || evidence_ref,'' "
                "FROM evidence_source.direct_anchor",
                (f"musicbrainz:{evidence.output_sha256}:",),
            )
            database.execute(
                "INSERT INTO claim(subject_namespace,subject_identifier,"
                "predicate,object_namespace,object_identifier,evidence_kind,"
                "source,facet,provenance_ref,release_group_id) "
                "SELECT 'musicbrainz_artist',artist_id,'artist_membership',"
                "'stable_seed',genre_id,'release_group_support',"
                "'musicbrainz_release_group_evidence',facet,? || evidence_ref,"
                "release_group_id FROM evidence_source.release_group_support",
                (f"musicbrainz:{evidence.output_sha256}:",),
            )
            # The source stays attached until this temporary connection closes.
            # Detaching during the active write transaction can lock SQLite even
            # though the source was opened read-only.
            _many(
                database,
                "INSERT OR IGNORE INTO identity(namespace,identifier,label,disposition) "
                "VALUES ('musicbrainz_artist',?,NULL,'source_entity')",
                ((x.artist_id,) for x in aliases.memberships),
            )
            _many(
                database,
                "INSERT INTO claim VALUES ('musicbrainz_artist',?,'artist_membership',"
                "'stable_seed',?,'reviewed_alias_context',"
                "'reviewed_alias_context',?,?,'')",
                (
                    (
                        x.artist_id,
                        x.seed_source_item_id,
                        x.facet,
                        f"alias:{aliases.output_sha256}:{x.contextual_evidence_ref}",
                    )
                    for x in aliases.memberships
                ),
            )
            _many(
                database,
                "INSERT INTO factual_relation VALUES ('stable_seed',?,"
                "'stable_seed',?,'wikidata','wikidata_p279_subclass_of',?)",
                (
                    (
                        e.child_seed_id,
                        e.parent_seed_id,
                        f"taxonomy:{taxonomy.output_sha256}:{o.evidence_ref}",
                    )
                    for e in taxonomy.edges
                    if e.disposition == "accepted_factual"
                    for o in e.factual_evidence
                ),
            )
            channels = ("direct", "support", "filtered_support")
            for channel, peer in zip(channels, peers, strict=True):
                _many(
                    database,
                    "INSERT INTO candidate_relation_score VALUES ('stable_seed',?,"
                    "'stable_seed',?,?,?,?,?,?,?)",
                    (
                        (
                            e.source_genre_id,
                            e.target_genre_id,
                            channel,
                            e.component_kind,
                            peer.metric,
                            e.score,
                            e.shared_supported_artist_count,
                            peer.output_sha256,
                        )
                        for e in peer.candidates
                    ),
                )
            if database.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise EvidenceGraphProjectionError("graph integrity check failed")
            if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise EvidenceGraphProjectionError("graph integrity check failed")
        digest, size = sha256_file(temporary)
        with closing(connect_readonly(temporary)) as database:
            count_queries = {
                "identity": "SELECT count(*) FROM identity WHERE namespace = 'stable_seed'",
                "total_identity": "SELECT count(*) FROM identity",
                "claim": "SELECT count(*) FROM claim",
                "abstention": "SELECT count(*) FROM abstention",
                "factual_relation": "SELECT count(*) FROM factual_relation",
                "candidate_relation_score": "SELECT count(*) FROM candidate_relation_score",
            }
            counts = {
                name: int(database.execute(query).fetchone()[0])
                for name, query in count_queries.items()
            }
        base = EvidenceGraphProjectionArtifact(
            inputs=receipts,
            database_sha256=digest,
            database_bytes=size,
            identity_count=counts["identity"],
            total_identity_count=counts["total_identity"],
            claim_count=counts["claim"],
            abstention_count=counts["abstention"],
            factual_relation_count=counts["factual_relation"],
            candidate_relation_score_count=counts["candidate_relation_score"],
            output_sha256="0" * 64,
        )
        artifact = base.model_copy(update={"output_sha256": artifact_sha256(base)})
        verify_evidence_graph_projection(artifact)
        temporary.replace(inputs.output_database)
        return artifact
    finally:
        temporary.unlink(missing_ok=True)


def write_evidence_graph_projection(path: Path, artifact: EvidenceGraphProjectionArtifact) -> None:
    """Atomically write a replay-verified JSON receipt."""
    verify_evidence_graph_projection(artifact)
    write_atomic_bytes(path, canonical_json(artifact.model_dump(mode="json")) + b"\n")
