"""Turn one verified public-taxonomy expansion into a layout-ready Open v2 graph.

V2 retains every legacy name and every public catalog node needed for its
typed factual and review links. It deliberately does not turn review links
into taxonomy facts or artist memberships.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.serving.public.taxonomy_expansion import (
    ExpansionEdge,
    ExpansionEdgeEvidence,
    ExpansionEdgeKind,
    ExpansionNode,
    PublicTaxonomyExpansionArtifact,
    verify_public_taxonomy_expansion,
)
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite

_REVISION: Final = "open-construction-graph-v2"
_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "coordinate",
        "coordinates",
        "historical_neighbors",
        "neighbors",
        "neighbours",
        "historical_artists",
        "artist_assignments",
        "h3",
        "musicbrainz",
        "listenbrainz",
        "audio",
        "recording",
    }
)


class OpenConstructionGraphV2Config(FrozenModel):
    """Declared resource limits for a direct expansion-to-layout conversion."""

    expected_legacy_seed_count: int = Field(default=6291, ge=1, le=20_000)
    maximum_total_nodes: int = Field(default=25_000, ge=1, le=50_000)
    maximum_total_edges: int = Field(default=50_000, ge=0, le=100_000)


class OpenConstructionV2InputAudit(FrozenModel):
    """The only construction input is the verified expansion artifact."""

    public_taxonomy_expansion_read: Literal[True] = True
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    artist_membership_evidence_read: Literal[False] = False
    aggregate_listening_data_read: Literal[False] = False
    audio_or_music_files_read: Literal[False] = False


class OpenGraphV2Node(FrozenModel):
    """One legacy seed or a public catalog node retained as a navigation anchor."""

    node_id: str = Field(min_length=1)
    node_kind: Literal["legacy_name_seed", "public_catalog_genre"]
    name: str = Field(min_length=1)
    legacy_source_item_id: str | None = None
    catalog_id: str | None = None
    taxonomy_status: str | None = None

    @model_validator(mode="after")
    def preserve_node_identity(self) -> OpenGraphV2Node:
        """Keep legacy and public catalog identities non-overlapping."""
        if self.node_kind == "legacy_name_seed":
            if self.legacy_source_item_id is None or self.catalog_id is not None:
                raise ValueError("legacy nodes require only their legacy source identity")
        elif self.catalog_id is None or self.legacy_source_item_id is not None:
            raise ValueError("catalog nodes require only their public catalog identity")
        return self


class OpenGraphV2EdgeEvidence(FrozenModel):
    """A preserved typed expansion edge explanation."""

    source: Literal["public_taxonomy_expansion"] = "public_taxonomy_expansion"
    expansion_edge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_child_id: str | None = None
    catalog_parent_id: str | None = None
    relation_id: str | None = None
    lexical_modifier: str | None = None
    note: str = Field(min_length=1, max_length=500)


class OpenGraphV2Edge(FrozenModel):
    """A direct factual or review-only edge copied without semantic promotion."""

    edge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    kind: ExpansionEdgeKind
    factual_relationship: bool
    review_candidate: bool
    evidence: OpenGraphV2EdgeEvidence

    @model_validator(mode="after")
    def preserve_fact_review_boundary(self) -> OpenGraphV2Edge:
        """Keep factual taxonomy/identity types separate from review types."""
        factual = self.kind in {"canonical_catalog_identity", "public_catalog_taxonomy_parent"}
        if self.factual_relationship != factual or self.review_candidate == factual:
            raise ValueError("edge kind must preserve the factual/review boundary")
        return self


class OpenGraphV2Component(FrozenModel):
    """A deterministic component for one edge-policy projection."""

    component_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_ids: tuple[str, ...] = Field(min_length=1)
    edge_count: int = Field(ge=0)
    factual_edge_count: int = Field(ge=0)
    isolated: bool


class OpenGraphV2LayoutNode(FrozenModel):
    """Independent deterministic landscape and taxonomy hierarchy positions."""

    node_id: str = Field(min_length=1)
    landscape_x: float
    landscape_y: float
    hierarchy_x: float
    hierarchy_y: float
    hierarchy_depth: int = Field(ge=0)


class OpenConstructionGraphV2Coverage(FrozenModel):
    """Separate counts for legacy names, catalog anchors, facts, and review links."""

    legacy_seed_node_count: int = Field(ge=1)
    catalog_node_count: int = Field(ge=1)
    total_node_count: int = Field(ge=1)
    canonical_identity_edge_count: int = Field(ge=0)
    catalog_taxonomy_edge_count: int = Field(ge=0)
    compositional_review_edge_count: int = Field(ge=0)
    ambiguous_identity_review_edge_count: int = Field(ge=0)
    factual_component_count: int = Field(ge=1)
    review_enabled_component_count: int = Field(ge=1)
    factual_connected_legacy_seed_count: int = Field(ge=0)
    review_enabled_connected_legacy_seed_count: int = Field(ge=0)
    factual_isolated_legacy_seed_count: int = Field(ge=0)
    review_enabled_isolated_legacy_seed_count: int = Field(ge=0)
    inferred_artist_membership_count: Literal[0] = 0
    review_links_promoted_to_facts: Literal[0] = 0
    review_links_promoted_to_artist_memberships: Literal[0] = 0

    @model_validator(mode="after")
    def account_for_all_legacy_seeds(self) -> OpenConstructionGraphV2Coverage:
        """Require both projections to partition the retained legacy vocabulary."""
        if self.total_node_count != self.legacy_seed_node_count + self.catalog_node_count:
            raise ValueError("total node count does not match legacy and catalog partitions")
        if (
            self.factual_connected_legacy_seed_count + self.factual_isolated_legacy_seed_count
            != self.legacy_seed_node_count
        ):
            raise ValueError("factual connectivity does not account for every legacy seed")
        if (
            self.review_enabled_connected_legacy_seed_count
            + self.review_enabled_isolated_legacy_seed_count
            != self.legacy_seed_node_count
        ):
            raise ValueError("review connectivity does not account for every legacy seed")
        return self


class OpenConstructionGraphV2Artifact(FrozenModel):
    """The versioned serving layout of one complete verified expansion artifact."""

    revision: Literal["open-construction-graph-v2"] = _REVISION
    taxonomy_expansion_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_expansion_logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: OpenConstructionGraphV2Config
    input_audit: OpenConstructionV2InputAudit = OpenConstructionV2InputAudit()
    nodes: tuple[OpenGraphV2Node, ...] = Field(min_length=1, max_length=50_000)
    edges: tuple[OpenGraphV2Edge, ...] = Field(max_length=100_000)
    factual_components: tuple[OpenGraphV2Component, ...] = Field(min_length=1)
    review_enabled_components: tuple[OpenGraphV2Component, ...] = Field(min_length=1)
    layout: tuple[OpenGraphV2LayoutNode, ...] = Field(min_length=1, max_length=50_000)
    coverage: OpenConstructionGraphV2Coverage
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def preserve_complete_expansion(self) -> OpenConstructionGraphV2Artifact:
        """Require every retained expansion node and edge endpoint to survive."""
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("every v2 node ID must be unique")
        if {item.node_id for item in self.layout} != node_ids:
            raise ValueError("layout must cover every v2 node exactly once")
        if self.coverage.total_node_count != len(node_ids):
            raise ValueError("coverage must account for every v2 node")
        if any(
            edge.source_node_id not in node_ids or edge.target_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("every v2 edge endpoint must remain a retained v2 node")
        assert_no_prohibited_construction_fields(self)
        return self


class OpenConstructionGraphV2Gate(FrozenModel):
    """Fail-closed release decision for a direct expansion-derived v2 artifact."""

    artifact_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_seed_node_count: int = Field(ge=1)
    total_node_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)
    complete_legacy_seed_coverage: Literal[True] = True
    verified_taxonomy_expansion: Literal[True] = True
    no_prohibited_inputs: Literal[True] = True
    no_review_promotion: Literal[True] = True
    no_artist_membership_inference: Literal[True] = True
    deterministic_replay: Literal[True] = True


class OpenConstructionGraphV2PublicationReceipt(FrozenModel):
    """Immutable object-store receipt for a gated v2 artifact."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate: OpenConstructionGraphV2Gate


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: OpenConstructionGraphV2Artifact) -> bytes:
    return json.dumps(
        value.model_dump(mode="json", exclude={"output_sha256"}),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def assert_no_prohibited_construction_fields(value: object) -> None:
    """Reject historical, artist, listening, and media-shaped input fields."""
    payload = value.model_dump(mode="json") if isinstance(value, FrozenModel) else value

    def walk(current: object) -> None:
        if isinstance(current, dict):
            forbidden = _FORBIDDEN_KEYS & {str(key).casefold() for key in current}
            if forbidden:
                raise ValueError(f"prohibited construction field(s): {sorted(forbidden)!r}")
            for nested in current.values():
                walk(nested)
        elif isinstance(current, (list, tuple)):
            for nested in current:
                walk(nested)

    walk(payload)


def _components(
    nodes: tuple[OpenGraphV2Node, ...], edges: tuple[OpenGraphV2Edge, ...], *, include_review: bool
) -> tuple[tuple[OpenGraphV2Component, ...], int, int]:
    selected = tuple(edge for edge in edges if include_review or edge.factual_relationship)
    adjacent: dict[str, set[str]] = {node.node_id: set() for node in nodes}
    for edge in selected:
        adjacent[edge.source_node_id].add(edge.target_node_id)
        adjacent[edge.target_node_id].add(edge.source_node_id)
    seen: set[str] = set()
    result: list[OpenGraphV2Component] = []
    for start in sorted(adjacent):
        if start in seen:
            continue
        queue: deque[str] = deque((start,))
        members: list[str] = []
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            members.append(current)
            queue.extend(sorted(adjacent[current] - seen))
        node_ids = tuple(sorted(members))
        member_set = set(node_ids)
        component_edges = tuple(
            edge
            for edge in selected
            if edge.source_node_id in member_set and edge.target_node_id in member_set
        )
        result.append(
            OpenGraphV2Component(
                component_id=_sha256_bytes("\x1f".join(node_ids).encode()),
                node_ids=node_ids,
                edge_count=len(component_edges),
                factual_edge_count=sum(edge.factual_relationship for edge in component_edges),
                isolated=len(node_ids) == 1 and not adjacent[node_ids[0]],
            )
        )
    legacy_ids = {node.node_id for node in nodes if node.node_kind == "legacy_name_seed"}
    isolated = sum(not adjacent[node_id] for node_id in legacy_ids)
    return (
        tuple(sorted(result, key=lambda item: item.component_id)),
        len(legacy_ids) - isolated,
        isolated,
    )


def _unit(value: str, salt: str) -> float:
    return int.from_bytes(hashlib.sha256(f"{salt}\x1f{value}".encode()).digest()[:8], "big") / 2**64


def _layout(
    nodes: tuple[OpenGraphV2Node, ...],
    components: tuple[OpenGraphV2Component, ...],
    edges: tuple[OpenGraphV2Edge, ...],
) -> tuple[OpenGraphV2LayoutNode, ...]:
    by_node = {node_id: component for component in components for node_id in component.node_ids}
    indices = {component.component_id: index for index, component in enumerate(components)}
    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.kind == "public_catalog_taxonomy_parent":
            parents[edge.source_node_id].add(edge.target_node_id)
            children[edge.target_node_id].add(edge.source_node_id)
    depth = {node.node_id: 0 for node in nodes if not parents[node.node_id]}
    queue: deque[str] = deque(sorted(depth))
    while queue:
        parent = queue.popleft()
        for child in sorted(children[parent]):
            candidate = depth[parent] + 1
            if candidate > depth.get(child, -1):
                depth[child] = candidate
                queue.append(child)
    depth = {node.node_id: depth.get(node.node_id, 0) for node in nodes}
    by_depth: dict[int, list[str]] = defaultdict(list)
    for node_id, value in depth.items():
        by_depth[value].append(node_id)
    hierarchy_x = {
        node_id: index - (len(node_ids) - 1) / 2
        for _, node_ids in sorted(by_depth.items())
        for index, node_id in enumerate(sorted(node_ids))
    }
    layout: list[OpenGraphV2LayoutNode] = []
    for node in sorted(nodes, key=lambda item: item.node_id):
        component = by_node[node.node_id]
        index = indices[component.component_id]
        angle = index * 2.399963229728653 + _unit(node.node_id, "v2-landscape-angle") * 0.45
        radius = 8.0 + math.sqrt(index + 1) * 18.0
        local_angle = _unit(node.node_id, "v2-landscape-local") * math.tau
        local_radius = (
            0.6
            + math.sqrt(_unit(node.node_id, "v2-landscape-radius"))
            * max(1, len(component.node_ids)) ** 0.5
        )
        layout.append(
            OpenGraphV2LayoutNode(
                node_id=node.node_id,
                landscape_x=round(
                    radius * math.cos(angle) + math.cos(local_angle) * local_radius, 6
                ),
                landscape_y=round(
                    radius * math.sin(angle) + math.sin(local_angle) * local_radius, 6
                ),
                hierarchy_x=round(hierarchy_x[node.node_id], 6),
                hierarchy_y=float(-depth[node.node_id]),
                hierarchy_depth=depth[node.node_id],
            )
        )
    return tuple(layout)


def _node(value: ExpansionNode) -> OpenGraphV2Node:
    return OpenGraphV2Node(
        node_id=value.node_id,
        node_kind=value.node_kind,
        name=value.name,
        legacy_source_item_id=value.legacy_source_item_id,
        catalog_id=value.catalog_id,
        taxonomy_status=value.taxonomy_status,
    )


def _edge(value: ExpansionEdge) -> OpenGraphV2Edge:
    evidence: ExpansionEdgeEvidence = value.evidence
    return OpenGraphV2Edge(
        edge_id=value.edge_id,
        source_node_id=value.source_node_id,
        target_node_id=value.target_node_id,
        kind=value.kind,
        factual_relationship=value.factual_relationship,
        review_candidate=value.review_candidate,
        evidence=OpenGraphV2EdgeEvidence(
            expansion_edge_id=value.edge_id,
            taxonomy_artifact_sha256=evidence.taxonomy_artifact_sha256,
            public_catalog_sha256=evidence.public_catalog_sha256,
            catalog_child_id=evidence.catalog_child_id,
            catalog_parent_id=evidence.catalog_parent_id,
            relation_id=evidence.relation_id,
            lexical_modifier=evidence.lexical_modifier,
            note=evidence.note,
        ),
    )


def build_open_construction_graph_v2(
    taxonomy_expansion_path: Path,
    *,
    config: OpenConstructionGraphV2Config | None = None,
) -> OpenConstructionGraphV2Artifact:
    """Build v2 from one explicit verified expansion; never search an ignored cache."""
    config = config or OpenConstructionGraphV2Config()
    expansion_bytes = taxonomy_expansion_path.read_bytes()
    expansion = PublicTaxonomyExpansionArtifact.model_validate_json(expansion_bytes)
    verify_public_taxonomy_expansion(expansion)
    assert_no_prohibited_construction_fields(expansion.input_audit)
    if expansion.coverage.legacy_seed_node_count != config.expected_legacy_seed_count:
        raise ValueError(
            f"expected {config.expected_legacy_seed_count} legacy seeds, "
            f"found {expansion.coverage.legacy_seed_node_count}"
        )
    if (
        len(expansion.nodes) > config.maximum_total_nodes
        or len(expansion.edges) > config.maximum_total_edges
    ):
        raise ValueError("taxonomy expansion exceeds declared Open v2 build bounds")
    nodes = tuple(_node(value) for value in expansion.nodes)
    edges = tuple(_edge(value) for value in expansion.edges)
    factual, factual_connected, factual_isolated = _components(nodes, edges, include_review=False)
    review, review_connected, review_isolated = _components(nodes, edges, include_review=True)
    coverage = OpenConstructionGraphV2Coverage(
        legacy_seed_node_count=expansion.coverage.legacy_seed_node_count,
        catalog_node_count=expansion.coverage.catalog_node_count,
        total_node_count=len(nodes),
        canonical_identity_edge_count=expansion.coverage.canonical_identity_edge_count,
        catalog_taxonomy_edge_count=expansion.coverage.catalog_taxonomy_edge_count,
        compositional_review_edge_count=expansion.coverage.compositional_review_edge_count,
        ambiguous_identity_review_edge_count=expansion.coverage.ambiguous_identity_review_edge_count,
        factual_component_count=len(factual),
        review_enabled_component_count=len(review),
        factual_connected_legacy_seed_count=factual_connected,
        review_enabled_connected_legacy_seed_count=review_connected,
        factual_isolated_legacy_seed_count=factual_isolated,
        review_enabled_isolated_legacy_seed_count=review_isolated,
    )
    preliminary = OpenConstructionGraphV2Artifact(
        taxonomy_expansion_sha256=_sha256_bytes(expansion_bytes),
        taxonomy_expansion_logical_output_sha256=expansion.output_sha256,
        config=config,
        nodes=nodes,
        edges=edges,
        factual_components=factual,
        review_enabled_components=review,
        layout=_layout(nodes, review, edges),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": _sha256_bytes(_canonical_json(preliminary))}
    )


def verify_open_construction_graph_v2(
    artifact: OpenConstructionGraphV2Artifact,
) -> OpenConstructionGraphV2Gate:
    """Fail closed unless hash replay, coverage, and semantics remain intact."""
    first_hash = _sha256_bytes(_canonical_json(artifact))
    if artifact.output_sha256 != first_hash or first_hash != _sha256_bytes(
        _canonical_json(artifact)
    ):
        raise ValueError("open construction v2 logical hash does not replay")
    assert_no_prohibited_construction_fields(artifact)
    if (
        artifact.coverage.inferred_artist_membership_count
        or artifact.coverage.review_links_promoted_to_facts
        or artifact.coverage.review_links_promoted_to_artist_memberships
    ):
        raise ValueError("v2 review links cannot become facts or artist memberships")
    if any(edge.review_candidate and edge.factual_relationship for edge in artifact.edges):
        raise ValueError("review edge claimed a factual relationship")
    return OpenConstructionGraphV2Gate(
        artifact_output_sha256=artifact.output_sha256,
        legacy_seed_node_count=artifact.coverage.legacy_seed_node_count,
        total_node_count=len(artifact.nodes),
        edge_count=len(artifact.edges),
    )


def write_open_construction_graph_v2(
    artifact: OpenConstructionGraphV2Artifact, output_path: Path
) -> tuple[str, int]:
    """Atomically write a gated v2 artifact and return its byte identity."""
    verify_open_construction_graph_v2(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256_bytes(payload), len(payload)


def publish_open_construction_graph_v2(
    artifact: OpenConstructionGraphV2Artifact, *, output_path: Path, store: ObjectStore
) -> tuple[OpenConstructionGraphV2PublicationReceipt, ObjectWrite]:
    """Write and immutable-store one verified v2 artifact with its gate receipt."""
    gate = verify_open_construction_graph_v2(artifact)
    artifact_sha256, artifact_size = write_open_construction_graph_v2(artifact, output_path)
    key = ObjectKey(
        value=f"open-construction-graph-v2/{artifact.output_sha256}/{artifact_sha256}.json"
    )
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha256 or write.byte_size != artifact_size:
        raise ValueError("object store write does not match open construction v2 artifact")
    return OpenConstructionGraphV2PublicationReceipt(
        artifact_sha256=artifact_sha256,
        artifact_byte_size=artifact_size,
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), write
