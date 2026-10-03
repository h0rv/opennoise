"""Source-only P279 graph neighborhoods, supported coordinates and frozen holdouts.

No type anchors, names, artist memberships or sonic features enter distances.
Coordinates have meaning within one source-graph component only. Retrieval
metrics measure source edge recovery, never independent musical relevance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph
from scipy.sparse.linalg import ArpackNoConvergence, eigsh

from opennoise.common import canonical_json, sha256_file
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Iterable

SEED = 20261002
FOLDS = 5
DEPTH = 3
NEIGHBORS = 10
MIN_COMPONENT = 4
AXIS_GAP = 1e-8
REVISION = "open-taxonomy-neighborhoods-v1"
PROTOCOL_SHA256 = "9ac488b93c448e94583388f9125c853a77ad2b334a87997fdc374a1c4d26b526"


class GraphSettings(FrozenModel):
    """Frozen construction settings declared before holdout measurement."""

    seed: Literal[20261002] = SEED
    folds: Literal[5] = FOLDS
    maximum_depth: Literal[3] = DEPTH
    neighbor_count: Literal[10] = NEIGHBORS
    minimum_layout_component_nodes: Literal[4] = MIN_COMPONENT
    excluded_signals: tuple[str, ...] = ("P31", "type_anchor", "names", "artists", "sonic")
    edge_policy: Literal["undirected_selected_P279_only"] = "undirected_selected_P279_only"
    coordinate_scope: Literal["component_local_source_structure"] = (
        "component_local_source_structure"
    )


class TaxonomyNeighbor(FrozenModel):
    """A supported graph walk, separate from direct artist membership or relevance."""

    genre_id: str
    score: float
    role: Literal["derived_taxonomy_graph_neighbor"] = "derived_taxonomy_graph_neighbor"
    musical_similarity_validated: Literal[False] = False
    sonic_similarity: Literal[False] = False


class GraphCoordinate(FrozenModel):
    """One supported component-local projection, without across-component semantics."""

    genre_id: str
    component_id: str
    x: float
    y: float


class GraphReceipt(FrozenModel):
    """Typed input, settings and output custody, with explicit interpretation limits."""

    revision: Literal["open-taxonomy-neighborhoods-v1"] = REVISION
    projection_sha256: str
    source_receipt_sha256: str
    protocol_sha256: str
    builder_sha256: str
    settings: GraphSettings
    license: Literal["CC0-1.0"] = "CC0-1.0"
    historical_inputs_used: Literal[False] = False
    artist_membership_inference: Literal[False] = False
    independent_musical_validation: Literal[False] = False
    output_sha256: str


def selected_p279_edges(projection: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Select only actual subclass edges with both endpoints in the frozen cohort."""
    selected = {row["qid"] for row in projection["entities"]}
    return tuple(
        sorted(
            {
                (
                    min(str(row["genre_qid"]), str(row["value_qid"])),
                    max(str(row["genre_qid"]), str(row["value_qid"])),
                )
                for row in projection["claims"]
                if row["property_id"] == "P279"
                and row["genre_qid"] in selected
                and row["value_qid"] in selected
                and row["genre_qid"] != row["value_qid"]
            }
        )
    )


def edge_fold(edge: tuple[str, str]) -> int:
    """Assign undirected pairs deterministically before inspecting recovery metrics."""
    first, second = sorted(edge)
    body = f"{SEED}|{first}|{second}".encode()
    return int(hashlib.sha256(body).hexdigest(), 16) % FOLDS


def _adjacency(nodes: tuple[str, ...], edges: Iterable[tuple[str, str]]) -> sparse.csr_matrix:
    indices = {node: index for index, node in enumerate(nodes)}
    pairs = [(indices[a], indices[b]) for a, b in edges]
    rows = [i for a, b in pairs for i in (a, b)]
    columns = [i for a, b in pairs for i in (b, a)]
    return sparse.csr_matrix((np.ones(len(rows)), (rows, columns)), shape=(len(nodes), len(nodes)))


def _walk_scores(adjacency: sparse.csr_matrix) -> sparse.csr_matrix:
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    inverse = np.divide(1.0, degree, out=np.zeros_like(degree), where=degree > 0)
    transition = sparse.diags(inverse) @ adjacency
    current = transition
    scores = transition * 0.5
    for depth in range(2, DEPTH + 1):
        current = current @ transition
        scores = scores + current * (0.5**depth)
    scores.setdiag(0)
    scores.eliminate_zeros()
    return sparse.csr_matrix(scores)


def _rank(
    scores: sparse.csr_matrix, index: int, nodes: tuple[str, ...], excluded: set[int]
) -> list[int]:
    row = scores.getrow(index)
    ranked = sorted(
        zip(row.indices, row.data, strict=True), key=lambda pair: (-pair[1], nodes[pair[0]])
    )
    return [
        int(candidate) for candidate, score in ranked if score > 0 and candidate not in excluded
    ][:NEIGHBORS]


def _neighbors(
    nodes: tuple[str, ...], adjacency: sparse.csr_matrix
) -> dict[str, list[dict[str, Any]]]:
    scores = _walk_scores(adjacency)
    result = {}
    for index, node in enumerate(nodes):
        result[node] = [
            TaxonomyNeighbor(
                genre_id=nodes[candidate], score=round(float(scores[index, candidate]), 12)
            ).model_dump(mode="json")
            for candidate in _rank(scores, index, nodes, {index})
        ]
    return result


def _canonical_axes(vectors: np.ndarray, eigenvalues: np.ndarray) -> np.ndarray:
    """Fix signs and rotate a repeated two-dimensional eigenspace by fixed anchors."""
    axes = vectors[:, 1:3].copy()
    if abs(float(eigenvalues[1] - eigenvalues[2])) < AXIS_GAP:
        # Projection of fixed identity-order anchors is basis invariant.
        anchor = np.arange(1, len(axes) + 1, dtype=float)
        first = axes @ (axes.T @ anchor)
        if np.linalg.norm(first) < AXIS_GAP:
            anchor = np.sin(anchor)
            first = axes @ (axes.T @ anchor)
        if np.linalg.norm(first) < AXIS_GAP:
            raise ValueError("repeated spectral axes have no stable anchor projection")
        first /= np.linalg.norm(first)
        second = axes @ (axes.T @ np.cos(anchor))
        second -= first * np.dot(first, second)
        if np.linalg.norm(second) < AXIS_GAP:
            raise ValueError("repeated spectral axes have no stable second anchor")
        axes = np.column_stack((first, second / np.linalg.norm(second)))
    for axis in range(2):
        magnitude = np.abs(axes[:, axis])
        anchor_index = int(np.flatnonzero(magnitude >= np.max(magnitude) - AXIS_GAP)[0])
        if axes[anchor_index, axis] < 0:
            axes[:, axis] *= -1
    maximum = np.max(np.abs(axes), axis=0)
    return axes / maximum


def graph_layout(nodes: tuple[str, ...], adjacency: sparse.csr_matrix) -> dict[str, Any]:
    """Position identifiable supported components; retain all unsupported nodes as abstentions."""
    count, labels = csgraph.connected_components(adjacency, directed=False)
    coordinates, abstentions, components = [], [], []
    for label in range(count):
        indices = np.flatnonzero(labels == label)
        members = [nodes[int(index)] for index in indices]
        component_id = f"component:{members[0]}"
        local = adjacency[indices][:, indices]
        reason = None
        eigenvalues = None
        axes = None
        if len(indices) < MIN_COMPONENT:
            reason = "isolated" if len(indices) == 1 else "component_too_small"
        else:
            laplacian = csgraph.laplacian(local, normed=True)
            try:
                if len(indices) <= 8:  # noqa: PLR2004 - tiny graphs need full boundary eigenvalues.
                    eigenvalues, vectors = np.linalg.eigh(laplacian.toarray())
                else:
                    eigenvalues, vectors = eigsh(
                        laplacian,
                        k=4,
                        which="SM",
                        v0=np.sin(np.arange(1, len(indices) + 1)),
                        tol=1e-10,
                    )
                    order = np.argsort(eigenvalues)
                    eigenvalues, vectors = eigenvalues[order], vectors[:, order]
                if float(eigenvalues[3] - eigenvalues[2]) < AXIS_GAP:
                    reason = "spectral_boundary_not_identifiable"
                else:
                    axes = _canonical_axes(vectors, eigenvalues)
            except (ArpackNoConvergence, ValueError, np.linalg.LinAlgError):
                reason = "spectral_projection_unavailable"
        if axes is not None:
            coordinates.extend(
                GraphCoordinate(
                    genre_id=node,
                    component_id=component_id,
                    x=round(float(axes[i, 0]), 10),
                    y=round(float(axes[i, 1]), 10),
                ).model_dump(mode="json")
                for i, node in enumerate(members)
            )
        else:
            abstentions.extend(
                {"genre_id": node, "component_id": component_id, "reason": reason}
                for node in members
            )
        components.append(
            {
                "component_id": component_id,
                "node_count": len(members),
                "edge_count": local.nnz // 2,
                "coordinate_status": "source_graph_projection" if axes is not None else reason,
                "eigenvalues": [round(float(value), 12) for value in eigenvalues[:4]]
                if eigenvalues is not None
                else None,
            }
        )
    return {
        "revision": "open-taxonomy-source-graph-layout-v1",
        "method": "component_local_normalized_laplacian",
        "axes": "source graph structure only; no acoustic meaning",
        "across_component_semantics": False,
        "coordinates": coordinates,
        "abstentions": abstentions,
        "components": components,
    }


def evaluate_graph(nodes: tuple[str, ...], edges: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """Evaluate all frozen folds and preserve every cold or empty node in denominators."""
    node_index = {node: i for i, node in enumerate(nodes)}
    full_neighbors = _neighbors(nodes, _adjacency(nodes, edges))
    folds = []
    for fold in range(FOLDS):
        training = tuple(edge for edge in edges if edge_fold(edge) != fold)
        heldout = tuple(edge for edge in edges if edge_fold(edge) == fold)
        adjacency = _adjacency(nodes, training)
        scores = _walk_scores(adjacency)
        degrees = np.asarray(adjacency.sum(axis=1)).ravel()
        _, training_components = csgraph.connected_components(adjacency, directed=False)
        baseline_order = sorted(range(len(nodes)), key=lambda i: (-degrees[i], nodes[i]))
        targets: dict[int, set[int]] = {}
        for first, second in heldout:
            a, b = node_index[first], node_index[second]
            targets.setdefault(a, set()).add(b)
            targets.setdefault(b, set()).add(a)
        hits = baseline_hits = positive_count = 0
        macro = baseline_macro = stability = 0.0
        for i, node in enumerate(nodes):
            excluded = {i, *map(int, adjacency.getrow(i).indices)}
            predicted = set(_rank(scores, i, nodes, excluded))
            # Apply rank truncation before converting to an unordered set.
            baseline = set(
                [candidate for candidate in baseline_order if candidate not in excluded][:NEIGHBORS]
            )
            positives = targets.get(i, set())
            hit, base_hit = len(predicted & positives), len(baseline & positives)
            hits += hit
            baseline_hits += base_hit
            positive_count += len(positives)
            if positives:
                macro += hit / len(positives)
                baseline_macro += base_hit / len(positives)
            before = {row["genre_id"] for row in full_neighbors[node]}
            after = {nodes[candidate] for candidate in _rank(scores, i, nodes, {i})}
            stability += len(before & after) / len(before | after) if before | after else 0.0
        folds.append(
            {
                "fold": fold,
                "train_edge_count": len(training),
                "heldout_undirected_edges": len(heldout),
                "directed_target_count": positive_count,
                "hits_at_10": hits,
                "degree_baseline_hits_at_10": baseline_hits,
                "micro_recall_at_10": hits / positive_count if positive_count else 0.0,
                "degree_baseline_micro_recall_at_10": baseline_hits / positive_count
                if positive_count
                else 0.0,
                "all_node_macro_recall_at_10": macro / len(nodes),
                "degree_baseline_all_node_macro_recall_at_10": baseline_macro / len(nodes),
                "all_node_neighbor_jaccard": stability / len(nodes),
                "cold_training_nodes": int(np.count_nonzero(degrees == 0)),
                "cold_query_directed_targets": sum(
                    len(positives) for i, positives in targets.items() if degrees[i] == 0
                ),
                "disconnected_directed_targets": int(
                    sum(
                        training_components[i] != training_components[target]
                        for i, positives in targets.items()
                        for target in positives
                    )
                ),
                "nodes_without_heldout_targets": len(nodes) - len(targets),
            }
        )
    total_targets = sum(row["directed_target_count"] for row in folds)
    return {
        "scope": "source_P279_edge_reconstruction_only",
        "independent_musical_validity": False,
        "node_count": len(nodes),
        "all_node_fold_denominator": len(nodes) * FOLDS,
        "directed_target_count": total_targets,
        "cold_query_directed_targets": sum(row["cold_query_directed_targets"] for row in folds),
        "disconnected_directed_targets": sum(row["disconnected_directed_targets"] for row in folds),
        "folds": folds,
        "micro_recall_at_10": sum(row["hits_at_10"] for row in folds) / total_targets
        if total_targets
        else 0.0,
        "degree_baseline_micro_recall_at_10": sum(
            row["degree_baseline_hits_at_10"] for row in folds
        )
        / total_targets
        if total_targets
        else 0.0,
        "all_node_macro_recall_at_10": sum(row["all_node_macro_recall_at_10"] for row in folds)
        / FOLDS,
        "degree_baseline_all_node_macro_recall_at_10": sum(
            row["degree_baseline_all_node_macro_recall_at_10"] for row in folds
        )
        / FOLDS,
        "all_node_neighbor_jaccard": sum(row["all_node_neighbor_jaccard"] for row in folds) / FOLDS,
    }


def build_taxonomy_neighborhoods(
    projection: dict[str, Any],
    *,
    projection_path: Path,
    source_receipt_path: Path,
    protocol_path: Path,
) -> dict[str, Any]:
    """Construct one source-bound graph, layout and heldout report from verified inputs."""
    if json.loads(projection_path.read_bytes()) != projection:
        raise ValueError("taxonomy projection differs from its bound source bytes")
    if sha256_file(protocol_path)[0] != PROTOCOL_SHA256:
        raise ValueError("frozen taxonomy evaluation protocol bytes differ")
    protocol = json.loads(protocol_path.read_bytes())
    if (
        protocol["seed"] != SEED
        or protocol["fold_count"] != FOLDS
        or protocol["maximum_depth"] != DEPTH
        or protocol["neighbor_count"] != NEIGHBORS
    ):
        raise ValueError("unsupported frozen taxonomy evaluation protocol")
    nodes = tuple(sorted(row["qid"] for row in projection["entities"]))
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("taxonomy source cohort must contain unique QIDs")
    edges = selected_p279_edges(projection)
    adjacency = _adjacency(nodes, edges)
    artifact = {
        "revision": REVISION,
        "node_ids": list(nodes),
        "selected_p279_undirected_edges": [list(edge) for edge in edges],
        "neighbors": _neighbors(nodes, adjacency),
        "layout": graph_layout(nodes, adjacency),
        "evaluation": evaluate_graph(nodes, edges),
        "excluded_p31_claim_count": sum(
            row["property_id"] == "P31" for row in projection["claims"]
        ),
        "p279_outside_selected_cohort_count": sum(
            row["property_id"] == "P279"
            and (row["genre_qid"] not in nodes or row["value_qid"] not in nodes)
            for row in projection["claims"]
        ),
    }
    receipt = GraphReceipt(
        projection_sha256=sha256_file(projection_path)[0],
        source_receipt_sha256=sha256_file(source_receipt_path)[0],
        protocol_sha256=sha256_file(protocol_path)[0],
        builder_sha256=sha256_file(Path(__file__))[0],
        settings=GraphSettings(),
        output_sha256=hashlib.sha256(canonical_json(artifact)).hexdigest(),
    )
    artifact["receipt"] = receipt.model_dump(mode="json")
    return artifact
