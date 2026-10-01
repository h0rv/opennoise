"""Independent support diagnostics for inferred communities, never genre ground truth.

Only musical feature identities enter this evaluator. Geography, dates, names,
historical assignments, and display coordinates are excluded by the caller.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from pydantic import TypeAdapter
from scipy import sparse

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

MAX_ARTISTS = 250_000
MAX_FEATURES = 100_000
MAX_OBSERVATIONS = 5_000_000
MAX_NULL_REPLICATES = 499
COHERENCE_SAMPLE_SIZE = 10_000


@dataclass(frozen=True, order=True)
class FeatureFact:
    """One musical feature observation and its upstream independence unit.

    Reissues and repeated credits must use the same release-group evidence key;
    repeated votes for an artist tag must use the same artist/source/tag key.
    """

    artist_id: str
    feature_id: str
    evidence_group: str


def split_feature_evidence(
    facts: Iterable[FeatureFact], *, salt: str
) -> tuple[tuple[FeatureFact, ...], tuple[FeatureFact, ...]]:
    """Withhold whole evidence components, including duplicated artist-feature pairs.

    Components join shared evidence groups and repeated artist-feature pairs.
    This intentionally cannot guarantee a usable training profile for every artist.
    """
    rows = tuple(sorted(set(facts)))
    parent: dict[str, str] = {}

    def root(value: str) -> str:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    pair_group: dict[tuple[str, str], str] = {}
    for fact in rows:
        if not fact.artist_id or not fact.feature_id or not fact.evidence_group:
            raise ValueError("feature evidence requires exact identities and an independence group")
        group = root(fact.evidence_group)
        pair = (fact.artist_id, fact.feature_id)
        other = root(pair_group.setdefault(pair, group))
        parent[max(group, other)] = min(group, other)
    train: list[FeatureFact] = []
    held_out: list[FeatureFact] = []
    for fact in rows:
        digest = hashlib.sha256(f"{salt}\0{root(fact.evidence_group)}".encode()).digest()
        (held_out if int.from_bytes(digest, "big") % 5 == 0 else train).append(fact)
    result = tuple(train), tuple(held_out)
    assert_feature_holdout_isolation(*result)
    return result


def assert_feature_holdout_isolation(
    train: Iterable[FeatureFact], held_out: Iterable[FeatureFact]
) -> None:
    """Reject vote/reissue/credit duplication across an evaluation boundary."""
    left, right = tuple(train), tuple(held_out)
    if {fact.evidence_group for fact in left} & {fact.evidence_group for fact in right}:
        raise ValueError("held-out evidence group also occurs in training")
    if {(fact.artist_id, fact.feature_id) for fact in left} & {
        (fact.artist_id, fact.feature_id) for fact in right
    }:
        raise ValueError("held-out artist-feature pair also occurs in training")


def evaluate_feature_recovery(
    train: Iterable[FeatureFact],
    held_out: Iterable[FeatureFact],
    rankings: Mapping[str, Sequence[str]],
    *,
    limit: int = 10,
) -> dict[str, object]:
    """Measure recovery of isolated positive features with all cold targets retained.

    Rankings must be frozen before reading held-out positives. They may contain
    only training feature identities and must exclude each artist's known facts.
    No precision or negative accuracy is claimed for unobserved metadata.
    """
    if not 1 <= limit <= 100:  # noqa: PLR2004 - bounded externally supplied ranking contract.
        raise ValueError("feature recovery rank limit must be between one and 100")
    observed, targets = tuple(train), tuple(held_out)
    assert_feature_holdout_isolation(observed, targets)
    known: dict[str, set[str]] = defaultdict(set)
    for fact in observed:
        known[fact.artist_id].add(fact.feature_id)
    universe = {fact.feature_id for fact in observed}
    artists = set(known) | {fact.artist_id for fact in targets}
    if set(rankings) - artists:
        raise ValueError("feature ranking references an unknown evaluation artist")
    for artist, features in rankings.items():
        if len(features) != len(set(features)):
            raise ValueError("feature ranking contains duplicate candidates")
        if set(features) - universe or set(features) & known[artist]:
            raise ValueError("feature ranking contains unknown or already observed candidates")
    pairs = sorted({(fact.artist_id, fact.feature_id) for fact in targets})
    hits = 0
    reciprocal = 0.0
    for artist, feature in pairs:
        candidates = tuple(rankings.get(artist, ()))[:limit]
        if feature in candidates:
            rank = candidates.index(feature) + 1
            hits += 1
            reciprocal += 1 / rank
    return {
        "evaluation_role": "group_isolated_positive_source_feature_recovery",
        "positive_pair_count": len(pairs),
        "cold_artist_positive_count": sum(not known[artist] for artist, _feature in pairs),
        "unseen_feature_positive_count": sum(feature not in universe for _artist, feature in pairs),
        "rank_limit": limit,
        "hits": hits,
        "recall": hits / len(pairs) if pairs else None,
        "mean_reciprocal_rank_per_positive": reciprocal / len(pairs) if pairs else None,
        "absence_is_negative": False,
        "independent_source_gold": False,
        "ranking_frozen_before_targets_required": True,
    }


def _profiles(
    profiles: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], sparse.csr_matrix]:
    artists = tuple(sorted(profiles))
    normalized = {artist: tuple(sorted(set(profiles[artist]))) for artist in artists}
    features = sorted({feature for values in normalized.values() for feature in values})
    observations = sum(map(len, normalized.values()))
    if (
        len(artists) > MAX_ARTISTS
        or len(features) > MAX_FEATURES
        or observations > MAX_OBSERVATIONS
    ):
        raise ValueError("community evaluation exceeds its explicit sparse bounds")
    feature_index = {feature: column for column, feature in enumerate(features)}
    row_ids, columns = [], []
    for row, artist in enumerate(artists):
        for feature in normalized[artist]:
            row_ids.append(row)
            columns.append(feature_index[feature])
    matrix = sparse.csr_matrix(
        (np.ones(observations), (row_ids, columns)), shape=(len(artists), len(features))
    )
    frequency = np.asarray(matrix.sum(axis=0)).ravel()
    idf = 1 + np.log((len(artists) + 1) / (frequency + 1))
    weighted = matrix.multiply(np.sqrt(idf)).tocsr()
    norms = np.sqrt(np.asarray(weighted.multiply(weighted).sum(axis=1)).ravel())
    weighted = (sparse.diags(1 / np.maximum(norms, 1)) @ weighted).tocsr()
    return artists, normalized, sparse.csr_matrix(weighted)


def _within_cosine(matrix: sparse.csr_matrix, labels: np.ndarray) -> float | None:
    if len(labels) < 2:  # noqa: PLR2004 - a pairwise statistic needs two observations.
        return None
    count = int(labels.max()) + 1
    memberships = sparse.csr_matrix(
        (np.ones(len(labels)), (labels, np.arange(len(labels)))), shape=(count, len(labels))
    )
    sizes = np.bincount(labels, minlength=count)
    pairs = int(np.sum(sizes * (sizes - 1) // 2))
    if not pairs:
        return None
    summed = memberships @ matrix
    total = float(summed.multiply(summed).sum()) - len(labels)
    return float(np.clip(total / (2 * pairs), 0, 1))


def _partition_stability(
    reference: Mapping[str, str | None], other: Mapping[str, str | None]
) -> dict[str, object]:
    shared = sorted(
        artist
        for artist, label in reference.items()
        if label is not None and other.get(artist) is not None
    )
    left = Counter(reference[artist] for artist in shared)
    right = Counter(other[artist] for artist in shared)
    joint = Counter((reference[artist], other[artist]) for artist in shared)
    size = len(shared)
    total_pairs = size * (size - 1) // 2
    left_pairs = sum(value * (value - 1) // 2 for value in left.values())
    right_pairs = sum(value * (value - 1) // 2 for value in right.values())
    ari = None
    if len(left) > 1 and len(right) > 1 and left_pairs and right_pairs:
        overlap = sum(value * (value - 1) // 2 for value in joint.values())
        expected = left_pairs * right_pairs / total_pairs
        maximum = (left_pairs + right_pairs) / 2
        ari = (overlap - expected) / (maximum - expected) if maximum != expected else None
    return {
        "jointly_assigned_artist_count": size,
        "joint_assignment_coverage": size / len(reference) if reference else 0,
        "adjusted_rand_index": ari,
        "status": "evaluated" if ari is not None else "unavailable_degenerate_partition",
    }


def evaluate_communities(
    profiles: Mapping[str, tuple[str, ...]],
    assignments: Mapping[str, str | None],
    *,
    null_replicates: int = 99,
    seed: int = 0,
    resampled_assignments: Sequence[Mapping[str, str | None]] = (),
) -> dict[str, object]:
    """Audit a disjoint primary partition using musical observations alone.

    Coherence is descriptive in-sample support, not a held-out accuracy claim.
    The null preserves community sizes and each community's feature-degree mix.
    Resamples must be fitted independently; this function never fits or tunes models.
    """
    if not 1 <= null_replicates <= MAX_NULL_REPLICATES:
        raise ValueError("null replicate count must be between one and 499")
    artists, canonical, matrix = _profiles(profiles)
    if set(assignments) - set(artists) or any(
        set(run) - set(artists) for run in resampled_assignments
    ):
        raise ValueError("community assignment references an unknown source artist")
    full = {artist: assignments.get(artist) for artist in artists}
    assigned = [row for row, artist in enumerate(artists) if full[artist] is not None]
    if any(not canonical[artists[row]] for row in assigned):
        raise ValueError("artists without musical features must abstain")
    labels = sorted({str(full[artists[row]]) for row in assigned})
    if any(not isinstance(full[artists[row]], str) or not full[artists[row]] for row in assigned):
        raise ValueError("community identities must be nonempty strings")
    label_index = {label: column for column, label in enumerate(labels)}
    sample = set(
        sorted(
            range(len(artists)),
            key=lambda row: hashlib.sha256(
                f"community-evaluation-sample-v1\0{artists[row]}".encode()
            ).digest(),
        )[:COHERENCE_SAMPLE_SIZE]
    )
    evaluated = [row for row in assigned if row in sample]
    numeric = np.array([label_index[str(full[artists[row]])] for row in evaluated], dtype=np.int64)
    signals = matrix[evaluated].tocsr()
    grouped: dict[str, list[str]] = defaultdict(list)
    signatures: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for row in assigned:
        artist = artists[row]
        label = str(full[artist])
        grouped[label].append(artist)
        signatures[canonical[artist]].add(label)
    split_profiles = sum(len(values) > 1 for values in signatures.values())
    communities = [
        {
            "community_id": label,
            "artist_count": len(members),
            "distinct_musical_profile_count": len({canonical[artist] for artist in members}),
        }
        for label, members in sorted(grouped.items())
    ]
    degrees = np.array([len(canonical[artists[row]]) for row in evaluated])
    strata = [np.flatnonzero(degrees == degree) for degree in np.unique(degrees)]
    observed = _within_cosine(signals, numeric)
    rng = np.random.default_rng(seed)
    null_values = []
    for _ in range(null_replicates):
        shuffled = numeric.copy()
        for rows in strata:
            shuffled[rows] = rng.permutation(numeric[rows])
        value = _within_cosine(signals, shuffled)
        if value is not None:
            null_values.append(value)
    null_mean = float(np.mean(null_values)) if null_values else None
    probability = (
        (1 + sum(value >= observed - 1e-12 for value in null_values)) / (1 + len(null_values))
        if observed is not None and null_values
        else None
    )
    stability = [_partition_stability(full, run) for run in resampled_assignments]
    return {
        "revision": "emergent-community-independent-evaluation-v1",
        "scope": "local_research_only",
        "evaluation_role": "source_feature_support_diagnostic_not_genre_ground_truth",
        "musical_features_only_required": True,
        "historical_assignments_used": False,
        "audio_used": False,
        "genre_names_validated": False,
        "held_out_prediction_evaluated": False,
        "overlapping_memberships_evaluated": False,
        "artist_count": len(artists),
        "assigned_artist_count": len(assigned),
        "abstained_artist_count": len(artists) - len(assigned),
        "community_count": len(communities),
        "communities": communities,
        "identical_musical_profiles_split_count": split_profiles,
        "identical_profile_constraint_passed": split_profiles == 0,
        "single_profile_community_count": sum(
            row["distinct_musical_profile_count"] == 1 for row in communities
        ),
        "coherence_evaluated_artist_count": len(evaluated),
        "coherence_sample_rule": "lowest_sha256_of_revision_and_exact_artist_id_before_assignment",
        "coherence_sample_maximum": COHERENCE_SAMPLE_SIZE,
        "within_community_idf_cosine": observed,
        "null": {
            "method": "shuffle_assignments_within_exact_musical_feature_degree",
            "replicates": len(null_values),
            "seed": seed,
            "mean_within_community_idf_cosine": null_mean,
            "observed_minus_null_mean": observed - null_mean
            if observed is not None and null_mean is not None
            else None,
            "upper_tail_empirical_p": probability,
            "selection_corrected": False,
        },
        "resample_stability": stability,
        "stability_status": "evaluated" if stability else "unavailable_no_independent_refits",
    }


def evaluate_topic_run(*, directory: Path, output: Path) -> dict[str, object]:
    """Verify a frozen topic run and independently diagnose its three primary levels."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace an independent community evaluation")
    report = json.loads((directory / "report.json").read_bytes())
    digest = report.pop("output_sha256")
    if sha256_json(report) != digest:
        raise ValueError("topic report hash mismatch")
    if (
        report["revision"]
        not in {
            "emergent-source-music-topics-v1",
            "emergent-source-music-topics-v3",
            "emergent-source-music-topics-v4",
        }
        or report["scope"] != "local_research_only"
        or report["historical_inputs_used"] is not False
        or report["artist_names_used_for_construction"] is not False
    ):
        raise ValueError("topic run does not declare the source-only construction boundary")
    for name in (
        "communities.json",
        "assignments.jsonl",
        "primary-assignments.json",
        "musical-profiles.jsonl",
    ):
        binding = report["files"][name]
        if sha256_file(directory / name) != (binding["sha256"], binding["bytes"]):
            raise ValueError("topic artifact bytes differ from the frozen report")
    profiles = {}
    with (directory / "musical-profiles.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            artist = row["artist_mbid"]
            if not isinstance(artist, str) or artist in profiles:
                raise ValueError("topic profile identities must be unique exact strings")
            profiles[artist] = TypeAdapter(tuple[str, ...]).validate_python(row["musical_features"])
    primary = TypeAdapter(dict[str, dict[str, str | None]]).validate_json(
        (directory / "primary-assignments.json").read_bytes()
    )
    if set(primary) != {"broad", "sub", "micro"} or any(
        assignments.keys() != profiles.keys() for assignments in primary.values()
    ):
        raise ValueError("topic primary partitions do not cover the complete source cohort")
    evaluations = {
        level: evaluate_communities(profiles, assignments) for level, assignments in primary.items()
    }
    result: dict[str, object] = {
        "revision": "emergent-topic-independent-evaluation-v1",
        "scope": "local_research_only",
        "model_report_output_sha256": digest,
        "features_sha256": report["features_sha256"],
        "evaluator_sha256": sha256_file(Path(__file__))[0],
        "primary_partition_evaluations": evaluations,
        "all_identical_profile_constraints_passed": all(
            cast("bool", evaluation["identical_profile_constraint_passed"])
            for evaluation in evaluations.values()
        ),
        "genre_names_validated": False,
        "held_out_prediction_evaluated": False,
        "independent_refit_stability_evaluated": False,
        "spotify_or_every_noise_parity_established": False,
    }
    result["output_sha256"] = sha256_json(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical_json(result) + b"\n")
    return result
