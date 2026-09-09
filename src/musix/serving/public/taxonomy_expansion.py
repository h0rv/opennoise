"""Expand the legacy name vocabulary through an audited CC0 taxonomy shell.

This module is deliberately narrower than an artist-membership model.  It
connects retained legacy *names* to public catalog identities only when the
sealed taxonomy artifact resolved an exact canonical or alias match.  Public
catalog hierarchy facts remain facts between catalog nodes.  Compositional and
ambiguous matches are retained as review/navigation links, never facts about
parentage or artist membership.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.common import sha256_file, sha256_hex, sha256_json, write_durable_bytes
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy.seeds.taxonomy import (
    GenreSeedPublicTaxonomyArtifact,
    InferenceStatus,
    SeedTaxonomyInference,
)

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "public-taxonomy-expansion-v1"

type ExpansionEdgeKind = Literal[
    "canonical_catalog_identity",
    "public_catalog_taxonomy_parent",
    "compositional_review_anchor",
    "ambiguous_identity_review_candidate",
]


class PublicTaxonomyExpansionConfig(FrozenModel):
    """Declared laptop bounds for one deterministic expansion."""

    expected_legacy_seed_count: int = Field(default=6291, ge=1, le=20_000)
    minimum_catalog_genres: int = Field(default=1, ge=1, le=50_000)
    max_catalog_genres: int = Field(default=5_000, ge=1, le=50_000)
    max_catalog_hierarchy_edges: int = Field(default=20_000, ge=0, le=100_000)
    include_ambiguous_exact_review_candidates: Literal[True] = True


class ExpansionInputAudit(FrozenModel):
    """Precisely declare the public inputs permitted during construction."""

    taxonomy_artifact_read: Literal[True] = True
    catalog_tables_read: tuple[
        Literal[
            "data_sources",
            "genres",
            "entity_identifiers",
            "identifier_types",
            "genre_hierarchy",
            "entity_provenance",
            "provenance_records",
            "rights_policies",
            "rights_policy_permissions",
        ],
        ...,
    ] = (
        "data_sources",
        "genres",
        "entity_identifiers",
        "identifier_types",
        "genre_hierarchy",
        "entity_provenance",
        "provenance_records",
        "rights_policies",
        "rights_policy_permissions",
    )
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    local_musicbrainz_research_read: Literal[False] = False
    artist_membership_evidence_read: Literal[False] = False
    listenbrainz_edges_read: Literal[False] = False
    audio_or_music_files_read: Literal[False] = False


class ExpansionNode(FrozenModel):
    """A legacy seed or a CC0 public taxonomy node."""

    node_id: str = Field(min_length=1)
    node_kind: Literal["legacy_name_seed", "public_catalog_genre"]
    name: str = Field(min_length=1)
    legacy_source_item_id: str | None = None
    catalog_id: str | None = None
    taxonomy_status: InferenceStatus | None = None

    @model_validator(mode="after")
    def _enforce_node_identity(self) -> ExpansionNode:
        if self.node_kind == "legacy_name_seed":
            if self.legacy_source_item_id is None or self.catalog_id is not None:
                raise ValueError("legacy seed nodes require only a legacy source identity")
            if self.taxonomy_status is None:
                raise ValueError("legacy seed nodes require a taxonomy status")
        elif self.catalog_id is None or self.legacy_source_item_id is not None:
            raise ValueError("catalog nodes require only a public catalog identity")
        return self


class ExpansionEdgeEvidence(FrozenModel):
    """A bounded explanation for a typed public expansion edge."""

    source: Literal["sealed_public_taxonomy", "cc0_public_catalog"]
    taxonomy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_child_id: str | None = None
    catalog_parent_id: str | None = None
    relation_id: str | None = None
    taxonomy_status: InferenceStatus | None = None
    lexical_modifier: str | None = None
    note: str = Field(min_length=1, max_length=500)


class ExpansionEdge(FrozenModel):
    """An identity, public taxonomy, or explicitly non-factual review edge."""

    edge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    kind: ExpansionEdgeKind
    factual_relationship: bool
    review_candidate: bool
    evidence: ExpansionEdgeEvidence

    @model_validator(mode="after")
    def _preserve_fact_review_boundary(self) -> ExpansionEdge:
        factual = self.kind in {"canonical_catalog_identity", "public_catalog_taxonomy_parent"}
        if self.factual_relationship != factual or self.review_candidate == factual:
            raise ValueError("edge kind must preserve the factual/review boundary")
        return self


class ConnectivityCoverage(FrozenModel):
    """Connectivity for one edge-policy projection of the same graph."""

    component_count: int = Field(ge=1)
    isolated_node_count: int = Field(ge=0)
    connected_legacy_seed_count: int = Field(ge=0)
    isolated_legacy_seed_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _partition_legacy_seeds(self) -> ConnectivityCoverage:
        if self.connected_legacy_seed_count + self.isolated_legacy_seed_count < 1:
            raise ValueError("connectivity must account for at least one legacy seed")
        return self


class PublicTaxonomyExpansionCoverage(FrozenModel):
    """Coverage split by factual and review-enabled views of the graph."""

    legacy_seed_node_count: int = Field(ge=1)
    catalog_node_count: int = Field(ge=1)
    canonical_identity_edge_count: int = Field(ge=0)
    catalog_taxonomy_edge_count: int = Field(ge=0)
    compositional_review_edge_count: int = Field(ge=0)
    ambiguous_identity_review_edge_count: int = Field(ge=0)
    exact_identity_legacy_seed_count: int = Field(ge=0)
    compositional_review_legacy_seed_count: int = Field(ge=0)
    ambiguous_review_legacy_seed_count: int = Field(ge=0)
    abstained_legacy_seed_count: int = Field(ge=0)
    factual_only: ConnectivityCoverage
    review_enabled: ConnectivityCoverage
    inferred_artist_membership_count: Literal[0] = 0
    review_links_promoted_to_facts: Literal[0] = 0
    review_links_promoted_to_artist_memberships: Literal[0] = 0

    @model_validator(mode="after")
    def _account_for_every_legacy_seed(self) -> PublicTaxonomyExpansionCoverage:
        accounted = (
            self.exact_identity_legacy_seed_count
            + self.compositional_review_legacy_seed_count
            + self.ambiguous_review_legacy_seed_count
            + self.abstained_legacy_seed_count
        )
        if accounted != self.legacy_seed_node_count:
            raise ValueError("coverage must account for every legacy seed exactly once")
        for projection in (self.factual_only, self.review_enabled):
            if (
                projection.connected_legacy_seed_count + projection.isolated_legacy_seed_count
                != self.legacy_seed_node_count
            ):
                raise ValueError("connectivity must account for every legacy seed")
        return self


class PublicTaxonomyExpansionArtifact(FrozenModel):
    """Replayable graph expansion over a fixed CC0 public catalog snapshot."""

    revision: Literal["public-taxonomy-expansion-v1"] = _REVISION
    taxonomy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: PublicTaxonomyExpansionConfig
    input_audit: ExpansionInputAudit = ExpansionInputAudit()
    nodes: tuple[ExpansionNode, ...] = Field(min_length=1, max_length=50_000)
    edges: tuple[ExpansionEdge, ...]
    coverage: PublicTaxonomyExpansionCoverage
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _complete_and_safe(self) -> PublicTaxonomyExpansionArtifact:
        node_ids = {item.node_id for item in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("every expansion node ID must be unique")
        if any(
            edge.source_node_id not in node_ids or edge.target_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("every edge endpoint must refer to a retained node")
        if len({edge.edge_id for edge in self.edges}) != len(self.edges):
            raise ValueError("every expansion edge ID must be unique")
        legacy = [item for item in self.nodes if item.node_kind == "legacy_name_seed"]
        catalog = [item for item in self.nodes if item.node_kind == "public_catalog_genre"]
        if len(legacy) != self.coverage.legacy_seed_node_count:
            raise ValueError("legacy seed coverage does not match nodes")
        if len(catalog) != self.coverage.catalog_node_count:
            raise ValueError("catalog coverage does not match nodes")
        if any(edge.review_candidate and edge.factual_relationship for edge in self.edges):
            raise ValueError("review links cannot be factual relationships")
        return self


class PublicTaxonomyExpansionGate(FrozenModel):
    """Fail-closed publication decision for a completed expansion artifact."""

    artifact_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_seed_node_count: int = Field(ge=1)
    catalog_node_count: int = Field(ge=1)
    factual_edge_count: int = Field(ge=0)
    review_edge_count: int = Field(ge=0)
    deterministic_replay: Literal[True] = True
    complete_legacy_seed_coverage: Literal[True] = True
    no_review_promotion: Literal[True] = True
    no_artist_membership_inference: Literal[True] = True


class PublicTaxonomyExpansionPublicationReceipt(FrozenModel):
    """Immutable object-store receipt for the public expansion artifact."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate: PublicTaxonomyExpansionGate


class _CatalogNode(FrozenModel):
    """Parsed CC0 catalog identity used only within the builder."""

    catalog_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class _InferenceDecision:
    """Typed policy decision for one sealed taxonomy inference."""

    kind: ExpansionEdgeKind | None
    factual_relationship: bool
    review_candidate: bool
    note: str | None


@dataclass(frozen=True, slots=True)
class _LegacyExpansion:
    """Edges and disjoint coverage sets produced from taxonomy inferences."""

    edges: tuple[ExpansionEdge, ...]
    exact_ids: frozenset[str]
    compositional_ids: frozenset[str]
    ambiguous_ids: frozenset[str]
    abstained_ids: frozenset[str]


def _edge_id(source: str, target: str, kind: str, evidence: ExpansionEdgeEvidence) -> str:
    return sha256_hex(
        json.dumps(
            {
                "source": source,
                "target": target,
                "kind": kind,
                "evidence": evidence.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )


def _catalog_node_id(catalog_id: str) -> str:
    return f"catalog:{catalog_id}"


def _legacy_node_id(source_item_id: str) -> str:
    return f"legacy:{source_item_id}"


def _read_catalog(path: Path) -> tuple[dict[str, _CatalogNode], tuple[tuple[str, str, str], ...]]:
    """Read precisely the CC0 taxonomy shell required by this artifact."""
    with closing(
        sqlite3.connect(f"file:{path.resolve(strict=True).as_posix()}?mode=ro", uri=True)
    ) as db:
        identities = {
            int(row_id): f"wikidata:genre:{value}"
            for row_id, value in db.execute(
                """SELECT identifier.entity_id, identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS kind ON kind.id = identifier.identifier_type_id
                   WHERE kind.type_key = 'wikidata_genre_qid'
                   ORDER BY identifier.entity_id, identifier.normalized_value"""
            )
        }
        catalog = {
            int(row_id): _CatalogNode(
                catalog_id=identities.get(int(row_id), f"public:genre:{row_id}"), name=str(name)
            )
            for row_id, name in db.execute(
                """SELECT genre.id, genre.name
                   FROM genres AS genre
                   WHERE genre.entity_kind = 'genre'
                     AND EXISTS (
                         SELECT 1
                         FROM entity_provenance AS entity_provenance
                         JOIN provenance_records AS provenance
                           ON provenance.id = entity_provenance.provenance_id
                         JOIN data_sources AS source ON source.id = provenance.source_id
                         JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                         JOIN rights_policy_permissions AS permission
                           ON permission.policy_id = policy.id
                         WHERE entity_provenance.entity_id = genre.id
                           AND source.license_name LIKE 'CC0-1.0%'
                           AND policy.local_only = 0
                           AND permission.use_kind = 'export'
                           AND permission.decision = 'allow'
                     )
                   ORDER BY genre.id"""
            )
        }
        by_catalog_id = {item.catalog_id: item for item in catalog.values()}
        if not by_catalog_id:
            raise ValueError("catalog has no row-level CC0 export-permitted genre nodes")
        if len(by_catalog_id) != len(catalog):
            raise ValueError("catalog genre identities must be unique")
        relations = tuple(
            (
                catalog[int(child)].catalog_id,
                catalog[int(parent)].catalog_id,
                str(relation_id),
            )
            for relation_id, child, parent in db.execute(
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
                   ORDER BY hierarchy.child_genre_id, hierarchy.parent_genre_id,
                            hierarchy.relation_id"""
            )
            if int(child) in catalog and int(parent) in catalog and int(child) != int(parent)
        )
    return by_catalog_id, relations


def _connectivity(
    nodes: tuple[ExpansionNode, ...], edges: tuple[ExpansionEdge, ...], *, include_review: bool
) -> ConnectivityCoverage:
    """Measure components without allowing review links into factual-only metrics."""
    selected = tuple(edge for edge in edges if include_review or edge.factual_relationship)
    adjacent: dict[str, set[str]] = {item.node_id: set() for item in nodes}
    for edge in selected:
        adjacent[edge.source_node_id].add(edge.target_node_id)
        adjacent[edge.target_node_id].add(edge.source_node_id)
    seen: set[str] = set()
    components = 0
    for start in sorted(adjacent):
        if start in seen:
            continue
        components += 1
        queue: deque[str] = deque((start,))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(sorted(adjacent[current] - seen))
    legacy_ids = {item.node_id for item in nodes if item.node_kind == "legacy_name_seed"}
    isolated_legacy = sum(not adjacent[node_id] for node_id in legacy_ids)
    return ConnectivityCoverage(
        component_count=components,
        isolated_node_count=sum(not item for item in adjacent.values()),
        connected_legacy_seed_count=len(legacy_ids) - isolated_legacy,
        isolated_legacy_seed_count=isolated_legacy,
    )


def _inference_catalog_ids(inference: SeedTaxonomyInference) -> tuple[str, ...]:
    """Return trusted catalog IDs according to the sealed inference state."""
    if inference.status in {"canonical_exact", "canonical_alias"}:
        return (inference.exact_candidates[0].catalog_id,)
    if inference.status == "anchored_compositional" and inference.anchor is not None:
        return (inference.anchor.catalog_id,)
    if inference.status == "ambiguous_exact":
        return tuple(candidate.catalog_id for candidate in inference.exact_candidates)
    return ()


def _inference_decision(
    inference: SeedTaxonomyInference, config: PublicTaxonomyExpansionConfig
) -> _InferenceDecision:
    """Return the sole predeclared semantic outcome for one taxonomy result."""
    match inference.status:
        case "canonical_exact" | "canonical_alias":
            return _InferenceDecision(
                kind="canonical_catalog_identity",
                factual_relationship=True,
                review_candidate=False,
                note="sealed exact public catalog identity for this retained legacy name",
            )
        case "anchored_compositional":
            return _InferenceDecision(
                kind="compositional_review_anchor",
                factual_relationship=False,
                review_candidate=True,
                note="public suffix anchor for review/navigation only; not parentage or membership",
            )
        case "ambiguous_exact" if config.include_ambiguous_exact_review_candidates:
            return _InferenceDecision(
                kind="ambiguous_identity_review_candidate",
                factual_relationship=False,
                review_candidate=True,
                note=(
                    "multiple exact public catalog candidates retained for review; "
                    "no identity claim"
                ),
            )
        case _:
            return _InferenceDecision(
                kind=None,
                factual_relationship=False,
                review_candidate=False,
                note=None,
            )


def _build_legacy_edges(
    taxonomy: GenreSeedPublicTaxonomyArtifact,
    catalog: dict[str, _CatalogNode],
    *,
    taxonomy_hash: str,
    catalog_hash: str,
    config: PublicTaxonomyExpansionConfig,
) -> _LegacyExpansion:
    """Create only identity facts and non-factual review links for legacy seeds."""
    edge_values: list[ExpansionEdge] = []
    exact_ids: set[str] = set()
    compositional_ids: set[str] = set()
    ambiguous_ids: set[str] = set()
    abstained_ids: set[str] = set()
    for inference in taxonomy.inferences:
        decision = _inference_decision(inference, config)
        catalog_ids = _inference_catalog_ids(inference)
        if decision.kind is None or not catalog_ids:
            abstained_ids.add(inference.source_item_id)
            continue
        if any(catalog_id not in catalog for catalog_id in catalog_ids):
            raise ValueError(
                "taxonomy artifact refers to a catalog identity absent from its snapshot"
            )
        match decision.kind:
            case "canonical_catalog_identity":
                exact_ids.add(inference.source_item_id)
            case "compositional_review_anchor":
                compositional_ids.add(inference.source_item_id)
            case "ambiguous_identity_review_candidate":
                ambiguous_ids.add(inference.source_item_id)
            case "public_catalog_taxonomy_parent":
                raise AssertionError("legacy inference cannot create a catalog hierarchy edge")
        source = _legacy_node_id(inference.source_item_id)
        for catalog_id in catalog_ids:
            evidence = ExpansionEdgeEvidence(
                source="sealed_public_taxonomy",
                taxonomy_artifact_sha256=taxonomy_hash,
                public_catalog_sha256=catalog_hash,
                catalog_parent_id=catalog_id,
                taxonomy_status=inference.status,
                lexical_modifier=inference.lexical_modifier,
                note=decision.note or "",
            )
            target = _catalog_node_id(catalog_id)
            edge_values.append(
                ExpansionEdge(
                    edge_id=_edge_id(source, target, decision.kind, evidence),
                    source_node_id=source,
                    target_node_id=target,
                    kind=decision.kind,
                    factual_relationship=decision.factual_relationship,
                    review_candidate=decision.review_candidate,
                    evidence=evidence,
                )
            )
    return _LegacyExpansion(
        edges=tuple(edge_values),
        exact_ids=frozenset(exact_ids),
        compositional_ids=frozenset(compositional_ids),
        ambiguous_ids=frozenset(ambiguous_ids),
        abstained_ids=frozenset(abstained_ids),
    )


def _build_catalog_edges(
    relations: tuple[tuple[str, str, str], ...], *, taxonomy_hash: str, catalog_hash: str
) -> tuple[ExpansionEdge, ...]:
    """Retain only directly permitted CC0 hierarchy facts between catalog nodes."""
    result: list[ExpansionEdge] = []
    for child_catalog_id, parent_catalog_id, relation_id in relations:
        source = _catalog_node_id(child_catalog_id)
        target = _catalog_node_id(parent_catalog_id)
        evidence = ExpansionEdgeEvidence(
            source="cc0_public_catalog",
            taxonomy_artifact_sha256=taxonomy_hash,
            public_catalog_sha256=catalog_hash,
            catalog_child_id=child_catalog_id,
            catalog_parent_id=parent_catalog_id,
            relation_id=relation_id,
            note="direct CC0 public taxonomy relation between public catalog genre identities",
        )
        result.append(
            ExpansionEdge(
                edge_id=_edge_id(source, target, "public_catalog_taxonomy_parent", evidence),
                source_node_id=source,
                target_node_id=target,
                kind="public_catalog_taxonomy_parent",
                factual_relationship=True,
                review_candidate=False,
                evidence=evidence,
            )
        )
    return tuple(result)


def build_public_taxonomy_expansion(
    taxonomy_artifact_path: Path,
    public_catalog_database: Path,
    *,
    config: PublicTaxonomyExpansionConfig | None = None,
) -> PublicTaxonomyExpansionArtifact:
    """Build a complete legacy-name graph through a public CC0 taxonomy shell."""
    config = config or PublicTaxonomyExpansionConfig()
    taxonomy_bytes = taxonomy_artifact_path.read_bytes()
    taxonomy = GenreSeedPublicTaxonomyArtifact.model_validate_json(taxonomy_bytes)
    if len(taxonomy.seed_input.names) != config.expected_legacy_seed_count:
        raise ValueError(
            "expected "
            f"{config.expected_legacy_seed_count} legacy seeds, "
            f"found {len(taxonomy.seed_input.names)}"
        )
    catalog_hash = sha256_file(public_catalog_database)[0]
    if catalog_hash != taxonomy.public_catalog.database_sha256:
        raise ValueError("taxonomy artifact public catalog hash does not match expansion input")
    catalog, relations = _read_catalog(public_catalog_database)
    if not config.minimum_catalog_genres <= len(catalog) <= config.max_catalog_genres:
        raise ValueError("catalog genre count exceeds declared expansion bound")
    if len(relations) > config.max_catalog_hierarchy_edges:
        raise ValueError("catalog taxonomy edge count exceeds declared expansion bound")
    inference_by_id = {item.source_item_id: item for item in taxonomy.inferences}
    nodes = tuple(
        sorted(
            (
                *(
                    ExpansionNode(
                        node_id=_legacy_node_id(seed.source_item_id),
                        node_kind="legacy_name_seed",
                        name=seed.name,
                        legacy_source_item_id=seed.source_item_id,
                        taxonomy_status=inference_by_id[seed.source_item_id].status,
                    )
                    for seed in taxonomy.seed_input.names
                ),
                *(
                    ExpansionNode(
                        node_id=_catalog_node_id(catalog_id),
                        node_kind="public_catalog_genre",
                        name=node.name,
                        catalog_id=catalog_id,
                    )
                    for catalog_id, node in catalog.items()
                ),
            ),
            key=lambda item: item.node_id,
        )
    )
    taxonomy_hash = sha256_hex(taxonomy_bytes)
    legacy_expansion = _build_legacy_edges(
        taxonomy,
        catalog,
        taxonomy_hash=taxonomy_hash,
        catalog_hash=catalog_hash,
        config=config,
    )
    edges = tuple(
        sorted(
            (
                *legacy_expansion.edges,
                *_build_catalog_edges(
                    relations, taxonomy_hash=taxonomy_hash, catalog_hash=catalog_hash
                ),
            ),
            key=lambda item: item.edge_id,
        )
    )
    coverage = PublicTaxonomyExpansionCoverage(
        legacy_seed_node_count=len(taxonomy.seed_input.names),
        catalog_node_count=len(catalog),
        canonical_identity_edge_count=sum(
            edge.kind == "canonical_catalog_identity" for edge in edges
        ),
        catalog_taxonomy_edge_count=sum(
            edge.kind == "public_catalog_taxonomy_parent" for edge in edges
        ),
        compositional_review_edge_count=sum(
            edge.kind == "compositional_review_anchor" for edge in edges
        ),
        ambiguous_identity_review_edge_count=sum(
            edge.kind == "ambiguous_identity_review_candidate" for edge in edges
        ),
        exact_identity_legacy_seed_count=len(legacy_expansion.exact_ids),
        compositional_review_legacy_seed_count=len(legacy_expansion.compositional_ids),
        ambiguous_review_legacy_seed_count=len(legacy_expansion.ambiguous_ids),
        abstained_legacy_seed_count=len(legacy_expansion.abstained_ids),
        factual_only=_connectivity(nodes, edges, include_review=False),
        review_enabled=_connectivity(nodes, edges, include_review=True),
    )
    preliminary = PublicTaxonomyExpansionArtifact(
        taxonomy_artifact_sha256=taxonomy_hash,
        taxonomy_logical_output_sha256=taxonomy.output_sha256,
        public_catalog_sha256=catalog_hash,
        config=config,
        nodes=nodes,
        edges=edges,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": sha256_json(
                preliminary.model_dump(mode="json", exclude={"output_sha256"})
            )
        }
    )


def verify_public_taxonomy_expansion(
    artifact: PublicTaxonomyExpansionArtifact,
) -> PublicTaxonomyExpansionGate:
    """Fail closed unless the graph is complete, deterministic, and policy-safe."""
    replayed = sha256_json(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    if artifact.output_sha256 != replayed:
        raise ValueError("public taxonomy expansion logical hash does not replay")
    if artifact.coverage.review_links_promoted_to_facts:
        raise ValueError("review links must not become factual relationships")
    if artifact.coverage.review_links_promoted_to_artist_memberships:
        raise ValueError("review links must not become artist memberships")
    if artifact.coverage.inferred_artist_membership_count:
        raise ValueError("taxonomy expansion must not infer artist memberships")
    return PublicTaxonomyExpansionGate(
        artifact_output_sha256=artifact.output_sha256,
        legacy_seed_node_count=artifact.coverage.legacy_seed_node_count,
        catalog_node_count=artifact.coverage.catalog_node_count,
        factual_edge_count=sum(edge.factual_relationship for edge in artifact.edges),
        review_edge_count=sum(edge.review_candidate for edge in artifact.edges),
    )


def write_public_taxonomy_expansion(
    artifact: PublicTaxonomyExpansionArtifact, output_path: Path
) -> tuple[str, int]:
    """Atomically write an already-gated artifact and return its byte identity."""
    verify_public_taxonomy_expansion(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(output_path, payload)
    return sha256_hex(payload), len(payload)


def publish_public_taxonomy_expansion(
    artifact: PublicTaxonomyExpansionArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[PublicTaxonomyExpansionPublicationReceipt, ObjectWrite]:
    """Publish one verified artifact through the configured object-store adapter."""
    gate = verify_public_taxonomy_expansion(artifact)
    artifact_sha256, artifact_size = write_public_taxonomy_expansion(artifact, output_path)
    key = ObjectKey(
        value=(f"public-taxonomy-expansion/{artifact.output_sha256}/{artifact_sha256}.json")
    )
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha256 or write.byte_size != artifact_size:
        raise ValueError("object store write does not match public taxonomy expansion")
    return PublicTaxonomyExpansionPublicationReceipt(
        artifact_sha256=artifact_sha256,
        artifact_byte_size=artifact_size,
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), write
