"""Positive-only held-out metrics and review-only containment proposals."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

from .contracts import (
    ContainmentCandidate,
    ContainmentCoverage,
    EvaluationPartition,
    FullGraphSignalSettings,
    MembershipModelEvaluation,
    ModelName,
    PeerRecovery,
    _PairData,
)

if TYPE_CHECKING:
    from scipy import sparse


def _heldout_by_artist(data: _PairData) -> dict[int, set[int]]:
    heldout: dict[int, set[int]] = defaultdict(set)
    for row, column in zip(data.heldout_rows, data.heldout_columns, strict=True):
        heldout[int(row)].add(int(column))
    return heldout


def _sampled_artists(heldout: dict[int, set[int]], settings: FullGraphSignalSettings) -> list[int]:
    """Use one deterministic bounded artist sample across membership and peer metrics."""
    return sorted(
        heldout,
        key=lambda artist: hashlib.sha256(f"{settings.split_seed}:{artist}".encode()).hexdigest(),
    )[: settings.maximum_evaluation_artists]


def _partition(
    values: dict[str, int], scoreable: dict[str, int], hits: dict[str, int]
) -> EvaluationPartition:
    total = values["count"]
    return EvaluationPartition(
        heldout_pair_count=total,
        scoreable_pair_count=scoreable["count"],
        abstained_pair_count=total - scoreable["count"],
        recall_at_1=hits["one"] / total if total else None,
        recall_at_10=hits["ten"] / total if total else None,
        recall_at_25=hits["twenty_five"] / total if total else None,
        score_coverage=scoreable["count"] / total if total else None,
    )


def _evaluate_membership(
    name: ModelName,
    train: sparse.csr_matrix,
    neighbors: sparse.csr_matrix,
    heldout: dict[int, set[int]],
    settings: FullGraphSignalSettings,
) -> MembershipModelEvaluation:
    ordered_artists = _sampled_artists(heldout, settings)
    anchored_values = {"count": 0}
    cold_values = {"count": 0}
    anchored_scoreable = {"count": 0}
    cold_scoreable = {"count": 0}
    anchored_hits = {"one": 0, "ten": 0, "twenty_five": 0}
    cold_hits = {"one": 0, "ten": 0, "twenty_five": 0}
    seed_train_counts = np.asarray(train.getnnz(axis=0)).ravel()
    for artist in ordered_artists:
        targets = heldout[artist]
        train_genres = train.indices[train.indptr[artist] : train.indptr[artist + 1]]
        scores: dict[int, float] = defaultdict(float)
        for genre in train_genres:
            start, end = neighbors.indptr[genre], neighbors.indptr[genre + 1]
            for candidate, value in zip(
                neighbors.indices[start:end], neighbors.data[start:end], strict=True
            ):
                if candidate not in train_genres:
                    scores[int(candidate)] += float(value)
        ranked = [
            candidate
            for candidate, _ in sorted(scores.items(), key=lambda row: (-row[1], row[0]))[:25]
        ]
        for target in targets:
            values, scoreable, hits = (
                (anchored_values, anchored_scoreable, anchored_hits)
                if seed_train_counts[target] > 0
                else (cold_values, cold_scoreable, cold_hits)
            )
            values["count"] += 1
            if seed_train_counts[target] > 0 and ranked:
                scoreable["count"] += 1
                if target in ranked[:1]:
                    hits["one"] += 1
                if target in ranked[:10]:
                    hits["ten"] += 1
                if target in ranked[:25]:
                    hits["twenty_five"] += 1
    return MembershipModelEvaluation(
        model=name,
        evaluated_artist_count=len(ordered_artists),
        heldout_pair_count_total=sum(len(targets) for targets in heldout.values()),
        evaluation_pair_count=anchored_values["count"] + cold_values["count"],
        anchored=_partition(anchored_values, anchored_scoreable, anchored_hits),
        split_cold=_partition(cold_values, cold_scoreable, cold_hits),
    )


def _peer_recovery(
    neighbors: sparse.csr_matrix, heldout: dict[int, set[int]], settings: FullGraphSignalSettings
) -> PeerRecovery:
    pairs: set[tuple[int, int]] = set()
    for artist in _sampled_artists(heldout, settings):
        labels = sorted(heldout[artist])[:20]
        for index, left in enumerate(labels):
            pairs.update((left, right) for right in labels[index + 1 :])
    scoreable = hits_ten = hits_twenty_five = 0
    for left, right in pairs:
        start, end = neighbors.indptr[left], neighbors.indptr[left + 1]
        ranked = [
            candidate
            for candidate, _ in sorted(
                zip(neighbors.indices[start:end], neighbors.data[start:end], strict=True),
                key=lambda row: (-row[1], row[0]),
            )
        ]
        if ranked:
            scoreable += 1
            hits_ten += right in ranked[:10]
            hits_twenty_five += right in ranked[:25]
    return PeerRecovery(
        heldout_open_peer_pair_count=len(pairs),
        scoreable_peer_pair_count=scoreable,
        abstained_peer_pair_count=len(pairs) - scoreable,
        recall_at_10=hits_ten / len(pairs) if pairs else None,
        recall_at_25=hits_twenty_five / len(pairs) if pairs else None,
    )


def _containment_candidates(
    binary: sparse.csr_matrix,
    raw_cooccurrence: sparse.csr_matrix,
    data: _PairData,
    settings: FullGraphSignalSettings,
) -> tuple[tuple[ContainmentCandidate, ...], ContainmentCoverage]:
    counts = np.asarray(binary.getnnz(axis=0)).ravel()
    candidates: list[ContainmentCandidate] = []
    columns = raw_cooccurrence.tocsc()
    for child, child_count in enumerate(counts):
        if child_count < settings.minimum_containment_child_support:
            continue
        start, end = columns.indptr[child], columns.indptr[child + 1]
        child_rows, shared = columns.indices[start:end], columns.data[start:end]
        eligible = sorted(
            (
                (float(value) / child_count, int(parent), int(value))
                for parent, value in zip(child_rows, shared, strict=True)
                if counts[parent] > child_count
                and value / child_count >= settings.minimum_containment_score
            ),
            key=lambda row: (-row[0], row[1]),
        )[:3]
        candidates.extend(
            ContainmentCandidate(
                parent_seed_id=data.seed_ids[parent],
                child_seed_id=data.seed_ids[child],
                containment_score=score,
                shared_artist_count=shared_count,
                child_artist_count=int(child_count),
                parent_artist_count=int(counts[parent]),
            )
            for score, parent, shared_count in eligible
        )
    candidates = sorted(
        candidates,
        key=lambda item: (-item.containment_score, item.child_seed_id, item.parent_seed_id),
    )[: settings.maximum_containment_candidates]
    parents: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        parents[candidate.child_seed_id].add(candidate.parent_seed_id)
    return tuple(candidates), ContainmentCoverage(
        candidate_count=len(candidates),
        child_count=len(parents),
        overlapping_parent_child_count=sum(len(values) > 1 for values in parents.values()),
    )
