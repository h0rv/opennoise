"""Recording/co-credit isolation and train-only descriptor comparisons, without relevance labels."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, TypedDict

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

REVISION = "recording-component-evaluation-v1"


class Policy(TypedDict):
    """Fixed experiment controls; no values are selected from held-out outcomes."""

    folds: int
    seed: str
    minimum_column_observations: int
    minimum_column_fraction: float
    minimum_complete_training_recordings: int
    maximum_standardized_offset: float
    neighbors: int


POLICY: Policy = {
    "folds": 3,
    "seed": "opennoise-recording-components-v1",
    "minimum_column_observations": 3,
    "minimum_column_fraction": 0.8,
    "minimum_complete_training_recordings": 3,
    "maximum_standardized_offset": 12.0,
    "neighbors": 5,
}


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def component_ledger(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Connect all native credit evidence before considering features or join outcomes.

    Each exact recording is one vertex even when observed for multiple artists.
    Conflicting native credits conservatively connect both credit sets. Cohort
    associations are never edges. Album and duplicate-recording proof is absent;
    projected descriptor equality is not proof of duplicate recording identity.
    """
    parents: dict[str, str] = {row["recording_mbid"]: row["recording_mbid"] for row in rows}

    def root(identity: str) -> str:
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    owners: dict[str, str] = {}
    by_recording: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        identity = row["recording_mbid"]
        by_recording[identity].append(row)
        artist_ids = set(row["credited_artist_mbids"] or [])
        fact = (row.get("companion") or {}).get("credit_fact")
        if fact is not None:
            artist_ids.update(fact["credited_artist_mbids"])
        for artist in sorted(artist_ids):
            left, right = root(identity), root(owners.setdefault(artist, identity))
            parents[max(left, right)] = min(left, right)
    records = []
    for identity, observations in sorted(by_recording.items()):
        component = root(identity)
        fold = int.from_bytes(_hash(f"{POLICY['seed']}\0{component}"), "big") % POLICY["folds"]
        state = "eligible"
        if any(row["join_state"] != "joined" for row in observations):
            state = "non_joined_observation"
        elif any(
            row["values"] != observations[0]["values"]
            or set(row["credited_artist_mbids"]) != set(observations[0]["credited_artist_mbids"])
            for row in observations[1:]
        ):
            state = "conflicting_recording_observations"
        records.append(
            {
                "recording_mbid": identity,
                "component_id": component,
                "fold": fold,
                "observation_count": len(observations),
                "join_states": sorted({row["join_state"] for row in observations}),
                "training_identity_state": state,
            }
        )
    return {
        "records": records,
        "observation_rows": len(rows),
        "unique_recordings": len(records),
        "components": len({row["component_id"] for row in records}),
        "isolation": {
            "exact_recording": True,
            "all_supplied_native_co_credits": True,
            "album_edges": "unavailable",
            "duplicate_recording_edges": "unavailable",
            "unknown_credit_aliases": "unresolved",
            "full_leakage_isolation_established": False,
        },
    }


def fit_frame(
    rows: Sequence[dict[str, Any]],
    ledger: dict[str, Any],
    heldout_fold: int,
    columns: Sequence[str],
) -> dict[str, Any]:
    """Select support and fit moments using unique eligible training recordings only."""
    if type(heldout_fold) is not int or not 0 <= heldout_fold < POLICY["folds"]:
        raise ValueError("invalid held-out component fold")
    by_recording = {row["recording_mbid"]: row for row in rows}
    ids = [
        row["recording_mbid"]
        for row in ledger["records"]
        if row["fold"] != heldout_fold and row["training_identity_state"] == "eligible"
    ]
    values = np.array([by_recording[identity]["values"] for identity in ids], dtype=float).reshape(
        len(ids), len(columns)
    )
    observed = np.isfinite(values)
    counts = observed.sum(axis=0)
    selected = np.flatnonzero(
        (counts >= POLICY["minimum_column_observations"])
        & (counts >= len(ids) * POLICY["minimum_column_fraction"])
    )
    frame: dict[str, Any] = {
        "heldout_fold": heldout_fold,
        "input_columns": list(columns),
        "training_recordings": ids,
        "column_observed_counts": counts.tolist(),
        "support_selected_columns": selected.tolist(),
        "fitted_recordings": [],
        "columns": [],
        "center": [],
        "scale": [],
        "state": "insufficient_training_support",
    }
    if not len(selected):
        return frame
    complete = observed[:, selected].all(axis=1)
    if int(complete.sum()) < POLICY["minimum_complete_training_recordings"]:
        return frame
    fitted = values[complete][:, selected]
    with np.errstate(over="ignore", invalid="ignore"):
        center, scale = fitted.mean(axis=0), fitted.std(axis=0)
    if not np.isfinite(center).all() or not np.isfinite(scale).all():
        raise ValueError("recording frame normalization exceeds finite support")
    active = scale > 0
    if not active.any():
        return frame
    frame.update(
        fitted_recordings=[identity for identity, use in zip(ids, complete, strict=True) if use],
        columns=selected[active].tolist(),
        center=center[active].tolist(),
        scale=scale[active].tolist(),
        state="fitted",
    )
    return frame


def transform(row: dict[str, Any], frame: dict[str, Any]) -> tuple[list[float], str | None]:
    """Use a fixed training frame; missing query fields never become zero or fitted values."""
    if row["join_state"] != "joined":
        return [], str(row["join_state"])
    if frame["state"] != "fitted":
        return [], "insufficient_training_support"
    selected = [row["values"][index] for index in frame["columns"]]
    if any(value is None or not math.isfinite(value) for value in selected):
        return [], "missing_required_descriptors"
    normalized = [
        (float(value) - float(center)) / float(scale)
        for value, center, scale in zip(selected, frame["center"], frame["scale"], strict=True)
    ]
    if any(
        not math.isfinite(value) or abs(value) > POLICY["maximum_standardized_offset"]
        for value in normalized
    ):
        return [], "outside_training_support"
    return normalized, None


def _quarantine_reason(metadata: dict[str, Any]) -> str | None:
    if metadata["training_identity_state"] == "eligible":
        return None
    if len(metadata["join_states"]) == 1 and metadata["join_states"][0] != "joined":
        return str(metadata["join_states"][0])
    return str(metadata["training_identity_state"])


def compare_recordings(
    rows: Sequence[dict[str, Any]], ledger: dict[str, Any], frames: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compare two target-free arms with a shared support gate and retain all observations."""
    if [frame["heldout_fold"] for frame in frames] != list(range(POLICY["folds"])):
        raise ValueError("evaluation requires exactly one ordered frame per fold")
    by_recording = {row["recording_mbid"]: row for row in rows}
    identities: dict[str, dict[str, Any]] = {
        row["recording_mbid"]: row for row in ledger["records"]
    }
    results: dict[str, dict[str, Any]] = {}
    candidate_counts = []
    for frame in frames:
        candidates: dict[str, list[float]] = {}
        for identity in frame["fitted_recordings"]:
            vector, reason = transform(by_recording[identity], frame)
            if reason is None:
                candidates[identity] = vector
        candidate_counts.append(
            {"fold": frame["heldout_fold"], "supported_candidates": len(candidates)}
        )
        for identity, metadata in identities.items():
            if metadata["fold"] != frame["heldout_fold"]:
                continue
            vector, reason = transform(by_recording[identity], frame)
            reason = _quarantine_reason(metadata) or reason
            allowed = {
                key: value
                for key, value in candidates.items()
                if identities[key]["component_id"] != metadata["component_id"]
            }
            if reason is None and not allowed:
                reason = "no_supported_cross_component_candidates"
            numeric: list[dict[str, Any]] = []
            hashed: list[str] = []
            if reason is None:
                distances = [(math.dist(vector, value), key) for key, value in allowed.items()]
                numeric = [
                    {"recording_mbid": key, "distance": distance}
                    for distance, key in sorted(distances)[: POLICY["neighbors"]]
                ]
                hashed = sorted(
                    allowed,
                    key=lambda key: (_hash(f"{POLICY['seed']}\0baseline\0{identity}\0{key}"), key),
                )[: POLICY["neighbors"]]
            results[identity] = {
                **metadata,
                "outcome": reason or "emitted",
                "candidate_count": len(allowed),
                "numeric": numeric,
                "fixed_hash": hashed,
            }
    queries = [
        {
            "observation_index": index,
            "artist_mbid": row["artist_mbid"],
            "source": row["source"],
            "join_state": row["join_state"],
            **results[row["recording_mbid"]],
            "outcome": (
                row["join_state"]
                if row["join_state"] != "joined"
                else results[row["recording_mbid"]]["outcome"]
            ),
        }
        for index, row in enumerate(rows)
    ]
    summary = {
        "observation_queries": len(queries),
        "unique_recording_queries": len(results),
        "observation_outcomes": dict(Counter(row["outcome"] for row in queries)),
        "unique_recording_outcomes": dict(Counter(row["outcome"] for row in results.values())),
        "observation_emission_fraction": (
            sum(row["outcome"] == "emitted" for row in queries) / len(queries) if queries else None
        ),
        "unique_recording_emission_fraction": (
            sum(row["outcome"] == "emitted" for row in results.values()) / len(results)
            if results
            else None
        ),
        "fold_candidates": candidate_counts,
        "relevance_metrics": None,
        "relevance_metrics_unavailable_reason": "no_recording_level_targets_or_listener_judgments",
        "musical_quality_established": False,
        "confirmation_claimed": False,
        "arms_use_same_supported_candidate_pool": True,
    }
    return queries, summary
