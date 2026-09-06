"""Bounded, review-only propagation from direct catalog anchors over co-listens.

The module intentionally treats ListenBrainz only as a graph edge source.  A
candidate is never a source claim: it is a reproducible retrieval result from
MusicBrainz/Wikidata direct anchors and privacy-safe artist co-listens.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import ijson
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from musix.genre_seed_universe import normalize_label
from musix.models import FrozenModel
from musix.models.modeling import DirectMembershipEvidence
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from musix.models.modeling import PublicModelInput
    from musix.musicbrainz_seed_targets import MusicBrainzSeedTargetArtifact
    from musix.public_artist_membership import NameUniverse

_SHA256 = r"^[0-9a-f]{64}$"
_SEED_COUNT = 6_291
type DirectFacet = Literal["musicbrainz_genre", "musicbrainz_tag", "wikidata_p136"]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_single_model[T: BaseModel](path: Path, prefix: str, model: type[T]) -> T:
    """Parse exactly one bounded object without materializing a large artifact."""
    with path.open("rb") as stream:
        rows = ijson.items(stream, prefix, use_float=True)
        try:
            raw = next(rows)
        except StopIteration as error:
            raise ValueError(f"propagation artifact lacks {prefix}") from error
        if next(rows, None) is not None:
            raise ValueError(f"propagation artifact repeats {prefix}")
    return model.model_validate(raw)


def _stream_single_string(path: Path, prefix: str) -> str:
    """Parse exactly one required root scalar from a large JSON artifact."""
    with path.open("rb") as stream:
        values = ijson.items(stream, prefix, use_float=True)
        try:
            value = next(values)
        except StopIteration as error:
            raise ValueError(f"propagation artifact lacks {prefix}") from error
        if next(values, None) is not None or not isinstance(value, str):
            raise ValueError(f"propagation artifact has invalid {prefix}")
    return value


def _verify_propagation_receipt(
    artifact_path: Path, receipt_path: Path
) -> ListenBrainzPropagationReceipt:
    """Verify byte custody before streaming untrusted candidate identifiers."""
    receipt = ListenBrainzPropagationReceipt.model_validate_json(receipt_path.read_bytes())
    artifact_file_sha256 = _file_sha256(artifact_path)
    if (
        artifact_file_sha256 != receipt.artifact_sha256
        or receipt.artifact.sha256 != receipt.artifact_sha256
    ):
        raise ValueError("propagation artifact byte hash does not match its receipt")
    if receipt.content_policy != "metadata_only_no_audio_or_historical_membership":
        raise ValueError("propagation receipt has an unsafe content policy")
    return receipt


def _stream_propagation_candidate_ids(
    artifact_path: Path,
    seed_source_item_ids: frozenset[str],
    maximum_candidates: int,
) -> dict[str, set[str]]:
    """Boundedly load unique candidate artist IDs per stable source seed."""
    by_seed: dict[str, set[str]] = defaultdict(set)
    candidate_count = 0
    seen: set[tuple[str, str]] = set()
    with artifact_path.open("rb") as stream:
        for raw in ijson.items(stream, "candidates.item", use_float=True):
            candidate = _PropagationCandidateBoundary.model_validate(raw)
            candidate_count += 1
            if candidate_count > maximum_candidates:
                raise ValueError("propagation candidate count exceeds configured summary bound")
            prefix = "legacy:"
            if not candidate.genre_id.startswith(prefix):
                raise ValueError("propagation candidate genre is outside the stable seed namespace")
            source_item_id = candidate.genre_id.removeprefix(prefix)
            if source_item_id not in seed_source_item_ids:
                raise ValueError("propagation candidate genre is outside the seed universe")
            key = (source_item_id, candidate.artist_id)
            if key in seen:
                raise ValueError("propagation artifact repeats a candidate artist/genre pair")
            seen.add(key)
            by_seed[source_item_id].add(candidate.artist_id)
    return by_seed


def load_listenbrainz_propagation_frontier_summary(
    artifact_path: Path,
    receipt_path: Path,
    *,
    seed_source_item_ids: frozenset[str],
    maximum_candidates: int = 100_000,
) -> ListenBrainzPropagationFrontierSummary:
    """Stream a sealed review artifact into a compact 6,291-seed frontier input."""
    if len(seed_source_item_ids) != _SEED_COUNT:
        raise ValueError("propagation summary requires the complete 6,291-seed universe")
    receipt = _verify_propagation_receipt(artifact_path, receipt_path)
    semantics = _stream_single_string(artifact_path, "membership_semantics")
    if semantics != "derived_review_evidence_not_factual_membership":
        raise ValueError("propagation artifact is not review-only evidence")
    output_sha256 = _stream_single_string(artifact_path, "output_sha256")
    if output_sha256 != receipt.logical_output_sha256:
        raise ValueError("propagation artifact logical hash does not match its receipt")
    coverage = _stream_single_model(artifact_path, "coverage", _PropagationCoverageBoundary)
    by_seed = _stream_propagation_candidate_ids(
        artifact_path, seed_source_item_ids, maximum_candidates
    )
    candidate_count = sum(len(values) for values in by_seed.values())
    if candidate_count != coverage.candidate_count:
        raise ValueError("propagation candidate stream does not match declared coverage")
    if sum(bool(values) for values in by_seed.values()) != coverage.candidate_genre_count:
        raise ValueError("propagation candidate genres do not match declared coverage")
    rows = tuple(
        ListenBrainzPropagationFrontierSeedSummary(
            source_item_id=source_item_id,
            candidate_count=len(by_seed[source_item_id]),
            candidate_artist_count=len(by_seed[source_item_id]),
        )
        for source_item_id in sorted(seed_source_item_ids)
    )
    preliminary = ListenBrainzPropagationFrontierSummary(
        propagation_output_sha256=output_sha256,
        propagation_file_sha256=receipt.artifact_sha256,
        propagation_receipt_artifact_sha256=receipt.artifact_sha256,
        propagation_receipt_logical_output_sha256=receipt.logical_output_sha256,
        candidate_count=candidate_count,
        candidate_genre_count=coverage.candidate_genre_count,
        rows=rows,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _hash(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


class ListenBrainzPropagationSettings(FrozenModel):
    """A priori bounds for a laptop-safe, one-hop retrieval experiment."""

    revision: Literal["listenbrainz-propagation-settings-v1"] = (
        "listenbrainz-propagation-settings-v1"
    )
    minimum_listener_day_support: int = Field(default=15, ge=1)
    minimum_supporting_windows: int = Field(default=2, ge=1)
    maximum_artist_degree: int = Field(default=250, ge=1, le=10_000)
    maximum_seed_anchors_per_artist: int = Field(default=32, ge=1, le=256)
    maximum_paths_per_candidate: int = Field(default=8, ge=1, le=64)
    maximum_candidates_per_genre: int = Field(default=2_500, ge=1, le=20_000)
    maximum_propagation_visits: int = Field(default=2_000_000, ge=1, le=50_000_000)
    holdout_modulus: int = Field(default=5, ge=2, le=100)
    holdout_bucket: int = Field(default=0, ge=0)
    holdout_seed: int = Field(default=20260906, ge=0)
    normalization: Literal["log1p_association_strength_v1"] = "log1p_association_strength_v1"
    candidate_kind: Literal["derived_review_evidence"] = "derived_review_evidence"
    historical_input_used_for_construction: Literal[False] = False
    audio_used_for_construction: Literal[False] = False

    @model_validator(mode="after")
    def require_holdout_bucket(self) -> ListenBrainzPropagationSettings:
        """Keep the deterministic holdout bucket in its declared partition."""
        if self.holdout_bucket >= self.holdout_modulus:
            raise ValueError("holdout bucket must be smaller than holdout modulus")
        return self


class PropagationInputFingerprint(FrozenModel):
    """Bind the sealed artifact to the exact local SQLite inputs and name vocabulary."""

    catalog_database_sha256: str = Field(pattern=_SHA256)
    listenbrainz_database_sha256: str = Field(pattern=_SHA256)
    name_universe_source_sha256: str = Field(pattern=_SHA256)
    musicbrainz_seed_target_output_sha256: str = Field(pattern=_SHA256)
    musicbrainz_seed_target_file_sha256: str = Field(pattern=_SHA256)
    public_input_sha256: str = Field(pattern=_SHA256)


class PropagationPath(FrozenModel):
    """One visible direct-anchor plus co-listen route to a review candidate."""

    seed_artist_id: str = Field(min_length=1)
    direct_facets: tuple[DirectFacet, ...] = Field(min_length=1)
    direct_evidence_refs: tuple[str, ...] = Field(min_length=1)
    listener_day_support: int = Field(gt=0)
    supporting_windows: int = Field(gt=0)
    co_listen_evidence_refs: tuple[str, ...] = Field(min_length=1)
    normalized_edge_weight: FiniteFloat = Field(gt=0.0, le=1.0)


class PropagationCandidate(FrozenModel):
    """A non-factual membership candidate, ranked only within its genre."""

    artist_id: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)
    genre_rank: int = Field(ge=1)
    score: FiniteFloat = Field(gt=0.0, le=1.0)
    paths: tuple[PropagationPath, ...] = Field(min_length=1)


class PropagationCoverage(FrozenModel):
    """Explain both graph filtering and 6,291-name incremental coverage."""

    name_universe_count: Literal[6291] = 6291
    uniquely_matched_name_universe_genre_count: int = Field(ge=0, le=6291)
    ambiguous_name_universe_genre_count: int = Field(ge=0, le=6291)
    direct_anchor_count: int = Field(ge=0)
    direct_anchor_artist_count: int = Field(ge=0)
    direct_anchor_genre_count: int = Field(ge=0)
    musicbrainz_only_anchor_count: int = Field(ge=0)
    wikidata_only_anchor_count: int = Field(ge=0)
    musicbrainz_wikidata_overlap_anchor_count: int = Field(ge=0)
    input_artist_pair_count: int = Field(ge=0)
    support_eligible_artist_pair_count: int = Field(ge=0)
    hub_capped_artist_count: int = Field(ge=0)
    hub_capped_artist_pair_count: int = Field(ge=0)
    retained_artist_pair_count: int = Field(ge=0)
    seed_anchor_capped_count: int = Field(ge=0)
    propagation_visit_count: int = Field(ge=0)
    candidate_count_before_genre_cap: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    candidate_artist_count: int = Field(ge=0)
    candidate_genre_count: int = Field(ge=0)
    incremental_name_universe_genre_count: int = Field(ge=0, le=6291)


class HeldOutAnchorRecovery(FrozenModel):
    """Positive-only recovery of a deterministic partition of direct source claims."""

    holdout_modulus: int = Field(ge=2)
    holdout_bucket: int = Field(ge=0)
    direct_anchor_count: int = Field(ge=0)
    heldout_anchor_count: int = Field(ge=0)
    training_anchor_count: int = Field(ge=0)
    eligible_heldout_anchor_count: int = Field(ge=0)
    recovered_heldout_anchor_count: int = Field(ge=0)
    positive_only_recall: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    negatives_assumed: Literal[False] = False
    historical_input_used_for_evaluation: Literal[False] = False


class ListenBrainzPropagationArtifact(FrozenModel):
    """A sealed review artifact; it cannot assert direct artist membership facts."""

    revision: Literal["listenbrainz-propagation-artifact-v1"] = (
        "listenbrainz-propagation-artifact-v1"
    )
    membership_semantics: Literal["derived_review_evidence_not_factual_membership"] = (
        "derived_review_evidence_not_factual_membership"
    )
    source_direct_facets: tuple[DirectFacet, ...] = Field(min_length=1)
    inputs: PropagationInputFingerprint
    settings: ListenBrainzPropagationSettings
    settings_sha256: str = Field(pattern=_SHA256)
    coverage: PropagationCoverage
    heldout_anchor_recovery: HeldOutAnchorRecovery
    candidates: tuple[PropagationCandidate, ...]
    output_sha256: str = Field(pattern=_SHA256)


class ListenBrainzPropagationReceipt(FrozenModel):
    """Immutable object-store receipt for a propagation review artifact."""

    revision: Literal["listenbrainz-propagation-publication-v1"] = (
        "listenbrainz-propagation-publication-v1"
    )
    artifact: ObjectWrite
    artifact_sha256: str = Field(pattern=_SHA256)
    logical_output_sha256: str = Field(pattern=_SHA256)
    inputs: PropagationInputFingerprint
    content_policy: Literal["metadata_only_no_audio_or_historical_membership"] = (
        "metadata_only_no_audio_or_historical_membership"
    )


class ListenBrainzPropagationFrontierSeedSummary(FrozenModel):
    """One compact all-seed summary of derived review candidates only."""

    source_item_id: str = Field(min_length=1, max_length=200)
    candidate_count: int = Field(ge=0)
    candidate_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _artist_count_is_bounded(self) -> ListenBrainzPropagationFrontierSeedSummary:
        if self.candidate_artist_count > self.candidate_count:
            raise ValueError("review candidate artist count exceeds candidate count")
        return self


class ListenBrainzPropagationFrontierSummary(FrozenModel):
    """Hash-bound compact projection of a sealed propagation artifact for a frontier."""

    revision: Literal["listenbrainz-propagation-frontier-summary-v1"] = (
        "listenbrainz-propagation-frontier-summary-v1"
    )
    propagation_output_sha256: str = Field(pattern=_SHA256)
    propagation_file_sha256: str = Field(pattern=_SHA256)
    propagation_receipt_artifact_sha256: str = Field(pattern=_SHA256)
    propagation_receipt_logical_output_sha256: str = Field(pattern=_SHA256)
    candidate_count: int = Field(ge=0)
    candidate_genre_count: int = Field(ge=0, le=6291)
    rows: tuple[ListenBrainzPropagationFrontierSeedSummary, ...] = Field(
        min_length=_SEED_COUNT, max_length=_SEED_COUNT
    )
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete_seed_projection(self) -> ListenBrainzPropagationFrontierSummary:
        source_ids = tuple(item.source_item_id for item in self.rows)
        if source_ids != tuple(sorted(source_ids)) or len(set(source_ids)) != _SEED_COUNT:
            raise ValueError("propagation frontier summary requires sorted complete seed rows")
        if self.candidate_count != sum(item.candidate_count for item in self.rows):
            raise ValueError("propagation frontier candidate total does not match seed rows")
        if self.candidate_genre_count != sum(item.candidate_count > 0 for item in self.rows):
            raise ValueError("propagation frontier genre total does not match seed rows")
        if self.propagation_output_sha256 != self.propagation_receipt_logical_output_sha256:
            raise ValueError("propagation receipt logical hash does not match source artifact")
        if self.propagation_file_sha256 != self.propagation_receipt_artifact_sha256:
            raise ValueError("propagation receipt byte hash does not match source artifact")
        return self


class _PropagationCoverageBoundary(BaseModel):
    """Read only the bounded coverage scalars needed by the frontier adapter."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    candidate_count: int = Field(ge=0)
    candidate_genre_count: int = Field(ge=0, le=6291)


class _PropagationCandidateBoundary(BaseModel):
    """Stream only stable candidate identifiers; paths are not frontier input."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    artist_id: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class _Anchor:
    artist_id: str
    genre_id: str
    facets: tuple[DirectFacet, ...]
    evidence_refs: tuple[str, ...]
    weight: float


@dataclass(frozen=True, slots=True)
class _Pair:
    left_artist_id: str
    right_artist_id: str
    listener_day_support: int
    supporting_windows: int
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _BuildResult:
    candidates: tuple[PropagationCandidate, ...]
    support_eligible_pair_count: int
    hub_capped_artist_count: int
    hub_capped_pair_count: int
    retained_pair_count: int
    seed_anchor_capped_count: int
    propagation_visit_count: int
    candidate_count_before_genre_cap: int


@dataclass(frozen=True, slots=True)
class _AnchorIndex:
    by_artist: dict[str, tuple[_Anchor, ...]]
    direct_pairs: set[tuple[str, str]]
    capped_anchor_count: int


@dataclass(frozen=True, slots=True)
class _RetainedPairs:
    eligible_count: int
    hub_count: int
    hub_pair_count: int
    pairs: tuple[_Pair, ...]
    strengths: dict[str, float]


def _anchors(direct: tuple[DirectMembershipEvidence, ...]) -> tuple[_Anchor, ...]:
    grouped: dict[tuple[str, str], list[DirectMembershipEvidence]] = defaultdict(list)
    for item in direct:
        grouped[(item.artist_id, item.genre_id)].append(item)
    return tuple(
        _Anchor(
            artist_id=artist_id,
            genre_id=genre_id,
            facets=tuple(sorted({item.facet for item in items})),
            evidence_refs=tuple(sorted({item.evidence_ref for item in items})),
            weight=max(item.value for item in items),
        )
        for (artist_id, genre_id), items in sorted(grouped.items())
    )


def merge_direct_memberships(
    musicbrainz: tuple[DirectMembershipEvidence, ...],
    wikidata: tuple[DirectMembershipEvidence, ...],
) -> tuple[DirectMembershipEvidence, ...]:
    """Return a monotonic source-facet union without silently deduplicating evidence."""
    merged = (*musicbrainz, *wikidata)
    unique = {
        (item.artist_id, item.genre_id, item.facet, item.evidence_ref): item for item in merged
    }
    if len(unique) != len(merged):
        raise ValueError("direct membership union contains duplicate source evidence")
    return tuple(unique[key] for key in sorted(unique))


def musicbrainz_seed_target_memberships(
    source: MusicBrainzSeedTargetArtifact,
    listenbrainz_artist_ids: set[str],
) -> tuple[DirectMembershipEvidence, ...]:
    """Stream full MusicBrainz target evidence, retaining only co-listen-reachable MBIDs."""
    # The full source has repeated facts for an artist/seed/facet.  One stable
    # representative retains source provenance and facet breadth while keeping
    # a local run bounded before the graph walk.  The source artifact's stream
    # order is deterministic, so this also makes the result reproducible.
    memberships: dict[tuple[str, str, DirectFacet], DirectMembershipEvidence] = {}
    for evidence in source.evidence:
        artist_id = f"musicbrainz:artist:{evidence.artist_id}"
        if artist_id not in listenbrainz_artist_ids:
            continue
        genre_id = f"legacy:{evidence.seed_source_item_id}"
        facet: DirectFacet = "musicbrainz_genre" if evidence.facet == "genre" else "musicbrainz_tag"
        key = (artist_id, genre_id, facet)
        memberships.setdefault(
            key,
            DirectMembershipEvidence(
                artist_id=artist_id,
                genre_id=genre_id,
                facet=facet,
                value=evidence.positive_weight,
                evidence_ref=f"musicbrainz:seed-target:{evidence.evidence_ref}",
            ),
        )
    return tuple(memberships[key] for key in sorted(memberships))


def wikidata_name_universe_memberships(
    inputs: PublicModelInput, universe: NameUniverse
) -> tuple[DirectMembershipEvidence, ...]:
    """Project accepted Wikidata direct anchors to unique 6,291-name identities."""
    universe_by_name: dict[str, list[str]] = defaultdict(list)
    for item in universe.names:
        universe_by_name[normalize_label(item.name)].append(f"legacy:{item.source_item_id}")
    resolved: dict[str, str] = {}
    for genre in inputs.genres:
        matches = universe_by_name.get(normalize_label(genre.name), ())
        if len(matches) == 1:
            resolved[genre.genre_id] = matches[0]
    return tuple(
        DirectMembershipEvidence(
            artist_id=item.artist_id,
            genre_id=resolved[item.genre_id],
            facet=item.facet,
            value=item.value,
            evidence_ref=item.evidence_ref,
        )
        for item in inputs.direct_memberships
        if item.facet == "wikidata_p136" and item.genre_id in resolved
    )


def _index_anchors(
    anchors: tuple[_Anchor, ...], settings: ListenBrainzPropagationSettings
) -> _AnchorIndex:
    by_artist: dict[str, list[_Anchor]] = defaultdict(list)
    direct_pairs: set[tuple[str, str]] = set()
    for anchor in anchors:
        by_artist[anchor.artist_id].append(anchor)
        direct_pairs.add((anchor.artist_id, anchor.genre_id))
    normalized: dict[str, tuple[_Anchor, ...]] = {}
    capped_anchor_count = 0
    for artist_id, artist_anchors in by_artist.items():
        ordered = tuple(
            sorted(
                artist_anchors,
                key=lambda item: (-item.weight, item.genre_id, item.evidence_refs),
            )
        )
        if len(ordered) > settings.maximum_seed_anchors_per_artist:
            capped_anchor_count += len(ordered) - settings.maximum_seed_anchors_per_artist
        normalized[artist_id] = ordered[: settings.maximum_seed_anchors_per_artist]
    return _AnchorIndex(
        by_artist=normalized,
        direct_pairs=direct_pairs,
        capped_anchor_count=capped_anchor_count,
    )


def _retained_pairs(
    inputs: PublicModelInput, settings: ListenBrainzPropagationSettings
) -> _RetainedPairs:
    eligible = tuple(
        _Pair(
            left_artist_id=item.left_artist_id,
            right_artist_id=item.right_artist_id,
            listener_day_support=item.listener_day_support,
            supporting_windows=item.supporting_windows,
            evidence_refs=item.evidence_refs,
        )
        for item in inputs.artist_pairs
        if item.listener_day_support >= settings.minimum_listener_day_support
        and item.supporting_windows >= settings.minimum_supporting_windows
    )
    degree: dict[str, int] = defaultdict(int)
    for pair in eligible:
        degree[pair.left_artist_id] += 1
        degree[pair.right_artist_id] += 1
    hubs = {
        artist_id for artist_id, value in degree.items() if value > settings.maximum_artist_degree
    }
    retained = tuple(
        pair
        for pair in eligible
        if pair.left_artist_id not in hubs and pair.right_artist_id not in hubs
    )
    strengths: dict[str, float] = defaultdict(float)
    for pair in retained:
        weight = math.log1p(pair.listener_day_support)
        strengths[pair.left_artist_id] += weight
        strengths[pair.right_artist_id] += weight
    return _RetainedPairs(
        eligible_count=len(eligible),
        hub_count=len(hubs),
        hub_pair_count=len(eligible) - len(retained),
        pairs=retained,
        strengths=strengths,
    )


def _accumulate_candidates(
    index: _AnchorIndex,
    pairs: _RetainedPairs,
    settings: ListenBrainzPropagationSettings,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], list[PropagationPath]], int]:
    raw: dict[tuple[str, str], float] = defaultdict(float)
    paths: dict[tuple[str, str], list[PropagationPath]] = defaultdict(list)
    visits = 0
    for pair in pairs.pairs:
        raw_support = math.log1p(pair.listener_day_support)
        denominator = math.sqrt(
            pairs.strengths[pair.left_artist_id] * pairs.strengths[pair.right_artist_id]
        )
        if denominator <= 0.0:
            raise ValueError("retained pair has nonpositive normalized degree")
        edge_weight = raw_support / denominator
        for target, seed_artist in (
            (pair.left_artist_id, pair.right_artist_id),
            (pair.right_artist_id, pair.left_artist_id),
        ):
            for anchor in index.by_artist.get(seed_artist, ()):
                visits += 1
                if visits > settings.maximum_propagation_visits:
                    raise ValueError("propagation visits exceed configured laptop bound")
                key = (target, anchor.genre_id)
                if key in index.direct_pairs:
                    continue
                raw[key] += edge_weight
                if len(paths[key]) < settings.maximum_paths_per_candidate:
                    paths[key].append(
                        PropagationPath(
                            seed_artist_id=seed_artist,
                            direct_facets=anchor.facets,
                            direct_evidence_refs=anchor.evidence_refs,
                            listener_day_support=pair.listener_day_support,
                            supporting_windows=pair.supporting_windows,
                            co_listen_evidence_refs=pair.evidence_refs,
                            normalized_edge_weight=edge_weight,
                        )
                    )
    return raw, paths, visits


def _rank_candidates(
    raw: dict[tuple[str, str], float],
    paths: dict[tuple[str, str], list[PropagationPath]],
    settings: ListenBrainzPropagationSettings,
) -> tuple[tuple[PropagationCandidate, ...], int]:
    by_genre: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (artist_id, genre_id), score in raw.items():
        if score > 0.0:
            by_genre[genre_id].append((artist_id, score))
    before_cap = sum(len(values) for values in by_genre.values())
    candidates: list[PropagationCandidate] = []
    for genre_id in sorted(by_genre):
        ordered = sorted(by_genre[genre_id], key=lambda item: (-item[1], item[0]))[
            : settings.maximum_candidates_per_genre
        ]
        maximum = ordered[0][1]
        for rank, (artist_id, score) in enumerate(ordered, 1):
            candidates.append(
                PropagationCandidate(
                    artist_id=artist_id,
                    genre_id=genre_id,
                    genre_rank=rank,
                    score=round(score / maximum, 12),
                    paths=tuple(
                        sorted(
                            paths[(artist_id, genre_id)],
                            key=lambda item: (
                                item.seed_artist_id,
                                item.direct_evidence_refs,
                                item.co_listen_evidence_refs,
                            ),
                        )
                    ),
                )
            )
    candidates.sort(key=lambda item: (item.genre_id, item.genre_rank, item.artist_id))
    return tuple(candidates), before_cap


def _is_heldout(anchor: _Anchor, settings: ListenBrainzPropagationSettings) -> bool:
    value = f"{settings.holdout_seed}\0{anchor.artist_id}\0{anchor.genre_id}".encode()
    return (
        int.from_bytes(hashlib.sha256(value).digest()[:8], "big") % settings.holdout_modulus
        == settings.holdout_bucket
    )


def _build_candidates(
    anchors: tuple[_Anchor, ...],
    input_pairs: PublicModelInput,
    settings: ListenBrainzPropagationSettings,
) -> _BuildResult:
    """Retrieve bounded one-hop candidates from one fixed anchor partition."""
    index = _index_anchors(anchors, settings)
    retained = _retained_pairs(input_pairs, settings)
    raw, paths, visits = _accumulate_candidates(index, retained, settings)
    candidates, before_cap = _rank_candidates(raw, paths, settings)
    return _BuildResult(
        candidates=candidates,
        support_eligible_pair_count=retained.eligible_count,
        hub_capped_artist_count=retained.hub_count,
        hub_capped_pair_count=retained.hub_pair_count,
        retained_pair_count=len(retained.pairs),
        seed_anchor_capped_count=index.capped_anchor_count,
        propagation_visit_count=visits,
        candidate_count_before_genre_cap=before_cap,
    )


def _universe_genres(inputs: PublicModelInput, universe: NameUniverse) -> tuple[int, int, set[str]]:
    """Match only unambiguous normalized public genre labels to the 6,291-name vocabulary."""
    public_by_name: dict[str, list[str]] = defaultdict(list)
    for genre in inputs.genres:
        public_by_name[normalize_label(genre.name)].append(genre.genre_id)
    resolved: set[str] = set()
    ambiguous = 0
    for name in universe.names:
        values = public_by_name.get(normalize_label(name.name), ())
        if len(values) == 1:
            resolved.add(values[0])
        elif len(values) > 1:
            ambiguous += 1
    return len(resolved), ambiguous, resolved


def build_listenbrainz_propagation(
    inputs: PublicModelInput,
    universe: NameUniverse,
    fingerprint: PropagationInputFingerprint,
    settings: ListenBrainzPropagationSettings,
    *,
    direct_memberships: tuple[DirectMembershipEvidence, ...] | None = None,
) -> ListenBrainzPropagationArtifact:
    """Seal full-corpus review candidates and an internal direct-anchor holdout metric."""
    direct = inputs.direct_memberships if direct_memberships is None else direct_memberships
    all_anchors = _anchors(direct)
    if not all_anchors:
        raise ValueError("propagation requires at least one accepted direct anchor")
    full = _build_candidates(all_anchors, inputs, settings)
    heldout = tuple(anchor for anchor in all_anchors if _is_heldout(anchor, settings))
    training = tuple(anchor for anchor in all_anchors if not _is_heldout(anchor, settings))
    heldout_result = _build_candidates(training, inputs, settings)
    heldout_pairs = {(item.artist_id, item.genre_id) for item in heldout}
    recovered = heldout_pairs & {
        (item.artist_id, item.genre_id) for item in heldout_result.candidates
    }
    matched_count, ambiguous_count, _matched_genre_ids = _universe_genres(inputs, universe)
    candidate_genres = {item.genre_id for item in full.candidates}
    universe_genre_ids = {f"legacy:{item.source_item_id}" for item in universe.names}
    coverage = PropagationCoverage(
        uniquely_matched_name_universe_genre_count=matched_count,
        ambiguous_name_universe_genre_count=ambiguous_count,
        direct_anchor_count=len(all_anchors),
        direct_anchor_artist_count=len({item.artist_id for item in all_anchors}),
        direct_anchor_genre_count=len({item.genre_id for item in all_anchors}),
        musicbrainz_only_anchor_count=sum(
            bool(set(item.facets) - {"wikidata_p136"}) and "wikidata_p136" not in item.facets
            for item in all_anchors
        ),
        wikidata_only_anchor_count=sum(item.facets == ("wikidata_p136",) for item in all_anchors),
        musicbrainz_wikidata_overlap_anchor_count=sum(
            "wikidata_p136" in item.facets and bool(set(item.facets) - {"wikidata_p136"})
            for item in all_anchors
        ),
        input_artist_pair_count=len(inputs.artist_pairs),
        support_eligible_artist_pair_count=full.support_eligible_pair_count,
        hub_capped_artist_count=full.hub_capped_artist_count,
        hub_capped_artist_pair_count=full.hub_capped_pair_count,
        retained_artist_pair_count=full.retained_pair_count,
        seed_anchor_capped_count=full.seed_anchor_capped_count,
        propagation_visit_count=full.propagation_visit_count,
        candidate_count_before_genre_cap=full.candidate_count_before_genre_cap,
        candidate_count=len(full.candidates),
        candidate_artist_count=len({item.artist_id for item in full.candidates}),
        candidate_genre_count=len(candidate_genres),
        incremental_name_universe_genre_count=len(candidate_genres & universe_genre_ids),
    )
    evaluation = HeldOutAnchorRecovery(
        holdout_modulus=settings.holdout_modulus,
        holdout_bucket=settings.holdout_bucket,
        direct_anchor_count=len(all_anchors),
        heldout_anchor_count=len(heldout),
        training_anchor_count=len(training),
        eligible_heldout_anchor_count=len(heldout_pairs),
        recovered_heldout_anchor_count=len(recovered),
        positive_only_recall=round(len(recovered) / len(heldout_pairs), 12)
        if heldout_pairs
        else None,
    )
    facets = tuple(sorted({facet for anchor in all_anchors for facet in anchor.facets}))
    preliminary = ListenBrainzPropagationArtifact(
        source_direct_facets=facets,
        inputs=fingerprint,
        settings=settings,
        settings_sha256=_hash(settings.model_dump(mode="json")),
        coverage=coverage,
        heldout_anchor_recovery=evaluation,
        candidates=full.candidates,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": _hash(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


def verify_listenbrainz_propagation(artifact: ListenBrainzPropagationArtifact) -> None:
    """Replay the self-hashes and enforce the non-factual semantic boundary."""
    if artifact.settings_sha256 != _hash(artifact.settings.model_dump(mode="json")):
        raise ValueError("propagation settings hash does not replay")
    if artifact.output_sha256 != _hash(artifact.model_dump(mode="json", exclude={"output_sha256"})):
        raise ValueError("propagation output hash does not replay")
    if artifact.membership_semantics != "derived_review_evidence_not_factual_membership":
        raise ValueError("propagation artifact has unsafe membership semantics")


def publish_listenbrainz_propagation(
    artifact: ListenBrainzPropagationArtifact, *, output_path: Path, store: ObjectStore
) -> tuple[ListenBrainzPropagationReceipt, ObjectWrite]:
    """Atomically write and custody the sealed review artifact."""
    verify_listenbrainz_propagation(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha256 = hashlib.sha256(payload).hexdigest()
    key = ObjectKey(
        value=f"listenbrainz-propagation/{artifact.output_sha256}/{artifact_sha256}.json"
    )
    write = store.push(output_path, key)
    if write.sha256 != artifact_sha256:
        raise ValueError("object store write does not match propagation artifact")
    return (
        ListenBrainzPropagationReceipt(
            artifact=write,
            artifact_sha256=artifact_sha256,
            logical_output_sha256=artifact.output_sha256,
            inputs=artifact.inputs,
        ),
        write,
    )
