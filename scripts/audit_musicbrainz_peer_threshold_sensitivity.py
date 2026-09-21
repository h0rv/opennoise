"""Stream a non-publishing scoped MusicBrainz peer-threshold sensitivity audit.

The audit reads only frozen candidate abstentions and direct-membership rows.
It replays overlap-one pairs incident to the 495 scoped unplaced seeds, writes
only a compact report, and never builds a full candidate, index, map, or DB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import ijson

from opennoise.peers.similarity.similarity import (
    GenrePeerSimilarityArtifact,
    PeerSimilaritySettings,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_HIGH_ADDED_EDGE_DEGREE = 10
_HIGH_ARTIST_SEED_DEGREE = 100


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _settings_sha256(settings: PeerSimilaritySettings) -> str:
    canonical = json.dumps(
        settings.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _read_layout(
    path: Path,
) -> tuple[frozenset[str], frozenset[str], tuple[tuple[str, str], ...], str]:
    raw: object = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise TypeError("layout must be an object")
    unplaced = raw.get("unplaced")
    coordinates = raw.get("coordinates")
    structural_edges = raw.get("structural_edges")
    output_sha256 = raw.get("output_sha256")
    if not isinstance(unplaced, list) or not isinstance(coordinates, list):
        raise TypeError("layout must contain unplaced and coordinates lists")
    if not isinstance(structural_edges, list) or not isinstance(output_sha256, str):
        raise TypeError("layout must contain structural_edges and output_sha256")
    unplaced_ids = frozenset(_required_string(row, "seed_id") for row in unplaced)
    placed_ids = frozenset(_required_string(row, "seed_id") for row in coordinates)
    edges = tuple(
        (_required_string(row, "left_seed_id"), _required_string(row, "right_seed_id"))
        for row in structural_edges
    )
    return unplaced_ids, placed_ids, edges, output_sha256


def _required_string(row: object, key: str) -> str:
    if not isinstance(row, dict) or not isinstance(value := row.get(key), str):
        raise TypeError(f"layout row requires a string {key}")
    return value


def _components(edges: Iterable[tuple[str, str]]) -> dict[str, int]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    identifiers: dict[str, int] = {}
    component_id = 0
    for start in sorted(adjacency):
        if start in identifiers:
            continue
        identifiers[start] = component_id
        pending = deque((start,))
        while pending:
            current = pending.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in identifiers:
                    identifiers[neighbor] = component_id
                    pending.append(neighbor)
        component_id += 1
    return identifiers


def _candidate_edges(artifact: GenrePeerSimilarityArtifact) -> tuple[tuple[str, str], ...]:
    return tuple((row.source_genre_id, row.target_genre_id) for row in artifact.candidates)


def _new_edges(
    baseline: GenrePeerSimilarityArtifact, sensitivity: GenrePeerSimilarityArtifact
) -> tuple[tuple[str, str], ...]:
    baseline_edges = frozenset(_candidate_edges(baseline))
    return tuple(edge for edge in _candidate_edges(sensitivity) if edge not in baseline_edges)


@dataclass(frozen=True, slots=True)
class SensitivityCounts:
    """Aggregate edge and placement counts for the threshold-one replay."""

    baseline_candidate_edge_count: int
    threshold_one_candidate_edge_count: int
    added_candidate_edge_count: int
    scoped_unplaced_seed_count: int
    scoped_unplaced_seeds_newly_connected: int
    added_edges_touching_scoped_unplaced: int
    scoped_unplaced_seeds_with_placed_neighbor: int
    distinct_existing_structural_components_reached: int
    all_added_edges_have_one_shared_artist: bool
    maximum_added_edge_degree: int
    added_edge_degree_at_or_above_10: int


def summarize_counts(
    *,
    baseline: GenrePeerSimilarityArtifact,
    sensitivity: GenrePeerSimilarityArtifact,
    scoped_unplaced: frozenset[str],
    placed_ids: frozenset[str],
    structural_edges: Iterable[tuple[str, str]],
) -> SensitivityCounts:
    """Summarize only edges admitted by changing the direct-overlap threshold."""
    added = _new_edges(baseline, sensitivity)
    added_rows = {(row.source_genre_id, row.target_genre_id): row for row in sensitivity.candidates}
    newly_connected = frozenset(seed for edge in added for seed in edge if seed in scoped_unplaced)
    touching = tuple(edge for edge in added if set(edge) & scoped_unplaced)
    placed_neighbors = {
        seed
        for left, right in touching
        for seed, other in ((left, right), (right, left))
        if seed in scoped_unplaced and other in placed_ids
    }
    component_ids = _components(structural_edges)
    reached_components = {
        component_ids[other]
        for left, right in touching
        for seed, other in ((left, right), (right, left))
        if seed in scoped_unplaced and other in component_ids
    }
    degree = Counter(seed for edge in added for seed in edge)
    return SensitivityCounts(
        baseline_candidate_edge_count=len(baseline.candidates),
        threshold_one_candidate_edge_count=len(sensitivity.candidates),
        added_candidate_edge_count=len(added),
        scoped_unplaced_seed_count=len(scoped_unplaced),
        scoped_unplaced_seeds_newly_connected=len(newly_connected),
        added_edges_touching_scoped_unplaced=len(touching),
        scoped_unplaced_seeds_with_placed_neighbor=len(placed_neighbors),
        distinct_existing_structural_components_reached=len(reached_components),
        all_added_edges_have_one_shared_artist=all(
            added_rows[edge].shared_direct_artist_count == 1 for edge in added
        ),
        maximum_added_edge_degree=max(degree.values(), default=0),
        added_edge_degree_at_or_above_10=sum(
            value >= _HIGH_ADDED_EDGE_DEGREE for value in degree.values()
        ),
    )


def _stream_scope(path: Path, unplaced: frozenset[str]) -> tuple[frozenset[str], int]:
    """Read candidate count and scoped abstentions without retaining rows."""
    candidate_count = 0
    scoped: set[str] = set()
    with path.open("rb") as stream:
        for prefix, event, _value in ijson.parse(stream):
            if prefix == "candidates.item" and event == "start_map":
                candidate_count += 1
    with path.open("rb") as stream:
        for row in ijson.items(stream, "abstentions.item"):
            if not isinstance(row, dict) or row.get("reason") != "insufficient_direct_overlap":
                continue
            for key in ("source_genre_id", "target_genre_id"):
                value = row.get(key)
                if isinstance(value, str) and value in unplaced:
                    scoped.add(value)
    return frozenset(scoped), candidate_count


def _stream_threshold_one_edges(  # noqa: C901
    path: Path, scoped: frozenset[str]
) -> tuple[tuple[tuple[str, str], ...], dict[tuple[str, str], int]]:
    """Replay only overlap-one pairs incident to the frozen abstention scope."""
    target_artists: set[str] = set()
    with path.open("rb") as stream:
        for row in ijson.items(stream, "direct_memberships.item"):
            if isinstance(row, dict) and row.get("genre_id") in scoped:
                artist = row.get("artist_id")
                if isinstance(artist, str):
                    target_artists.add(artist)
    artist_genres: dict[str, set[str]] = {artist: set() for artist in target_artists}
    with path.open("rb") as stream:
        for row in ijson.items(stream, "direct_memberships.item"):
            if not isinstance(row, dict):
                continue
            artist, genre = row.get("artist_id"), row.get("genre_id")
            if isinstance(artist, str) and isinstance(genre, str) and artist in artist_genres:
                artist_genres[artist].add(genre)
    pair_count: Counter[tuple[str, str]] = Counter()
    pair_degrees: dict[tuple[str, str], list[int]] = defaultdict(list)
    for genres in artist_genres.values():
        degree = len(genres)
        for left in sorted(genres):
            for right in sorted(genres):
                if left < right and (left in scoped or right in scoped):
                    pair_count[(left, right)] += 1
                    pair_degrees[(left, right)].append(degree)
    edges = tuple(edge for edge, count in sorted(pair_count.items()) if count == 1)
    return edges, {edge: pair_degrees[edge][0] for edge in edges}


def main() -> int:
    """Write the bounded local-only threshold sensitivity report."""
    parser = argparse.ArgumentParser(prog="audit-musicbrainz-peer-threshold-sensitivity")
    parser.add_argument("--public-input", type=Path, required=True)
    parser.add_argument("--seed-reconciliation", type=Path, required=True)
    parser.add_argument("--baseline-candidate", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite report: {arguments.output}")

    unplaced_ids, placed_ids, structural_edges, layout_output_sha256 = _read_layout(
        arguments.layout
    )
    scoped_unplaced, baseline_count = _stream_scope(arguments.baseline_candidate, unplaced_ids)
    added, edge_artist_degree = _stream_threshold_one_edges(arguments.public_input, scoped_unplaced)
    baseline_raw: object = json.loads(arguments.baseline_candidate.read_bytes())
    if not isinstance(baseline_raw, dict):
        raise TypeError("baseline candidate must be an object")
    baseline_output = _required_string(baseline_raw, "output_sha256")
    baseline_input = _required_string(baseline_raw, "input_sha256")
    baseline_settings_hash = _required_string(baseline_raw, "settings_sha256")
    baseline_settings = PeerSimilaritySettings()
    if _settings_sha256(baseline_settings) != baseline_settings_hash:
        raise ValueError("baseline settings do not match the supplied candidate settings hash")
    sensitivity_settings = baseline_settings.model_copy(update={"minimum_shared_artists": 1})
    degree = Counter(seed for edge in added for seed in edge)
    placed_neighbors = {
        seed
        for left, right in added
        for seed, other in ((left, right), (right, left))
        if seed in scoped_unplaced and other in placed_ids
    }
    components = _components(structural_edges)
    reached = {
        components[other]
        for left, right in added
        for seed, other in ((left, right), (right, left))
        if seed in scoped_unplaced and other in components
    }
    conservative = tuple(
        edge for edge in added if edge_artist_degree[edge] < _HIGH_ADDED_EDGE_DEGREE
    )
    conservative_degree = Counter(seed for edge in conservative for seed in edge)
    conservative_placed = {
        seed
        for left, right in conservative
        for seed, other in ((left, right), (right, left))
        if seed in scoped_unplaced and other in placed_ids
    }
    conservative_reached = {
        components[other]
        for left, right in conservative
        for seed, other in ((left, right), (right, left))
        if seed in scoped_unplaced and other in components
    }
    report = {
        "audit_revision": "musicbrainz-peer-threshold-sensitivity-v1",
        "publication_scope": "local_only_non_publishing_threshold_replay",
        "historical_every_noise_inputs_read": "none; layout seed IDs only",
        "threshold_change": {"minimum_shared_artists": {"baseline": 2, "replay": 1}},
        "inputs": {
            "baseline_candidate": {
                "path": str(arguments.baseline_candidate),
                "byte_sha256": _file_sha256(arguments.baseline_candidate),
                "logical_output_sha256": baseline_output,
                "input_sha256": baseline_input,
                "settings_sha256": baseline_settings_hash,
            },
            "public_input": {
                "path": str(arguments.public_input),
                "byte_sha256": _file_sha256(arguments.public_input),
            },
            "seed_reconciliation": {
                "path": str(arguments.seed_reconciliation),
                "byte_sha256": _file_sha256(arguments.seed_reconciliation),
            },
            "layout": {
                "path": str(arguments.layout),
                "byte_sha256": _file_sha256(arguments.layout),
                "logical_output_sha256": layout_output_sha256,
            },
        },
        "replay": {
            "baseline_logical_output_sha256": baseline_output,
            "threshold_one_settings_sha256": _settings_sha256(sensitivity_settings),
            "counts": {
                "baseline_candidate_edge_count": baseline_count,
                "scoped_unplaced_seed_count": len(scoped_unplaced),
                "scoped_unplaced_seeds_newly_connected": len(
                    {seed for edge in added for seed in edge if seed in scoped_unplaced}
                ),
                "added_edges_touching_scoped_unplaced": len(added),
                "scoped_unplaced_seeds_with_placed_neighbor": len(placed_neighbors),
                "distinct_existing_structural_components_reached": len(reached),
                "all_added_edges_have_one_shared_artist": True,
                "maximum_added_edge_degree": max(degree.values(), default=0),
            },
        },
        "hub_effects": {
            "maximum_shared_artist_seed_degree": max(edge_artist_degree.values(), default=0),
            "added_edges_with_shared_artist_seed_degree_at_or_above_10": sum(
                degree >= _HIGH_ADDED_EDGE_DEGREE for degree in edge_artist_degree.values()
            ),
            "added_edges_with_shared_artist_seed_degree_at_or_above_100": sum(
                degree >= _HIGH_ARTIST_SEED_DEGREE for degree in edge_artist_degree.values()
            ),
        },
        "conservative_variant": {
            "sole_shared_artist_seed_degree_must_be_below": _HIGH_ADDED_EDGE_DEGREE,
            "added_edge_count": len(conservative),
            "scoped_unplaced_seeds_newly_connected": len(
                {seed for edge in conservative for seed in edge if seed in scoped_unplaced}
            ),
            "scoped_unplaced_seeds_with_placed_neighbor": len(conservative_placed),
            "distinct_existing_structural_components_reached": len(conservative_reached),
            "maximum_added_edge_degree": max(conservative_degree.values(), default=0),
        },
        "false_link_risk": {
            "interpretation": (
                "Every added edge has exactly one shared direct artist; this is a sensitivity "
                "signal, not a validated musical-similarity claim."
            ),
            "publication_decision": "not_published",
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
