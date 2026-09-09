"""Bounded local peer artifacts built from one declared metadata membership source."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
from pydantic import Field
from scipy.sparse import coo_matrix, csr_matrix, triu

from musix.models import FrozenModel
from musix.taxonomy.seeds.reconciliation import load_seed_reconciliation
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


MAX_NNZ: Final = 2_000_000
MAX_PAIR_VISITS: Final = 5_000_000
MAX_CANDIDATES: Final = 500_000
TOP_K: Final = 25
MembershipTable = Literal["direct_anchor", "release_group_support"]


class ReleaseGroupSupportPeerError(ValueError):
    """Report an invalid or out-of-bound local support peer input."""


class SupportPeerEdge(FrozenModel):
    """One canonical, source-labeled binary-Jaccard edge."""

    source_genre_id: str = Field(min_length=1)
    target_genre_id: str = Field(min_length=1)
    score: float = Field(gt=0.0, le=1.0)
    component_kind: Literal["release_group_artist_overlap", "direct_artist_overlap"]
    shared_supported_artist_count: int = Field(ge=1)
    support_binary_jaccard_score: float = Field(gt=0.0, le=1.0)


class SupportPeerArtifact(FrozenModel):
    """A source-neutral local candidate, separate from public peer models."""

    revision: Literal["release-group-support-peer-v2"] = "release-group-support-peer-v2"
    scope: Literal["local_research_non_production"] = "local_research_non_production"
    serving_allowed: Literal[False] = False
    historical_inputs_used_for_construction: Literal[False] = False
    database_sha256: Sha256
    reconciliation_sha256: Sha256
    membership_table: MembershipTable
    component_kind: Literal["release_group_artist_overlap", "direct_artist_overlap"]
    metric: Literal["binary_jaccard"] = "binary_jaccard"
    seed_count: int = Field(ge=0)
    support_membership_count: int = Field(ge=0)
    support_genre_count: int = Field(ge=0)
    empty_input_seed_count: int = Field(ge=0)
    seeds_without_qualifying_neighbors_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    pair_visit_upper_bound: int = Field(ge=0)
    excluded_artist_ids: tuple[str, ...] = ()
    excluded_membership_count: int = Field(default=0, ge=0)
    candidates: tuple[SupportPeerEdge, ...]
    output_sha256: Sha256


@dataclass(frozen=True, slots=True)
class _MembershipSource:
    table: MembershipTable
    component_kind: Literal["release_group_artist_overlap", "direct_artist_overlap"]


_SOURCES: Final = {
    "direct_anchor": _MembershipSource("direct_anchor", "direct_artist_overlap"),
    "release_group_support": _MembershipSource(
        "release_group_support", "release_group_artist_overlap"
    ),
}


def logical_sha(value: object) -> Sha256:
    """Hash a canonical JSON-compatible value."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def file_sha(path: Path) -> Sha256:
    """Hash a local immutable input or output file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _seed_ids(reconciliation: Path) -> tuple[str, ...]:
    try:
        artifact = load_seed_reconciliation(reconciliation)
        values = tuple(row.source_item_id for row in artifact.dispositions)
    except (OSError, ValueError) as error:
        raise ReleaseGroupSupportPeerError("invalid seed reconciliation") from error
    if len(set(values)) != len(values):
        raise ReleaseGroupSupportPeerError("reconciliation has duplicate source item IDs")
    return values


def _membership_query(table: MembershipTable) -> str:
    if table == "direct_anchor":
        return "SELECT genre_id, artist_id FROM direct_anchor GROUP BY genre_id, artist_id"
    return "SELECT genre_id, artist_id FROM release_group_support GROUP BY genre_id, artist_id"


def _pair_visit_bound(connection: sqlite3.Connection, table: MembershipTable) -> int:
    queries: dict[MembershipTable, str] = {
        "direct_anchor": (
            "SELECT sum(n * (n - 1) / 2) FROM "
            "(SELECT count(DISTINCT genre_id) n FROM direct_anchor GROUP BY artist_id)"
        ),
        "release_group_support": (
            "SELECT sum(n * (n - 1) / 2) FROM "
            "(SELECT count(DISTINCT genre_id) n FROM release_group_support GROUP BY artist_id)"
        ),
    }
    result = connection.execute(queries[table]).fetchone()[0]
    return int(result or 0)


def _edges(
    matrix: csr_matrix, seed_ids: tuple[str, ...]
) -> tuple[tuple[SupportPeerEdge, ...], int]:
    degree = np.asarray(matrix.sum(axis=1)).ravel().astype(np.int64)
    overlap = triu((matrix @ matrix.T).astype(np.int64), k=1).tocoo()
    neighbors: list[list[tuple[str, float, int]]] = [[] for _ in seed_ids]
    for left, right, shared in zip(overlap.row, overlap.col, overlap.data, strict=True):
        union = int(degree[left] + degree[right] - shared)
        if union:
            score = float(shared / union)
            neighbors[left].append((seed_ids[right], score, int(shared)))
            neighbors[right].append((seed_ids[left], score, int(shared)))
    selected: dict[tuple[str, str], SupportPeerEdge] = {}
    for index, values in enumerate(neighbors):
        for target, score, shared in sorted(values, key=lambda value: (-value[1], value[0]))[
            :TOP_K
        ]:
            left, right = sorted((seed_ids[index], target))
            selected[(left, right)] = SupportPeerEdge(
                source_genre_id=left,
                target_genre_id=right,
                score=score,
                component_kind="release_group_artist_overlap",
                shared_supported_artist_count=shared,
                support_binary_jaccard_score=score,
            )
    return tuple(selected[key] for key in sorted(selected)), int((degree > 0).sum())


def build_support_peer_artifact(
    *,
    database: Path,
    reconciliation: Path,
    membership_table: MembershipTable = "release_group_support",
    excluded_artist_ids: frozenset[str] = frozenset(),
) -> SupportPeerArtifact:
    """Build a bounded local candidate from deduplicated metadata memberships."""
    source = _SOURCES[membership_table]
    seed_ids = _seed_ids(reconciliation)
    seed_index = {seed: index for index, seed in enumerate(seed_ids)}
    artists: dict[str, int] = {}
    rows: list[int] = []
    columns: list[int] = []
    with closing(sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only = ON")
        potential = _pair_visit_bound(connection, membership_table)
        if potential > MAX_PAIR_VISITS:
            raise ReleaseGroupSupportPeerError("membership pair visits exceed bound")
        excluded_memberships = 0
        for genre_id, artist_id in connection.execute(_membership_query(membership_table)):
            row = seed_index.get(str(genre_id))
            if row is None:
                raise ReleaseGroupSupportPeerError(
                    "membership references a seed outside reconciliation"
                )
            artist = str(artist_id)
            if artist in excluded_artist_ids:
                excluded_memberships += 1
                continue
            column = artists.setdefault(artist, len(artists))
            rows.append(row)
            columns.append(column)
            if len(rows) > MAX_NNZ:
                raise ReleaseGroupSupportPeerError("membership count exceeds bound")
    matrix = coo_matrix(
        (np.ones(len(rows), dtype=np.int64), (np.asarray(rows), np.asarray(columns))),
        shape=(len(seed_ids), len(artists)),
        dtype=np.int64,
    ).tocsr()
    edges, support_genres = _edges(matrix, seed_ids)
    if source.component_kind != "release_group_artist_overlap":
        edges = tuple(
            edge.model_copy(update={"component_kind": source.component_kind}) for edge in edges
        )
    if len(edges) > MAX_CANDIDATES:
        raise ReleaseGroupSupportPeerError("candidate count exceeds bound")
    has_neighbor = {edge.source_genre_id for edge in edges} | {
        edge.target_genre_id for edge in edges
    }
    preliminary = SupportPeerArtifact(
        database_sha256=file_sha(database),
        reconciliation_sha256=file_sha(reconciliation),
        membership_table=membership_table,
        component_kind=source.component_kind,
        seed_count=len(seed_ids),
        support_membership_count=len(rows),
        support_genre_count=support_genres,
        empty_input_seed_count=len(seed_ids) - support_genres,
        seeds_without_qualifying_neighbors_count=sum(seed not in has_neighbor for seed in seed_ids)
        - (len(seed_ids) - support_genres),
        artist_count=len(artists),
        pair_visit_upper_bound=potential,
        excluded_artist_ids=tuple(sorted(excluded_artist_ids)),
        excluded_membership_count=excluded_memberships,
        candidates=edges,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": logical_sha(
                preliminary.model_dump(mode="json", exclude={"output_sha256"})
            )
        }
    )


def artifact_neighbors(
    artifact: SupportPeerArtifact, *, genre_ids: set[str], k: int
) -> dict[str, tuple[str, ...]]:
    """Adapt a sealed source artifact to deterministic directed top-k neighborhoods."""
    ranked: dict[str, list[tuple[str, float]]] = {}
    for edge in artifact.candidates:
        if edge.source_genre_id in genre_ids and edge.target_genre_id in genre_ids:
            ranked.setdefault(edge.source_genre_id, []).append((edge.target_genre_id, edge.score))
            ranked.setdefault(edge.target_genre_id, []).append((edge.source_genre_id, edge.score))
    return {
        genre: tuple(
            target for target, _ in sorted(rows, key=lambda value: (-value[1], value[0]))[:k]
        )
        for genre, rows in ranked.items()
    }


def write_artifact_and_receipt(artifact: SupportPeerArtifact, output: Path, receipt: Path) -> None:
    """Write a versioned artifact and its byte-binding local custody receipt."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "revision": "release-group-support-peer-receipt-v1",
                "artifact_path": str(output),
                "artifact_bytes_sha256": file_sha(output),
                "artifact_logical_output_sha256": artifact.output_sha256,
                "artifact_bytes": output.stat().st_size,
                "database_sha256": artifact.database_sha256,
                "reconciliation_sha256": artifact.reconciliation_sha256,
                "serving_allowed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
