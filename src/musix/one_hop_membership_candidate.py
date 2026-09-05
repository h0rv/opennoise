"""Sealed, public-input-only conservative one-hop membership experiment."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.ml.public_graph import _direct_scores
from musix.models import FrozenModel
from musix.models.modeling import ArtistPairEvidence, PublicModelInput
from musix.types import Sha256

type AbstentionReason = Literal[
    "seed_source_diversity",
    "seed_direct_strength",
    "genre_direct_support",
    "edge_support",
    "edge_window_support",
    "target_missing_taxonomy_anchor",
    "target_taxonomy_distance",
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: object) -> Sha256:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class OneHopMembershipCandidatePolicy(FrozenModel):
    """A priori public graph eligibility rules; none may use external labels."""

    revision: Literal["one-hop-membership-candidate-policy-v2"] = (
        "one-hop-membership-candidate-policy-v2"
    )
    candidate_id: Literal["one-hop-membership-conservative-v2"] = (
        "one-hop-membership-conservative-v2"
    )
    selection_basis: Literal["a_priori_public_inputs_only"] = "a_priori_public_inputs_only"
    minimum_seed_source_diversity: int = Field(default=1, ge=1, le=2)
    minimum_seed_direct_score: FiniteFloat = Field(default=0.85, gt=0.0, le=1.0)
    minimum_genre_direct_seed_count: int = Field(default=3, ge=1)
    minimum_listener_day_support: int = Field(default=15, ge=1)
    minimum_supporting_windows: int = Field(default=2, ge=1)
    required_edge_type: Literal["listenbrainz_privacy_safe_co_listen"] = (
        "listenbrainz_privacy_safe_co_listen"
    )
    maximum_target_taxonomy_distance: int = Field(default=1, ge=0, le=8)
    require_target_direct_taxonomy_anchor: Literal[True] = True
    external_reference_used_for_construction: Literal[False] = False
    historical_input_used_for_construction: Literal[False] = False


class CandidatePath(FrozenModel):
    """One accepted public evidence path behind a candidate membership."""

    seed_artist_id: str
    seed_direct_score: FiniteFloat = Field(gt=0.0, le=1.0)
    seed_source_diversity: int = Field(ge=1)
    genre_direct_seed_count: int = Field(ge=1)
    listener_day_support: int = Field(gt=0)
    supporting_windows: int = Field(gt=0)
    edge_type: Literal["listenbrainz_privacy_safe_co_listen"] = (
        "listenbrainz_privacy_safe_co_listen"
    )
    target_taxonomy_distance: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class CandidateMembership(FrozenModel):
    artist_id: str
    genre_id: str
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    paths: tuple[CandidatePath, ...] = Field(min_length=1)


class AbstentionCount(FrozenModel):
    reason: AbstentionReason
    count: int = Field(ge=0)


class CandidateCoverage(FrozenModel):
    baseline_one_hop_path_count: int = Field(ge=0)
    accepted_path_count: int = Field(ge=0)
    accepted_membership_count: int = Field(ge=0)
    abstentions: tuple[AbstentionCount, ...]

    @model_validator(mode="after")
    def require_partition(self) -> CandidateCoverage:
        if self.baseline_one_hop_path_count != self.accepted_path_count + sum(
            item.count for item in self.abstentions
        ):
            raise ValueError("candidate coverage does not partition one-hop paths")
        return self


class OneHopMembershipCandidateArtifact(FrozenModel):
    """Sealed experimental output. It is not a public serving model artifact."""

    revision: Literal["one-hop-membership-candidate-artifact-v2"] = (
        "one-hop-membership-candidate-artifact-v2"
    )
    non_production_experiment: Literal[True] = True
    post_seal_external_evaluation_required: Literal[True] = True
    input_sha256: Sha256
    policy_sha256: Sha256
    output_sha256: Sha256
    policy: OneHopMembershipCandidatePolicy
    memberships: tuple[CandidateMembership, ...]
    coverage: CandidateCoverage


def _taxonomy_distances(inputs: PublicModelInput) -> dict[str, dict[str, int]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in inputs.hierarchy:
        graph[edge.child_genre_id].add(edge.parent_genre_id)
        graph[edge.parent_genre_id].add(edge.child_genre_id)
    return {
        origin: _bounded_distances(graph, origin)
        for origin in sorted({item.genre_id for item in inputs.genres})
    }


def _bounded_distances(graph: dict[str, set[str]], origin: str) -> dict[str, int]:
    distances = {origin: 0}
    queue: deque[str] = deque((origin,))
    while queue:
        current = queue.popleft()
        for neighbor in sorted(graph[current]):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def _path_failure(
    pair: ArtistPairEvidence,
    seed: object,
    *,
    direct_genres: dict[str, set[str]],
    genre_seed_counts: Counter[str],
    distances: dict[str, dict[str, int]],
    policy: OneHopMembershipCandidatePolicy,
) -> tuple[AbstentionReason | None, int | None]:
    # ``seed`` is a MembershipScore without importing its type into this boundary.
    seed_artist = str(getattr(seed, "artist_id"))
    seed_genre = str(getattr(seed, "genre_id"))
    components = tuple(getattr(seed, "components"))
    source_diversity = len({item.component_kind for item in components})
    if source_diversity < policy.minimum_seed_source_diversity:
        return "seed_source_diversity", None
    if float(getattr(seed, "score")) < policy.minimum_seed_direct_score:
        return "seed_direct_strength", None
    if genre_seed_counts[seed_genre] < policy.minimum_genre_direct_seed_count:
        return "genre_direct_support", None
    if pair.listener_day_support < policy.minimum_listener_day_support:
        return "edge_support", None
    if pair.supporting_windows < policy.minimum_supporting_windows:
        return "edge_window_support", None
    target = pair.right_artist_id if pair.left_artist_id == seed_artist else pair.left_artist_id
    anchors = direct_genres[target]
    if not anchors:
        return "target_missing_taxonomy_anchor", None
    candidate_distances = [distances.get(seed_genre, {}).get(anchor) for anchor in anchors]
    known = [distance for distance in candidate_distances if distance is not None]
    if not known or min(known) > policy.maximum_target_taxonomy_distance:
        return "target_taxonomy_distance", None
    return None, min(known)


def build_one_hop_membership_candidate(
    inputs: PublicModelInput, policy: OneHopMembershipCandidatePolicy
) -> OneHopMembershipCandidateArtifact:
    """Build the one predeclared candidate without consulting external reference labels."""
    direct = _direct_scores(inputs.direct_memberships)
    direct_pairs = {(item.artist_id, item.genre_id) for item in direct}
    direct_genres: dict[str, set[str]] = defaultdict(set)
    seeds: dict[str, list[object]] = defaultdict(list)
    genre_seed_counts: Counter[str] = Counter()
    for item in direct:
        direct_genres[item.artist_id].add(item.genre_id)
        seeds[item.artist_id].append(item)
        genre_seed_counts[item.genre_id] += 1
    distances = _taxonomy_distances(inputs)
    strengths: dict[str, float] = defaultdict(float)
    for pair in inputs.artist_pairs:
        weight = math.log1p(pair.listener_day_support)
        strengths[pair.left_artist_id] += weight
        strengths[pair.right_artist_id] += weight
    raw: dict[tuple[str, str], float] = defaultdict(float)
    paths: dict[tuple[str, str], list[CandidatePath]] = defaultdict(list)
    abstentions: Counter[AbstentionReason] = Counter()
    total_paths = accepted_paths = 0
    for pair in inputs.artist_pairs:
        weight = math.log1p(pair.listener_day_support)
        edge = weight / math.sqrt(strengths[pair.left_artist_id] * strengths[pair.right_artist_id])
        for target, source in ((pair.left_artist_id, pair.right_artist_id), (pair.right_artist_id, pair.left_artist_id)):
            for seed in seeds.get(source, ()):
                if (target, str(getattr(seed, "genre_id"))) in direct_pairs:
                    continue
                total_paths += 1
                failure, distance = _path_failure(
                    pair,
                    seed,
                    direct_genres=direct_genres,
                    genre_seed_counts=genre_seed_counts,
                    distances=distances,
                    policy=policy,
                )
                if failure is not None:
                    abstentions[failure] += 1
                    continue
                accepted_paths += 1
                genre_id = str(getattr(seed, "genre_id"))
                key = (target, genre_id)
                raw[key] += edge * float(getattr(seed, "score"))
                components = tuple(getattr(seed, "components"))
                paths[key].append(
                    CandidatePath(
                        seed_artist_id=str(getattr(seed, "artist_id")),
                        seed_direct_score=float(getattr(seed, "score")),
                        seed_source_diversity=len({item.component_kind for item in components}),
                        genre_direct_seed_count=genre_seed_counts[genre_id],
                        listener_day_support=pair.listener_day_support,
                        supporting_windows=pair.supporting_windows,
                        target_taxonomy_distance=distance if distance is not None else 0,
                        evidence_refs=tuple(sorted((*pair.evidence_refs, *getattr(seed, "evidence_refs")))),
                    )
                )
    maxima: dict[str, float] = defaultdict(float)
    for (_artist, genre), value in raw.items():
        maxima[genre] = max(maxima[genre], value)
    memberships = tuple(
        CandidateMembership(
            artist_id=artist,
            genre_id=genre,
            score=round(value / maxima[genre], 12),
            paths=tuple(sorted(paths[(artist, genre)], key=lambda item: (item.seed_artist_id, item.evidence_refs))),
        )
        for (artist, genre), value in sorted(raw.items())
        if value > 0.0
    )
    coverage = CandidateCoverage(
        baseline_one_hop_path_count=total_paths,
        accepted_path_count=accepted_paths,
        accepted_membership_count=len(memberships),
        abstentions=tuple(
            AbstentionCount(reason=reason, count=abstentions[reason])
            for reason in (
                "seed_source_diversity",
                "seed_direct_strength",
                "genre_direct_support",
                "edge_support",
                "edge_window_support",
                "target_missing_taxonomy_anchor",
                "target_taxonomy_distance",
            )
        ),
    )
    input_sha = _sha256(inputs.model_dump(mode="json"))
    policy_sha = _sha256(policy.model_dump(mode="json"))
    payload = {
        "revision": "one-hop-membership-candidate-artifact-v2",
        "non_production_experiment": True,
        "post_seal_external_evaluation_required": True,
        "input_sha256": input_sha,
        "policy_sha256": policy_sha,
        "policy": policy.model_dump(mode="json"),
        "memberships": [item.model_dump(mode="json") for item in memberships],
        "coverage": coverage.model_dump(mode="json"),
    }
    return OneHopMembershipCandidateArtifact(
        input_sha256=input_sha,
        policy_sha256=policy_sha,
        output_sha256=_sha256(payload),
        policy=policy,
        memberships=memberships,
        coverage=coverage,
    )
