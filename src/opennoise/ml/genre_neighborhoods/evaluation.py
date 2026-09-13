"""Evaluation-only diagnostics; these reports never feed construction weights or thresholds."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

from opennoise.common import write_atomic_bytes

from .query import CertifiedNeighborhoodCache, neighbors_for_seed

_DIAGNOSTIC_LABELS: Final = (
    "intelligent dance music",
    "post-punk",
    "jazz",
    "hip hop",
    "trap",
    "k-pop",
    "j-pop",
    "metal",
    "regional",
    "ambient",
    "breakcore",
    "drill",
    "acid techno",
)


def write_quality_diagnostics(
    cache: CertifiedNeighborhoodCache, graph_database: Path, output: Path
) -> None:
    """Write human-review diagnostics for diverse labels without introducing labels into training."""
    with (
        closing(
            sqlite3.connect(f"{graph_database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        ) as graph,
        closing(
            sqlite3.connect(f"{cache.database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        ) as model,
    ):
        labels = {
            str(seed): (str(label) if label is not None else str(seed))
            for seed, label in graph.execute(
                "SELECT identifier, label FROM identity WHERE namespace = 'stable_seed'"
            )
        }
        degrees = {
            str(seed): int(degree)
            for seed, degree in model.execute(
                "SELECT seed_id, count(*) FROM neighbor WHERE channel = 'artist_direct' GROUP BY seed_id"
            )
        }
        states = {
            str(seed): str(state)
            for seed, state in model.execute(
                "SELECT seed_id, state FROM genre_state WHERE channel = 'artist_direct'"
            )
        }
    rows: list[dict[str, object]] = []
    for needle in _DIAGNOSTIC_LABELS:
        matched = sorted(
            (seed for seed, label in labels.items() if needle in label.casefold()),
            key=lambda seed: (labels[seed], seed),
        )[:3]
        for seed in matched:
            page = neighbors_for_seed(cache, seed, limit=10)
            peers = [
                {
                    "seed_id": peer.seed_id,
                    "label": labels.get(peer.seed_id, peer.seed_id),
                    "shrunk_npmi": peer.score,
                    "raw_mass": peer.raw_mass,
                    "window_support": peer.window_support,
                    "artist_pair_support": peer.artist_pair_support,
                }
                for peer in page.neighbors
            ]
            leakage = sum(
                1
                for peer in peers
                if any(
                    other != needle and other in str(peer["label"]).casefold()
                    for other in _DIAGNOSTIC_LABELS
                )
            )
            rows.append(
                {
                    "requested_label": needle,
                    "seed_id": seed,
                    "label": labels[seed],
                    "state": page.state,
                    "peer_degree": degrees.get(seed, 0),
                    "top_peers": peers,
                    "cross_umbrella_peer_count": leakage,
                    "relation_semantics": "peer_not_parent_child",
                }
            )
    distribution = {
        state: sum(1 for value in states.values() if value == state)
        for state in ("observed", "abstained", "isolated")
    }
    payload = {
        "evaluation_only": True,
        "construction_labels_used": False,
        "channel": "artist_direct",
        "stable_seed_count": 6291,
        "state_counts": distribution,
        "nonzero_peer_degree_count": sum(1 for degree in degrees.values() if degree),
        "disconnected_seed_count": 6291 - sum(1 for degree in degrees.values() if degree),
        "child_to_parent_is_not_inferred": True,
        "peer_relation_kind": "peer_not_parent_child",
        "diagnostics": rows,
    }
    write_atomic_bytes(output, json.dumps(payload, sort_keys=True, indent=2).encode() + b"\n")
