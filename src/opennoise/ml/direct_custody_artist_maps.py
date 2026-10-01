"""Bounded offline artist maps from exact direct genre overlap, with explicit abstention."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
from scipy.sparse.linalg import ArpackNoConvergence

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json
from opennoise.ml.direct_custody_neighborhoods import MIN_SHARED, ObservationIndex
from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas

if TYPE_CHECKING:
    from pathlib import Path

    from scipy import sparse

MAX_ARTISTS_PER_GENRE: Final = 200
MAX_NEIGHBORS: Final = 10
REVISION: Final = "direct-custody-artist-overlap-maps-v2"
AFFINITY_SHRINKAGE: Final = 5
CANDIDATE_SELECTION: Final = "multi_genre_then_mean_target_affinity_descending_then_mbid"
METHOD: Final = "direct_genre_idf_cosine_spectral_rectangular_atlas"


@dataclass(frozen=True)
class _Context:
    index: ObservationIndex
    by_genre: sparse.csc_matrix
    degree: np.ndarray
    idf: np.ndarray
    mass: np.ndarray
    target_affinity: np.ndarray


def _context(index: ObservationIndex) -> _Context:
    counts = np.asarray(index.binary.sum(axis=0)).ravel()
    idf = 1 + np.log((len(index.artists) + 1) / (counts + 1))
    shared = (index.binary.T @ index.binary).toarray()
    target_affinity = shared / (counts[None, :] + AFFINITY_SHRINKAGE)
    target_affinity[shared < MIN_SHARED] = 0
    np.fill_diagonal(target_affinity, 0)
    return _Context(
        index=index,
        by_genre=index.binary.tocsc(),
        degree=np.diff(index.binary.indptr),
        idf=idf,
        mass=np.asarray(index.binary @ idf).ravel(),
        target_affinity=target_affinity,
    )


def _artist_map(context: _Context, column: int) -> dict[str, object]:
    index = context.index
    start, end = context.by_genre.indptr[column : column + 2]
    source_rows = context.by_genre.indices[start:end]
    # Mean target affinity discourages broad profiles from winning by tag count alone.
    # The target's self-observation contributes neither numerator nor denominator.
    degrees = context.degree[source_rows]
    affinity = np.asarray(index.binary[source_rows] @ context.target_affinity[column]).ravel()
    affinity /= np.maximum(1, degrees - 1)
    multi_profile = (degrees >= MIN_SHARED).astype(np.int8)
    order = np.lexsort((source_rows, -affinity, -multi_profile))[:MAX_ARTISTS_PER_GENRE]
    selected_offsets = order[np.argsort(source_rows[order])]
    selected = source_rows[selected_offsets]
    selected_affinity = affinity[selected_offsets]
    profiles = index.binary[selected]
    shared = (profiles @ profiles.T).toarray()
    weighted = (profiles.multiply(context.idf) @ profiles.T).toarray()
    mass = context.mass[selected]
    scores = weighted / np.sqrt(mass[:, None] * mass[None, :])
    scores[shared < MIN_SHARED] = 0
    np.fill_diagonal(scores, 0)
    names = tuple(index.artists[int(row)] for row in selected)
    neighbors: dict[str, list[dict[str, object]]] = {}
    weights: dict[tuple[str, str], float] = {}
    for local, artist in enumerate(names):
        candidates = np.flatnonzero(scores[local] > 0)
        ranked = candidates[np.lexsort((candidates, -scores[local, candidates]))[:MAX_NEIGHBORS]]
        peers: list[dict[str, object]] = []
        for peer in ranked:
            other = names[int(peer)]
            left, right = sorted((artist, other))
            weights[left, right] = float(scores[local, peer])
            common = np.intersect1d(
                profiles.getrow(local).indices, profiles.getrow(int(peer)).indices
            )
            peers.append(
                {
                    "id": other,
                    "score": float(scores[local, peer]),
                    "shared_seed_ids": [index.seeds[int(seed)] for seed in common],
                    "shared_genre_count": len(common),
                }
            )
        neighbors[artist] = peers
    connected = tuple(sorted({artist for edge in weights for artist in edge}))
    layout_state = "ready" if connected else "abstained_no_supported_pairs"
    try:
        coordinates = build_weighted_spectral_coordinates(connected, weights)
        atlas = build_rectangular_atlas(
            tuple(
                AtlasPoint(point.genre_id, point.x, point.y, str(point.component))
                for point in coordinates
            )
        )
        positions = atlas.positions
    except ArpackNoConvergence:
        # Do not replace failed evidence geometry with invented positions.
        positions = {}
        layout_state = "abstained_spectral_nonconvergence"
    artists: list[dict[str, object]] = []
    for local, artist in enumerate(names):
        position = positions.get(artist)
        reason = (
            None
            if position is not None
            else "single_direct_genre"
            if context.degree[selected[local]] < MIN_SHARED
            else "spectral_nonconvergence"
            if neighbors[artist]
            else "no_two_genre_overlap_in_selected_cohort"
        )
        artists.append(
            {
                "id": artist,
                "x": round(position[0], 10) if position else None,
                "y": round(position[1], 10) if position else None,
                "state": "positioned" if position else "abstained",
                "abstention_reason": reason,
                "direct_genre_count": int(context.degree[selected[local]]),
                "source_affinity_score": float(selected_affinity[local]),
                "supported_neighbor_count": int(np.count_nonzero(scores[local] > 0)),
                "neighbors": neighbors[artist],
            }
        )
    return {
        "revision": REVISION,
        "scope": "local_research_only",
        "genre_id": index.seeds[column],
        "role": "inferred_artist_overlap_map",
        "quality_evaluated": False,
        "method": METHOD,
        "layout_state": layout_state,
        "total_count": len(source_rows),
        "selected_count": len(selected),
        "positioned_count": len(positions),
        "abstained_count": len(selected) - len(positions),
        "omitted_count": len(source_rows) - len(selected),
        "truncated": len(selected) < len(source_rows),
        "candidate_selection": CANDIDATE_SELECTION,
        "affinity_support_shrinkage": AFFINITY_SHRINKAGE,
        "affinity_formula": (
            "mean shared(target,other)/(support(other)+5); self excluded; shared>=2"
        ),
        "cohort_relevance_evaluated": False,
        "maximum_artist_count": MAX_ARTISTS_PER_GENRE,
        "minimum_shared_genres": MIN_SHARED,
        "maximum_neighbors_per_artist": MAX_NEIGHBORS,
        "layout_edge_count": len(weights),
        "source_names_used_for_geometry": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "world_width": 16 / 9,
        "world_height": 1,
        "artists": artists,
    }


def genre_artist_map(index: ObservationIndex, seed_id: str) -> dict[str, object]:
    """Construct a single bounded source cohort map; an unknown genre is rejected."""
    if seed_id not in index.seeds:
        raise ValueError("artist map requires an observed direct genre")
    return _artist_map(_context(index), index.seeds.index(seed_id))


def build_genre_artist_maps(
    index: ObservationIndex, *, output_directory: Path
) -> dict[str, object]:
    """Write one offline map per source genre into a new local-only directory.

    A caller may join exact-ID display labels after geometry is fixed and bind the
    resulting bytes in its encompassing preview receipt. No labels enter this API.
    """
    require_local_candidate_destination(output_directory)
    if output_directory.exists() or output_directory.is_symlink():
        raise FileExistsError("refusing to replace existing genre artist maps")
    if any(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", seed) is None for seed in index.seeds):
        raise ValueError("source seed cannot form a safe artist-map filename")
    context = _context(index)
    output_directory.mkdir(parents=True)
    totals: dict[str, int] = {
        "selected_artist_occurrence_count": 0,
        "positioned_artist_occurrence_count": 0,
        "abstained_artist_occurrence_count": 0,
        "truncated_genre_count": 0,
        "positioned_genre_count": 0,
        "spectral_nonconvergence_genre_count": 0,
    }
    for column, seed in enumerate(index.seeds):
        payload = _artist_map(context, column)
        (output_directory / f"{seed}.json").write_bytes(canonical_json(payload) + b"\n")
        for key, value in (
            ("selected_artist_occurrence_count", payload["selected_count"]),
            ("positioned_artist_occurrence_count", payload["positioned_count"]),
            ("abstained_artist_occurrence_count", payload["abstained_count"]),
        ):
            assert isinstance(value, int)  # noqa: S101 - local payload contract.
            totals[key] += value
        totals["truncated_genre_count"] += int(bool(payload["truncated"]))
        totals["positioned_genre_count"] += int(bool(payload["positioned_count"]))
        totals["spectral_nonconvergence_genre_count"] += int(
            payload["layout_state"] == "abstained_spectral_nonconvergence"
        )
    return {
        "revision": REVISION,
        "method": METHOD,
        "scope": "local_research_only",
        "quality_evaluated": False,
        "genre_count": len(index.seeds),
        "candidate_selection": CANDIDATE_SELECTION,
        "maximum_artists_per_genre": MAX_ARTISTS_PER_GENRE,
        **totals,
    }
