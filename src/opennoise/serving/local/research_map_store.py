"""Serve a receipt-bound local peer layout without inventing positions."""
# ruff: noqa: D101, D102

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.serving.local.research_peer_layout import (
    LocalResearchPeerLayoutArtifact,
    local_research_peer_layout_output_sha256,
)

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.taxonomy.seeds.reconciliation import SeedReconciliationArtifact

_BUDGET = 240


class LocalResearchMapError(ValueError):
    """Report an invalid local-only graph/layout binding."""


class LocalResearchMapNode(FrozenModel):
    node_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    x: float
    y: float
    degree: int = Field(ge=0)
    node_kind: Literal["peer_community", "legacy_name_seed"]
    placed: bool = True
    source_item_id: str | None = None


class LocalResearchMapEdge(FrozenModel):
    source: str
    target: str
    kind: Literal["peer_similarity"] = "peer_similarity"
    factual_relationship: Literal[False] = False
    review_candidate: Literal[False] = False
    confidence: float = Field(gt=0, le=1)


class LocalResearchMapResponse(FrozenModel):
    source: Literal["local-research-peer-layout"] = "local-research-peer-layout"
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    level: int = Field(ge=0, le=3)
    offset: int = Field(default=0, ge=0)
    node_budget: int = Field(ge=1)
    total_node_count: int = Field(ge=1)
    total_edge_count: int = Field(ge=0)
    truncated: bool
    nodes: tuple[LocalResearchMapNode, ...]
    edges: tuple[LocalResearchMapEdge, ...]


class LocalResearchMapSearchHit(FrozenModel):
    node_id: str
    name: str
    placed: bool
    unplaced_reason: Literal["no_peer_similarity_evidence"] | None = None


@dataclass(slots=True)
class LocalResearchMapStore:
    layout_path: Path
    index_path: Path
    reconciliation: SeedReconciliationArtifact
    _artifact: LocalResearchPeerLayoutArtifact | None = None
    _nodes: dict[str, LocalResearchMapNode] | None = None
    _edges: tuple[LocalResearchMapEdge, ...] = ()
    _communities: dict[str, tuple[str, ...]] | None = None

    @property
    def configured(self) -> bool:
        return self._artifact is not None

    def start(self) -> None:
        artifact = LocalResearchPeerLayoutArtifact.model_validate_json(
            self.layout_path.read_bytes()
        )
        if artifact.publication_scope != "local_research_only" or artifact.export_allowed:
            raise LocalResearchMapError("layout is not local-only")
        if local_research_peer_layout_output_sha256(artifact) != artifact.output_sha256:
            raise LocalResearchMapError("layout logical hash is invalid")
        if _sha(self.index_path) != artifact.source_index_sha256:
            raise LocalResearchMapError("layout does not bind the local peer index")
        names = {row.source_item_id: row.seed_name for row in self.reconciliation.dispositions}
        coordinates = {row.genre_id: row for row in artifact.coordinates}
        if set(coordinates) | {row.source_item_id for row in artifact.unplaced} != set(names):
            raise LocalResearchMapError("layout does not account for reconciliation seeds")
        weights = _edges(self.index_path)
        degree: dict[str, int] = defaultdict(int)
        for left, right, _ in weights:
            degree[left] += 1
            degree[right] += 1
        self._nodes = {
            f"legacy:{seed}": LocalResearchMapNode(
                node_id=f"legacy:{seed}",
                name=name,
                x=coordinates[seed].x,
                y=coordinates[seed].y,
                degree=degree[seed],
                node_kind="legacy_name_seed",
                source_item_id=seed,
            )
            for seed, name in names.items()
            if seed in coordinates
        }
        self._edges = tuple(
            LocalResearchMapEdge(
                source=f"legacy:{left}", target=f"legacy:{right}", confidence=score
            )
            for left, right, score in weights
        )
        grouped: dict[str, list[str]] = defaultdict(list)
        for seed, coordinate in coordinates.items():
            grouped[str(coordinate.component)].append(seed)
        self._communities = {key: tuple(sorted(value)) for key, value in grouped.items()}
        self._artifact = artifact

    def response(self, *, level: int) -> LocalResearchMapResponse:
        self._require()
        assert self._artifact is not None and self._nodes is not None  # noqa: S101, PT018
        if level == 0:
            nodes = self._community_nodes()
            edges: tuple[LocalResearchMapEdge, ...] = ()
        else:
            nodes = tuple(
                sorted(self._nodes.values(), key=lambda node: (-node.degree, node.name.casefold()))[
                    :_BUDGET
                ]
            )
            ids = {node.node_id for node in nodes}
            edges = tuple(
                edge for edge in self._edges if edge.source in ids and edge.target in ids
            )[:512]
        return LocalResearchMapResponse(
            logical_output_sha256=self._artifact.output_sha256,
            level=level,
            offset=0,
            node_budget=_BUDGET,
            total_node_count=len(self._nodes),
            total_edge_count=len(self._edges),
            truncated=len(nodes) > _BUDGET,
            nodes=nodes,
            edges=edges,
        )

    def neighbors(self, node_id: str, *, offset: int = 0) -> LocalResearchMapResponse:
        self._require()
        assert (  # noqa: S101, PT018
            self._artifact is not None and self._nodes is not None and self._communities is not None
        )
        if offset < 0:
            raise LocalResearchMapError("community offset must not be negative")
        if node_id.startswith("community:"):
            members = self._communities.get(node_id.removeprefix("community:"))
            if members is None:
                raise LocalResearchMapError("unknown community")
            nodes = tuple(
                self._nodes[f"legacy:{seed}"] for seed in members[offset : offset + _BUDGET]
            )
        else:
            node = self._nodes.get(node_id)
            if node is None:
                raise LocalResearchMapError("unplaced or unknown seed has no map neighborhood")
            edges = [edge for edge in self._edges if node_id in {edge.source, edge.target}][:24]
            ids = {node_id} | {
                edge.target if edge.source == node_id else edge.source for edge in edges
            }
            nodes = tuple(self._nodes[value] for value in sorted(ids))
            return LocalResearchMapResponse(
                logical_output_sha256=self._artifact.output_sha256,
                level=3,
                offset=0,
                node_budget=25,
                total_node_count=len(self._nodes),
                total_edge_count=len(self._edges),
                truncated=False,
                nodes=nodes,
                edges=tuple(edges),
            )
        ids = {node.node_id for node in nodes}
        edges = tuple(edge for edge in self._edges if edge.source in ids and edge.target in ids)[
            :512
        ]
        return LocalResearchMapResponse(
            logical_output_sha256=self._artifact.output_sha256,
            level=1,
            offset=offset,
            node_budget=_BUDGET,
            total_node_count=len(self._nodes),
            total_edge_count=len(self._edges),
            truncated=offset + len(nodes) < len(members),
            nodes=nodes,
            edges=edges,
        )

    def search(self, query: str) -> tuple[LocalResearchMapSearchHit, ...]:
        self._require()
        assert self._nodes is not None  # noqa: S101
        needle = query.strip().casefold()
        if not needle:
            return ()
        placed = {node.source_item_id for node in self._nodes.values()}
        return tuple(
            LocalResearchMapSearchHit(
                node_id=f"legacy:{row.source_item_id}",
                name=row.seed_name,
                placed=row.source_item_id in placed,
                unplaced_reason=None
                if row.source_item_id in placed
                else "no_peer_similarity_evidence",
            )
            for row in self.reconciliation.dispositions
            if needle in row.seed_name.casefold()
        )[:50]

    def _community_nodes(self) -> tuple[LocalResearchMapNode, ...]:
        assert self._nodes is not None and self._communities is not None  # noqa: S101, PT018
        result = []
        for key, members in self._communities.items():
            rows = [self._nodes[f"legacy:{seed}"] for seed in members]
            result.append(
                LocalResearchMapNode(
                    node_id=f"community:{key}",
                    name=f"Evidence community {key}",
                    x=sum(row.x for row in rows) / len(rows),
                    y=sum(row.y for row in rows) / len(rows),
                    degree=sum(row.degree for row in rows),
                    node_kind="peer_community",
                )
            )
        return tuple(sorted(result, key=lambda node: (-node.degree, node.node_id)))

    def _require(self) -> None:
        if self._artifact is None or self._nodes is None or self._communities is None:
            raise LocalResearchMapError("local research map is unavailable")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _edges(path: Path) -> tuple[tuple[str, str, float], ...]:
    with closing(sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT source_genre_id, target_genre_id, score FROM peer_edge "
            "ORDER BY source_genre_id, target_genre_id"
        ).fetchall()
    return tuple((str(left), str(right), float(score)) for left, right, score in rows)
