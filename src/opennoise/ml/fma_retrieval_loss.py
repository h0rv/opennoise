"""Read-only source-positive accounting on exact previously inspected predictions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

import numpy as np
import zstandard

from opennoise.ml.fma_component_balanced import load_corpus
from opennoise.ml.fma_retrieval_loss_custody import (
    digest,
    encoded,
    inventory,
    verify_seal,
    write_outputs,
)

MAX_CANDIDATES = 2048
NEIGHBOR_ARM_COUNT = 2
GIANT_COMPONENT = 2
DISTANCE_TOLERANCE = 1e-10

ARMS = (
    "raw44_neighbors",
    "ridge8_neighbors",
    "recording_gaussian",
    "balanced_gaussian",
    "recording_popularity",
)
BUCKETS = (
    "descriptor_or_retrieval_abstention",
    "absent_from_candidate_label_union",
    "available_in_pool_not_retrieved",
    "retrieved_label_below_top10_vote_rank",
    "recovered_top10",
)
REASONS = {
    "missing_descriptors",
    "outside_training_support",
    "raw_zero_norm",
    "embedding_zero_norm",
    "embedding_zero_rank",
    "no_joint_candidates",
}
STAT_COLUMNS = (
    "queries",
    "labeled_queries",
    "positives",
    "hits10",
    "rr_sum",
    "positive_rr_sum",
    "covered_queries",
    "covered_positives",
    "active_label_positives",
    "recoverable_positives",
    "covered_labeled_queries",
    "descriptor_queries",
    "neighbor_queries",
    "descriptor_supported_positives",
)
COVERAGE = ("descriptor_queries", "neighbor_queries", "genre_ranking_queries")


def vote_ranking(neighbors: list[int], labels: dict[int, set[int]]) -> list[int]:
    """Recompute complete positive votes with exact native genre-ID ties."""
    votes: Counter[int] = Counter()
    for track_id in neighbors:
        votes.update(labels[track_id])
    return sorted(votes, key=lambda genre: (-votes[genre], genre))


def loss_buckets(
    positives: set[int], pool: set[int], neighbors: set[int], ranking: list[int], reason: str | None
) -> list[int]:
    """Assign every positive to exactly one ordered descriptive category."""
    counts = [0] * len(BUCKETS)
    recovered = set(ranking[:10])
    for genre in positives:
        if reason is not None:
            bucket = 0
        elif genre not in pool:
            bucket = 1
        elif genre not in neighbors:
            bucket = 2
        elif genre not in recovered:
            bucket = 3
        else:
            bucket = 4
        counts[bucket] += 1
    return counts


def _id_list(values: object, allowed: set[int]) -> list[int]:
    if (
        not isinstance(values, list)
        or any(type(value) is not int or value not in allowed for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Invalid, duplicate or unknown native IDs")
    return cast("list[int]", values)


def candidate_pool(
    payload: dict[str, Any], fold: int, roster: dict[int, dict[str, Any]]
) -> tuple[set[int], set[int]]:
    """Check the fixed shared roster and derive its labels without refitting eligibility."""
    nominated = _id_list(payload["nominated_ids"], set(roster))
    joint = _id_list(payload["joint_ids"], set(nominated))
    if len(nominated) > MAX_CANDIDATES or nominated != sorted(nominated) or joint != sorted(joint):
        raise ValueError("Candidate roster bound or ordering differs")
    groups = [roster[track]["component_id"] for track in nominated]
    if len(set(groups)) != len(groups) or any(
        roster[track]["inner_fold"] == fold for track in nominated
    ):
        raise ValueError("Candidate component or fold leakage")
    descriptor = set(_id_list(payload["intrinsic_descriptor_ids"], set(nominated)))
    raw = set(_id_list(payload["intrinsic_raw_ids"], descriptor))
    embedded = set(_id_list(payload["intrinsic_embedding_ids"], descriptor))
    if set(joint) != raw & embedded:
        raise ValueError("Shared candidate pool differs from saved eligibility")
    union: set[int] = set()
    for track in joint:
        union.update(roster[track]["targets"])
    if _id_list(payload["candidate_label_union"], union) != sorted(union):
        raise ValueError("Candidate source-label union differs")
    return set(joint), union


def validate_prediction(  # noqa: C901, PLR0912, PLR0913, PLR0917 - explicit fixed-arm custody checks.
    prediction: dict[str, Any],
    arm: str,
    query: dict[str, Any],
    pool: set[int],
    labels: dict[int, set[int]],
    roster: dict[int, dict[str, Any]],
    taxonomy: set[int],
    popularity: list[int],
) -> tuple[list[int], set[int]]:
    """Verify fixed votes, eligibility, abstention consistency and control ranking."""
    ranking = _id_list(prediction["ranking"], taxonomy)
    reason = prediction["reason"]
    descriptor = prediction["descriptor_available"]
    if type(descriptor) is not bool or (reason is not None and reason not in REASONS):
        raise ValueError("Invalid prediction status")
    if reason is not None and ranking:
        raise ValueError("Abstained prediction has a ranking")
    if arm == "recording_popularity":
        if ranking != popularity or reason is not None or not descriptor:
            raise ValueError("Original training popularity ranking differs")
        return ranking, set()
    if arm not in ARMS[:2]:
        if reason not in {
            None,
            "missing_descriptors",
            "outside_training_support",
        } or descriptor != (reason is None):
            raise ValueError("Gaussian status is inconsistent")
        return ranking, set()
    allowed = {None, "missing_descriptors", "outside_training_support", "no_joint_candidates"}
    allowed |= (
        {"raw_zero_norm"} if arm == ARMS[0] else {"embedding_zero_norm", "embedding_zero_rank"}
    )
    if reason not in allowed or descriptor != (reason is None or reason == "no_joint_candidates"):
        raise ValueError("Retrieval status is inconsistent")
    neighbors = _id_list(prediction["neighbor_ids"], pool)
    if reason is not None and neighbors:
        raise ValueError("Abstained retrieval has neighbors")
    if reason is None and (not pool or len(neighbors) != min(10, len(pool))):
        raise ValueError("Incomplete supported neighbor roster")
    if reason == "no_joint_candidates" and pool:
        raise ValueError("False empty-pool abstention")
    if any(
        roster[track]["component_id"] == query["component_id"]
        or roster[track]["inner_fold"] == query["inner_fold"]
        for track in neighbors
    ):
        raise ValueError("Neighbor component or fold leakage")
    distances = prediction["cosine_distances"]
    if (
        not isinstance(distances, list)
        or len(distances) != len(neighbors)
        or any(
            type(value) not in {int, float}
            or not np.isfinite(value)
            or value < -DISTANCE_TOLERANCE
            or value > 2 + DISTANCE_TOLERANCE
            or (index and value < distances[index - 1] - DISTANCE_TOLERANCE)
            for index, value in enumerate(distances)
        )
    ):
        raise ValueError("Invalid saved neighbor distances")
    if ranking != vote_ranking(neighbors, labels):
        raise ValueError("Saved positive-label vote ranking differs")
    return ranking, set[int]().union(*(labels[track] for track in neighbors))


def _component(component: int, fold: int) -> dict[str, Any]:
    return {
        "component_id": component,
        "inner_fold": fold,
        "queries": 0,
        "labeled_queries": 0,
        "positives": 0,
        "buckets": [[0] * 5 for _ in range(2)],
        "hits10": [0] * 5,
        "coverage": [[0] * 3 for _ in range(5)],
        "reasons": {arm: {} for arm in ARMS},
    }


def analyze_fold(
    folder: Path, fold: int, roster: dict[int, dict[str, Any]], taxonomy: set[int]
) -> list[dict[str, Any]]:
    """Stream each original held-out query exactly once; no scoring or geometry changes."""
    expected = {track for track, row in roster.items() if row["inner_fold"] == fold}
    pool, union = candidate_pool(
        json.loads((folder / "candidates.json").read_bytes()), fold, roster
    )
    labels = {track: row["targets"] for track, row in roster.items()}
    support: Counter[int] = Counter()
    for track, row in roster.items():
        if row["inner_fold"] != fold:
            support.update(labels[track])
    popularity = sorted(support, key=lambda genre: (-support[genre], genre))
    components: dict[int, dict[str, Any]] = {}
    seen: set[int] = set()
    coverage_checks: dict[int, np.ndarray] = {}
    with zstandard.open(folder / "ranks.jsonl.zst", "rt") as stream:
        for line in stream:
            saved = json.loads(line)
            track = saved["track_id"]
            if type(track) is not int or track not in expected or track in seen:
                raise ValueError("Duplicate or unexpected held-out query")
            seen.add(track)
            query = roster[track]
            if (
                type(saved["component_id"]) is not int
                or type(saved["inner_fold"]) is not int
                or saved["component_id"] != query["component_id"]
                or saved["inner_fold"] != fold
                or _id_list(saved["targets"], taxonomy) != sorted(query["targets"])
                or set(saved["arms"]) != set(ARMS)
            ):
                raise ValueError("Saved query identity or target labels differ")
            component = query["component_id"]
            row = components.setdefault(component, _component(component, fold))
            checks = coverage_checks.setdefault(component, np.zeros((5, 9), dtype=np.int64))
            positives = query["targets"]
            row["queries"] += 1
            row["labeled_queries"] += bool(positives)
            row["positives"] += len(positives)
            for index, arm in enumerate(ARMS):
                prediction = saved["arms"][arm]
                ranking, selected = validate_prediction(
                    prediction, arm, query, pool, labels, roster, taxonomy, popularity
                )
                hits = len(positives.intersection(ranking[:10]))
                covered = bool(ranking)
                neighbors = bool(prediction.get("neighbor_ids", []))
                descriptor = prediction["descriptor_available"]
                row["hits10"][index] += hits
                row["coverage"][index] = [
                    a + int(b)
                    for a, b in zip(
                        row["coverage"][index], [descriptor, neighbors, covered], strict=True
                    )
                ]
                checks[index] += [
                    1,
                    bool(positives),
                    len(positives),
                    hits,
                    covered,
                    len(positives) * covered,
                    bool(positives) * covered,
                    descriptor,
                    neighbors,
                ]
                reason = prediction["reason"]
                if reason is not None:
                    row["reasons"][arm][reason] = row["reasons"][arm].get(reason, 0) + 1
                if index < NEIGHBOR_ARM_COUNT:
                    buckets = loss_buckets(positives, union, selected, ranking, reason)
                    row["buckets"][index] = [
                        a + b for a, b in zip(row["buckets"][index], buckets, strict=True)
                    ]
    if seen != expected:
        raise ValueError("Omitted held-out queries")
    _verify_statistics(folder, components, coverage_checks, len(expected))
    return [components[key] for key in sorted(components)]


def _verify_statistics(
    folder: Path, components: dict[int, dict[str, Any]], checks: dict[int, np.ndarray], queries: int
) -> None:
    with np.load(folder / "statistics.npz", allow_pickle=False) as saved:
        if set(saved.files) != {"components", "values"}:
            raise ValueError("Saved statistics schema differs")
        ids, values = saved["components"], saved["values"]
    if (
        ids.tolist() != sorted(components)
        or values.shape != (len(components), 5, 14)
        or not np.isfinite(values).all()
    ):
        raise ValueError("Saved component statistics roster differs")
    for index, component in enumerate(ids.tolist()):
        if not np.array_equal(values[index][:, [0, 1, 2, 3, 6, 7, 10, 11, 12]], checks[component]):
            raise ValueError("Original hit or coverage counts differ")
        row = components[component]
        if any(
            sum(buckets) != row["positives"] or buckets[4] != row["hits10"][arm]
            for arm, buckets in enumerate(row["buckets"])
        ):
            raise ValueError("Component positive buckets do not conserve")
    receipt = json.loads((folder / "receipt.json").read_bytes())
    reasons = {
        arm: dict(sum((Counter(row["reasons"][arm]) for row in components.values()), Counter()))
        for arm in ARMS
    }
    if (
        receipt["heldout_queries"] != queries
        or receipt["components"] != len(components)
        or receipt["abstentions"] != reasons
        or receipt["arms"] != list(ARMS)
        or receipt["columns"] != list(STAT_COLUMNS)
    ):
        raise ValueError("Saved receipt population or reasons differ")


def summarize(components: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep full positive denominators and equal weight only defined component ratios."""
    positive = [row for row in components if row["positives"]]
    totals = {
        name: sum(row[name] for row in components)
        for name in ("queries", "labeled_queries", "positives")
    }
    arms = {}
    for index, arm in enumerate(ARMS):
        hits = sum(row["hits10"][index] for row in components)
        value = {
            "hits10": hits,
            "recall10": hits / totals["positives"] if totals["positives"] else None,
            "component_equal_recall10": sum(
                row["hits10"][index] / row["positives"] for row in positive
            )
            / len(positive)
            if positive
            else None,
            "coverage": {
                name: sum(row["coverage"][index][col] for row in components)
                for col, name in enumerate(COVERAGE)
            },
            "abstention_reasons": dict(
                sum((Counter(row["reasons"][arm]) for row in components), Counter())
            ),
        }
        if index < NEIGHBOR_ARM_COUNT:
            buckets = [sum(row["buckets"][index][col] for row in components) for col in range(5)]
            if sum(buckets) != totals["positives"] or buckets[4] != hits:
                raise ValueError("Aggregate loss buckets do not conserve")
            value.update(
                buckets=dict(zip(BUCKETS, buckets, strict=True)),
                positive_fractions=[count / totals["positives"] for count in buckets]
                if totals["positives"]
                else None,
                component_equal_fractions=[
                    sum(row["buckets"][index][col] / row["positives"] for row in positive)
                    / len(positive)
                    for col in range(5)
                ]
                if positive
                else None,
            )
        arms[arm] = value
    return {
        **totals,
        "components": len(components),
        "positive_components": len(positive),
        "arms": arms,
    }


def compute(seal: Path) -> dict[str, Any]:
    """Verify frozen inputs and recompute deterministic descriptive outputs only."""
    spec = verify_seal(seal)
    data = load_corpus({"source": spec["source"]})
    roster = {}
    for index, track in enumerate(data.ids.tolist()):
        labels = data.targets.indices[data.targets.indptr[index] : data.targets.indptr[index + 1]]
        roster[track] = {
            "component_id": int(data.groups[index]),
            "inner_fold": int(data.inner_folds[index]),
            "targets": {data.labels[col] for col in labels},
        }
    components = []
    for fold in range(5):
        components.extend(
            analyze_fold(Path(spec["run"]) / f"fold-{fold}", fold, roster, set(data.labels))
        )
    components.sort(key=lambda row: row["component_id"])
    if len({row["component_id"] for row in components}) != len(components) or sum(
        row["queries"] for row in components
    ) != len(roster):
        raise ValueError("Global query or component conservation differs")
    results = {
        "revision": "fma-frozen-retrieval-loss-v1",
        "pooled": summarize(components),
        "per_fold": {
            str(fold): summarize([row for row in components if row["inner_fold"] == fold])
            for fold in range(5)
        },
        "giant_component_2": summarize(
            [row for row in components if row["component_id"] == GIANT_COMPONENT]
        ),
        "all_other_components": summarize(
            [row for row in components if row["component_id"] != GIANT_COMPONENT]
        ),
        "interpretation": spec["protocol"]["interpretation"],
    }
    return {
        "results.json": results,
        "components.json": {
            "arms": ARMS,
            "buckets": BUCKETS,
            "coverage_columns": COVERAGE,
            "components": components,
        },
    }


def run(seal: Path, output: Path) -> None:
    """Write a fresh diagnostic with closed, source-bound output hashes."""
    values = compute(seal)

    values["receipt.json"] = {
        "revision": "fma-retrieval-loss-output-v1",
        "seal_sha256": digest(seal),
        "deploy_authorized": False,
        "model_fit": False,
        "files": {
            name: {
                "bytes": len(encoded(value)),
                "sha256": hashlib.sha256(encoded(value)).hexdigest(),
            }
            for name, value in values.items()
        },
    }
    write_outputs(output, values)


def replay(seal: Path, output: Path) -> None:
    """Reject changed output claims even when their local hashes were recomputed."""
    values = compute(seal)
    actual = inventory(output)
    receipt = json.loads((output / "receipt.json").read_bytes())
    if (
        set(actual) != set(values) | {"receipt.json"}
        or set(receipt) != {"revision", "seal_sha256", "deploy_authorized", "model_fit", "files"}
        or receipt["revision"] != "fma-retrieval-loss-output-v1"
        or receipt["seal_sha256"] != digest(seal)
        or receipt["deploy_authorized"] is not False
        or receipt["model_fit"] is not False
        or receipt["files"] != {name: actual[name] for name in values}
    ):
        raise ValueError("Diagnostic output inventory or claims differ")
    if any((output / name).read_bytes() != encoded(value) for name, value in values.items()):
        raise ValueError("Numerical diagnostic replay differs")
