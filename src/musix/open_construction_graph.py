"""Build and publish a bounded public-only graph for the legacy name vocabulary.

The construction boundary is deliberately small: the name-only seed projection,
the typed public taxonomy-anchor artifact, and four public catalog tables.  It
does not open artist evidence, historical maps, coordinates, H3, neighbours, or
MusicBrainz research artifacts.  Lexical anchors are useful navigation/review
hints, but are explicitly not memberships or hierarchy claims.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.common import sha256_file, sha256_hex, sha256_json, write_durable_bytes
from musix.taxonomy.seeds.genre_seed_taxonomy import GenreSeedPublicTaxonomyArtifact, SeedTaxonomyInference
from musix.taxonomy.seeds.genre_seed_universe import SeedInput, load_seed_input
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "open-construction-graph-v1"
_GENERIC_TOKENS: Final[frozenset[str]] = frozenset(
    {"genre", "genres", "music", "musical", "sound", "style", "styles"}
)
_FORBIDDEN_CONSTRUCTION_KEYS: Final[frozenset[str]] = frozenset(
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
    }
)


class OpenConstructionGraphConfig(FrozenModel):
    """Explicit confidence and anti-hub limits for one deterministic build."""

    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    max_review_anchor_degree: int = Field(default=24, ge=1, le=128)
    factual_taxonomy_confidence: float = Field(default=0.98, ge=0.0, le=1.0)
    review_anchor_confidence: float = Field(default=0.62, ge=0.0, le=1.0)


class ConstructionInputAudit(FrozenModel):
    """The only fields/tables opened during construction, for reproducibility."""

    seed_fields_read: tuple[
        Literal["source_id", "content_sha256", "source_item_id", "external_id", "name"], ...
    ] = (
        "source_id",
        "content_sha256",
        "source_item_id",
        "external_id",
        "name",
    )
    public_catalog_tables_read: tuple[
        Literal[
            "data_sources",
            "genres",
            "entity_names",
            "entity_identifiers",
            "identifier_types",
            "genre_hierarchy",
        ],
        ...,
    ] = (
        "data_sources",
        "genres",
        "entity_names",
        "entity_identifiers",
        "identifier_types",
        "genre_hierarchy",
    )
    historical_coordinates_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    artist_assignments_read: Literal[False] = False
    h3_read: Literal[False] = False
    musicbrainz_supplementary_genres_read: Literal[False] = False


class OpenGraphNode(FrozenModel):
    """One retained seed, including a node for an explicit abstention."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    taxonomy_status: str = Field(min_length=1)
    public_catalog_id: str | None = None
    review_anchor_catalog_id: str | None = None


class OpenGraphEdgeEvidence(FrozenModel):
    """A bounded, human-readable explanation for one edge."""

    source: Literal["public_catalog_taxonomy", "public_taxonomy_anchor"]
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_child_id: str | None = None
    catalog_parent_id: str | None = None
    relation_id: str | None = None
    lexical_modifier: str | None = None
    note: str = Field(min_length=1, max_length=500)


class OpenGraphEdge(FrozenModel):
    """An explainable taxonomy fact or an explicitly non-factual review link."""

    edge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_item_id: str = Field(min_length=1)
    target_item_id: str = Field(min_length=1)
    kind: Literal["public_taxonomy_parent", "lexical_review_anchor"]
    confidence: float = Field(ge=0.0, le=1.0)
    factual_relationship: bool
    review_candidate: bool
    evidence: OpenGraphEdgeEvidence

    @model_validator(mode="after")
    def _preserve_review_boundary(self) -> OpenGraphEdge:
        factual = self.kind == "public_taxonomy_parent"
        if self.factual_relationship != factual or self.review_candidate == factual:
            raise ValueError("edge kind must preserve the factual/review boundary")
        return self


class OpenGraphComponent(FrozenModel):
    """A deterministic connected component over factual and review links."""

    component_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_ids: tuple[str, ...] = Field(min_length=1)
    edge_count: int = Field(ge=0)
    factual_edge_count: int = Field(ge=0)
    isolated: bool


class OpenGraphLayoutNode(FrozenModel):
    """Independent deterministic landscape and hierarchy positions for one seed."""

    source_item_id: str = Field(min_length=1)
    landscape_x: float
    landscape_y: float
    hierarchy_x: float
    hierarchy_y: float
    hierarchy_depth: int = Field(ge=0)


class OpenGraphCoverage(FrozenModel):
    """Coverage and abstention facts; review coverage is not membership coverage."""

    seed_count: int = Field(ge=1)
    node_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)
    factual_taxonomy_edge_count: int = Field(ge=0)
    lexical_review_edge_count: int = Field(ge=0)
    connected_component_count: int = Field(ge=1)
    isolated_node_count: int = Field(ge=0)
    factual_hierarchy_node_count: int = Field(ge=0)
    review_anchored_node_count: int = Field(ge=0)
    abstained_node_count: int = Field(ge=0)
    ambiguous_node_count: int = Field(ge=0)
    generic_token_rejection_count: int = Field(ge=0)
    review_hub_rejection_count: int = Field(ge=0)
    inferred_membership_count: Literal[0] = 0
    review_candidates_promoted_to_memberships: Literal[0] = 0


class OpenConstructionGraphArtifact(FrozenModel):
    """Complete replayable public graph without historical or artist inputs."""

    revision: Literal["open-construction-graph-v1"] = _REVISION
    seed_input: SeedInput
    taxonomy_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: OpenConstructionGraphConfig
    input_audit: ConstructionInputAudit = ConstructionInputAudit()
    nodes: tuple[OpenGraphNode, ...] = Field(min_length=1, max_length=20_000)
    edges: tuple[OpenGraphEdge, ...] = ()
    components: tuple[OpenGraphComponent, ...] = Field(min_length=1)
    layout: tuple[OpenGraphLayoutNode, ...] = Field(min_length=1, max_length=20_000)
    coverage: OpenGraphCoverage
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _complete_and_bounded(self) -> OpenConstructionGraphArtifact:
        seed_ids = {item.source_item_id for item in self.seed_input.names}
        if {item.source_item_id for item in self.nodes} != seed_ids:
            raise ValueError("every seed must remain exactly one graph node")
        if {item.source_item_id for item in self.layout} != seed_ids:
            raise ValueError("layout must cover every graph node exactly once")
        if self.coverage.seed_count != len(seed_ids) or self.coverage.node_count != len(self.nodes):
            raise ValueError("coverage must account for all seeds and nodes")
        hierarchy_ids = {
            edge.source_item_id for edge in self.edges if edge.kind == "public_taxonomy_parent"
        } | {edge.target_item_id for edge in self.edges if edge.kind == "public_taxonomy_parent"}
        if self.coverage.factual_hierarchy_node_count != len(hierarchy_ids):
            raise ValueError("factual hierarchy coverage does not match taxonomy edges")
        assert_no_prohibited_construction_fields(self)
        return self


class OpenConstructionGraphGate(FrozenModel):
    """A fail-closed publication decision for an open construction artifact."""

    artifact_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)
    component_count: int = Field(ge=1)
    complete_seed_coverage: Literal[True] = True
    no_prohibited_inputs: Literal[True] = True
    no_review_membership_promotion: Literal[True] = True
    deterministic_replay: Literal[True] = True


class OpenConstructionGraphPublicationReceipt(FrozenModel):
    """Immutable object-store receipt for a verified public graph artifact."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_byte_size: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate: OpenConstructionGraphGate


@dataclass(frozen=True, slots=True)
class _CatalogNode:
    row_id: int
    catalog_id: str
    name: str


def assert_no_prohibited_construction_fields(value: object) -> None:
    """Fail if a constructed artifact contains a forbidden input-shaped field.

    This check is applied to the construction projection and final graph, not
    the retained source document.  The latter may contain legacy material, but
    :func:`load_seed_input` projects it away before this builder begins.
    """
    payload = value.model_dump(mode="json") if isinstance(value, FrozenModel) else value

    def walk(current: object) -> None:
        if isinstance(current, dict):
            forbidden = _FORBIDDEN_CONSTRUCTION_KEYS & {str(key).casefold() for key in current}
            if forbidden:
                raise ValueError(f"prohibited construction field(s): {sorted(forbidden)!r}")
            for nested in current.values():
                walk(nested)
        elif isinstance(current, (list, tuple)):
            for nested in current:
                walk(nested)

    walk(payload)


def _read_public_catalog(
    path: Path,
) -> tuple[dict[int, _CatalogNode], tuple[tuple[int, int, str], ...]]:
    """Read only CC0 taxonomy identity/edge tables, never membership tables."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        licenses = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT license_name FROM data_sources ORDER BY license_name"
            )
            if row[0]
        )
        if not licenses or any(not item.startswith("CC0-1.0") for item in licenses):
            raise ValueError("open construction requires a CC0-only public catalog")
        identities = {
            int(row[0]): f"wikidata:genre:{row[1]}"
            for row in connection.execute(
                """SELECT identifier.entity_id, identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   WHERE type.type_key = 'wikidata_genre_qid'
                   ORDER BY identifier.entity_id, identifier.normalized_value"""
            )
        }
        nodes = {
            int(row[0]): _CatalogNode(
                row_id=int(row[0]),
                catalog_id=identities.get(int(row[0]), f"public:genre:{row[0]}"),
                name=str(row[1]),
            )
            for row in connection.execute(
                "SELECT id, name FROM genres WHERE entity_kind = 'genre' ORDER BY id"
            )
        }
        # Read aliases solely to make the input audit truthful; taxonomy matching is supplied
        # by the typed anchor artifact and no fuzzy/catalog membership lookup is performed here.
        connection.execute(
            "SELECT entity_id, name FROM entity_names ORDER BY entity_id, name"
        ).fetchall()
        relations = tuple(
            (int(row[0]), int(row[1]), str(row[2]))
            for row in connection.execute(
                """SELECT child_genre_id, parent_genre_id, relation_id
                   FROM genre_hierarchy ORDER BY child_genre_id, parent_genre_id, relation_id"""
            )
            if int(row[0]) in nodes and int(row[1]) in nodes
        )
    return nodes, relations


def _assert_taxonomy_matches_seed(
    seed: SeedInput, taxonomy: GenreSeedPublicTaxonomyArtifact
) -> None:
    if taxonomy.seed_input != seed:
        raise ValueError("taxonomy anchor artifact does not match the name-only seed projection")
    if taxonomy.public_catalog.local_nc_research_excluded is not True:
        raise ValueError("taxonomy artifact must exclude local MusicBrainz research")


def _would_make_cycle(child: str, parent: str, parents: dict[str, set[str]]) -> bool:
    """Return whether child -> parent would close a taxonomy cycle."""
    queue: deque[str] = deque([parent])
    seen: set[str] = set()
    while queue:
        current = queue.popleft()
        if current == child:
            return True
        if current in seen:
            continue
        seen.add(current)
        queue.extend(sorted(parents.get(current, ())))
    return False


def _edge_id(source: str, target: str, kind: str, evidence: OpenGraphEdgeEvidence) -> str:
    return sha256_hex(
        json.dumps(
            {
                "source": source,
                "target": target,
                "kind": kind,
                "evidence": evidence.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


def _components(
    nodes: tuple[OpenGraphNode, ...], edges: list[OpenGraphEdge]
) -> tuple[OpenGraphComponent, ...]:
    adjacent: dict[str, set[str]] = {node.source_item_id: set() for node in nodes}
    factual_by_node: dict[str, int] = defaultdict(int)
    for edge in edges:
        adjacent[edge.source_item_id].add(edge.target_item_id)
        adjacent[edge.target_item_id].add(edge.source_item_id)
        if edge.factual_relationship:
            factual_by_node[edge.source_item_id] += 1
            factual_by_node[edge.target_item_id] += 1
    seen: set[str] = set()
    components: list[OpenGraphComponent] = []
    for start in sorted(adjacent):
        if start in seen:
            continue
        queue: deque[str] = deque([start])
        member_ids: list[str] = []
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            member_ids.append(current)
            queue.extend(sorted(adjacent[current] - seen))
        members = tuple(sorted(member_ids))
        member_set = set(members)
        component_edges = [
            edge for edge in edges if {edge.source_item_id, edge.target_item_id} <= member_set
        ]
        components.append(
            OpenGraphComponent(
                component_id=sha256_hex("\x1f".join(members).encode()),
                node_ids=members,
                edge_count=len(component_edges),
                factual_edge_count=sum(edge.factual_relationship for edge in component_edges),
                isolated=len(members) == 1 and not adjacent[members[0]],
            )
        )
    return tuple(sorted(components, key=lambda item: item.component_id))


def _unit(value: str, salt: str) -> float:
    return int.from_bytes(hashlib.sha256(f"{salt}\x1f{value}".encode()).digest()[:8], "big") / 2**64


def _depths(nodes: tuple[OpenGraphNode, ...], edges: list[OpenGraphEdge]) -> dict[str, int]:
    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.kind == "public_taxonomy_parent":
            parents[edge.source_item_id].add(edge.target_item_id)
            children[edge.target_item_id].add(edge.source_item_id)
    roots = sorted(node.source_item_id for node in nodes if not parents[node.source_item_id])
    depth = dict.fromkeys(roots, 0)
    queue: deque[str] = deque(roots)
    while queue:
        parent = queue.popleft()
        for child in sorted(children[parent]):
            candidate = depth[parent] + 1
            if candidate > depth.get(child, -1):
                depth[child] = candidate
                queue.append(child)
    return {node.source_item_id: depth.get(node.source_item_id, 0) for node in nodes}


def _layout(
    nodes: tuple[OpenGraphNode, ...],
    components: tuple[OpenGraphComponent, ...],
    edges: list[OpenGraphEdge],
) -> tuple[OpenGraphLayoutNode, ...]:
    component_by_node = {
        node_id: component for component in components for node_id in component.node_ids
    }
    ordered_components = sorted(components, key=lambda item: item.component_id)
    component_index = {
        component.component_id: index for index, component in enumerate(ordered_components)
    }
    depths = _depths(nodes, edges)
    by_depth: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        by_depth[depths[node.source_item_id]].append(node.source_item_id)
    hierarchy_x = {
        node_id: index - (len(ids) - 1) / 2
        for _, ids in sorted(by_depth.items())
        for index, node_id in enumerate(sorted(ids))
    }
    result: list[OpenGraphLayoutNode] = []
    for node in sorted(nodes, key=lambda item: item.source_item_id):
        component = component_by_node[node.source_item_id]
        index = component_index[component.component_id]
        angle = index * 2.399963229728653 + _unit(node.source_item_id, "landscape-angle") * 0.45
        radius = 8.0 + math.sqrt(index + 1) * 18.0
        center_x, center_y = radius * math.cos(angle), radius * math.sin(angle)
        local_angle = _unit(node.source_item_id, "landscape-local") * math.tau
        local_radius = (
            0.6
            + math.sqrt(_unit(node.source_item_id, "landscape-radius"))
            * max(1, len(component.node_ids)) ** 0.5
        )
        result.append(
            OpenGraphLayoutNode(
                source_item_id=node.source_item_id,
                landscape_x=round(center_x + math.cos(local_angle) * local_radius, 6),
                landscape_y=round(center_y + math.sin(local_angle) * local_radius, 6),
                hierarchy_x=round(hierarchy_x[node.source_item_id], 6),
                hierarchy_y=float(-depths[node.source_item_id]),
                hierarchy_depth=depths[node.source_item_id],
            )
        )
    return tuple(result)


def build_open_construction_graph(  # noqa: C901
    seed_artifact: Path,
    taxonomy_artifact: Path,
    public_catalog_database: Path,
    *,
    config: OpenConstructionGraphConfig | None = None,
) -> OpenConstructionGraphArtifact:
    """Build one confidence-scored graph from public taxonomy and lexical evidence."""
    config = config or OpenConstructionGraphConfig()
    seed = load_seed_input(seed_artifact)
    if len(seed.names) != config.expected_seed_count:
        raise ValueError(
            f"expected {config.expected_seed_count} name seeds, found {len(seed.names)}"
        )
    taxonomy = GenreSeedPublicTaxonomyArtifact.model_validate_json(taxonomy_artifact.read_bytes())
    _assert_taxonomy_matches_seed(seed, taxonomy)
    assert_no_prohibited_construction_fields(taxonomy)
    catalog_nodes, relations = _read_public_catalog(public_catalog_database)
    catalog_sha = sha256_file(public_catalog_database)[0]
    if taxonomy.public_catalog.database_sha256 != catalog_sha:
        raise ValueError("taxonomy artifact public catalog hash does not match graph catalog input")

    inference_by_id = {item.source_item_id: item for item in taxonomy.inferences}
    nodes = tuple(
        OpenGraphNode(
            source_item_id=item.source_item_id,
            source_external_id=item.source_external_id,
            name=item.name,
            taxonomy_status=inference_by_id[item.source_item_id].status,
            public_catalog_id=_canonical_catalog_id(inference_by_id[item.source_item_id]),
            review_anchor_catalog_id=_review_anchor_catalog_id(
                inference_by_id[item.source_item_id]
            ),
        )
        for item in seed.names
    )
    canonical_to_seed_ids: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        if node.public_catalog_id:
            canonical_to_seed_ids[node.public_catalog_id].append(node.source_item_id)
    canonical_unique = {
        key: values[0] for key, values in canonical_to_seed_ids.items() if len(values) == 1
    }

    edges: list[OpenGraphEdge] = []
    hierarchy_parents: dict[str, set[str]] = defaultdict(set)
    for child_row, parent_row, relation_id in relations:
        child_catalog, parent_catalog = (
            catalog_nodes[child_row].catalog_id,
            catalog_nodes[parent_row].catalog_id,
        )
        child, parent = canonical_unique.get(child_catalog), canonical_unique.get(parent_catalog)
        if (
            child is None
            or parent is None
            or child == parent
            or _would_make_cycle(child, parent, hierarchy_parents)
        ):
            continue
        evidence = OpenGraphEdgeEvidence(
            source="public_catalog_taxonomy",
            public_catalog_sha256=catalog_sha,
            taxonomy_artifact_sha256=taxonomy.output_sha256,
            catalog_child_id=child_catalog,
            catalog_parent_id=parent_catalog,
            relation_id=relation_id,
            note="direct CC0 public taxonomy relation between uniquely resolved seed identities",
        )
        edges.append(
            OpenGraphEdge(
                edge_id=_edge_id(child, parent, "public_taxonomy_parent", evidence),
                source_item_id=child,
                target_item_id=parent,
                kind="public_taxonomy_parent",
                confidence=config.factual_taxonomy_confidence,
                factual_relationship=True,
                review_candidate=False,
                evidence=evidence,
            )
        )
        hierarchy_parents[child].add(parent)

    review_candidates: dict[str, list[SeedTaxonomyInference]] = defaultdict(list)
    generic_token_rejections = 0
    for inference in taxonomy.inferences:
        if inference.status != "anchored_compositional" or inference.anchor is None:
            continue
        modifier_tokens = set((inference.lexical_modifier or "").split())
        target = canonical_unique.get(inference.anchor.catalog_id)
        if target is None:
            continue
        if modifier_tokens & _GENERIC_TOKENS:
            generic_token_rejections += 1
            continue
        review_candidates[target].append(inference)
    review_hub_rejections = 0
    for target, candidates in sorted(review_candidates.items()):
        for inference in sorted(candidates, key=lambda item: item.source_item_id)[
            : config.max_review_anchor_degree
        ]:
            evidence = OpenGraphEdgeEvidence(
                source="public_taxonomy_anchor",
                public_catalog_sha256=catalog_sha,
                taxonomy_artifact_sha256=taxonomy.output_sha256,
                catalog_parent_id=inference.anchor.catalog_id if inference.anchor else None,
                lexical_modifier=inference.lexical_modifier,
                note=(
                    "unique public taxonomy suffix anchor; review/navigation only, "
                    "not parentage or membership"
                ),
            )
            edges.append(
                OpenGraphEdge(
                    edge_id=_edge_id(
                        inference.source_item_id, target, "lexical_review_anchor", evidence
                    ),
                    source_item_id=inference.source_item_id,
                    target_item_id=target,
                    kind="lexical_review_anchor",
                    confidence=config.review_anchor_confidence,
                    factual_relationship=False,
                    review_candidate=True,
                    evidence=evidence,
                )
            )
        review_hub_rejections += max(0, len(candidates) - config.max_review_anchor_degree)
    edges.sort(key=lambda item: item.edge_id)
    components = _components(nodes, edges)
    layout = _layout(nodes, components, edges)
    ambiguous = sum(item.status.startswith("ambiguous") for item in taxonomy.inferences)
    coverage = OpenGraphCoverage(
        seed_count=len(nodes),
        node_count=len(nodes),
        edge_count=len(edges),
        factual_taxonomy_edge_count=sum(edge.factual_relationship for edge in edges),
        lexical_review_edge_count=sum(edge.review_candidate for edge in edges),
        connected_component_count=len(components),
        isolated_node_count=sum(component.isolated for component in components),
        factual_hierarchy_node_count=len(
            {
                endpoint
                for edge in edges
                if edge.factual_relationship
                for endpoint in (edge.source_item_id, edge.target_item_id)
            }
        ),
        review_anchored_node_count=sum(edge.review_candidate for edge in edges),
        abstained_node_count=sum(item.status == "abstained" for item in taxonomy.inferences),
        ambiguous_node_count=ambiguous,
        generic_token_rejection_count=generic_token_rejections,
        review_hub_rejection_count=review_hub_rejections,
    )
    preliminary = OpenConstructionGraphArtifact(
        seed_input=seed,
        taxonomy_artifact_sha256=taxonomy.output_sha256,
        public_catalog_sha256=catalog_sha,
        config=config,
        nodes=nodes,
        edges=tuple(edges),
        components=components,
        layout=layout,
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


def _canonical_catalog_id(inference: SeedTaxonomyInference) -> str | None:
    if inference.status in {"canonical_exact", "canonical_alias"} and inference.exact_candidates:
        return inference.exact_candidates[0].catalog_id
    return None


def _review_anchor_catalog_id(inference: SeedTaxonomyInference) -> str | None:
    return (
        inference.anchor.catalog_id
        if inference.status == "anchored_compositional" and inference.anchor
        else None
    )


def verify_open_construction_graph(
    artifact: OpenConstructionGraphArtifact,
) -> OpenConstructionGraphGate:
    """Verify hash, coverage, review boundary, and deterministic serialization."""
    if artifact.output_sha256 != sha256_json(
        artifact.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("open construction graph logical hash does not match content")
    assert_no_prohibited_construction_fields(artifact)
    if (
        artifact.coverage.inferred_membership_count
        or artifact.coverage.review_candidates_promoted_to_memberships
    ):
        raise ValueError("review candidates must not be promoted to memberships")
    if any(edge.review_candidate and edge.factual_relationship for edge in artifact.edges):
        raise ValueError("review edge claimed a factual relationship")
    if any(
        edge.kind == "lexical_review_anchor" and edge.source_item_id == edge.target_item_id
        for edge in artifact.edges
    ):
        raise ValueError("review anchor cannot point to itself")
    return OpenConstructionGraphGate(
        artifact_output_sha256=artifact.output_sha256,
        node_count=len(artifact.nodes),
        edge_count=len(artifact.edges),
        component_count=len(artifact.components),
    )


def write_open_construction_graph(
    artifact: OpenConstructionGraphArtifact, output_path: Path
) -> tuple[str, int]:
    """Atomically write a verified artifact and return its byte identity."""
    verify_open_construction_graph(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(output_path, payload)
    return sha256_hex(payload), len(payload)


def publish_open_construction_graph(
    artifact: OpenConstructionGraphArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[OpenConstructionGraphPublicationReceipt, ObjectWrite]:
    """Write, verify, and publish the artifact under an immutable content key."""
    gate = verify_open_construction_graph(artifact)
    artifact_sha, size = write_open_construction_graph(artifact, output_path)
    key = ObjectKey(value=f"open-construction-graph/{artifact.output_sha256}/{artifact_sha}.json")
    object_write = store.push(output_path, key)
    if object_write.sha256 != artifact_sha or object_write.byte_size != size:
        raise ValueError("object store write does not match open construction artifact")
    return OpenConstructionGraphPublicationReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_size=size,
        object_key=key.value,
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    ), object_write
