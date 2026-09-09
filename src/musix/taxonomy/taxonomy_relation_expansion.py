"""Expand the seed hierarchy from independently observed taxonomy relations.

The input boundary is intentionally small.  A relation feed contains immutable
source-response hashes plus direct Wikidata or MusicBrainz genre relations.
Only a canonical/alias Wikidata QID already bound by the sealed taxonomy may
be projected onto a legacy seed.  Names, aliases in a relation feed, and
normalised strings are not a join key here.

P279 and an explicitly hierarchical MusicBrainz genre relation are factual
source statements.  P31, part-of, and non-hierarchical MusicBrainz relations
are useful navigation evidence, but remain review candidates.  The retained
projection is a deterministic DAG; lower-priority rows that would close a
cycle are retained as abstentions with their provenance.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.common import sha256_file, sha256_json
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.types import Sha256  # noqa: TC001  # Pydantic resolves this Annotated alias at runtime.

if TYPE_CHECKING:
    from musix.taxonomy.genre_seed_taxonomy import GenreSeedPublicTaxonomyArtifact

_FEED_REVISION: Final = "taxonomy-relation-feed-v1"
_REVISION: Final = "taxonomy-relation-expansion-v1"
_EVALUATION_REVISION: Final = "taxonomy-relation-expansion-evaluation-v1"
_RECEIPT_REVISION: Final = "taxonomy-relation-expansion-publication-v1"

type RelationSource = Literal["wikidata", "musicbrainz"]
type RelationKind = Literal[
    "wikidata_p279_subclass_of",
    "wikidata_p31_instance_of",
    "wikidata_p361_part_of",
    "musicbrainz_subgenre_of",
    "musicbrainz_part_of",
    "musicbrainz_related",
]
type EdgeDisposition = Literal["accepted_factual", "review_derived", "abstained_cycle"]
type EdgeReason = Literal[
    "direct_subclass_relation",
    "direct_musicbrainz_subgenre_relation",
    "instance_or_part_of_review_relation",
    "musicbrainz_nonhierarchical_review_relation",
    "cycle_detected",
]
type FactualReplayKind = Literal["catalog_wikidata_p279_sqlite_v1"]


class ExactMusicBrainzGenreQidMapping(FrozenModel):
    """A direct identifier crosswalk, never a name-derived crosswalk."""

    musicbrainz_genre_id: str = Field(min_length=1, max_length=200)
    wikidata_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    mapping_kind: Literal["exact_identifier"] = "exact_identifier"
    evidence_ref: str = Field(min_length=1, max_length=1_000)
    source_response_sha256: Sha256


class RelationSourceCustodyReceipt(FrozenModel):
    """A portable receipt for the immutable source object behind a feed response."""

    source_response_sha256: Sha256
    object_key: ObjectKey
    object_sha256: Sha256
    object_byte_size: int = Field(ge=1)
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def bind_response_to_object(self) -> RelationSourceCustodyReceipt:
        """Make the response hash, byte object, and receipt identity agree."""
        if self.source_response_sha256 != self.object_sha256:
            raise ValueError("relation response hash must equal its immutable source object hash")
        receipt = sha256_json(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if receipt != self.receipt_sha256:
            raise ValueError("relation source custody receipt hash does not replay")
        return self


def relation_source_custody_receipt(
    source_response_sha256: Sha256, source_artifact: ObjectWrite
) -> RelationSourceCustodyReceipt:
    """Convert a completed object-store write into a stable feed custody receipt."""
    provisional = RelationSourceCustodyReceipt.model_construct(
        source_response_sha256=source_response_sha256,
        object_key=source_artifact.key,
        object_sha256=source_artifact.sha256,
        object_byte_size=source_artifact.byte_size,
        receipt_sha256="0" * 64,
    )
    return RelationSourceCustodyReceipt(
        source_response_sha256=source_response_sha256,
        object_key=source_artifact.key,
        object_sha256=source_artifact.sha256,
        object_byte_size=source_artifact.byte_size,
        receipt_sha256=sha256_json(provisional.model_dump(mode="json", exclude={"receipt_sha256"})),
    )


class TaxonomyRelationObservation(FrozenModel):
    """One direct source relation, bound to the immutable response that supplied it."""

    observation_id: str = Field(min_length=1, max_length=300)
    source: RelationSource
    relation_kind: RelationKind
    child_source_id: str = Field(min_length=1, max_length=200)
    parent_source_id: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=1_000)
    source_response_sha256: Sha256
    factual_replay_kind: FactualReplayKind | None = None
    factual_replay_relation_id: int | None = Field(default=None, ge=1)
    factual_replay_row_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def require_source_specific_identifiers(self) -> TaxonomyRelationObservation:
        """Reject source and relation-kind combinations that cannot be replayed."""
        if self.child_source_id == self.parent_source_id:
            raise ValueError("taxonomy relation observations cannot be self relations")
        wikidata = self.relation_kind.startswith("wikidata_")
        if wikidata != (self.source == "wikidata"):
            raise ValueError("relation kind must agree with its declared source")
        if self.source == "wikidata" and (
            not self.child_source_id.startswith("Q") or not self.parent_source_id.startswith("Q")
        ):
            raise ValueError("Wikidata relation endpoints must be QIDs")
        replay_values = (
            self.factual_replay_kind,
            self.factual_replay_relation_id,
            self.factual_replay_row_sha256,
        )
        if any(value is not None for value in replay_values) and any(
            value is None for value in replay_values
        ):
            raise ValueError("factual replay bindings must be complete")
        if self.factual_replay_kind is not None and (
            self.source != "wikidata" or self.relation_kind != "wikidata_p279_subclass_of"
        ):
            raise ValueError("only Wikidata P279 observations can carry a factual replay binding")
        return self


class TaxonomyRelationFeed(FrozenModel):
    """A replayable local cache of direct external relation observations."""

    revision: Literal["taxonomy-relation-feed-v1"] = _FEED_REVISION
    source_custodies: tuple[RelationSourceCustodyReceipt, ...] = ()
    musicbrainz_qid_mappings: tuple[ExactMusicBrainzGenreQidMapping, ...] = ()
    observations: tuple[TaxonomyRelationObservation, ...] = Field(max_length=500_000)
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_unique_source_records(self) -> TaxonomyRelationFeed:
        """Ensure a feed cannot hide a source-record collision."""
        mapping_ids = tuple(item.musicbrainz_genre_id for item in self.musicbrainz_qid_mappings)
        if len(mapping_ids) != len(set(mapping_ids)):
            raise ValueError("a MusicBrainz genre ID may have one exact QID mapping per feed")
        observation_ids = tuple(item.observation_id for item in self.observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("relation observation IDs must be unique")
        custody_hashes = tuple(item.source_response_sha256 for item in self.source_custodies)
        if len(custody_hashes) != len(set(custody_hashes)):
            raise ValueError("each source response hash needs one custody receipt per feed")
        response_hashes = {
            item.source_response_sha256
            for item in (*self.musicbrainz_qid_mappings, *self.observations)
        }
        if response_hashes != set(custody_hashes):
            raise ValueError("every relation row and mapping needs a source custody receipt")
        if taxonomy_relation_feed_output_sha256(self) != self.output_sha256:
            raise ValueError("relation feed logical hash does not replay")
        return self


class TaxonomyRelationExpansionPolicy(FrozenModel):
    """Bounded, explicit controls for this direct-relation projection."""

    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    maximum_observations: int = Field(default=500_000, ge=1, le=2_000_000)
    maximum_edges: int = Field(default=250_000, ge=1, le=1_000_000)


class RelationEdgeEvidence(FrozenModel):
    """Provenance for one direct signal supporting a projected seed edge."""

    source: RelationSource
    relation_kind: RelationKind
    observation_id: str = Field(min_length=1, max_length=300)
    child_source_id: str = Field(min_length=1, max_length=200)
    parent_source_id: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=1_000)
    source_response_sha256: Sha256
    musicbrainz_child_mapping_evidence_ref: str | None = None
    musicbrainz_parent_mapping_evidence_ref: str | None = None
    factual_replay_kind: FactualReplayKind | None = None
    factual_replay_relation_id: int | None = Field(default=None, ge=1)
    factual_replay_row_sha256: Sha256 | None = None


class TaxonomyRelationEdge(FrozenModel):
    """A multi-parent seed edge with source facts and review signals kept separate."""

    child_seed_id: str = Field(min_length=1, max_length=200)
    parent_seed_id: str = Field(min_length=1, max_length=200)
    disposition: EdgeDisposition
    reason: EdgeReason
    factual_evidence: tuple[RelationEdgeEvidence, ...] = ()
    review_evidence: tuple[RelationEdgeEvidence, ...] = ()

    @model_validator(mode="after")
    def retain_fact_review_boundary(self) -> TaxonomyRelationEdge:
        """Keep source facts and derived review relations in separate fields."""
        if self.child_seed_id == self.parent_seed_id:
            raise ValueError("projected taxonomy edges cannot be self edges")
        if self.disposition == "accepted_factual":
            if not self.factual_evidence or self.reason not in {
                "direct_subclass_relation",
                "direct_musicbrainz_subgenre_relation",
            }:
                raise ValueError("accepted factual edges require direct hierarchy evidence")
        elif self.disposition == "review_derived":
            if self.factual_evidence or not self.review_evidence:
                raise ValueError("review edges cannot contain factual hierarchy evidence")
        elif self.reason != "cycle_detected":
            raise ValueError("cycle abstentions require the cycle_detected reason")
        return self


class RelationExpansionCoverage(FrozenModel):
    """Complete accounting for direct observations and the retained DAG."""

    seed_count: int = Field(ge=1)
    exact_qid_mapped_seed_count: int = Field(ge=0)
    input_observation_count: int = Field(ge=0)
    projected_observation_count: int = Field(ge=0)
    skipped_unknown_endpoint_count: int = Field(ge=0)
    skipped_ambiguous_exact_qid_count: int = Field(ge=0)
    accepted_factual_edge_count: int = Field(ge=0)
    review_derived_edge_count: int = Field(ge=0)
    cycle_abstained_edge_count: int = Field(ge=0)
    factual_isolated_seed_count: int = Field(ge=0)
    factual_isolated_seed_reduction: int = Field(ge=0)

    @model_validator(mode="after")
    def bound_coverage(self) -> RelationExpansionCoverage:
        """Require a full observation partition and coherent isolation measure."""
        if (
            self.projected_observation_count
            + self.skipped_unknown_endpoint_count
            + self.skipped_ambiguous_exact_qid_count
            != self.input_observation_count
        ):
            raise ValueError("relation observation coverage must be a complete partition")
        if self.factual_isolated_seed_count > self.seed_count:
            raise ValueError("isolated seed count exceeds seed universe")
        if (
            self.factual_isolated_seed_reduction
            != self.seed_count - self.factual_isolated_seed_count
        ):
            raise ValueError("isolated-seed reduction must be measured from an empty seed graph")
        return self


class TaxonomyRelationExpansionArtifact(FrozenModel):
    """Hash-bound factual-and-review projection of an immutable relation feed."""

    revision: Literal["taxonomy-relation-expansion-v1"] = _REVISION
    taxonomy_output_sha256: Sha256
    relation_feed_output_sha256: Sha256
    relation_source_custodies: tuple[RelationSourceCustodyReceipt, ...]
    policy: TaxonomyRelationExpansionPolicy
    policy_sha256: Sha256
    edges: tuple[TaxonomyRelationEdge, ...]
    coverage: RelationExpansionCoverage
    normalized_name_relations_used: Literal[False] = False
    historical_data_used_for_construction: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_artifact(self) -> TaxonomyRelationExpansionArtifact:
        """Bind policy, unique projection pairs, and the logical artifact hash."""
        if sha256_json(self.policy.model_dump(mode="json")) != self.policy_sha256:
            raise ValueError("relation expansion policy hash does not replay")
        pairs = tuple((item.child_seed_id, item.parent_seed_id) for item in self.edges)
        if len(pairs) != len(set(pairs)):
            raise ValueError("projected seed edges must be unique")
        if len(self.edges) > self.policy.maximum_edges:
            raise ValueError("projected edge count exceeds the policy bound")
        if not self.relation_source_custodies:
            raise ValueError("relation expansion requires receipt-rooted source custody")
        if taxonomy_relation_expansion_output_sha256(self) != self.output_sha256:
            raise ValueError("relation expansion logical hash does not replay")
        return self


class TaxonomyRelationExpansionGate(FrozenModel):
    """Fail-closed check for an immutable DAG publication."""

    artifact_output_sha256: Sha256
    seed_count: int = Field(ge=1)
    accepted_factual_edge_count: int = Field(ge=0)
    review_derived_edge_count: int = Field(ge=0)
    acyclic: Literal[True] = True
    no_normalized_name_relations: Literal[True] = True
    no_historical_inputs: Literal[True] = True


class TaxonomyRelationExpansionReceipt(FrozenModel):
    """Object-store receipt for the published relation-expansion artifact."""

    revision: Literal["taxonomy-relation-expansion-publication-v1"] = _RECEIPT_REVISION
    artifact: ObjectWrite
    artifact_sha256: Sha256
    logical_output_sha256: Sha256


class TaxonomyRelationHoldoutPolicy(FrozenModel):
    """Deterministically hide reference facts without feeding them into construction."""

    edge_modulus: int = Field(default=5, ge=2, le=1_000)
    edge_remainder: int = Field(default=0, ge=0, le=999)
    node_modulus: int = Field(default=7, ge=2, le=1_000)
    node_remainder: int = Field(default=0, ge=0, le=999)

    @model_validator(mode="after")
    def require_valid_remainders(self) -> TaxonomyRelationHoldoutPolicy:
        """Keep deterministic edge and node sampling within each modulus."""
        if self.edge_remainder >= self.edge_modulus or self.node_remainder >= self.node_modulus:
            raise ValueError("holdout remainder must be lower than its modulus")
        return self


@dataclass(frozen=True, slots=True)
class TaxonomyRelationEvaluationInputs:
    """The independent training source, oracle, and custody store for one holdout run."""

    full_relation_feed: TaxonomyRelationFeed
    reference_factual_edges: frozenset[tuple[str, str]]
    holdout_policy: TaxonomyRelationHoldoutPolicy
    source_store: ObjectStore
    defensible_negative_edges: frozenset[tuple[str, str]] | None = None


class TaxonomyRelationExpansionEvaluation(FrozenModel):
    """Positive holdout recall plus precision only over explicitly labelled negatives."""

    revision: Literal["taxonomy-relation-expansion-evaluation-v1"] = _EVALUATION_REVISION
    expansion_output_sha256: Sha256
    training_relation_feed_output_sha256: Sha256
    holdout_policy: TaxonomyRelationHoldoutPolicy
    reference_factual_edge_count: int = Field(ge=0)
    hidden_node_count: int = Field(ge=0)
    hidden_factual_edge_count: int = Field(ge=0)
    recovered_hidden_factual_edge_count: int = Field(ge=0)
    recall: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    precision: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    precision_status: Literal["not_evaluable_without_negatives", "evaluated"]
    evaluated_prediction_count: int = Field(ge=0)
    baseline_factual_isolated_seed_count: int = Field(ge=0)
    expanded_factual_isolated_seed_count: int = Field(ge=0)
    isolated_seed_reduction: int = Field(ge=0)

    @model_validator(mode="after")
    def require_honest_metrics(self) -> TaxonomyRelationExpansionEvaluation:
        """Expose recall and precision only when their denominators are labelled."""
        if self.hidden_factual_edge_count == 0 and self.recall is not None:
            raise ValueError(
                "recall is unavailable when a deterministic split has no hidden positives"
            )
        if self.hidden_factual_edge_count and self.recall is None:
            raise ValueError("recall is required when hidden positives exist")
        if (self.precision is None) != (self.precision_status == "not_evaluable_without_negatives"):
            raise ValueError(
                "precision status must state whether defensible negatives were supplied"
            )
        if self.isolated_seed_reduction != (
            self.baseline_factual_isolated_seed_count - self.expanded_factual_isolated_seed_count
        ):
            raise ValueError("isolated-seed reduction does not replay")
        return self


@dataclass(slots=True)
class _ProjectedProposal:
    factual: list[RelationEdgeEvidence] = field(default_factory=list)
    review: list[RelationEdgeEvidence] = field(default_factory=list)
    cycle_detected: bool = False


def taxonomy_relation_feed_output_sha256(feed: TaxonomyRelationFeed) -> Sha256:
    """Recompute an immutable relation-feed logical hash."""
    return sha256_json(feed.model_dump(mode="json", exclude={"output_sha256"}))


def build_taxonomy_relation_feed(
    source_custodies: tuple[RelationSourceCustodyReceipt, ...],
    mappings: tuple[ExactMusicBrainzGenreQidMapping, ...],
    observations: tuple[TaxonomyRelationObservation, ...],
) -> TaxonomyRelationFeed:
    """Create a hash-bound feed after parsing a cached source response once."""
    provisional = TaxonomyRelationFeed.model_construct(
        source_custodies=source_custodies,
        musicbrainz_qid_mappings=mappings,
        observations=observations,
        output_sha256="0" * 64,
    )
    return TaxonomyRelationFeed(
        source_custodies=source_custodies,
        musicbrainz_qid_mappings=mappings,
        observations=observations,
        output_sha256=taxonomy_relation_feed_output_sha256(provisional),
    )


def load_taxonomy_relation_feed(path: Path) -> TaxonomyRelationFeed:
    """Load a previously cached relation feed and verify its logical identity."""
    return TaxonomyRelationFeed.model_validate_json(path.read_bytes())


def verify_relation_source_custodies(
    custodies: tuple[RelationSourceCustodyReceipt, ...], *, store: ObjectStore
) -> None:
    """Verify every receipt names an existing object with exactly matching bytes."""
    if not custodies:
        raise ValueError("raw unreceipted relation feeds cannot construct factual taxonomy edges")
    for custody in custodies:
        if not store.exists(custody.object_key):
            raise FileNotFoundError(
                f"relation source object {custody.object_key.value!r} is not present"
            )
        metadata = store.inspect(custody.object_key)
        if (
            metadata.key != custody.object_key
            or metadata.sha256 != custody.object_sha256
            or metadata.byte_size != custody.object_byte_size
        ):
            raise ValueError("relation source object does not match its custody receipt")


def verify_taxonomy_relation_feed_custody(
    feed: TaxonomyRelationFeed, *, store: ObjectStore
) -> None:
    """Verify the full feed's declared source receipts before factual projection."""
    verify_relation_source_custodies(feed.source_custodies, store=store)


def _catalog_wikidata_p279_rows(path: Path) -> dict[int, tuple[str, str]]:
    """Replay the one permitted catalog extraction with its export-policy filter."""
    uri = f"file:{path.resolve(strict=True).as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        qids = {
            int(entity_id): str(value)
            for entity_id, value in db.execute(
                """SELECT identifier.entity_id, identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS kind ON kind.id = identifier.identifier_type_id
                   WHERE kind.type_key = 'wikidata_genre_qid'
                   ORDER BY identifier.entity_id, identifier.normalized_value"""
            )
        }
        rows = tuple(
            (int(relation_id), int(child_id), int(parent_id))
            for relation_id, child_id, parent_id in db.execute(
                """SELECT DISTINCT hierarchy.relation_id, hierarchy.child_genre_id,
                                   hierarchy.parent_genre_id
                   FROM genre_hierarchy AS hierarchy
                   JOIN provenance_records AS provenance ON provenance.id = hierarchy.provenance_id
                   JOIN data_sources AS source ON source.id = provenance.source_id
                   JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                   JOIN rights_policy_permissions AS permission ON permission.policy_id = policy.id
                   WHERE source.license_name LIKE 'CC0-1.0%'
                     AND policy.local_only = 0
                     AND permission.use_kind = 'export'
                     AND permission.decision = 'allow'
                   ORDER BY hierarchy.relation_id"""
            )
        )
    return {
        relation_id: (qids[child_id], qids[parent_id])
        for relation_id, child_id, parent_id in rows
        if child_id in qids and parent_id in qids and qids[child_id] != qids[parent_id]
    }


def _catalog_row_sha256(relation_id: int, child_qid: str, parent_qid: str) -> Sha256:
    """Bind an observation to the exact canonical extraction record, not just source bytes."""
    return sha256_json(
        {
            "revision": "catalog-wikidata-p279-sqlite-v1",
            "relation_id": relation_id,
            "child_qid": child_qid,
            "parent_qid": parent_qid,
        }
    )


def verify_replayable_factual_observations(  # noqa: C901 - one fail-closed replay boundary.
    feed: TaxonomyRelationFeed, *, store: ObjectStore
) -> None:
    """Reparse every factual source row before it can become an accepted edge.

    Generic relation envelopes can retain review observations, but a hash of an
    unrelated response is not evidence for a factual hierarchy statement.
    """
    factual = tuple(row for row in feed.observations if _relation_is_factual(row.relation_kind))
    if not factual:
        return
    for row in factual:
        if row.factual_replay_kind != "catalog_wikidata_p279_sqlite_v1":
            raise ValueError(
                "factual taxonomy relations require replayable catalog_wikidata_p279 extraction"
            )
    custody_by_hash = {item.source_response_sha256: item for item in feed.source_custodies}
    with tempfile.TemporaryDirectory(prefix="musix-taxonomy-replay-") as temporary:
        root = Path(temporary)
        rows_by_source: dict[str, dict[int, tuple[str, str]]] = {}
        for source_hash in sorted({row.source_response_sha256 for row in factual}):
            custody = custody_by_hash.get(source_hash)
            if custody is None:
                raise ValueError("factual taxonomy relation has no source custody receipt")
            snapshot = root / f"{source_hash}.sqlite"
            restored = store.pull(custody.object_key, snapshot)
            if (restored.sha256, restored.byte_size) != (
                custody.object_sha256,
                custody.object_byte_size,
            ):
                raise ValueError("replayed catalog object does not match its custody receipt")
            try:
                rows_by_source[source_hash] = _catalog_wikidata_p279_rows(snapshot)
            except sqlite3.Error as error:
                raise ValueError(
                    "factual taxonomy relation source is not a replayable catalog SQLite snapshot"
                ) from error
        for row in factual:
            relation_id = row.factual_replay_relation_id
            row_sha = row.factual_replay_row_sha256
            if relation_id is None or row_sha is None:
                raise ValueError("factual taxonomy relation replay binding is incomplete")
            extracted = rows_by_source[row.source_response_sha256].get(relation_id)
            if extracted != (row.child_source_id, row.parent_source_id):
                raise ValueError(
                    "factual taxonomy relation does not replay from its catalog source row"
                )
            if row_sha != _catalog_row_sha256(
                relation_id, row.child_source_id, row.parent_source_id
            ):
                raise ValueError("factual taxonomy relation canonical row hash does not replay")


def catalog_wikidata_p279_feed(path: Path, *, store: ObjectStore) -> TaxonomyRelationFeed:
    """Extract permitted local catalog hierarchy rows as direct P279 observations.

    The existing catalog does not retain P31/P361 or MusicBrainz genre
    relations.  Those can enter through a separately cached relation feed;
    this extractor deliberately does not invent them.
    """
    database_sha = sha256_file(path)[0]
    source_write = store.push(
        path,
        ObjectKey(value=f"taxonomy-relation-expansion/source/sha256/{database_sha}.sqlite"),
    )
    if source_write.sha256 != database_sha:
        raise ValueError("catalog source publication does not match the local snapshot bytes")
    rows = _catalog_wikidata_p279_rows(path)
    observations = tuple(
        TaxonomyRelationObservation(
            observation_id=f"catalog:{database_sha}:genre_hierarchy:{relation_id}",
            source="wikidata",
            relation_kind="wikidata_p279_subclass_of",
            child_source_id=child_qid,
            parent_source_id=parent_qid,
            evidence_ref=f"catalog:{database_sha}:genre_hierarchy:{relation_id}",
            source_response_sha256=database_sha,
            factual_replay_kind="catalog_wikidata_p279_sqlite_v1",
            factual_replay_relation_id=relation_id,
            factual_replay_row_sha256=_catalog_row_sha256(relation_id, child_qid, parent_qid),
        )
        for relation_id, (child_qid, parent_qid) in sorted(rows.items())
    )
    return build_taxonomy_relation_feed(
        (relation_source_custody_receipt(database_sha, source_write),), (), observations
    )


def merge_taxonomy_relation_feeds(feeds: tuple[TaxonomyRelationFeed, ...]) -> TaxonomyRelationFeed:
    """Merge immutable feeds without allowing an ID to conceal a disagreement."""
    custodies: dict[str, RelationSourceCustodyReceipt] = {}
    mappings: dict[str, ExactMusicBrainzGenreQidMapping] = {}
    observations: dict[str, TaxonomyRelationObservation] = {}
    for feed in feeds:
        for custody in feed.source_custodies:
            existing_custody = custodies.setdefault(custody.source_response_sha256, custody)
            if existing_custody != custody:
                raise ValueError("conflicting source custody receipt across relation feeds")
        for mapping in feed.musicbrainz_qid_mappings:
            existing = mappings.setdefault(mapping.musicbrainz_genre_id, mapping)
            if existing != mapping:
                raise ValueError(
                    "conflicting exact MusicBrainz-to-QID mapping across relation feeds"
                )
        for observation in feed.observations:
            existing = observations.setdefault(observation.observation_id, observation)
            if existing != observation:
                raise ValueError("conflicting observation ID across relation feeds")
    return build_taxonomy_relation_feed(
        tuple(sorted(custodies.values(), key=lambda item: item.source_response_sha256)),
        tuple(sorted(mappings.values(), key=lambda item: item.musicbrainz_genre_id)),
        tuple(sorted(observations.values(), key=lambda item: item.observation_id)),
    )


def _exact_seed_qid_map(
    taxonomy: GenreSeedPublicTaxonomyArtifact,
) -> tuple[dict[str, str], frozenset[str]]:
    mapped: dict[str, set[str]] = defaultdict(set)
    for inference in taxonomy.inferences:
        if inference.status not in {"canonical_exact", "canonical_alias"}:
            continue
        catalog_id = inference.exact_candidates[0].catalog_id
        prefix = "wikidata:genre:"
        if catalog_id.startswith(prefix):
            mapped[catalog_id.removeprefix(prefix)].add(inference.source_item_id)
    ambiguous = frozenset(qid for qid, seeds in mapped.items() if len(seeds) != 1)
    return (
        {qid: next(iter(seeds)) for qid, seeds in mapped.items() if len(seeds) == 1},
        ambiguous,
    )


def _relation_is_factual(kind: RelationKind) -> bool:
    return kind in {"wikidata_p279_subclass_of", "musicbrainz_subgenre_of"}


def _edge_reason(proposal: _ProjectedProposal) -> EdgeReason:
    if proposal.cycle_detected:
        return "cycle_detected"
    if proposal.factual:
        if any(item.relation_kind == "wikidata_p279_subclass_of" for item in proposal.factual):
            return "direct_subclass_relation"
        return "direct_musicbrainz_subgenre_relation"
    if any(
        item.relation_kind
        in {"wikidata_p31_instance_of", "wikidata_p361_part_of", "musicbrainz_part_of"}
        for item in proposal.review
    ):
        return "instance_or_part_of_review_relation"
    return "musicbrainz_nonhierarchical_review_relation"


def _path_exists(parents: dict[str, set[str]], start: str, target: str) -> bool:
    pending = [start]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(sorted(parents[current]))
    return False


def _mark_cycles(proposals: dict[tuple[str, str], _ProjectedProposal]) -> None:
    """Retain every source row but only allow a deterministic DAG projection."""
    parents: dict[str, set[str]] = defaultdict(set)

    def priority(pair: tuple[str, str]) -> tuple[int, str, str]:
        proposal = proposals[pair]
        return (0 if proposal.factual else 1, pair[0], pair[1])

    for child, parent in sorted(proposals, key=priority):
        if _path_exists(parents, parent, child):
            proposals[(child, parent)].cycle_detected = True
        else:
            parents[child].add(parent)


def _edge_from_proposal(
    pair: tuple[str, str], proposal: _ProjectedProposal
) -> TaxonomyRelationEdge:
    disposition: EdgeDisposition = (
        "abstained_cycle"
        if proposal.cycle_detected
        else "accepted_factual"
        if proposal.factual
        else "review_derived"
    )
    return TaxonomyRelationEdge(
        child_seed_id=pair[0],
        parent_seed_id=pair[1],
        disposition=disposition,
        reason=_edge_reason(proposal),
        factual_evidence=tuple(
            sorted(proposal.factual, key=lambda item: (item.observation_id, item.evidence_ref))
        ),
        review_evidence=tuple(
            sorted(proposal.review, key=lambda item: (item.observation_id, item.evidence_ref))
        ),
    )


def _factual_isolated_count(
    seed_ids: frozenset[str], edges: tuple[TaxonomyRelationEdge, ...]
) -> int:
    connected = {
        seed_id
        for edge in edges
        if edge.disposition == "accepted_factual"
        for seed_id in (edge.child_seed_id, edge.parent_seed_id)
    }
    return len(seed_ids - connected)


def build_taxonomy_relation_expansion(
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    feed: TaxonomyRelationFeed,
    policy: TaxonomyRelationExpansionPolicy | None = None,
    *,
    source_store: ObjectStore,
) -> TaxonomyRelationExpansionArtifact:
    """Project independently cached relations onto exact, unambiguous seed QIDs."""
    resolved = policy or TaxonomyRelationExpansionPolicy()
    verify_taxonomy_relation_feed_custody(feed, store=source_store)
    verify_replayable_factual_observations(feed, store=source_store)
    seed_ids = frozenset(item.source_item_id for item in taxonomy.inferences)
    if len(seed_ids) != resolved.expected_seed_count:
        raise ValueError("taxonomy does not cover the expected immutable seed universe")
    if len(feed.observations) > resolved.maximum_observations:
        raise ValueError("relation feed observation count exceeds the policy bound")
    qid_to_seed, ambiguous_qids = _exact_seed_qid_map(taxonomy)
    mb_mappings = {item.musicbrainz_genre_id: item for item in feed.musicbrainz_qid_mappings}
    proposals: dict[tuple[str, str], _ProjectedProposal] = {}
    skipped_unknown = 0
    skipped_ambiguous = 0
    projected = 0
    for observation in feed.observations:
        child_qid: str
        parent_qid: str
        child_mapping: ExactMusicBrainzGenreQidMapping | None = None
        parent_mapping: ExactMusicBrainzGenreQidMapping | None = None
        if observation.source == "wikidata":
            child_qid, parent_qid = observation.child_source_id, observation.parent_source_id
        else:
            child_mapping = mb_mappings.get(observation.child_source_id)
            parent_mapping = mb_mappings.get(observation.parent_source_id)
            if child_mapping is None or parent_mapping is None:
                skipped_unknown += 1
                continue
            child_qid, parent_qid = child_mapping.wikidata_qid, parent_mapping.wikidata_qid
        if child_qid in ambiguous_qids or parent_qid in ambiguous_qids:
            skipped_ambiguous += 1
            continue
        child_seed = qid_to_seed.get(child_qid)
        parent_seed = qid_to_seed.get(parent_qid)
        if child_seed is None or parent_seed is None or child_seed == parent_seed:
            skipped_unknown += 1
            continue
        evidence = RelationEdgeEvidence(
            source=observation.source,
            relation_kind=observation.relation_kind,
            observation_id=observation.observation_id,
            child_source_id=observation.child_source_id,
            parent_source_id=observation.parent_source_id,
            evidence_ref=observation.evidence_ref,
            source_response_sha256=observation.source_response_sha256,
            musicbrainz_child_mapping_evidence_ref=(
                child_mapping.evidence_ref if child_mapping is not None else None
            ),
            musicbrainz_parent_mapping_evidence_ref=(
                parent_mapping.evidence_ref if parent_mapping is not None else None
            ),
            factual_replay_kind=observation.factual_replay_kind,
            factual_replay_relation_id=observation.factual_replay_relation_id,
            factual_replay_row_sha256=observation.factual_replay_row_sha256,
        )
        proposal = proposals.setdefault((child_seed, parent_seed), _ProjectedProposal())
        evidence_list = (
            proposal.factual if _relation_is_factual(observation.relation_kind) else proposal.review
        )
        evidence_list.append(evidence)
        projected += 1
    _mark_cycles(proposals)
    edges = tuple(_edge_from_proposal(pair, proposals[pair]) for pair in sorted(proposals))
    if len(edges) > resolved.maximum_edges:
        raise ValueError("relation projection edge count exceeds the policy bound")
    isolated = _factual_isolated_count(seed_ids, edges)
    coverage = RelationExpansionCoverage(
        seed_count=len(seed_ids),
        exact_qid_mapped_seed_count=len(qid_to_seed),
        input_observation_count=len(feed.observations),
        projected_observation_count=projected,
        skipped_unknown_endpoint_count=skipped_unknown,
        skipped_ambiguous_exact_qid_count=skipped_ambiguous,
        accepted_factual_edge_count=sum(edge.disposition == "accepted_factual" for edge in edges),
        review_derived_edge_count=sum(edge.disposition == "review_derived" for edge in edges),
        cycle_abstained_edge_count=sum(edge.disposition == "abstained_cycle" for edge in edges),
        factual_isolated_seed_count=isolated,
        factual_isolated_seed_reduction=len(seed_ids) - isolated,
    )
    policy_sha = sha256_json(resolved.model_dump(mode="json"))
    preliminary = TaxonomyRelationExpansionArtifact.model_construct(
        taxonomy_output_sha256=taxonomy.output_sha256,
        relation_feed_output_sha256=feed.output_sha256,
        relation_source_custodies=feed.source_custodies,
        policy=resolved,
        policy_sha256=policy_sha,
        edges=edges,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return TaxonomyRelationExpansionArtifact(
        taxonomy_output_sha256=taxonomy.output_sha256,
        relation_feed_output_sha256=feed.output_sha256,
        relation_source_custodies=feed.source_custodies,
        policy=resolved,
        policy_sha256=policy_sha,
        edges=edges,
        coverage=coverage,
        output_sha256=taxonomy_relation_expansion_output_sha256(preliminary),
    )


def taxonomy_relation_expansion_output_sha256(
    artifact: TaxonomyRelationExpansionArtifact,
) -> Sha256:
    """Recompute the relation-expansion artifact's logical identity."""
    return sha256_json(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def _assert_dag(edges: tuple[TaxonomyRelationEdge, ...]) -> None:
    parents: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.disposition != "abstained_cycle":
            parents[edge.child_seed_id].add(edge.parent_seed_id)
    for start in sorted(parents):
        if _path_exists(parents, start, start):
            # _path_exists is true at zero steps, so run a proper successor traversal here.
            pending = list(parents[start])
            seen: set[str] = set()
            while pending:
                current = pending.pop()
                if current == start:
                    raise ValueError("retained taxonomy relation graph contains a cycle")
                if current not in seen:
                    seen.add(current)
                    pending.extend(parents[current])


def verify_taxonomy_relation_expansion(
    artifact: TaxonomyRelationExpansionArtifact,
    *,
    source_store: ObjectStore,
) -> TaxonomyRelationExpansionGate:
    """Fail closed before publishing a factual/review-separated DAG."""
    if taxonomy_relation_expansion_output_sha256(artifact) != artifact.output_sha256:
        raise ValueError("relation expansion output hash does not replay")
    verify_relation_source_custodies(artifact.relation_source_custodies, store=source_store)
    # The published edge evidence must remain replayable from the exact cached catalog bytes.
    # Reconstruct a minimal feed view so the same source-row gate is applied at every use site.
    replay_feed = TaxonomyRelationFeed.model_construct(
        source_custodies=artifact.relation_source_custodies,
        musicbrainz_qid_mappings=(),
        observations=tuple(
            TaxonomyRelationObservation(
                observation_id=evidence.observation_id,
                source=evidence.source,
                relation_kind=evidence.relation_kind,
                child_source_id=evidence.child_source_id,
                parent_source_id=evidence.parent_source_id,
                evidence_ref=evidence.evidence_ref,
                source_response_sha256=evidence.source_response_sha256,
                factual_replay_kind=evidence.factual_replay_kind,
                factual_replay_relation_id=evidence.factual_replay_relation_id,
                factual_replay_row_sha256=evidence.factual_replay_row_sha256,
            )
            for edge in artifact.edges
            for evidence in edge.factual_evidence
        ),
        output_sha256="0" * 64,
    )
    verify_replayable_factual_observations(replay_feed, store=source_store)
    _assert_dag(artifact.edges)
    return TaxonomyRelationExpansionGate(
        artifact_output_sha256=artifact.output_sha256,
        seed_count=artifact.coverage.seed_count,
        accepted_factual_edge_count=artifact.coverage.accepted_factual_edge_count,
        review_derived_edge_count=artifact.coverage.review_derived_edge_count,
    )


def publish_taxonomy_relation_expansion(
    artifact: TaxonomyRelationExpansionArtifact, *, output: Path, store: ObjectStore
) -> TaxonomyRelationExpansionReceipt:
    """Atomically write and immutable-store a verified relation expansion."""
    verify_taxonomy_relation_expansion(artifact, source_store=store)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    write = store.push(
        output,
        ObjectKey(value=f"taxonomy-relation-expansion/sha256/{artifact.output_sha256}.json"),
    )
    if write.sha256 != artifact_sha or write.byte_size != len(payload):
        raise ValueError("object store write does not match relation expansion bytes")
    return TaxonomyRelationExpansionReceipt(
        artifact=write, artifact_sha256=artifact_sha, logical_output_sha256=artifact.output_sha256
    )


def _holdout_value(value: str, modulus: int) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big") % modulus


def _holdout_sets(
    seed_ids: frozenset[str],
    reference_factual_edges: frozenset[tuple[str, str]],
    policy: TaxonomyRelationHoldoutPolicy,
) -> tuple[frozenset[str], frozenset[tuple[str, str]]]:
    """Choose reproducible hidden nodes and edges without inspecting predictions."""
    hidden_nodes = frozenset(
        seed
        for seed in seed_ids
        if _holdout_value(seed, policy.node_modulus) == policy.node_remainder
    )
    hidden_edges = frozenset(
        edge
        for edge in reference_factual_edges
        if _holdout_value(f"{edge[0]}\x00{edge[1]}", policy.edge_modulus) == policy.edge_remainder
        or edge[0] in hidden_nodes
        or edge[1] in hidden_nodes
    )
    return hidden_nodes, hidden_edges


def _project_observation_pair(
    observation: TaxonomyRelationObservation,
    *,
    qid_to_seed: dict[str, str],
    ambiguous_qids: frozenset[str],
    musicbrainz_mappings: dict[str, ExactMusicBrainzGenreQidMapping],
) -> tuple[str, str] | None:
    """Return the exact seed pair for one source row, or ``None`` when it abstains."""
    if observation.source == "wikidata":
        child_qid, parent_qid = observation.child_source_id, observation.parent_source_id
    else:
        child_mapping = musicbrainz_mappings.get(observation.child_source_id)
        parent_mapping = musicbrainz_mappings.get(observation.parent_source_id)
        if child_mapping is None or parent_mapping is None:
            return None
        child_qid, parent_qid = child_mapping.wikidata_qid, parent_mapping.wikidata_qid
    if child_qid in ambiguous_qids or parent_qid in ambiguous_qids:
        return None
    child_seed = qid_to_seed.get(child_qid)
    parent_seed = qid_to_seed.get(parent_qid)
    if child_seed is None or parent_seed is None or child_seed == parent_seed:
        return None
    return child_seed, parent_seed


def split_taxonomy_relation_feed_for_holdout(
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    feed: TaxonomyRelationFeed,
    *,
    reference_factual_edges: frozenset[tuple[str, str]],
    policy: TaxonomyRelationHoldoutPolicy | None = None,
) -> TaxonomyRelationFeed:
    """Remove every exact source row that exposes a deterministically hidden fact.

    This is the anti-leakage boundary.  The returned feed is the *only* feed
    allowed to construct an artifact that will be evaluated against this split.
    Rows without an exact, unique seed projection cannot expose a held-out
    seed relation and remain in the training cache.
    """
    resolved = policy or TaxonomyRelationHoldoutPolicy()
    seed_ids = frozenset(item.source_item_id for item in taxonomy.inferences)
    if any(
        child not in seed_ids or parent not in seed_ids for child, parent in reference_factual_edges
    ):
        raise ValueError("reference factual edges must remain inside the taxonomy seed universe")
    hidden_nodes, hidden_edges = _holdout_sets(seed_ids, reference_factual_edges, resolved)
    qid_to_seed, ambiguous_qids = _exact_seed_qid_map(taxonomy)
    mappings = {item.musicbrainz_genre_id: item for item in feed.musicbrainz_qid_mappings}
    retained = tuple(
        observation
        for observation in feed.observations
        if (
            (
                pair := _project_observation_pair(
                    observation,
                    qid_to_seed=qid_to_seed,
                    ambiguous_qids=ambiguous_qids,
                    musicbrainz_mappings=mappings,
                )
            )
            is None
            or (
                pair not in hidden_edges
                and pair[0] not in hidden_nodes
                and pair[1] not in hidden_nodes
            )
        )
    )
    return build_taxonomy_relation_feed(
        feed.source_custodies, feed.musicbrainz_qid_mappings, retained
    )


def _isolated_from_pairs(seed_ids: frozenset[str], pairs: frozenset[tuple[str, str]]) -> int:
    connected = {seed for pair in pairs for seed in pair}
    return len(seed_ids - connected)


def evaluate_taxonomy_relation_expansion(
    artifact: TaxonomyRelationExpansionArtifact,
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    inputs: TaxonomyRelationEvaluationInputs,
) -> TaxonomyRelationExpansionEvaluation:
    """Evaluate independent predictions against hidden facts and explicit negatives.

    The reference graph determines a training-feed split before construction.
    This function recomputes that split and refuses an artifact whose input
    hash is not the derived training feed.  Unlabelled candidate edges are
    neither true nor false, so precision is unavailable unless a caller
    supplies a defensible negative set.
    """
    verify_taxonomy_relation_expansion(artifact, source_store=inputs.source_store)
    seed_ids = frozenset(item.source_item_id for item in taxonomy.inferences)
    if artifact.taxonomy_output_sha256 != taxonomy.output_sha256:
        raise ValueError("evaluation taxonomy does not match the expansion artifact")
    if artifact.coverage.seed_count != len(seed_ids):
        raise ValueError("evaluation seed IDs do not match artifact seed universe")
    if any(
        child not in seed_ids or parent not in seed_ids
        for child, parent in inputs.reference_factual_edges
    ):
        raise ValueError("reference factual edges must remain inside the seed universe")
    negatives = inputs.defensible_negative_edges or frozenset()
    if inputs.reference_factual_edges & negatives:
        raise ValueError("defensible negatives cannot overlap known factual positives")
    training_feed = split_taxonomy_relation_feed_for_holdout(
        taxonomy,
        inputs.full_relation_feed,
        reference_factual_edges=inputs.reference_factual_edges,
        policy=inputs.holdout_policy,
    )
    if artifact.relation_feed_output_sha256 != training_feed.output_sha256:
        raise ValueError(
            "expansion was not constructed from the deterministic holdout training feed"
        )
    hidden_nodes, hidden_edges = _holdout_sets(
        seed_ids, inputs.reference_factual_edges, inputs.holdout_policy
    )
    baseline = inputs.reference_factual_edges - hidden_edges
    predictions = frozenset(
        (edge.child_seed_id, edge.parent_seed_id)
        for edge in artifact.edges
        if edge.disposition == "accepted_factual"
    )
    recovered = predictions & hidden_edges
    recall = round(len(recovered) / len(hidden_edges), 12) if hidden_edges else None
    if inputs.defensible_negative_edges is None:
        precision: float | None = None
        status: Literal["not_evaluable_without_negatives", "evaluated"] = (
            "not_evaluable_without_negatives"
        )
        evaluated_count = 0
    else:
        evaluated = predictions & (inputs.reference_factual_edges | negatives)
        true_positive = len(evaluated & inputs.reference_factual_edges)
        precision = round(true_positive / len(evaluated), 12) if evaluated else None
        # A supplied label set with no predicted labelled edge has no precision denominator.
        status = "evaluated" if precision is not None else "not_evaluable_without_negatives"
        evaluated_count = len(evaluated)
    baseline_isolated = _isolated_from_pairs(seed_ids, baseline)
    expanded_isolated = _isolated_from_pairs(seed_ids, baseline | predictions)
    return TaxonomyRelationExpansionEvaluation(
        expansion_output_sha256=artifact.output_sha256,
        training_relation_feed_output_sha256=training_feed.output_sha256,
        holdout_policy=inputs.holdout_policy,
        reference_factual_edge_count=len(inputs.reference_factual_edges),
        hidden_node_count=len(hidden_nodes),
        hidden_factual_edge_count=len(hidden_edges),
        recovered_hidden_factual_edge_count=len(recovered),
        recall=recall,
        precision=precision,
        precision_status=status,
        evaluated_prediction_count=evaluated_count,
        baseline_factual_isolated_seed_count=baseline_isolated,
        expanded_factual_isolated_seed_count=expanded_isolated,
        isolated_seed_reduction=baseline_isolated - expanded_isolated,
    )
