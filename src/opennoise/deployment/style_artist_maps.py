"""Bounded source-only artist profile maps for named style cohorts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import numpy as np
from scipy.sparse.linalg import ArpackNoConvergence

from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas

if TYPE_CHECKING:
    from scipy import sparse

MAX_ARTISTS = 200
MAX_NEIGHBORS = 10
MAX_SHARED_VALUE_EXAMPLES = 5
MIN_SHARED_VALUES = 2
MIN_VALUE_SUPPORT = 2
MIN_STYLE_SUPPORT = 5
REVISION = "named-style-source-artist-maps-v1"
METHOD = "source_musical_value_idf_cosine_spectral_rectangular_atlas"
SELECTION = "informative_source_music_degree_descending_then_exact_mbid"


@dataclass(frozen=True)
class ArtistMapContext:
    """Names-free aligned musical profiles and global distinct-artist IDF weights."""

    artist_ids: tuple[str, ...]
    artist_index: dict[str, int]
    vocabulary: tuple[str, ...]
    profiles: sparse.csr_matrix
    idf: np.ndarray
    degree: np.ndarray
    mass: np.ndarray
    duplicate_profile: np.ndarray


def map_context(
    artist_ids: tuple[str, ...], values: list[str], matrix: sparse.csr_matrix
) -> ArtistMapContext:
    """Collapse source facets to binary musical values and exclude singleton columns."""
    if matrix.shape != (len(artist_ids), len(values)) or len(set(artist_ids)) != len(artist_ids):
        raise ValueError("source artist map identities differ from profile dimensions")
    if any(str(UUID(artist)) != artist for artist in artist_ids):
        raise ValueError("source artist map requires exact canonical MusicBrainz IDs")
    matrix = cast("sparse.csr_matrix", matrix.copy())
    matrix.sort_indices()
    if (
        not matrix.has_canonical_format
        or not np.isfinite(matrix.data).all()
        or not np.all(matrix.data == 1)
    ):
        raise ValueError("artist geometry requires deduplicated binary source musical profiles")
    counts = np.asarray(matrix.sum(axis=0)).ravel()
    selected = np.flatnonzero(counts >= MIN_VALUE_SUPPORT)
    profiles = cast("sparse.csr_matrix", matrix[:, selected].tocsr())
    profiles.sort_indices()
    idf = 1 + np.log((len(artist_ids) + 1) / (counts[selected] + 1))
    signatures: dict[bytes, list[int]] = defaultdict(list)
    for row in range(len(artist_ids)):
        columns = profiles.indices[profiles.indptr[row] : profiles.indptr[row + 1]]
        signatures[columns.tobytes()].append(row)
    duplicate_profile = np.zeros(len(artist_ids), dtype=bool)
    for group in signatures.values():
        if len(group) > 1:
            duplicate_profile[group] = True
    return ArtistMapContext(
        artist_ids,
        {artist: row for row, artist in enumerate(artist_ids)},
        tuple(values[column] for column in selected),
        profiles,
        idf,
        np.diff(profiles.indptr),
        np.asarray(profiles @ idf).ravel(),
        duplicate_profile,
    )


def _graph(
    context: ArtistMapContext, selected: list[str]
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, str],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
]:
    rows = [context.artist_index[artist] for artist in selected]
    profiles = context.profiles[rows].tocsr()
    duplicates = {
        artist for artist, row in zip(selected, rows, strict=True) if context.duplicate_profile[row]
    }
    shared = (profiles @ profiles.T).toarray()
    weighted = (profiles.multiply(context.idf) @ profiles.T).toarray()
    mass = context.mass[rows]
    denominator = np.sqrt(mass[:, None] * mass[None, :])
    scores = np.divide(weighted, denominator, out=np.zeros_like(weighted), where=denominator > 0)
    scores[shared < MIN_SHARED_VALUES] = 0
    np.clip(scores, 0, 1, out=scores)
    np.fill_diagonal(scores, 0)
    for local, artist in enumerate(selected):
        if artist in duplicates:
            scores[local, :] = 0
            scores[:, local] = 0
    neighbors: dict[str, list[dict[str, Any]]] = {}
    weights: dict[tuple[str, str], float] = {}
    supports = {}
    for local, artist in enumerate(selected):
        candidates = np.flatnonzero(scores[local] > 0)
        ranked = sorted(candidates, key=lambda other: (-scores[local, other], selected[other]))
        neighbors[artist] = []
        for other in ranked[:MAX_NEIGHBORS]:
            left, right = sorted((artist, selected[other]))
            weights[left, right] = float(scores[local, other])
            supports[left, right] = int(shared[local, other])
            shared_columns = np.intersect1d(
                profiles.indices[profiles.indptr[local] : profiles.indptr[local + 1]],
                profiles.indices[profiles.indptr[other] : profiles.indptr[other + 1]],
                assume_unique=True,
            )
            neighbors[artist].append(
                {
                    "artist_mbid": selected[other],
                    "score": float(scores[local, other]),
                    "shared_music_value_count": int(shared[local, other]),
                    "shared_music_values": sorted(
                        context.vocabulary[column] for column in shared_columns
                    )[:MAX_SHARED_VALUE_EXAMPLES],
                }
            )
    connected = tuple(sorted({artist for edge in weights for artist in edge}))
    reasons = {
        artist: "identical_usable_source_music_profile"
        if artist in duplicates
        else "insufficient_shared_source_music_values"
        for artist in selected
    }
    try:
        coordinates = build_weighted_spectral_coordinates(connected, weights) if connected else ()
        atlas = build_rectangular_atlas(
            tuple(
                AtlasPoint(point.genre_id, point.x, point.y, str(point.component))
                for point in coordinates
            )
        )
        positions = {
            artist: (round(x, 10), round(y, 10)) for artist, (x, y) in atlas.positions.items()
        }
    except ArpackNoConvergence:
        positions = {}
        reasons.update(dict.fromkeys(connected, "spectral_nonconvergence"))
    edges = [
        {
            "artist_mbids": [left, right],
            "weight": weights[left, right],
            "shared_music_value_count": supports[left, right],
        }
        for left, right in sorted(weights)
    ]
    return positions, reasons, neighbors, edges


def style_artist_map(
    context: ArtistMapContext, style_id: str, members: dict[str, list[str]]
) -> dict[str, Any]:
    """Select source members by informative degree and UUID, then abstain unsupported nodes."""
    source_roles = {"observed_artist_feature", "credited_release_context"}
    if any(
        artist not in context.artist_index or not roles or set(roles) - source_roles
        for artist, roles in members.items()
    ):
        raise ValueError("artist map cohort must contain exact source memberships only")
    selected = sorted(
        members,
        key=lambda artist: (
            -context.degree[context.artist_index[artist]],
            artist,
        ),
    )[:MAX_ARTISTS]
    selected.sort()
    positions, reasons, neighbors, edges = _graph(context, selected)
    artists = []
    for artist in selected:
        position = positions.get(artist)
        artists.append(
            {
                "artist_mbid": artist,
                "x": position[0] if position else None,
                "y": position[1] if position else None,
                "layout_status": "positioned" if position else "abstained",
                "abstention_reason": None if position else reasons[artist],
                "membership_roles": sorted(members[artist]),
                "source_music_value_count": int(context.degree[context.artist_index[artist]]),
                "supported_neighbor_count": len(neighbors[artist]),
                "neighbors": neighbors[artist],
                "profile_path": f"artists/{artist[:3]}.json",
            }
        )
    return {
        "revision": REVISION,
        "style_id": style_id,
        "scope": "local_research_only",
        "role": "inferred_source_artist_profile_map",
        "native_fact": False,
        "method": METHOD,
        "candidate_selection": SELECTION,
        "cohort_roles": sorted(source_roles),
        "quality_evaluated": False,
        "source_names_used_for_geometry": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "inferred_memberships_used_for_geometry": False,
        "total_count": len(members),
        "selected_count": len(selected),
        "positioned_count": len(positions),
        "abstained_count": len(selected) - len(positions),
        "omitted_count": len(members) - len(selected),
        "truncated": len(selected) < len(members),
        "maximum_artist_count": MAX_ARTISTS,
        "maximum_neighbors_per_artist": MAX_NEIGHBORS,
        "maximum_shared_music_value_examples": MAX_SHARED_VALUE_EXAMPLES,
        "minimum_shared_music_values": MIN_SHARED_VALUES,
        "minimum_music_value_artist_support": MIN_VALUE_SUPPORT,
        "idf_formula": "1 + ln((source_artist_count + 1) / (music_value_artist_support + 1))",
        "cosine_formula": "sum(shared_idf) / sqrt(sum(left_idf) * sum(right_idf))",
        "identical_profile_abstention_scope": "complete_source_artist_corpus",
        "usable_canonical_music_values": len(context.vocabulary),
        "layout_edge_count": len(edges),
        "world_width": 16 / 9,
        "world_height": 1,
        "artists": artists,
        "edges": edges,
    }
