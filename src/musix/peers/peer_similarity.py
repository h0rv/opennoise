"""Deterministic, public-evidence genre peer-similarity candidates.

This module is deliberately a small layer beside the public graph builder.  It
consumes the already typed public input boundary and emits a candidate artifact
whose undirected pairs are explainable from direct artist membership overlap
and privacy-safe, listener-day aggregates.  It does not consume coordinates,
audio, historical data, or listener identities.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.public_artist_membership import (
    GenreDisposition,
    PublicArtistMembershipCandidateArtifact,
    verify_public_artist_membership_candidate,
)
from musix.taxonomy.seed_reconciliation import (
    SeedReconciliationArtifact,
    verify_seed_reconciliation,
)
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from musix.evidence.reconstruction import ReconstructionInputs

_REVISION = "genre-peer-similarity-v4"
_RECEIPT_REVISION = "genre-peer-similarity-receipt-v4"
_GATE_REVISION = "genre-peer-similarity-gate-v4"
_SETTINGS_REVISION = "genre-peer-similarity-v3"
_MAX_GENRES = 20_000
_MAX_CANDIDATES = 500_000
_MAX_PAIR_VISITS = 5_000_000
_NAME_UNIVERSE_COUNT = 6_291
_MAX_EVIDENCE_REF_LENGTH = 500

type PeerMetric = Literal["weighted_jaccard", "cosine"]
type PairSufficiency = Literal["direct_and_aggregate", "direct_only", "aggregate_only"]
type AbstentionReason = Literal[
    "insufficient_direct_overlap",
    "insufficient_aggregate_support",
    "insufficient_combined_support",
]


class PeerSimilaritySettings(FrozenModel):
    """Versioned, bounded settings for one peer candidate build."""

    revision: Literal["genre-peer-similarity-v3"] = _SETTINGS_REVISION
    metric: PeerMetric = "weighted_jaccard"
    minimum_shared_artists: int = Field(default=2, ge=1, le=10_000)
    minimum_aggregate_support: int = Field(default=2, ge=1, le=100_000_000)
    minimum_aggregate_windows: int = Field(default=1, ge=1, le=366)
    direct_component_weight: FiniteFloat = Field(default=0.7, ge=0.0, le=1.0)
    aggregate_component_weight: FiniteFloat = Field(default=0.3, ge=0.0, le=1.0)
    maximum_neighbors: int = Field(default=25, ge=1, le=100)
    maximum_candidate_pairs: int = Field(default=_MAX_CANDIDATES, ge=1, le=_MAX_CANDIDATES)
    maximum_pair_visits: int = Field(default=_MAX_PAIR_VISITS, ge=1, le=_MAX_PAIR_VISITS)

    @model_validator(mode="after")
    def require_component_weight(self) -> PeerSimilaritySettings:
        """Require a meaningful, explicitly weighted score."""
        if self.direct_component_weight + self.aggregate_component_weight <= 0.0:
            raise ValueError("at least one peer similarity component must have positive weight")
        return self


class PeerSimilarityComponent(FrozenModel):
    """One visible scoring component for an undirected genre pair."""

    component_kind: Literal["direct_artist_overlap", "aggregate_listening_support"]
    raw_value: FiniteFloat = Field(ge=0.0)
    normalized_value: FiniteFloat = Field(ge=0.0, le=1.0)
    configured_weight: FiniteFloat = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_support_reference(self) -> PeerSimilarityComponent:
        """Require a traceable reference whenever a component has support."""
        if self.raw_value > 0.0 and not self.evidence_refs:
            raise ValueError("supported peer components require evidence references")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("peer component evidence references must be unique")
        return self


class GenrePeerSimilarityCandidate(FrozenModel):
    """One canonical, symmetric candidate with all score inputs exposed."""

    source_genre_id: str = Field(min_length=1, max_length=200)
    target_genre_id: str = Field(min_length=1, max_length=200)
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    direct_score: FiniteFloat = Field(ge=0.0, le=1.0)
    aggregate_score: FiniteFloat = Field(ge=0.0, le=1.0)
    shared_direct_artist_count: int = Field(ge=0)
    aggregate_listener_day_support: int = Field(ge=0)
    aggregate_supporting_windows: int = Field(ge=0)
    sufficiency: PairSufficiency
    components: tuple[PeerSimilarityComponent, ...] = Field(min_length=1, max_length=2)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_canonical_pair_and_components(self) -> GenrePeerSimilarityCandidate:
        """Prevent directional duplicates and unexplainable score claims."""
        if self.source_genre_id >= self.target_genre_id:
            raise ValueError("peer similarity pairs require ascending distinct genre IDs")
        kinds = {item.component_kind for item in self.components}
        if len(kinds) != len(self.components):
            raise ValueError("peer similarity components must be unique")
        if self.direct_score > 0.0 and "direct_artist_overlap" not in kinds:
            raise ValueError("direct score needs a direct overlap component")
        if self.aggregate_score > 0.0 and "aggregate_listening_support" not in kinds:
            raise ValueError("aggregate score needs a listening component")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("peer candidate evidence references must be unique")
        expected_sufficiency = (
            "direct_and_aggregate"
            if self.direct_score > 0.0 and self.aggregate_score > 0.0
            else "direct_only"
            if self.direct_score > 0.0
            else "aggregate_only"
        )
        if self.sufficiency != expected_sufficiency:
            raise ValueError("peer candidate sufficiency does not match scoring components")
        return self


class GenrePeerSimilarityAbstention(FrozenModel):
    """One observed pair that was intentionally withheld for weak support."""

    source_genre_id: str = Field(min_length=1, max_length=200)
    target_genre_id: str = Field(min_length=1, max_length=200)
    reason: AbstentionReason
    shared_direct_artist_count: int = Field(ge=0)
    aggregate_listener_day_support: int = Field(ge=0)
    aggregate_supporting_windows: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_canonical_pair(self) -> GenrePeerSimilarityAbstention:
        """Keep abstentions as deterministic undirected pair records."""
        if self.source_genre_id >= self.target_genre_id:
            raise ValueError("peer abstentions require ascending distinct genre IDs")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("peer abstention evidence references must be unique")
        return self


class GenrePeerSimilarityNeighbor(FrozenModel):
    """One deterministic directional view over a canonical pair."""

    source_genre_id: str = Field(min_length=1, max_length=200)
    target_genre_id: str = Field(min_length=1, max_length=200)
    rank: int = Field(gt=0, le=100)
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    shared_direct_artist_count: int = Field(ge=0)
    aggregate_listener_day_support: int = Field(ge=0)

    @model_validator(mode="after")
    def require_distinct_endpoints(self) -> GenrePeerSimilarityNeighbor:
        """Reject self-neighbors in the directional serving view."""
        if self.source_genre_id == self.target_genre_id:
            raise ValueError("peer similarity neighbors cannot be self loops")
        return self


class PeerSimilarityCoverage(FrozenModel):
    """Counts that make observed support and withheld pairs auditable."""

    genre_count: int = Field(ge=0, le=_MAX_GENRES)
    observed_direct_membership_count: int = Field(ge=0)
    observed_aggregate_pair_count: int = Field(ge=0)
    direct_artist_count: int = Field(ge=0)
    aggregate_artist_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    abstained_pair_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    directional_neighbor_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    all_inputs_export_allowed: bool


class GenrePeerSimilarityArtifact(FrozenModel):
    """Content-addressed derived candidates, separate from public observations."""

    revision: Literal["genre-peer-similarity-v4"] = _REVISION
    non_production_candidate: Literal[True] = True
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    source_artifacts: tuple[PublicArtifact, ...] = Field(min_length=1, max_length=64)
    similarity_per_seed_accounting: Literal[
        "unbridged", "sealed_membership_bridge-v1", "sealed_seed_reconciliation-v2"
    ] = "unbridged"
    seed_reconciliation_output_sha256: Sha256 | None = None
    seed_reconciliation_name_count: int = Field(default=0, ge=0, le=_NAME_UNIVERSE_COUNT)
    candidate_artifact_sha256: Sha256 | None = None
    candidate_source_content_sha256: Sha256 | None = None
    candidate_name_count: int = Field(default=0, ge=0, le=_NAME_UNIVERSE_COUNT)
    membership_dispositions: tuple[GenreDisposition, ...] = Field(
        default=(), max_length=_NAME_UNIVERSE_COUNT
    )
    candidates: tuple[GenrePeerSimilarityCandidate, ...] = Field(max_length=_MAX_CANDIDATES)
    abstentions: tuple[GenrePeerSimilarityAbstention, ...] = Field(max_length=_MAX_CANDIDATES)
    directional_neighbors: tuple[GenrePeerSimilarityNeighbor, ...] = Field(
        default=(), max_length=_MAX_CANDIDATES
    )
    coverage: PeerSimilarityCoverage

    @model_validator(mode="after")
    def require_complete_candidate_universe(  # noqa: C901
        self,
    ) -> GenrePeerSimilarityArtifact:
        """Preserve every retained name disposition when a sealed candidate is used."""
        if self.similarity_per_seed_accounting == "sealed_seed_reconciliation-v2":
            if self.seed_reconciliation_output_sha256 is None:
                raise ValueError("sealed seed accounting needs its reconciliation output hash")
            if self.seed_reconciliation_name_count != _NAME_UNIVERSE_COUNT:
                raise ValueError("sealed seed accounting must contain exactly 6291 names")
        elif (
            self.seed_reconciliation_output_sha256 is not None
            or self.seed_reconciliation_name_count
        ):
            raise ValueError("seed reconciliation metadata requires sealed seed accounting")
        if self.candidate_name_count == 0:
            if (
                self.candidate_artifact_sha256 is not None
                or self.candidate_source_content_sha256 is not None
                or self.membership_dispositions
            ):
                raise ValueError("candidate metadata needs a complete retained-name universe")
            return self
        if self.similarity_per_seed_accounting != "sealed_membership_bridge-v1":
            raise ValueError("membership candidate metadata requires sealed membership accounting")
        if self.candidate_name_count != _NAME_UNIVERSE_COUNT:
            raise ValueError("candidate name universe must contain exactly 6291 entries")
        if len(self.membership_dispositions) != self.candidate_name_count:
            raise ValueError("candidate dispositions must account for every retained name")
        ids = tuple(item.source_item_id for item in self.membership_dispositions)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate disposition source item IDs must be unique")
        if self.candidate_artifact_sha256 is None:
            raise ValueError("candidate dispositions need the sealed candidate artifact hash")
        if self.candidate_source_content_sha256 is None:
            raise ValueError("candidate dispositions need the sealed name-universe hash")
        return self


class PeerSimilarityReceipt(FrozenModel):
    """Replay receipt binding observed inputs, settings, and derived output."""

    revision: Literal["genre-peer-similarity-receipt-v4"] = _RECEIPT_REVISION
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    candidate_pair_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    abstained_pair_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    deterministic_replay: Literal[True] = True


class PeerSimilarityGateReport(FrozenModel):
    """Fail-closed publication diagnostics for one peer candidate artifact."""

    revision: Literal["genre-peer-similarity-gate-v4"] = _GATE_REVISION
    passed: bool
    failures: tuple[str, ...]
    input_sha256: Sha256
    settings_sha256: Sha256
    artifact_output_sha256: Sha256
    recomputed_output_sha256: Sha256
    candidate_pair_count: int = Field(ge=0)
    abstained_pair_count: int = Field(ge=0)
    symmetric: bool
    bounded_scores: bool
    privacy_safe_inputs: bool
    provenance_complete: bool
    all_inputs_export_allowed: bool
    directional_top_k: bool


class PeerSimilarityGateError(RuntimeError):
    """Raised when candidate output cannot cross its publication gate."""

    def __init__(self, failures: tuple[str, ...]) -> None:
        """Store all gate failures for a useful publication error."""
        self.failures = failures
        super().__init__("genre peer similarity gate failed: " + "; ".join(failures))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _sha256(value: object) -> Sha256:
    return hashlib.sha256(_canonical(value)).hexdigest()


def peer_similarity_output_sha256(artifact: GenrePeerSimilarityArtifact) -> Sha256:
    """Recompute the logical output hash without trusting its stored hash."""
    return _sha256(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def _direct_vectors(
    inputs: PublicModelInput,
) -> tuple[dict[str, dict[str, float]], dict[tuple[str, str], set[str]]]:
    values: dict[tuple[str, str], float] = defaultdict(float)
    refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in inputs.direct_memberships:
        values[(item.genre_id, item.artist_id)] += float(item.value)
        refs[(item.genre_id, item.artist_id)].add(item.evidence_ref)
    vectors: dict[str, dict[str, float]] = defaultdict(dict)
    for (genre, artist), value in sorted(values.items()):
        vectors[genre][artist] = value
    return dict(vectors), dict(refs)


def _direct_pairs(
    vectors: dict[str, dict[str, float]],
    refs_by_key: dict[tuple[str, str], set[str]],
    settings: PeerSimilaritySettings,
) -> tuple[dict[tuple[str, str], tuple[float, int, tuple[str, ...]]], int]:
    pairs: dict[tuple[str, str], tuple[float, int, tuple[str, ...]]] = {}
    visits = 0
    inverted: dict[str, list[str]] = defaultdict(list)
    for genre, artists in vectors.items():
        for artist in artists:
            inverted[artist].append(genre)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    common_artists: dict[tuple[str, str], list[str]] = defaultdict(list)
    for artist, artist_genres in sorted(inverted.items()):
        ordered = sorted(artist_genres)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                visits += 1
                if visits > settings.maximum_pair_visits:
                    raise ValueError("direct overlap exceeds maximum_pair_visits")
                key = (left, right)
                counts[key] += 1
                common_artists[key].append(artist)
    for (left, right), shared_count in sorted(counts.items()):
        common = common_artists[(left, right)]
        minimum_sum = sum(min(vectors[left][artist], vectors[right][artist]) for artist in common)
        union = sum(vectors[left].values()) + sum(vectors[right].values()) - minimum_sum
        dot = sum(vectors[left][artist] * vectors[right][artist] for artist in common)
        left_norm = math.sqrt(sum(value * value for value in vectors[left].values()))
        right_norm = math.sqrt(sum(value * value for value in vectors[right].values()))
        score = (
            minimum_sum / union
            if settings.metric == "weighted_jaccard" and union
            else (dot / (left_norm * right_norm) if left_norm and right_norm else 0.0)
        )
        refs = tuple(
            sorted(
                {
                    ref
                    for artist in common
                    for ref in (
                        *refs_by_key.get((left, artist), set()),
                        *refs_by_key.get((right, artist), set()),
                    )
                }
            )
        )
        pairs[(left, right)] = (score, shared_count, refs)
    return pairs, visits


def _aggregate_pairs(
    inputs: PublicModelInput,
    vectors: dict[str, dict[str, float]],
    settings: PeerSimilaritySettings,
) -> tuple[dict[tuple[str, str], tuple[int, int, tuple[str, ...]]], int]:
    by_artist = {
        artist: tuple(sorted(genres)) for artist, genres in _artist_genres(vectors).items()
    }
    support: dict[tuple[str, str], int] = defaultdict(int)
    windows: dict[tuple[str, str], int] = defaultdict(int)
    refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    visits = 0
    for pair in inputs.artist_pairs:
        left_genres = by_artist.get(pair.left_artist_id, ())
        right_genres = by_artist.get(pair.right_artist_id, ())
        for left in left_genres:
            for right in right_genres:
                if left == right:
                    continue
                key = (left, right) if left < right else (right, left)
                visits += 1
                if visits > settings.maximum_pair_visits:
                    raise ValueError("aggregate overlap exceeds maximum_pair_visits")
                support[key] += pair.listener_day_support
                windows[key] += pair.supporting_windows
                refs[key].update(pair.evidence_refs)
    return {
        key: (support[key], windows[key], tuple(sorted(refs[key]))) for key in sorted(support)
    }, visits


def _artist_genres(vectors: dict[str, dict[str, float]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for genre, artists in vectors.items():
        for artist in artists:
            result[artist].add(genre)
    return result


def build_peer_similarity(  # noqa: C901, PLR0915
    inputs: PublicModelInput,
    settings: PeerSimilaritySettings | None = None,
    *,
    candidate_artifact: PublicArtistMembershipCandidateArtifact | None = None,
    seed_reconciliation: SeedReconciliationArtifact | None = None,
) -> GenrePeerSimilarityArtifact:
    """Build deterministic symmetric candidates from public observations only."""
    resolved = settings or PeerSimilaritySettings()
    _validate_observed_sources(inputs)
    vectors, refs_by_artist = _direct_vectors(inputs)
    direct, _direct_visits = _direct_pairs(vectors, refs_by_artist, resolved)
    aggregate, _aggregate_visits = _aggregate_pairs(inputs, vectors, resolved)
    if _direct_visits + _aggregate_visits > resolved.maximum_pair_visits:
        raise ValueError("peer similarity exceeds maximum_pair_visits")
    pair_keys = sorted(set(direct) | set(aggregate))
    if len(pair_keys) > resolved.maximum_candidate_pairs:
        raise ValueError("peer similarity exceeds maximum_candidate_pairs")
    max_aggregate = max((values[0] for values in aggregate.values()), default=0)
    candidates: list[GenrePeerSimilarityCandidate] = []
    abstentions: list[GenrePeerSimilarityAbstention] = []
    for key in pair_keys:
        direct_score, shared_count, direct_refs = direct.get(key, (0.0, 0, ()))
        aggregate_support, aggregate_windows, aggregate_refs = aggregate.get(key, (0, 0, ()))
        aggregate_score = (
            math.log1p(aggregate_support) / math.log1p(max_aggregate) if max_aggregate else 0.0
        )
        direct_ok = shared_count >= resolved.minimum_shared_artists
        aggregate_ok = (
            aggregate_support >= resolved.minimum_aggregate_support
            and aggregate_windows >= resolved.minimum_aggregate_windows
        )
        evidence_refs = tuple(sorted(set(direct_refs) | set(aggregate_refs)))
        if not direct_ok and not aggregate_ok:
            reason: AbstentionReason = (
                "insufficient_combined_support"
                if direct_score > 0.0 and aggregate_support > 0
                else "insufficient_direct_overlap"
                if direct_score > 0.0
                else "insufficient_aggregate_support"
            )
            abstentions.append(
                GenrePeerSimilarityAbstention(
                    source_genre_id=key[0],
                    target_genre_id=key[1],
                    reason=reason,
                    shared_direct_artist_count=shared_count,
                    aggregate_listener_day_support=aggregate_support,
                    aggregate_supporting_windows=aggregate_windows,
                    evidence_refs=evidence_refs,
                )
            )
            continue
        components: list[PeerSimilarityComponent] = []
        if direct_ok and direct_score > 0.0 and resolved.direct_component_weight > 0.0:
            components.append(
                PeerSimilarityComponent(
                    component_kind="direct_artist_overlap",
                    raw_value=float(shared_count),
                    normalized_value=direct_score,
                    configured_weight=float(resolved.direct_component_weight),
                    evidence_refs=direct_refs,
                )
            )
        if aggregate_ok and aggregate_score > 0.0 and resolved.aggregate_component_weight > 0.0:
            components.append(
                PeerSimilarityComponent(
                    component_kind="aggregate_listening_support",
                    raw_value=float(aggregate_support),
                    normalized_value=aggregate_score,
                    configured_weight=float(resolved.aggregate_component_weight),
                    evidence_refs=aggregate_refs,
                )
            )
        weight_sum = sum(float(item.configured_weight) for item in components)
        if weight_sum <= 0.0:
            abstentions.append(
                GenrePeerSimilarityAbstention(
                    source_genre_id=key[0],
                    target_genre_id=key[1],
                    reason="insufficient_combined_support",
                    shared_direct_artist_count=shared_count,
                    aggregate_listener_day_support=aggregate_support,
                    aggregate_supporting_windows=aggregate_windows,
                    evidence_refs=evidence_refs,
                )
            )
            continue
        scored_direct = (
            direct_score if direct_ok and resolved.direct_component_weight > 0.0 else 0.0
        )
        scored_aggregate = (
            aggregate_score if aggregate_ok and resolved.aggregate_component_weight > 0.0 else 0.0
        )
        score = _weighted_component_score(components)
        sufficiency: PairSufficiency = (
            "direct_and_aggregate"
            if scored_direct > 0.0 and scored_aggregate > 0.0
            else "direct_only"
            if scored_direct > 0.0
            else "aggregate_only"
        )
        candidates.append(
            GenrePeerSimilarityCandidate(
                source_genre_id=key[0],
                target_genre_id=key[1],
                score=score,
                direct_score=scored_direct,
                aggregate_score=scored_aggregate,
                shared_direct_artist_count=shared_count,
                aggregate_listener_day_support=aggregate_support,
                aggregate_supporting_windows=aggregate_windows,
                sufficiency=sufficiency,
                components=tuple(components),
                evidence_refs=evidence_refs,
            )
        )
    selected_candidate = candidate_artifact
    if selected_candidate is not None and seed_reconciliation is not None:
        raise ValueError("peer similarity accepts one seed accounting artifact at a time")
    if selected_candidate is not None:
        _validate_candidate_binding(selected_candidate, inputs)
    if seed_reconciliation is not None:
        _validate_seed_reconciliation_binding(seed_reconciliation, inputs)
    directional_neighbors = _directional_neighbors(candidates, resolved.maximum_neighbors)
    sources = tuple(
        sorted(
            inputs.artifacts,
            key=lambda item: (item.source, item.snapshot, item.artifact_key),
        )
    )
    if not sources:
        raise ValueError("peer similarity requires at least one provenance artifact")
    coverage = PeerSimilarityCoverage(
        genre_count=len(inputs.genres),
        observed_direct_membership_count=len(inputs.direct_memberships),
        observed_aggregate_pair_count=len(inputs.artist_pairs),
        direct_artist_count=len({item.artist_id for item in inputs.direct_memberships}),
        aggregate_artist_count=len(
            {
                artist
                for pair in inputs.artist_pairs
                for artist in (pair.left_artist_id, pair.right_artist_id)
            }
        ),
        candidate_pair_count=len(candidates),
        abstained_pair_count=len(abstentions),
        directional_neighbor_count=len(directional_neighbors),
        all_inputs_export_allowed=all(item.export_allowed for item in inputs.artifacts),
    )
    input_sha = _sha256(inputs.model_dump(mode="json"))
    settings_sha = _sha256(resolved.model_dump(mode="json"))
    preliminary = GenrePeerSimilarityArtifact(
        input_sha256=input_sha,
        settings_sha256=settings_sha,
        output_sha256="0" * 64,
        source_artifacts=sources,
        candidate_artifact_sha256=(
            selected_candidate.output_sha256 if selected_candidate is not None else None
        ),
        candidate_source_content_sha256=(
            selected_candidate.name_universe.source_content_sha256
            if selected_candidate is not None
            else None
        ),
        candidate_name_count=(
            len(selected_candidate.dispositions) if selected_candidate is not None else 0
        ),
        similarity_per_seed_accounting=(
            "sealed_membership_bridge-v1"
            if selected_candidate is not None
            else "sealed_seed_reconciliation-v2"
            if seed_reconciliation is not None
            else "unbridged"
        ),
        seed_reconciliation_output_sha256=(
            seed_reconciliation.output_sha256 if seed_reconciliation is not None else None
        ),
        seed_reconciliation_name_count=(
            seed_reconciliation.seed_count if seed_reconciliation is not None else 0
        ),
        membership_dispositions=(
            selected_candidate.dispositions if selected_candidate is not None else ()
        ),
        candidates=tuple(candidates),
        abstentions=tuple(abstentions),
        directional_neighbors=directional_neighbors,
        coverage=coverage,
    )
    return preliminary.model_copy(
        update={"output_sha256": peer_similarity_output_sha256(preliminary)}
    )


def _validate_observed_sources(inputs: PublicModelInput) -> None:
    """Require source artifact declarations to cover each observed evidence family."""
    if inputs.artist_pairs and not any(item.source == "listenbrainz" for item in inputs.artifacts):
        raise ValueError("aggregate listening observations require a ListenBrainz artifact")
    if inputs.direct_memberships and not any(
        item.source in {"musicbrainz", "wikidata"} for item in inputs.artifacts
    ):
        raise ValueError("direct memberships require a public metadata artifact")


def _validate_candidate_binding(
    candidate: PublicArtistMembershipCandidateArtifact,
    inputs: PublicModelInput,
) -> None:
    """Prove a sealed name candidate is derived from this exact public input.

    The candidate's own hash proves its internal integrity.  The row-level
    checks below prevent attaching a valid candidate from another corpus to a
    peer artifact merely because both artifacts are individually well formed.
    """
    verify_public_artist_membership_candidate(candidate)
    input_genres = {item.genre_id for item in inputs.genres}
    candidate_genres = {
        item.genre_id for item in candidate.dispositions if item.genre_id is not None
    }
    if not candidate_genres <= input_genres:
        raise ValueError("membership candidate references genres outside peer input")
    direct_keys = {(item.artist_id, item.genre_id) for item in inputs.direct_memberships}
    for item in candidate.directly_observed_memberships:
        if (item.artist_id, item.genre_id) not in direct_keys:
            raise ValueError("membership candidate direct rows are not in peer input")
    aggregate_rows = {
        (
            item.left_artist_id,
            item.right_artist_id,
            item.listener_day_support,
            item.supporting_windows,
        )
        for item in inputs.artist_pairs
    }
    for item in candidate.propagated_candidates:
        for path in item.paths:
            if path.listener_day_support is None or path.supporting_windows is None:
                continue
            left, right = sorted((item.artist_id, path.seed_artist_id))
            if (
                left,
                right,
                path.listener_day_support,
                path.supporting_windows,
            ) not in aggregate_rows:
                raise ValueError("membership candidate aggregate paths are not in peer input")


def _validate_seed_reconciliation_binding(
    reconciliation: SeedReconciliationArtifact,
    inputs: PublicModelInput,
) -> None:
    """Bind stable seed accounting to the exact identities used by the peer graph."""
    verify_seed_reconciliation(reconciliation)
    if reconciliation.seed_count != _NAME_UNIVERSE_COUNT:
        raise ValueError("peer seed reconciliation must account for exactly 6291 names")
    seed_ids = {item.source_item_id for item in reconciliation.dispositions}
    input_genres = {item.genre_id for item in inputs.genres}
    if not input_genres <= seed_ids:
        raise ValueError("peer input contains a genre outside seed reconciliation")


class _ReconstructionEdgeProjection(FrozenModel):
    """Parse reconstruction edges while retaining their genre/tag facet."""

    genre_id: str
    artist_id: str
    weight: FiniteFloat
    evidence_refs: tuple[str, ...]
    facet: Literal["genre", "tag", "musicbrainz_genre", "musicbrainz_tag"] = "genre"


def public_model_input_from_reconstruction(
    inputs: ReconstructionInputs,
) -> PublicModelInput:
    """Adapt direct reconstruction memberships without admitting evaluation data.

    The reconstruction corpus is local-only evidence.  Its historical points
    and neighbor lists are rejected rather than silently ignored, so callers
    cannot accidentally turn evaluation observations into construction input.
    """
    if (
        inputs.historical_artifact is not None
        or inputs.historical_points
        or inputs.historical_neighbors
    ):
        raise ValueError("historical observations cannot enter peer similarity construction")
    artifact = PublicArtifact(
        source="musicbrainz",
        snapshot=inputs.membership_artifact.revision,
        artifact_key=inputs.membership_artifact.artifact_key,
        content_sha256=inputs.membership_artifact.content_sha256,
        export_allowed=False,
    )
    projected_edges = tuple(
        _ReconstructionEdgeProjection.model_validate(edge.model_dump(mode="python"))
        for edge in inputs.membership_edges
    )
    genres = tuple(
        GenreIdentity(
            genre_id=genre_id,
            name=genre_id,
            evidence_refs=(f"reconstruction:{genre_id}",),
        )
        for genre_id in sorted({edge.genre_id for edge in projected_edges})
    )
    memberships = tuple(
        DirectMembershipEvidence(
            artist_id=edge.artist_id,
            genre_id=edge.genre_id,
            facet=(
                "musicbrainz_tag"
                if edge.facet in {"tag", "musicbrainz_tag"}
                else "musicbrainz_genre"
            ),
            value=float(edge.weight),
            evidence_ref=_combined_reconstruction_evidence_ref(edge.evidence_refs),
        )
        for edge in sorted(projected_edges, key=lambda item: (item.artist_id, item.genre_id))
    )
    return PublicModelInput(
        artifacts=(artifact,),
        genres=genres,
        direct_memberships=memberships,
    )


def _combined_reconstruction_evidence_ref(evidence_refs: tuple[str, ...]) -> str:
    """Carry every edge reference through the single-ref public input field."""
    combined = "reconstruction:evidence:" + "|".join(evidence_refs)
    if len(combined) > _MAX_EVIDENCE_REF_LENGTH:
        raise ValueError("reconstruction evidence references exceed public ref bound")
    return combined


def _weighted_component_score(components: list[PeerSimilarityComponent]) -> float:
    """Combine only positive-weight components with an explicit zero guard."""
    denominator = sum(float(item.configured_weight) for item in components)
    if denominator == 0.0:
        raise ValueError("peer score has no positive component weight")
    numerator = sum(
        float(item.normalized_value) * float(item.configured_weight) for item in components
    )
    return float(numerator) / denominator  # ty: ignore[division-by-zero]


def _directional_neighbors(
    candidates: list[GenrePeerSimilarityCandidate],
    maximum_neighbors: int,
) -> tuple[GenrePeerSimilarityNeighbor, ...]:
    """Expand canonical pairs into a bounded, deterministic top-k view."""
    ranked: dict[str, list[GenrePeerSimilarityCandidate]] = defaultdict(list)
    for candidate in candidates:
        ranked[candidate.source_genre_id].append(candidate)
        ranked[candidate.target_genre_id].append(candidate)
    neighbors: list[GenrePeerSimilarityNeighbor] = []
    for source_genre_id in sorted(ranked):
        options = sorted(
            ranked[source_genre_id],
            key=lambda item: (
                -item.score,
                item.target_genre_id
                if item.source_genre_id == source_genre_id
                else item.source_genre_id,
            ),
        )[:maximum_neighbors]
        for rank, candidate in enumerate(options, start=1):
            target = (
                candidate.target_genre_id
                if candidate.source_genre_id == source_genre_id
                else candidate.source_genre_id
            )
            neighbors.append(
                GenrePeerSimilarityNeighbor(
                    source_genre_id=source_genre_id,
                    target_genre_id=target,
                    rank=rank,
                    score=candidate.score,
                    shared_direct_artist_count=candidate.shared_direct_artist_count,
                    aggregate_listener_day_support=candidate.aggregate_listener_day_support,
                )
            )
    return tuple(neighbors)


def build_peer_similarity_receipt(
    inputs: PublicModelInput,
    settings: PeerSimilaritySettings,
    artifact: GenrePeerSimilarityArtifact,
) -> PeerSimilarityReceipt:
    """Create a receipt only after checking the artifact's logical hash."""
    if artifact.input_sha256 != _sha256(inputs.model_dump(mode="json")):
        raise ValueError("peer artifact input hash does not match observed input")
    if artifact.settings_sha256 != _sha256(settings.model_dump(mode="json")):
        raise ValueError("peer artifact settings hash does not match settings")
    if peer_similarity_output_sha256(artifact) != artifact.output_sha256:
        raise ValueError("peer artifact output hash does not replay")
    return PeerSimilarityReceipt(
        input_sha256=artifact.input_sha256,
        settings_sha256=artifact.settings_sha256,
        output_sha256=artifact.output_sha256,
        candidate_pair_count=len(artifact.candidates),
        abstained_pair_count=len(artifact.abstentions),
    )


def evaluate_peer_similarity_gate(  # noqa: C901, PLR0912
    artifact: GenrePeerSimilarityArtifact,
    inputs: PublicModelInput,
    settings: PeerSimilaritySettings,
) -> PeerSimilarityGateReport:
    """Evaluate provenance, privacy, symmetry, and score bounds without mutation."""
    failures: list[str] = []
    try:
        _validate_observed_sources(inputs)
        provenance_complete = True
    except ValueError as error:
        provenance_complete = False
        failures.append(str(error))
    expected_input = _sha256(inputs.model_dump(mode="json"))
    expected_settings = _sha256(settings.model_dump(mode="json"))
    recomputed_output = peer_similarity_output_sha256(artifact)
    if artifact.input_sha256 != expected_input:
        failures.append("peer artifact input hash does not match observed input")
    if artifact.settings_sha256 != expected_settings:
        failures.append("peer artifact settings hash does not match settings")
    if artifact.output_sha256 != recomputed_output:
        failures.append("peer artifact output hash does not replay")
    pair_keys = [(item.source_genre_id, item.target_genre_id) for item in artifact.candidates]
    symmetric = len(pair_keys) == len(set(pair_keys)) and all(
        left < right for left, right in pair_keys
    )
    if not symmetric:
        failures.append("peer candidate pairs are not canonical and unique")
    bounded = all(
        0.0 < item.score <= 1.0
        and 0.0 <= item.direct_score <= 1.0
        and 0.0 <= item.aggregate_score <= 1.0
        for item in artifact.candidates
    )
    if not bounded:
        failures.append("peer candidate score is outside [0, 1]")
    expected_neighbors = _directional_neighbors(
        list(artifact.candidates), settings.maximum_neighbors
    )
    directional_top_k = artifact.directional_neighbors == expected_neighbors
    if not directional_top_k:
        failures.append("peer directional neighbors do not replay from canonical candidates")
    if artifact.coverage.directional_neighbor_count != len(artifact.directional_neighbors):
        failures.append("peer directional neighbor coverage count does not match rows")
    if artifact.similarity_per_seed_accounting == "sealed_seed_reconciliation-v2":
        if (
            artifact.seed_reconciliation_output_sha256 is None
            or artifact.seed_reconciliation_name_count != _NAME_UNIVERSE_COUNT
        ):
            failures.append("peer seed reconciliation accounting is incomplete")
    elif (
        artifact.seed_reconciliation_output_sha256 is not None
        or artifact.seed_reconciliation_name_count
    ):
        failures.append("peer seed reconciliation metadata is inconsistent")
    privacy_safe = True
    for pair in inputs.artist_pairs:
        if not isinstance(pair, ArtistPairEvidence):
            privacy_safe = False
            break
    if not privacy_safe:
        failures.append("aggregate inputs are not the typed privacy-safe ArtistPairEvidence")
    if len(artifact.candidates) > settings.maximum_candidate_pairs:
        failures.append("peer candidate count exceeds configured bound")
    return PeerSimilarityGateReport(
        passed=not failures,
        failures=tuple(failures),
        input_sha256=artifact.input_sha256,
        settings_sha256=artifact.settings_sha256,
        artifact_output_sha256=artifact.output_sha256,
        recomputed_output_sha256=recomputed_output,
        candidate_pair_count=len(artifact.candidates),
        abstained_pair_count=len(artifact.abstentions),
        symmetric=symmetric,
        bounded_scores=bounded,
        privacy_safe_inputs=privacy_safe,
        provenance_complete=provenance_complete,
        all_inputs_export_allowed=all(item.export_allowed for item in inputs.artifacts),
        directional_top_k=directional_top_k,
    )


def require_peer_similarity_gate(
    artifact: GenrePeerSimilarityArtifact,
    inputs: PublicModelInput,
    settings: PeerSimilaritySettings,
) -> PeerSimilarityGateReport:
    """Return a passing gate report or fail closed before publication."""
    report = evaluate_peer_similarity_gate(artifact, inputs, settings)
    if not report.passed:
        raise PeerSimilarityGateError(report.failures)
    return report


def replay_peer_similarity(
    inputs: PublicModelInput,
    settings: PeerSimilaritySettings,
    artifact: GenrePeerSimilarityArtifact,
    *,
    candidate_artifact: PublicArtistMembershipCandidateArtifact | None = None,
) -> GenrePeerSimilarityArtifact:
    """Rebuild and require an exact content-addressed replay."""
    replayed = build_peer_similarity(inputs, settings, candidate_artifact=candidate_artifact)
    if replayed != artifact:
        raise ValueError("peer similarity deterministic replay changed the artifact")
    return replayed
