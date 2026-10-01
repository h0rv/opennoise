"""Bounded linear source reconstruction with validation-selected, isolated edge holdouts.

The only training facts are portable direct artist proper-genre observations.
Coefficients and predicted genres are inferences, never promoted memberships.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import scipy
from scipy import linalg, sparse

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.ml.direct_custody_neighborhoods import (
    BLOCK_SIZE,
    MIN_SHARED,
    RECALL_MIDDLE_K,
    ObservationIndex,
    _transfer,
    genre_neighbors,
    load_neighborhood_index,
    observation_index,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

REVISION: Final = "direct-custody-linear-reconstruction-v2"
ARMS: Final = (
    "specificity_transfer",
    "conditional_5",
    "conditional_50",
    "ridge_1",
    "ridge_10",
    "ridge_100",
    "ridge_1000",
    "ridge_10_scaled010",
    "ridge_10_scaled025",
    "ridge_10_scaled050",
    "ridge_100_scaled010",
    "ridge_100_scaled025",
    "ridge_100_scaled050",
)
COEFFICIENT_EPSILON: Final = 1e-12
MIN_TRAIN: Final = 4
RANK_K: Final = 10
DISPLAY_K: Final = 20


@dataclass(frozen=True)
class ReconstructionMetric:
    """All-positive source reconstruction metrics, including cold-artist abstentions."""

    positive_count: int
    cold_artist_positive_count: int
    positive_score_count: int
    hits_at_1: int
    hits_at_5: int
    hits_at_10: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    macro_seed_recall_at_10: float
    mrr_at_10: float
    evaluated_seed_count: int
    train_support_strata: dict[str, dict[str, int | float]]


def split_observations(
    memberships: Mapping[str, tuple[str, ...]], *, partition: str
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Withhold a salted lowest fifth per seed, retaining at least four observations."""
    train: dict[str, tuple[str, ...]] = {}
    hidden: dict[str, tuple[str, ...]] = {}
    for seed, artists in sorted(memberships.items()):
        unique = set(artists)
        ordered = sorted(
            unique,
            key=lambda artist: (
                hashlib.sha256(f"{REVISION}\0{partition}\0{seed}\0{artist}".encode()).digest(),
                artist,
            ),
        )
        count = min(len(ordered) // 5, max(0, len(ordered) - MIN_TRAIN))
        hidden[seed] = tuple(sorted(ordered[:count]))
        train[seed] = tuple(sorted(ordered[count:]))
    return train, hidden


def fit_transfer(index: ObservationIndex, arm: str) -> np.ndarray:
    """Fit a genre-square matrix; never allocate an artist-square matrix.

    Ridge uses the zero-diagonal constrained linear reconstruction solution:
    P = inverse(X.T X + lambda I), B[i,j] = -P[i,j]/P[j,j], B[j,j] = 0.
    Negative coefficients remain in scoring and may cancel redundant signals.
    """
    if arm not in ARMS:
        raise ValueError("unknown predeclared reconstruction arm")
    if arm == "specificity_transfer":
        return _transfer(index, genre_neighbors(index, arm), arm).toarray().astype(np.float64)
    gram = (index.binary.T @ index.binary).toarray().astype(np.float64)
    family, strength_text, *calibration = arm.split("_")
    strength = float(strength_text)
    if family == "conditional":
        frequency = np.maximum(1, np.diag(gram))
        matrix = gram / frequency[:, None] * gram / (gram + strength)
    else:
        identity = np.eye(len(index.seeds), dtype=np.float64)
        precision = linalg.solve(gram + strength * identity, identity, assume_a="pos")
        matrix = -precision / np.diag(precision)[None, :]
    if calibration:
        exponent = {"scaled010": 0.1, "scaled025": 0.25, "scaled050": 0.5}[calibration[0]]
        matrix /= np.maximum(1, np.diag(gram))[None, :] ** exponent
    np.fill_diagonal(matrix, 0)
    matrix[np.abs(matrix) < COEFFICIENT_EPSILON] = 0
    if not np.isfinite(matrix).all():
        raise ValueError("nonfinite reconstruction coefficient")
    return matrix


def _ranking(values: np.ndarray, known: np.ndarray, limit: int) -> np.ndarray:
    scores = values.copy()
    scores[known] = -np.inf
    candidates = np.flatnonzero(scores > 0)
    return candidates[np.lexsort((candidates, -scores[candidates]))[:limit]]


def evaluate_transfer(  # noqa: C901, PLR0912 - one fit-only evaluation accounting boundary.
    index: ObservationIndex, targets: Mapping[str, tuple[str, ...]], transfer: np.ndarray
) -> ReconstructionMetric:
    """Evaluate every hidden observation, rejecting leakage and unseen seed identities."""
    if set(targets) - set(index.seeds):
        raise ValueError("target seed missing from training universe")
    if transfer.shape != (len(index.seeds), len(index.seeds)) or not np.isfinite(transfer).all():
        raise ValueError("invalid transfer shape or values")
    artist_rows = {artist: row for row, artist in enumerate(index.artists)}
    by_artist: dict[int, list[int]] = defaultdict(list)
    total = np.zeros(len(index.seeds), dtype=np.int64)
    recovered = np.zeros(len(index.seeds), dtype=np.int64)
    cold = 0
    for column, seed in enumerate(index.seeds):
        if len(set(targets.get(seed, ()))) != len(targets.get(seed, ())):
            raise ValueError("duplicate held-out target")
        total[column] = len(targets.get(seed, ()))
        for artist in targets.get(seed, ()):
            row = artist_rows.get(artist)
            if row is None:
                cold += 1
            elif index.binary[row, column] != 0:
                raise ValueError("held-out target leaked into training observations")
            else:
                by_artist[row].append(column)
    hits = [0, 0, 0]
    reciprocal, supported = 0.0, 0
    active = sorted(by_artist)
    for offset in range(0, len(active), BLOCK_SIZE):
        rows = active[offset : offset + BLOCK_SIZE]
        scores = index.binary[rows] @ transfer
        for local, row in enumerate(rows):
            known = index.binary.indices[index.binary.indptr[row] : index.binary.indptr[row + 1]]
            selected = _ranking(scores[local], known, RANK_K)
            ranks = {int(target): rank for rank, target in enumerate(selected, 1)}
            for target in by_artist[row]:
                supported += int(scores[local, target] > 0)
                rank = ranks.get(target)
                if rank is not None:
                    hits[0] += int(rank == 1)
                    hits[1] += int(rank <= RECALL_MIDDLE_K)
                    hits[2] += 1
                    recovered[target] += 1
                    reciprocal += 1 / rank
    denominator = int(total.sum())
    train_counts = np.asarray(index.binary.sum(axis=0)).ravel()
    strata = {}
    for label, low, high in (("4_to_20", 0, 20), ("21_to_100", 20, 100), ("over_100", 100, np.inf)):
        selected = (total > 0) & (train_counts > low) & (train_counts <= high)
        positives, successes = int(total[selected].sum()), int(recovered[selected].sum())
        strata[label] = {
            "seed_count": int(selected.sum()),
            "positive_count": positives,
            "hits_at_10": successes,
            "recall_at_10": successes / positives if positives else 0.0,
        }
    evaluated = total > 0
    return ReconstructionMetric(
        positive_count=denominator,
        cold_artist_positive_count=cold,
        positive_score_count=supported,
        hits_at_1=hits[0],
        hits_at_5=hits[1],
        hits_at_10=hits[2],
        recall_at_1=hits[0] / denominator if denominator else 0.0,
        recall_at_5=hits[1] / denominator if denominator else 0.0,
        recall_at_10=hits[2] / denominator if denominator else 0.0,
        macro_seed_recall_at_10=float(np.mean(recovered[evaluated] / total[evaluated]))
        if evaluated.any()
        else 0.0,
        mrr_at_10=reciprocal / denominator if denominator else 0.0,
        evaluated_seed_count=int(evaluated.sum()),
        train_support_strata=strata,
    )


def select_arm(metrics: Mapping[str, ReconstructionMetric]) -> str:
    """Select on validation, requiring macro recall at least as high as the baseline."""
    eligible = [
        arm
        for arm in ARMS
        if metrics[arm].macro_seed_recall_at_10 >= metrics[ARMS[0]].macro_seed_recall_at_10
    ]
    return max(
        eligible,
        key=lambda arm: (metrics[arm].recall_at_10, metrics[arm].mrr_at_10, -ARMS.index(arm)),
    )


def _preview(index: ObservationIndex, transfer: np.ndarray) -> list[dict[str, object]]:
    """Summarize positive influences with shared direct evidence and full model scores.

    Peer lists are bounded explanations, not the coefficient matrix used for scoring.
    Artist proposals retain all positive and negative contributing seed identities.
    """
    shared = (index.binary.T @ index.binary).toarray()
    observed = index.binary.tocsc()
    rows: list[dict[str, object]] = []
    for column, seed in enumerate(index.seeds):
        influences = transfer[:, column].copy()
        influences[shared[:, column] < MIN_SHARED] = 0
        peers = _ranking(influences, np.array([column]), DISPLAY_K)
        scores = np.asarray(index.binary @ transfer[:, column]).ravel()
        known = observed.indices[observed.indptr[column] : observed.indptr[column + 1]]
        candidates = _ranking(scores, known, DISPLAY_K)
        proposals = []
        for artist in candidates:
            features = index.binary.getrow(int(artist)).indices
            proposals.append(
                {
                    "artist_mbid": index.artists[int(artist)],
                    "score": float(scores[artist]),
                    "role": "inferred_artist_candidate",
                    "via_seed_ids": [
                        index.seeds[int(j)] for j in features if transfer[j, column] > 0
                    ],
                    "opposing_seed_ids": [
                        index.seeds[int(j)] for j in features if transfer[j, column] < 0
                    ],
                }
            )
        rows.append(
            {
                "seed_id": seed,
                "observed_artist_count": len(known),
                "state": "supported" if len(peers) else "abstained_insufficient_shared_artists",
                "peers": [
                    {
                        "seed_id": index.seeds[int(j)],
                        "score": float(influences[j]),
                        "shared_artist_count": int(shared[j, column]),
                        "role": "inferred_genre_overlap_neighbor",
                    }
                    for j in peers
                ],
                "artist_candidates": proposals,
            }
        )
    return rows


def build_reconstruction(
    *, receipt_path: Path, object_store: Path, output: Path
) -> dict[str, object]:
    """Fit frozen competitors, select on validation, score test once, and save a local fit."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a reconstruction run")
    receipt_bytes = receipt_path.read_bytes()
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(receipt_bytes)
    grouped: dict[str, set[str]] = defaultdict(set)
    for claim in iter_verified_portable_direct_proper_genre_claims(
        receipt, object_store=object_store
    ):
        grouped[claim.seed_id].add(claim.artist_mbid)
    memberships = {seed: tuple(sorted(artists)) for seed, artists in sorted(grouped.items())}
    outer_members, test = split_observations(memberships, partition="outer")
    inner_members, validation = split_observations(outer_members, partition="inner")
    inner = observation_index(inner_members)
    validation_metrics = {
        arm: evaluate_transfer(inner, validation, fit_transfer(inner, arm)) for arm in ARMS
    }
    selected = select_arm(validation_metrics)
    outer = observation_index(outer_members)
    # The test is touched only after validation has irrevocably selected the arm.
    test_metrics = {
        arm: evaluate_transfer(outer, test, fit_transfer(outer, arm))
        for arm in dict.fromkeys((ARMS[0], selected))
    }
    full = observation_index(memberships)
    transfer = fit_transfer(full, selected)
    model = {
        "revision": REVISION,
        "scope": "local_research_only",
        "fit": "full_source_refit",
        "selected_arm": selected,
        "public_export_authorized": False,
        "serving_authorized": False,
        "custody_receipt_output_sha256": receipt.output_sha256,
        "custody_object_sha256": receipt.claims_object_sha256,
        "input_role": "direct_artist_proper_genre_observations_only",
        "genre_to_artist_ranking_evaluated": False,
        "genres": _preview(full, transfer),
    }
    output.mkdir(parents=True)
    (output / "model.json").write_bytes(canonical_json(model) + b"\n")
    (output / "identities.json").write_bytes(
        canonical_json({"artists": full.artists, "seeds": full.seeds}) + b"\n"
    )
    sparse.save_npz(output / "observations.npz", full.binary)
    np.save(output / "transfer.npy", transfer, allow_pickle=False)
    report: dict[str, object] = {
        "revision": REVISION,
        "scope": "local_research_only",
        "selected_arm": selected,
        "declared_arms": ARMS,
        "artist_count": len(full.artists),
        "observed_seed_count": len(full.seeds),
        "unique_observation_count": full.binary.nnz,
        "input_role": "direct_artist_proper_genre_observations_only",
        "historical_coordinates_or_assignments_used": False,
        "names_used_for_training": False,
        "release_context_or_tags_used": False,
        "absence_is_negative": False,
        "training_objective": "regularized squared reconstruction of observed binary source matrix",
        "zero_training_entries": "unobserved; reconstruction surrogate, not verified negatives",
        "independent_source_gold": False,
        "public_export_authorized": False,
        "serving_authorized": False,
        "genre_to_artist_ranking_evaluated": False,
        "artist_neighbor_ranking_evaluated": False,
        "custody_receipt_byte_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "custody_receipt_output_sha256": receipt.output_sha256,
        "custody_object_sha256": receipt.claims_object_sha256,
        "code_sha256": sha256_file(Path(__file__))[0],
        "baseline_code_sha256": sha256_file(
            Path(__file__).with_name("direct_custody_neighborhoods.py")
        )[0],
        "split_rule": (
            "SHA256(revision,NUL,partition,NUL,seed,NUL,artist), lowest fifth; retain four"
        ),
        "split_counts": {
            "inner_train": inner.binary.nnz,
            "validation": sum(map(len, validation.values())),
            "outer_train": outer.binary.nnz,
            "test": sum(map(len, test.values())),
        },
        "selection_rule": (
            "validation macro Recall@10 >= baseline; maximize micro Recall@10, "
            "then MRR@10, then declared arm order"
        ),
        "test_policy": "selected arm and prior baseline only; no test-based reselection",
        "validation": {arm: asdict(metric) for arm, metric in validation_metrics.items()},
        "test": {arm: asdict(metric) for arm, metric in test_metrics.items()},
        "coefficient_shape": list(transfer.shape),
        "negative_coefficient_count": int((transfer < 0).sum()),
        "runtime_versions": {"numpy": np.__version__, "scipy": scipy.__version__},
        "files": {
            name: {"sha256": sha256_file(output / name)[0], "bytes": (output / name).stat().st_size}
            for name in ("model.json", "identities.json", "observations.npz", "transfer.npy")
        },
    }
    report["output_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report


def load_reconstruction(directory: Path) -> tuple[ObservationIndex, np.ndarray]:
    """Verify every output binding before exposing a signed reconstruction matrix."""
    index = load_neighborhood_index(directory)
    report = json.loads((directory / "report.json").read_bytes())
    if report.get("revision") != REVISION:
        raise ValueError("unexpected reconstruction revision")
    binding = report["files"]["transfer.npy"]
    if sha256_file(directory / "transfer.npy") != (binding["sha256"], binding["bytes"]):
        raise ValueError("reconstruction coefficient byte binding mismatch")
    transfer = np.load(directory / "transfer.npy", allow_pickle=False)
    if (
        transfer.shape != (len(index.seeds), len(index.seeds))
        or not np.isfinite(transfer).all()
        or np.any(np.diag(transfer) != 0)
    ):
        raise ValueError("invalid reconstruction coefficient contract")
    return index, transfer


def predict_artist_genres(
    index: ObservationIndex, transfer: np.ndarray, artist_mbid: str, *, limit: int = RANK_K
) -> list[dict[str, object]]:
    """Rank inferred genres with signed source contributions; cold artists abstain."""
    if not 1 <= limit <= DISPLAY_K:
        raise ValueError("prediction limit must be from 1 through 20")
    if transfer.shape != (len(index.seeds), len(index.seeds)) or not np.isfinite(transfer).all():
        raise ValueError("invalid transfer shape or values")
    if artist_mbid not in index.artists:
        return []
    row = index.artists.index(artist_mbid)
    profile = index.binary.getrow(row)
    scores = np.asarray(profile @ transfer).ravel()
    selected = _ranking(scores, profile.indices, limit)
    return [
        {
            "seed_id": index.seeds[int(target)],
            "score": float(scores[target]),
            "role": "inferred_genre_candidate",
            "contributions": [
                {"seed_id": index.seeds[int(j)], "weight": float(transfer[j, target])}
                for j in profile.indices
                if transfer[j, target] != 0
            ],
        }
        for target in selected
    ]


def verify_artist_proposal(  # noqa: PLR0913 - explicit typed proposal evidence boundary.
    *,
    index: ObservationIndex,
    transfer: np.ndarray,
    seed_id: str,
    artist_mbid: str,
    score: float,
    via_seed_ids: tuple[str, ...],
    opposing_seed_ids: tuple[str, ...],
) -> None:
    """Replay signed proposal evidence against all direct inputs, not display peers."""
    target = bisect_left(index.seeds, seed_id)
    row = bisect_left(index.artists, artist_mbid)
    if (
        target >= len(index.seeds)
        or index.seeds[target] != seed_id
        or row >= len(index.artists)
        or index.artists[row] != artist_mbid
    ):
        raise ValueError("proposal contains an unknown source identity")
    known = index.binary.getrow(row).indices
    if target in known:
        raise ValueError("proposal duplicates a direct observation")
    positive = tuple(index.seeds[int(j)] for j in known if transfer[j, target] > 0)
    negative = tuple(index.seeds[int(j)] for j in known if transfer[j, target] < 0)
    actual = float(transfer[known, target].sum())
    if (
        via_seed_ids != positive
        or opposing_seed_ids != negative
        or not np.isfinite(score)
        or score <= 0
        or not np.isclose(score, actual, rtol=1e-10, atol=1e-12)
    ):
        raise ValueError("proposal signed contributions do not replay")
