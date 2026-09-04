"""Fit a full Every Noise-compatible map from H3 memberships, not H2 coordinates."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import laplacian
from scipy.sparse.linalg import eigsh

from musix.models.historical_signal import (
    CoordinateComparison,
    HistoricalSignalAblation,
    HistoricalSignalArtifact,
    HistoricalSignalCommunity,
    HistoricalSignalGeometry,
    HistoricalSignalHierarchyNode,
    HistoricalSignalInput,
    HistoricalSignalLOD,
    HistoricalSignalNeighbor,
    HistoricalSignalNode,
    HistoricalSignalQuality,
    HistoricalSignalSettings,
    HistoricalSignalTile,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from musix.models.historical import HistoricalCompatibilityManifest

type Pair = tuple[int, int]
_ASPECT = 16 / 9
_LOD_BUDGETS = (24, 240, 1_200)
_TILE_GRID = 16
_MINIMUM_ALIGNMENT_NODES = 3
_OVERVIEW_SEED_MINIMUM_DISTANCE = 0.08
_MINIMUM_SPECTRAL_COMPONENT_SIZE = 4
_HIERARCHY_SUBCOMMUNITY_LEVEL = 1
_HIERARCHY_MICROGENRE_LEVEL = 2
_LEXICAL_MIN_WORD_LENGTH = 3
_LEXICAL_TRIGRAM_MIN_WORD_LENGTH = 4
_LEXICAL_MAX_DOCUMENT_FREQUENCY = 64
_LEXICAL_SIMILARITY_CUTOFF = 0.02
_DISPLAY_HEAD_MIN_HITS = 2


class HistoricalSignalInputError(ValueError):
    """Reject a membership database that cannot prove the requested H3 source."""


@dataclass(frozen=True, slots=True)
class _SimilarityCandidate:
    """One sparse pair with distinct explainable similarity statistics."""

    weighted_jaccard: float
    cosine: float
    idf_overlap: float
    shared_artist_count: int


@dataclass(frozen=True, slots=True)
class _HierarchyGroup:
    """A disjoint topology-only cohort while constructing a bounded zoom hierarchy."""

    members: tuple[int, ...]

    @property
    def member_count(self) -> int:
        return len(self.members)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _hash_unit(seed: int, *parts: str) -> float:
    digest = hashlib.sha256(f"{seed}\0".encode() + "\0".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)


def _legacy_vocabulary(manifest: HistoricalCompatibilityManifest) -> tuple[tuple[str, str], ...]:
    """Read IDs and names only; this function deliberately never accesses coordinates."""
    normalized: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for genre in manifest.genres:
        normalized[_normalize_name(genre.name)].append((genre.external_id, genre.name))
    result = [items[0] for _name, items in sorted(normalized.items()) if len(items) == 1]
    if len(result) != len(manifest.genres):
        raise HistoricalSignalInputError("legacy genre names must be unique after normalization")
    return tuple(sorted(result))


def _load_memberships(
    database_path: Path,
    vocabulary: tuple[tuple[str, str], ...],
    expected_h3_sha256: str,
) -> tuple[dict[str, set[str]], str, int]:
    """Load source-scoped H3 memberships using only IDs/names, never map geometry."""
    name_to_id = {_normalize_name(name): genre_id for genre_id, name in vocabulary}
    memberships: dict[str, set[str]] = {genre_id: set() for genre_id, _name in vocabulary}
    query = """
        SELECT genre.name, observation.source_artist_id, observation.source_artifact_sha256
        FROM historical_genre_artist_observations AS observation
        JOIN genres AS genre ON genre.id = observation.genre_id
        WHERE observation.observation_role = 'genre_page_member'
          AND observation.source_artist_id IS NOT NULL
        ORDER BY genre.name COLLATE NOCASE, observation.source_artist_id
    """
    source_hashes: set[str] = set()
    rows = 0
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        # The sealed input is read-only; keep the deterministic ORDER BY sort off disk.
        connection.execute("PRAGMA temp_store = MEMORY")
        for genre_name, artist_id, source_hash in connection.execute(query):
            source_hashes.add(str(source_hash))
            genre_id = name_to_id.get(_normalize_name(str(genre_name)))
            if genre_id is None:
                continue
            memberships[genre_id].add(str(artist_id))
            rows += 1
    if source_hashes != {expected_h3_sha256}:
        raise HistoricalSignalInputError(
            "membership database must contain exactly the declared H3 artifact hash"
        )
    return memberships, _sha256_path(database_path), rows


def _idf_candidates(
    memberships: Mapping[str, set[str]],
    settings: HistoricalSignalSettings,
) -> tuple[dict[Pair, _SimilarityCandidate], dict[str, int]]:
    """Build bounded weighted-Jaccard/cosine candidates from the sparse bipartite matrix."""
    genre_ids = tuple(sorted(memberships))
    index = {genre_id: position for position, genre_id in enumerate(genre_ids)}
    artist_genres: dict[str, list[int]] = defaultdict(list)
    for genre_id in sorted(memberships):
        # Memberships are sets after ingestion.  Their iteration order depends
        # on PYTHONHASHSEED, so preserve a canonical artist insertion order
        # before the later floating-point reductions.
        for artist_id in sorted(memberships[genre_id]):
            artist_genres[artist_id].append(index[genre_id])
    norm_sum = [0.0] * len(genre_ids)
    norm_square = [0.0] * len(genre_ids)
    overlap: dict[Pair, list[float]] = {}
    artist_degrees: dict[str, int] = {}
    total_genres = len(genre_ids)
    for artist_id in sorted(artist_genres):
        positions = artist_genres[artist_id]
        unique_positions = sorted(set(positions))
        degree = len(unique_positions)
        artist_degrees[artist_id] = degree
        if degree > settings.maximum_artist_genre_degree:
            continue
        weight = math.log((total_genres + 1) / (degree + 1)) + 1.0
        for position in unique_positions:
            norm_sum[position] += weight
            norm_square[position] += weight * weight
        for offset, left in enumerate(unique_positions):
            for right in unique_positions[offset + 1 :]:
                key = (left, right)
                entry = overlap.setdefault(key, [0.0, 0.0, 0.0])
                entry[0] += weight
                entry[1] += weight * weight
                entry[2] += 1.0
    candidates: dict[Pair, _SimilarityCandidate] = {}
    for (left, right), (jaccard_overlap, cosine_overlap, shared) in overlap.items():
        union = norm_sum[left] + norm_sum[right] - jaccard_overlap
        denominator = math.sqrt(norm_square[left] * norm_square[right])
        if union <= 0.0 or denominator <= 0.0:
            continue
        candidates[(left, right)] = _SimilarityCandidate(
            weighted_jaccard=jaccard_overlap / union,
            cosine=cosine_overlap / denominator,
            idf_overlap=jaccard_overlap,
            shared_artist_count=int(shared),
        )
    return candidates, artist_degrees


def _knn(
    genre_ids: tuple[str, ...],
    candidates: Mapping[Pair, _SimilarityCandidate],
    settings: HistoricalSignalSettings,
) -> tuple[HistoricalSignalNeighbor, ...]:
    per_genre: list[list[tuple[int, _SimilarityCandidate]]] = [[] for _ in genre_ids]
    for (left, right), candidate in candidates.items():
        per_genre[left].append((right, candidate))
        per_genre[right].append((left, candidate))
    result: list[HistoricalSignalNeighbor] = []
    for position, candidates_for_genre in enumerate(per_genre):
        ranked = sorted(
            candidates_for_genre,
            key=lambda item: (
                -item[1].weighted_jaccard,
                -item[1].cosine,
                -item[1].shared_artist_count,
                genre_ids[item[0]],
            ),
        )[: settings.neighbors_per_genre]
        for rank, (neighbor, candidate) in enumerate(ranked, start=1):
            result.append(
                HistoricalSignalNeighbor(
                    genre_id=genre_ids[position],
                    neighbor_genre_id=genre_ids[neighbor],
                    rank=rank,
                    weighted_jaccard=round(candidate.weighted_jaccard, 12),
                    cosine=round(candidate.cosine, 12),
                    idf_overlap=round(candidate.idf_overlap, 12),
                    shared_artist_count=candidate.shared_artist_count,
                )
            )
    return tuple(result)


def _weighted_graph(
    genre_ids: tuple[str, ...],
    neighbors: Iterable[HistoricalSignalNeighbor],
    *,
    reciprocal: bool = False,
) -> list[dict[int, float]]:
    index = {genre_id: position for position, genre_id in enumerate(genre_ids)}
    directed: dict[tuple[int, int], float] = {}
    for edge in neighbors:
        left, right = index[edge.genre_id], index[edge.neighbor_genre_id]
        directed[(left, right)] = max(
            directed.get((left, right), 0.0), float(edge.weighted_jaccard)
        )
    graph: list[dict[int, float]] = [{} for _ in genre_ids]
    for (left, right), weight in sorted(directed.items()):
        if reciprocal and (right, left) not in directed:
            continue
        graph[left][right] = max(graph[left].get(right, 0.0), weight)
        graph[right][left] = max(graph[right].get(left, 0.0), weight)
    return graph


def _components(graph: list[dict[int, float]]) -> list[int]:
    result = [-1] * len(graph)
    component = 0
    for root in range(len(graph)):
        if result[root] >= 0:
            continue
        result[root] = component
        queue = deque((root,))
        while queue:
            current = queue.popleft()
            for neighbor in graph[current]:
                if result[neighbor] < 0:
                    result[neighbor] = component
                    queue.append(neighbor)
        component += 1
    return result


def _group_components(
    group: _HierarchyGroup, graph: list[dict[int, float]]
) -> tuple[_HierarchyGroup, ...]:
    """Split a cohort into its graph-connected pieces without inspecting names or geometry."""
    allowed = set(group.members)
    remaining = set(group.members)
    components: list[_HierarchyGroup] = []
    while remaining:
        root = min(remaining)
        remaining.remove(root)
        found = [root]
        queue = deque((root,))
        while queue:
            current = queue.popleft()
            for neighbor in graph[current]:
                if neighbor in remaining and neighbor in allowed:
                    remaining.remove(neighbor)
                    found.append(neighbor)
                    queue.append(neighbor)
        components.append(_HierarchyGroup(tuple(sorted(found))))
    return tuple(components)


def _partition_connected_group(
    group: _HierarchyGroup,
    genre_ids: tuple[str, ...],
    maximum_members: int,
    positions: np.ndarray | None,
) -> tuple[_HierarchyGroup, ...]:
    """Partition by a stable longest embedding axis in one bounded sort.

    The retained H3 graph is responsible for the embedding in ``positions``. Sorting
    that embedding once and taking balanced contiguous chunks keeps this operation
    deterministic and O(n log n), instead of repeatedly traversing weighted shortest
    paths for every candidate seed.
    """
    if group.member_count <= maximum_members:
        return (group,)
    members = list(group.members)
    if positions is None:
        ranked = sorted(members, key=lambda member: genre_ids[member])
    else:
        values = positions[members]
        spread = np.ptp(values, axis=0)
        axis = 0 if float(spread[0]) >= float(spread[1]) else 1
        ranked = sorted(
            members,
            key=lambda member: (float(positions[member, axis]), genre_ids[member]),
        )
    part_count = math.ceil(group.member_count / maximum_members)
    # Balanced chunks ensure every bucket is within the configured bound while
    # preserving the order learned from the graph embedding.
    base, remainder = divmod(group.member_count, part_count)
    partitions: list[_HierarchyGroup] = []
    offset = 0
    for ordinal in range(part_count):
        size = base + (1 if ordinal < remainder else 0)
        partitions.append(_HierarchyGroup(tuple(sorted(ranked[offset : offset + size]))))
        offset += size
    return tuple(partitions)


def _pack_disconnected_components(
    components: tuple[_HierarchyGroup, ...],
    genre_ids: tuple[str, ...],
    maximum_members: int,
) -> tuple[_HierarchyGroup, ...]:
    """Bundle small disconnected components deterministically without inventing semantic links."""
    ordered = sorted(
        components,
        key=lambda component: (
            -component.member_count,
            tuple(genre_ids[item] for item in component.members),
        ),
    )
    bins: list[list[int]] = []
    for component in ordered:
        for bucket in bins:
            if len(bucket) + component.member_count <= maximum_members:
                bucket.extend(component.members)
                break
        else:
            bins.append(list(component.members))
    return tuple(_HierarchyGroup(tuple(sorted(bucket))) for bucket in bins)


def _partition_graph(
    members: tuple[int, ...],
    graph: list[dict[int, float]],
    genre_ids: tuple[str, ...],
    maximum_members: int,
    positions: np.ndarray | None = None,
) -> tuple[_HierarchyGroup, ...]:
    """Bound graph-derived hierarchy groups; disconnected regions stay visibly disconnected."""
    group = _HierarchyGroup(tuple(sorted(members)))
    components = _group_components(group, graph)
    if len(components) == 1:
        partitions = list(
            _partition_connected_group(components[0], genre_ids, maximum_members, positions)
        )
    else:
        oversized = [
            partition
            for component in components
            if component.member_count > maximum_members
            for partition in _partition_connected_group(
                component, genre_ids, maximum_members, positions
            )
        ]
        small = _pack_disconnected_components(
            tuple(
                component for component in components if component.member_count <= maximum_members
            ),
            genre_ids,
            maximum_members,
        )
        partitions = oversized + list(small)
    return tuple(
        sorted(partitions, key=lambda group: tuple(genre_ids[item] for item in group.members))
    )


def _hierarchy_component_count(group: _HierarchyGroup, graph: list[dict[int, float]]) -> int:
    """Count original H3 graph components represented by an aggregate cohort."""
    return len(_group_components(group, graph))


def _hierarchy_representative(
    group: _HierarchyGroup,
    graph: list[dict[int, float]],
    genre_ids: tuple[str, ...],
) -> int:
    """Choose a label representative from internal H3-similarity degree with stable ties."""
    allowed = set(group.members)
    return min(
        group.members,
        key=lambda member: (
            -sum(weight for neighbor, weight in graph[member].items() if neighbor in allowed),
            genre_ids[member],
        ),
    )


def _hierarchy_centroid(group: _HierarchyGroup, positions: np.ndarray) -> tuple[float, float]:
    """Place a graph aggregate at the deterministic centroid of its learned members."""
    centroid = np.mean(positions[list(group.members)], axis=0)
    return round(float(centroid[0] * _ASPECT), 12), round(float(centroid[1]), 12)


def _contract_groups(
    graph: list[dict[int, float]], groups: tuple[_HierarchyGroup, ...]
) -> list[dict[int, float]]:
    """Contract a partition while retaining internal weight as deterministic self-loops."""
    owner = {member: ordinal for ordinal, group in enumerate(groups) for member in group.members}
    contracted: list[dict[int, float]] = [defaultdict(float) for _group in groups]
    for left, neighbors in enumerate(graph):
        for right, weight in neighbors.items():
            if right < left:
                continue
            left_group, right_group = owner[left], owner[right]
            if left == right:
                contracted[left_group][left_group] += weight
            elif left_group == right_group:
                contracted[left_group][left_group] += 2.0 * weight
            else:
                contracted[left_group][right_group] += weight
                contracted[right_group][left_group] += weight
    return [dict(neighbors) for neighbors in contracted]


def _modularity_groups(
    graph: list[dict[int, float]],
    groups: tuple[_HierarchyGroup, ...],
    genre_ids: tuple[str, ...],
    *,
    seed: int,
    resolution: float = 1.0,
) -> tuple[_HierarchyGroup, ...]:
    """Perform deterministic positive modularity moves on a weighted sparse graph."""
    labels = list(range(len(groups)))
    degree = [sum(neighbors.values()) for neighbors in graph]
    total_weight_twice = sum(degree)
    if total_weight_twice == 0.0:
        return groups
    totals = degree.copy()
    order = sorted(
        range(len(groups)),
        key=lambda ordinal: hashlib.sha256(
            f"{seed}\0{','.join(genre_ids[item] for item in groups[ordinal].members)}".encode()
        ).hexdigest(),
    )
    for _iteration in range(80):
        changed = False
        for item in order:
            current = labels[item]
            totals[current] -= degree[item]
            scores: dict[int, float] = defaultdict(float)
            for neighbor, weight in graph[item].items():
                if neighbor != item:
                    scores[labels[neighbor]] += weight
            scores[current] += 0.0
            current_score = (
                scores[current] - resolution * degree[item] * totals[current] / total_weight_twice
            )
            candidate = min(
                scores,
                key=lambda label: (
                    -(
                        scores[label]
                        - resolution * degree[item] * totals[label] / total_weight_twice
                    ),
                    label,
                ),
            )
            candidate_score = (
                scores[candidate]
                - resolution * degree[item] * totals[candidate] / total_weight_twice
            )
            if candidate_score <= current_score + 1e-15:
                candidate = current
            totals[candidate] += degree[item]
            changed = changed or candidate != current
            labels[item] = candidate
        if not changed:
            break
    members: dict[int, list[int]] = defaultdict(list)
    for ordinal, label in enumerate(labels):
        members[label].extend(groups[ordinal].members)
    return tuple(
        _HierarchyGroup(tuple(sorted(group_members)))
        for group_members in sorted(
            members.values(), key=lambda value: tuple(genre_ids[item] for item in sorted(value))
        )
    )


def _natural_subcommunities(
    graph: list[dict[int, float]], genre_ids: tuple[str, ...], seed: int
) -> tuple[_HierarchyGroup, ...]:
    """Resolve reciprocal H3 affinity before any name-derived coarse grouping."""
    groups = tuple(_HierarchyGroup((member,)) for member in range(len(graph)))
    current_graph = graph
    for round_ordinal in range(4):
        moved = _modularity_groups(current_graph, groups, genre_ids, seed=seed + round_ordinal)
        if len(moved) == len(groups):
            break
        current_graph = _contract_groups(current_graph, moved)
        groups = moved
    return groups


def _lexical_meta_graph(  # noqa: PLR0912
    groups: tuple[_HierarchyGroup, ...], names: Mapping[str, str], genre_ids: tuple[str, ...]
) -> list[dict[int, float]]:
    """Build sparse TF-IDF word/character lexical affinity without all-pairs comparison."""
    token_counts: list[dict[str, float]] = []
    document_frequency: dict[str, int] = defaultdict(int)
    for group in groups:
        counts: dict[str, float] = defaultdict(float)
        for member in group.members:
            for word in re.findall(r"[a-z0-9]+", names[genre_ids[member]].casefold()):
                if len(word) < _LEXICAL_MIN_WORD_LENGTH:
                    continue
                counts[f"word:{word}"] += 1.0
                if len(word) >= _LEXICAL_TRIGRAM_MIN_WORD_LENGTH:
                    for start in range(len(word) - 2):
                        counts[f"char:{word[start : start + 3]}"] += 0.2
        token_counts.append(dict(counts))
        for token in counts:
            document_frequency[token] += 1
    inverted: dict[str, list[tuple[int, float]]] = defaultdict(list)
    norms: list[float] = []
    for ordinal, counts in enumerate(token_counts):
        weighted: dict[str, float] = {}
        for token, count in counts.items():
            frequency = document_frequency[token]
            if frequency > _LEXICAL_MAX_DOCUMENT_FREQUENCY:
                continue
            weighted[token] = count * (math.log((len(groups) + 1) / (frequency + 1)) + 1.0)
        norms.append(math.sqrt(sum(value * value for value in weighted.values())))
        for token, value in weighted.items():
            inverted[token].append((ordinal, value))
    dot_products: dict[tuple[int, int], float] = defaultdict(float)
    for entries in inverted.values():
        for offset, (left, left_weight) in enumerate(entries):
            for right, right_weight in entries[offset + 1 :]:
                dot_products[(left, right)] += left_weight * right_weight
    graph: list[dict[int, float]] = [{} for _group in groups]
    for (left, right), dot_product in sorted(dot_products.items()):
        denominator = norms[left] * norms[right]
        similarity = dot_product / denominator if denominator else 0.0
        if similarity >= _LEXICAL_SIMILARITY_CUTOFF:
            graph[left][right] = similarity
            graph[right][left] = similarity
    return graph


def _normalized_meta_graph(
    graph: list[dict[int, float]], groups: tuple[_HierarchyGroup, ...]
) -> list[dict[int, float]]:
    """Use the union H3 graph between natural communities, normalised by their sizes."""
    owner = {member: ordinal for ordinal, group in enumerate(groups) for member in group.members}
    raw: list[dict[int, float]] = [defaultdict(float) for _group in groups]
    for left, neighbors in enumerate(graph):
        for right, weight in neighbors.items():
            if right <= left or owner[left] == owner[right]:
                continue
            raw[owner[left]][owner[right]] += weight
            raw[owner[right]][owner[left]] += weight
    normalized: list[dict[int, float]] = [{} for _group in groups]
    for left, neighbors in enumerate(raw):
        for right, weight in neighbors.items():
            if right <= left:
                continue
            denominator = math.sqrt(groups[left].member_count * groups[right].member_count)
            normalized[left][right] = weight / denominator
            normalized[right][left] = normalized[left][right]
    return normalized


def _coarse_umbrellas(
    union_graph: list[dict[int, float]],
    natural: tuple[_HierarchyGroup, ...],
    names: Mapping[str, str],
    genre_ids: tuple[str, ...],
    seed: int,
) -> tuple[_HierarchyGroup, ...]:
    """Coarsen natural H3 communities with sparse lexical affinity for honest display regions."""
    graph = _normalized_meta_graph(union_graph, natural)
    lexical = _lexical_meta_graph(natural, names, genre_ids)
    for left, neighbors in enumerate(lexical):
        for right, weight in neighbors.items():
            graph[left][right] = graph[left].get(right, 0.0) + 0.8 * weight
    coarse = _modularity_groups(graph, natural, genre_ids, seed=seed, resolution=1.5)
    # Groups with no union or lexical affinity have no semantic parent evidence.  They are one
    # explicitly disconnected display region, never a claimed taxonomy or balanced bin.
    linked_members = {member for neighbors in graph for member in neighbors}
    disconnected = tuple(
        group for ordinal, group in enumerate(natural) if ordinal not in linked_members
    )
    if len(disconnected) > 1:
        disconnected_members = {member for group in disconnected for member in group.members}
        retained = tuple(
            group for group in coarse if not set(group.members).issubset(disconnected_members)
        )
        coarse = (*retained, _HierarchyGroup(tuple(sorted(disconnected_members))))
    # Re-evaluate the resulting meta communities from their original sparse signals.  This is
    # multilevel modularity coarsening, not balanced packing: every merge remains a positive
    # affinity/modularity move on the freshly contracted evidence graph.
    for round_ordinal in range(4):
        meta = _normalized_meta_graph(union_graph, coarse)
        lexical = _lexical_meta_graph(coarse, names, genre_ids)
        for left, neighbors in enumerate(lexical):
            for right, weight in neighbors.items():
                meta[left][right] = meta[left].get(right, 0.0) + 0.8 * weight
        moved = _modularity_groups(
            meta, coarse, genre_ids, seed=seed + round_ordinal + 1, resolution=1.5
        )
        if len(moved) == len(coarse):
            break
        coarse = moved
    return tuple(sorted(coarse, key=lambda group: tuple(genre_ids[item] for item in group.members)))


def _display_family(
    group: _HierarchyGroup, names: Mapping[str, str], genre_ids: tuple[str, ...]
) -> str | None:
    """Choose a broad, source-name-derived display family for an H3 natural community."""
    words = [
        word
        for member in group.members
        for word in re.findall(r"[a-z0-9]+", names[genre_ids[member]].casefold())
    ]
    counts = Counter(words)
    latin_families = {
        "Latin & Caribbean — salsa": ("salsa", "reggaeton", "bachata", "merengue", "cumbia"),
        "Latin & Caribbean — samba": ("samba", "bossa"),
        "Latin & Caribbean — regional Mexican": ("norteno",),
        "Latin & Caribbean": ("latin",),
    }
    latin_scores = {
        family: sum(counts[word] for word in family_words)
        for family, family_words in latin_families.items()
    }
    _latin_label, latin_hits = min(latin_scores.items(), key=lambda item: (-item[1], item[0]))
    global_hits = sum(
        counts[word]
        for word in (
            "indian",
            "hindustani",
            "carnatic",
            "african",
            "arabic",
            "turkish",
            "kurdish",
            "persian",
        )
    )
    if latin_hits >= _DISPLAY_HEAD_MIN_HITS:
        return "Latin & Caribbean"
    if global_hits >= _DISPLAY_HEAD_MIN_HITS:
        return "Global & traditional"
    hip_hop_hits = sum(
        bool(re.search(r"\bhip[ -]hop\b|\brap\b", names[genre_ids[member]].casefold()))
        for member in group.members
    )
    scores = {
        "Hip-hop": hip_hop_hits,
        "Metal": counts["metal"],
        "Jazz": counts["jazz"],
        "Classical": counts["classical"] + counts["classique"],
        "Electronic": sum(
            counts[word] for word in ("house", "techno", "edm", "electro", "electronic", "idm")
        ),
        "Rock": counts["rock"],
        "Pop": counts["pop"],
        "Latin & Caribbean": latin_hits,
        "Global & traditional": global_hits,
        "Reggae": counts["reggae"] + counts["dancehall"],
        "Folk & country": counts["folk"] + counts["country"],
        "Blues": counts["blues"],
    }
    label, score = min(scores.items(), key=lambda item: (-item[1], item[0]))
    return label if score >= _DISPLAY_HEAD_MIN_HITS else None


def _semantic_umbrellas(
    natural: tuple[_HierarchyGroup, ...],
    names: Mapping[str, str],
    genre_ids: tuple[str, ...],
) -> tuple[tuple[_HierarchyGroup, ...], dict[tuple[int, ...], str]]:
    """Preserve natural H3 groups while using explicit observed name heads for overview families."""
    by_family: dict[str, list[int]] = defaultdict(list)
    unresolved: list[_HierarchyGroup] = []
    for group in natural:
        family = _display_family(group, names, genre_ids)
        if family is None:
            unresolved.append(group)
        else:
            by_family[family].extend(group.members)
    labels = {tuple(sorted(members)): family for family, members in by_family.items()}
    coarse: list[_HierarchyGroup] = []
    # Residual natural communities have no repeated broad lexical head.  Their sole overview
    # parent is an explicitly non-taxonomic Other region, not a fabricated semantic family.
    if unresolved:
        other = _HierarchyGroup(
            tuple(sorted(member for group in unresolved for member in group.members))
        )
        coarse.append(other)
        labels[other.members] = "Other / unplaced"
    umbrellas = tuple(
        _HierarchyGroup(tuple(sorted(members))) for members in by_family.values()
    ) + tuple(coarse)
    return (
        tuple(
            sorted(umbrellas, key=lambda group: tuple(genre_ids[item] for item in group.members))
        ),
        labels,
    )


def _graph_hierarchy(  # noqa: PLR0913, PLR0917
    graph: list[dict[int, float]],
    reciprocal_graph: list[dict[int, float]],
    genre_ids: tuple[str, ...],
    names: Mapping[str, str],
    positions: np.ndarray,
    settings: HistoricalSignalSettings,
) -> tuple[tuple[HistoricalSignalHierarchyNode, ...], dict[int, tuple[str, str, str]]]:
    """Emit H3 natural communities below lexically coarsened evidence-derived regions."""
    natural = _natural_subcommunities(reciprocal_graph, genre_ids, settings.embedding_seed)
    umbrellas, display_labels = _semantic_umbrellas(natural, names, genre_ids)
    hierarchy: list[HistoricalSignalHierarchyNode] = []
    assignments: dict[int, tuple[str, str, str]] = {}
    for umbrella_ordinal, umbrella in enumerate(umbrellas):
        umbrella_id = f"graph:umbrella:{umbrella_ordinal:03d}"
        umbrella_members = set(umbrella.members)
        subcommunities = tuple(
            group for group in natural if set(group.members).issubset(umbrella_members)
        )
        if not subcommunities:
            raise ValueError("every lexical umbrella must retain at least one natural subcommunity")
        subcommunity_ids = tuple(
            f"{umbrella_id}:sub:{subcommunity_ordinal:03d}"
            for subcommunity_ordinal in range(len(subcommunities))
        )
        umbrella_representative = _hierarchy_representative(umbrella, graph, genre_ids)
        umbrella_x, umbrella_y = _hierarchy_centroid(umbrella, positions)
        hierarchy.append(
            HistoricalSignalHierarchyNode(
                hierarchy_id=umbrella_id,
                children_ids=subcommunity_ids,
                level=0,
                member_count=umbrella.member_count,
                component_count=_hierarchy_component_count(umbrella, graph),
                representative_genre_id=genre_ids[umbrella_representative],
                representative_label=display_labels.get(
                    umbrella.members, names[genre_ids[umbrella_representative]]
                ),
                x=umbrella_x,
                y=umbrella_y,
                provenance="graph_and_genre_name_derived",
                connectivity=(
                    "connected"
                    if _hierarchy_component_count(umbrella, graph) == 1
                    else "disconnected_bundle"
                ),
            )
        )
        for subcommunity_ordinal, subcommunity in enumerate(subcommunities):
            subcommunity_id = subcommunity_ids[subcommunity_ordinal]
            microgenres = _partition_graph(
                subcommunity.members,
                reciprocal_graph,
                genre_ids,
                settings.hierarchy_microgenre_max_members,
                positions,
            )
            microgenre_ids = tuple(
                f"{subcommunity_id}:micro:{microgenre_ordinal:03d}"
                for microgenre_ordinal in range(len(microgenres))
            )
            subcommunity_representative = _hierarchy_representative(subcommunity, graph, genre_ids)
            subcommunity_x, subcommunity_y = _hierarchy_centroid(subcommunity, positions)
            hierarchy.append(
                HistoricalSignalHierarchyNode(
                    hierarchy_id=subcommunity_id,
                    parent_id=umbrella_id,
                    children_ids=microgenre_ids,
                    level=1,
                    member_count=subcommunity.member_count,
                    component_count=_hierarchy_component_count(subcommunity, graph),
                    representative_genre_id=genre_ids[subcommunity_representative],
                    representative_label=names[genre_ids[subcommunity_representative]],
                    x=subcommunity_x,
                    y=subcommunity_y,
                    connectivity=(
                        "connected"
                        if _hierarchy_component_count(subcommunity, graph) == 1
                        else "disconnected_bundle"
                    ),
                )
            )
            for microgenre_ordinal, microgenre in enumerate(microgenres):
                microgenre_id = microgenre_ids[microgenre_ordinal]
                representative = _hierarchy_representative(microgenre, graph, genre_ids)
                microgenre_x, microgenre_y = _hierarchy_centroid(microgenre, positions)
                hierarchy.append(
                    HistoricalSignalHierarchyNode(
                        hierarchy_id=microgenre_id,
                        parent_id=subcommunity_id,
                        level=2,
                        member_count=microgenre.member_count,
                        component_count=_hierarchy_component_count(microgenre, graph),
                        representative_genre_id=genre_ids[representative],
                        representative_label=names[genre_ids[representative]],
                        x=microgenre_x,
                        y=microgenre_y,
                        connectivity=(
                            "connected"
                            if _hierarchy_component_count(microgenre, graph) == 1
                            else "disconnected_bundle"
                        ),
                    )
                )
                for member in microgenre.members:
                    assignments[member] = (umbrella_id, subcommunity_id, microgenre_id)
    return tuple(hierarchy), assignments


def _microgenre_internal_edge_fraction(
    graph: list[dict[int, float]], assignments: Mapping[int, tuple[str, str, str]]
) -> float:
    """Measure how much retained H3 similarity remains inside the finest graph grouping."""
    total_weight = 0.0
    internal_weight = 0.0
    for left, neighbors in enumerate(graph):
        for right, weight in neighbors.items():
            if right <= left:
                continue
            total_weight += weight
            if assignments[left][2] == assignments[right][2]:
                internal_weight += weight
    return internal_weight / total_weight if total_weight else 0.0


def _embed(
    genre_ids: tuple[str, ...], graph: list[dict[int, float]], settings: HistoricalSignalSettings
) -> np.ndarray:
    """Use deterministic anchored neighbor diffusion, a sparse topology-only 2D embedding."""
    anchors = np.array(
        [
            (
                _hash_unit(settings.embedding_seed, genre_id, "x"),
                _hash_unit(settings.embedding_seed, genre_id, "y"),
            )
            for genre_id in genre_ids
        ],
        dtype=np.float64,
    )
    positions = anchors.copy()
    for _iteration in range(settings.embedding_iterations):
        updated = anchors * 0.30
        for position, weighted_neighbors in enumerate(graph):
            if not weighted_neighbors:
                updated[position] += positions[position] * 0.70
                continue
            total = sum(weighted_neighbors.values())
            average = (
                sum(
                    (
                        positions[neighbor] * weight
                        for neighbor, weight in weighted_neighbors.items()
                    ),
                    start=np.zeros(2, dtype=np.float64),
                )
                / total
            )
            updated[position] += average * 0.70
        positions = updated
    lower = np.quantile(positions, 0.01, axis=0)
    upper = np.quantile(positions, 0.99, axis=0)
    scale = np.where(upper > lower, upper - lower, 1.0)
    return np.clip((positions - lower) / scale, 0.0, 1.0)


def _normalized_component_positions(values: np.ndarray) -> np.ndarray:
    """Normalize two spectral columns without borrowing a legacy-map axis."""
    lower = np.quantile(values, 0.02, axis=0)
    upper = np.quantile(values, 0.98, axis=0)
    scale = np.where(upper > lower, upper - lower, 1.0)
    return np.clip((values - lower) / scale, 0.0, 1.0)


def _spectral_embed(
    genre_ids: tuple[str, ...],
    graph: list[dict[int, float]],
    components: list[int],
    seed: int,
) -> np.ndarray:
    """Embed each sparse graph component with a deterministic normalized Laplacian basis."""
    positions = np.zeros((len(genre_ids), 2), dtype=np.float64)
    by_component: dict[int, list[int]] = defaultdict(list)
    for index, component in enumerate(components):
        by_component[component].append(index)
    largest_component = max(by_component.values(), key=len)
    for component, indices in sorted(by_component.items()):
        if len(indices) < _MINIMUM_SPECTRAL_COMPONENT_SIZE:
            for index in indices:
                positions[index] = (
                    _hash_unit(seed, genre_ids[index], "spectral-x"),
                    _hash_unit(seed, genre_ids[index], "spectral-y"),
                )
            continue
        local = {global_index: position for position, global_index in enumerate(indices)}
        rows: list[int] = []
        columns: list[int] = []
        values: list[float] = []
        for global_index in indices:
            for neighbor, weight in graph[global_index].items():
                if neighbor in local:
                    rows.append(local[global_index])
                    columns.append(local[neighbor])
                    values.append(weight)
        adjacency = csr_matrix((values, (rows, columns)), shape=(len(indices), len(indices)))
        normalized_laplacian = laplacian(adjacency, normed=True)
        initial = np.array(
            [_hash_unit(seed, genre_ids[index], "spectral-v0") for index in indices],
            dtype=np.float64,
        )
        _eigenvalues, eigenvectors = eigsh(
            normalized_laplacian,
            k=3,
            which="SM",
            v0=initial,
            tol=1e-7,
        )
        local_positions = eigenvectors[:, 1:3]
        for axis in range(2):
            pivot = int(np.argmax(np.abs(local_positions[:, axis])))
            if local_positions[pivot, axis] < 0.0:
                local_positions[:, axis] *= -1.0
        normalized = _normalized_component_positions(local_positions)
        if indices == largest_component:
            positions[indices] = normalized * 0.90 + 0.05
        else:
            center = np.array(
                (
                    _hash_unit(seed, str(component), "component-x"),
                    _hash_unit(seed, str(component), "component-y"),
                )
            )
            positions[indices] = np.clip(center + (normalized - 0.5) * 0.12, 0.0, 1.0)
    return positions


def _spectral_force_refine(
    positions: np.ndarray, graph: list[dict[int, float]], seed: int, iterations: int = 45
) -> np.ndarray:
    """Apply bounded sparse attraction and deterministic negative-sample repulsion."""
    generator = np.random.default_rng(seed)
    negative = generator.integers(0, len(positions), size=(len(positions), 32))
    current = positions.copy()
    for _iteration in range(iterations):
        attractive = np.zeros_like(current)
        for index, weighted_neighbors in enumerate(graph):
            if not weighted_neighbors:
                attractive[index] = current[index]
                continue
            total = sum(weighted_neighbors.values())
            attractive[index] = (
                sum(
                    (current[neighbor] * weight for neighbor, weight in weighted_neighbors.items()),
                    start=np.zeros(2, dtype=np.float64),
                )
                / total
            )
        delta = current[:, np.newaxis, :] - current[negative]
        squared = np.sum(np.square(delta), axis=2, keepdims=True) + 1e-4
        repulsion = np.sum(delta / squared, axis=1) / negative.shape[1]
        current = np.clip(current + 0.16 * (attractive - current) + 0.0015 * repulsion, 0.0, 1.0)
    return _normalized_component_positions(current)


def _overview_communities(
    graph: list[dict[int, float]], positions: np.ndarray, count: int = 24
) -> tuple[list[int], list[int]]:
    """Choose bounded topology representatives then assign nodes by learned embedding distance."""
    degree = [sum(neighbors.values()) for neighbors in graph]
    ranked = sorted(range(len(graph)), key=lambda item: (-degree[item], item))
    seeds: list[int] = []
    for candidate in ranked:
        if len(seeds) == count:
            break
        if (
            not seeds
            or min(float(np.linalg.norm(positions[candidate] - positions[seed])) for seed in seeds)
            >= _OVERVIEW_SEED_MINIMUM_DISTANCE
        ):
            seeds.append(candidate)
    for candidate in ranked:
        if len(seeds) == count:
            break
        if candidate not in seeds:
            seeds.append(candidate)
    assignment = [
        min(
            range(len(seeds)),
            key=lambda item: (float(np.linalg.norm(point - positions[seeds[item]])), item),
        )
        for point in positions
    ]
    return seeds, assignment


def _lods(
    genre_ids: tuple[str, ...], memberships: Mapping[str, set[str]], communities: list[int]
) -> list[int]:
    """Choose deterministic globally bounded progressive node cohorts."""
    ranked = sorted(
        range(len(genre_ids)),
        key=lambda item: (-len(memberships[genre_ids[item]]), communities[item], genre_ids[item]),
    )
    result = [3] * len(genre_ids)
    for level, limit in enumerate(_LOD_BUDGETS):
        for index in ranked[: min(limit, len(ranked))]:
            result[index] = min(result[index], level)
    return result


def _tiles(nodes: Iterable[HistoricalSignalNode]) -> tuple[HistoricalSignalTile, ...]:
    buckets: dict[tuple[int, int, int], list[str]] = defaultdict(list)
    for node in nodes:
        for level in range(node.lod_min, 4):
            column = min(_TILE_GRID - 1, int(node.x / _ASPECT * _TILE_GRID))
            row = min(_TILE_GRID - 1, int(node.y * _TILE_GRID))
            buckets[(level, column, row)].append(node.genre_id)
    return tuple(
        HistoricalSignalTile(level=level, column=column, row=row, node_ids=tuple(sorted(ids)))
        for (level, column, row), ids in sorted(buckets.items())
    )


def _coordinate_evaluation(
    nodes: tuple[HistoricalSignalNode, ...],
    legacy: HistoricalCompatibilityManifest,
    settings: HistoricalSignalSettings,
    candidates: Mapping[Pair, _SimilarityCandidate],
    neighbors: tuple[HistoricalSignalNeighbor, ...],
) -> CoordinateComparison:
    """Evaluate after fitting; H2 coordinates never enter graph or embedding construction."""
    legacy_by_id = {genre.external_id: genre for genre in legacy.genres}
    comparable = [node for node in nodes if node.genre_id in legacy_by_id]
    if len(comparable) < _MINIMUM_ALIGNMENT_NODES:
        return CoordinateComparison(compared_node_count=len(comparable))
    fitted = np.array([(node.x / _ASPECT, node.y) for node in comparable], dtype=np.float64)
    oracle = np.array(
        [
            (
                legacy_by_id[node.genre_id].coordinate.x_px,
                legacy_by_id[node.genre_id].coordinate.y_px,
            )
            for node in comparable
        ],
        dtype=np.float64,
    )
    oracle = (oracle - oracle.min(axis=0)) / np.where(
        oracle.max(axis=0) > oracle.min(axis=0), oracle.max(axis=0) - oracle.min(axis=0), 1.0
    )
    centered_fit = fitted - fitted.mean(axis=0)
    centered_oracle = oracle - oracle.mean(axis=0)
    fit_norm = np.linalg.norm(centered_fit)
    oracle_norm = np.linalg.norm(centered_oracle)
    if fit_norm == 0.0 or oracle_norm == 0.0:
        return CoordinateComparison(compared_node_count=len(comparable))
    normalized_fit = centered_fit / fit_norm
    normalized_oracle = centered_oracle / oracle_norm
    left, _singular, right = np.linalg.svd(normalized_fit.T @ normalized_oracle)
    aligned = normalized_fit @ left @ right
    residual = normalized_oracle - aligned
    rms = float(np.sqrt(np.mean(np.square(residual))))
    stress = float(np.linalg.norm(residual) / np.linalg.norm(normalized_oracle))
    sample_count = min(512, len(comparable))
    sample = sorted(
        range(len(comparable)),
        key=lambda item: _hash_unit(settings.embedding_seed, comparable[item].genre_id),
    )[:sample_count]
    model_neighbors = {node.genre_id: set() for node in nodes}
    expected_neighbors: dict[str, set[str]] = {}
    # Derived from model positions only; comparison against H2 is below.
    for index in sample:
        distances = np.sum(np.square(fitted - fitted[index]), axis=1)
        nearest = np.argsort(distances)[1 : settings.evaluation_neighbor_count + 1]
        model_neighbors[comparable[index].genre_id] = {
            comparable[int(neighbor)].genre_id for neighbor in nearest
        }
    for index in sample:
        distances = np.sum(np.square(oracle - oracle[index]), axis=1)
        nearest = np.argsort(distances)[1 : settings.evaluation_neighbor_count + 1]
        expected = {comparable[int(neighbor)].genre_id for neighbor in nearest}
        expected_neighbors[comparable[index].genre_id] = expected
    recalls = [
        len(model_neighbors[genre_id] & expected) / settings.evaluation_neighbor_count
        for genre_id, expected in expected_neighbors.items()
    ]
    candidate_neighbors: list[list[tuple[int, float, float, float, int]]] = [[] for _ in comparable]
    comparable_index = {node.genre_id: index for index, node in enumerate(comparable)}
    for (left, right), candidate in candidates.items():
        left_id, right_id = nodes[left].genre_id, nodes[right].genre_id
        if left_id not in comparable_index or right_id not in comparable_index:
            continue
        local_left, local_right = comparable_index[left_id], comparable_index[right_id]
        candidate_neighbors[local_left].append(
            (
                local_right,
                candidate.weighted_jaccard,
                candidate.cosine,
                candidate.idf_overlap,
                candidate.shared_artist_count,
            )
        )
        candidate_neighbors[local_right].append(
            (
                local_left,
                candidate.weighted_jaccard,
                candidate.cosine,
                candidate.idf_overlap,
                candidate.shared_artist_count,
            )
        )
    metrics: list[list[float]] = [[], [], [], []]
    for local_index in sample:
        genre_id = comparable[local_index].genre_id
        expected = expected_neighbors[genre_id]
        for metric_index, collection in enumerate(metrics, start=1):
            ranked = sorted(
                candidate_neighbors[local_index],
                key=lambda item: (-item[metric_index], comparable[item[0]].genre_id),
            )[: settings.evaluation_neighbor_count]
            actual = {comparable[item[0]].genre_id for item in ranked}
            collection.append(len(actual & expected) / settings.evaluation_neighbor_count)
    direct_graph_neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in neighbors:
        direct_graph_neighbors[edge.genre_id].add(edge.neighbor_genre_id)
    embedding_graph_recalls = [
        len(model_neighbors[genre_id] & direct_graph_neighbors[genre_id])
        / settings.evaluation_neighbor_count
        for genre_id in expected_neighbors
    ]
    pair_count = min(settings.evaluation_pair_sample, len(comparable) * (len(comparable) - 1) // 2)
    model_distances: list[float] = []
    oracle_distances: list[float] = []
    for ordinal in range(pair_count):
        left_index = int(
            _hash_unit(settings.embedding_seed, str(ordinal), "left") * len(comparable)
        )
        right_index = int(
            _hash_unit(settings.embedding_seed, str(ordinal), "right") * len(comparable)
        )
        if left_index == right_index:
            right_index = (right_index + 1) % len(comparable)
        model_distances.append(float(np.linalg.norm(fitted[left_index] - fitted[right_index])))
        oracle_distances.append(float(np.linalg.norm(oracle[left_index] - oracle[right_index])))
    model_ranks = np.argsort(np.argsort(np.array(model_distances, dtype=np.float64)))
    oracle_ranks = np.argsort(np.argsort(np.array(oracle_distances, dtype=np.float64)))
    rank_correlation = float(np.corrcoef(model_ranks, oracle_ranks)[0, 1])
    return CoordinateComparison(
        compared_node_count=len(comparable),
        procrustes_aligned_rms=round(rms, 12),
        normalized_stress=round(stress, 12),
        sampled_distance_rank_correlation=round(rank_correlation, 12),
        legacy_neighborhood_recall_at_k=round(sum(recalls) / len(recalls), 12),
        embedding_graph_neighbor_recall_at_k=round(
            sum(embedding_graph_recalls) / len(embedding_graph_recalls), 12
        ),
        direct_weighted_jaccard_recall_at_k=round(sum(metrics[0]) / len(metrics[0]), 12),
        direct_cosine_recall_at_k=round(sum(metrics[1]) / len(metrics[1]), 12),
        direct_idf_overlap_recall_at_k=round(sum(metrics[2]) / len(metrics[2]), 12),
        direct_shared_artist_recall_at_k=round(sum(metrics[3]) / len(metrics[3]), 12),
    )


def build_historical_signal_model(
    *,
    historical: HistoricalCompatibilityManifest,
    membership_database: Path,
    h3_artifact_sha256: str,
    settings: HistoricalSignalSettings | None = None,
) -> HistoricalSignalArtifact:
    """Build a deterministic all-node map with H2 held out exclusively for evaluation."""
    resolved_settings = settings or HistoricalSignalSettings()
    vocabulary = _legacy_vocabulary(historical)
    memberships, database_sha, membership_rows = _load_memberships(
        membership_database, vocabulary, h3_artifact_sha256
    )
    genre_ids = tuple(genre_id for genre_id, _name in vocabulary)
    names = dict(vocabulary)
    candidates, artist_degrees = _idf_candidates(memberships, resolved_settings)
    neighbors = _knn(genre_ids, candidates, resolved_settings)
    graph = _weighted_graph(genre_ids, neighbors)
    reciprocal_graph = _weighted_graph(genre_ids, neighbors, reciprocal=True)
    components = _components(graph)
    if resolved_settings.embedding_method == "anchored_diffusion":
        positions = _embed(genre_ids, graph, resolved_settings)
    else:
        positions = _spectral_embed(genre_ids, graph, components, resolved_settings.embedding_seed)
        if resolved_settings.embedding_method == "spectral_force_refined":
            positions = _spectral_force_refine(positions, graph, resolved_settings.embedding_seed)
    hierarchy, hierarchy_assignments = _graph_hierarchy(
        graph, reciprocal_graph, genre_ids, names, positions, resolved_settings
    )
    umbrella_ids = tuple(item.hierarchy_id for item in hierarchy if item.level == 0)
    umbrella_positions = {
        hierarchy_id: position for position, hierarchy_id in enumerate(umbrella_ids)
    }
    overview = [
        umbrella_positions[hierarchy_assignments[index][0]] for index in range(len(genre_ids))
    ]
    lod_min = _lods(genre_ids, memberships, overview)
    nodes = tuple(
        HistoricalSignalNode(
            genre_id=genre_id,
            name=names[genre_id],
            x=round(float(positions[position, 0] * _ASPECT), 12),
            y=round(float(positions[position, 1]), 12),
            community_id=hierarchy_assignments[position][0],
            umbrella_id=hierarchy_assignments[position][0],
            subcommunity_id=hierarchy_assignments[position][1],
            microgenre_id=hierarchy_assignments[position][2],
            component_id=components[position],
            membership_count=len(memberships[genre_id]),
            lod_min=lod_min[position],
            evidence_kind="h3_genre_to_artist" if memberships[genre_id] else "no_h3_membership",
        )
        for position, genre_id in enumerate(genre_ids)
    )
    communities = tuple(
        HistoricalSignalCommunity(
            community_id=umbrella.hierarchy_id,
            member_count=umbrella.member_count,
            component_count=len(
                {
                    components[index]
                    for index, assignment in hierarchy_assignments.items()
                    if assignment[0] == umbrella.hierarchy_id
                }
            ),
            representative_genre_id=umbrella.representative_genre_id,
        )
        for umbrella in hierarchy
        if umbrella.level == 0
    )
    q05, q95 = np.quantile(np.array([(node.x, node.y) for node in nodes]), (0.05, 0.95), axis=0)
    span_x, span_y = float(q95[0] - q05[0]), float(q95[1] - q05[1])
    geometry = HistoricalSignalGeometry(
        central_q05_q95_span_x=round(span_x, 12),
        central_q05_q95_span_y=round(span_y, 12),
        central_span_aspect_ratio=round(span_x / span_y, 12) if span_y else 1.0,
        tile_columns=_TILE_GRID,
        tile_rows=_TILE_GRID,
    )
    progressive_lods = tuple(
        HistoricalSignalLOD(
            level=level,
            node_count=sum(node.lod_min <= level for node in nodes),
            focus_edge_budget=resolved_settings.neighbors_per_genre,
        )
        for level in range(4)
    )
    inputs = HistoricalSignalInput(
        h2_artifact_sha256=historical.artifact.content_sha256,
        h3_artifact_sha256=h3_artifact_sha256,
        h3_database_sha256=database_sha,
        genre_count=len(nodes),
        membership_count=membership_rows,
        mapped_membership_genre_count=sum(bool(value) for value in memberships.values()),
        distinct_artist_count=len(artist_degrees),
    )
    ablations = (
        HistoricalSignalAblation(
            name="h3_idf_membership",
            role="active",
            detail=(
                "Weighted Jaccard/cosine over direct genre-to-artist memberships; the retained "
                "kNN graph produces layout, similarity, and the natural subcommunity/microgenre "
                "levels of the zoom hierarchy."
            ),
        ),
        HistoricalSignalAblation(
            name="genre_name_display_taxonomy",
            role="active",
            detail=(
                "Sparse TF-IDF word and character affinity is used only to coarsen reciprocal-H3 "
                "natural communities into level-0 display regions; it never changes H3 kNN, "
                "similarity weights, layout coordinates, or lower hierarchy levels."
            ),
        ),
        HistoricalSignalAblation(
            name="h2_legacy_coordinates",
            role="evaluation_oracle",
            detail="Read after fitting for alignment and neighborhood comparison only.",
        ),
    )
    preliminary = HistoricalSignalArtifact(
        settings=resolved_settings,
        inputs=inputs,
        nodes=nodes,
        neighbors=neighbors,
        communities=communities,
        hierarchy=hierarchy,
        geometry=geometry,
        progressive_lods=progressive_lods,
        tiles=_tiles(nodes),
        ablations=ablations,
        coordinate_evaluation=_coordinate_evaluation(
            nodes, historical, resolved_settings, candidates, neighbors
        ),
        quality=HistoricalSignalQuality(
            node_count=len(nodes),
            member_genre_count=sum(bool(value) for value in memberships.values()),
            zero_membership_genre_count=sum(not value for value in memberships.values()),
            similarity_edge_count=len(neighbors),
            community_count=len(communities),
            connected_component_count=len(set(components)),
            mean_neighbor_weight=round(
                sum(float(edge.weighted_jaccard) for edge in neighbors) / len(neighbors), 12
            )
            if neighbors
            else 0.0,
            hierarchy_umbrella_count=len(communities),
            hierarchy_subcommunity_count=sum(
                item.level == _HIERARCHY_SUBCOMMUNITY_LEVEL for item in hierarchy
            ),
            hierarchy_microgenre_count=sum(
                item.level == _HIERARCHY_MICROGENRE_LEVEL for item in hierarchy
            ),
            hierarchy_node_coverage=round(len(hierarchy_assignments) / len(nodes), 12),
            hierarchy_microgenre_internal_edge_fraction=round(
                _microgenre_internal_edge_fraction(graph, hierarchy_assignments), 12
            ),
            hierarchy_max_microgenre_member_count=max(
                (
                    item.member_count
                    for item in hierarchy
                    if item.level == _HIERARCHY_MICROGENRE_LEVEL
                ),
                default=0,
            ),
            artifact_sha256="0" * 64,
            exact_rerun=True,
        ),
    )
    content_sha = _canonical_sha256(preliminary)
    return preliminary.model_copy(
        update={"quality": preliminary.quality.model_copy(update={"artifact_sha256": content_sha})}
    )
