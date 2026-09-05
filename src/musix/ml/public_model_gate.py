"""Publication checks for an independent, public-only graph artifact.

The model builder already keeps the public sources and the layout lenses typed.
This module is the release-boundary check that turns those declarations into a
small, machine-readable claim: every published neighbor can be recomputed from
the sparse profile rows, every membership has source evidence, and layout
coordinates are hashed separately from model evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from musix.ml.public_graph import public_model_output_sha256
from musix.models import FrozenModel
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Iterator

    from musix.models.modeling import GenreNeighbor, MembershipScore, PublicModelArtifact

_BLOCKED_TERMS = (
    "every noise",
    "every_noise",
    "everynoise",
    "historical",
    "spotify_genres_artists_map",
)
_EXPECTED_REVISION: Literal["public-model-gate-v1"] = "public-model-gate-v1"


class PublicModelGateError(RuntimeError):
    """Raised when a public model cannot be published as independent evidence."""

    def __init__(self, failures: tuple[str, ...]) -> None:
        """Store all failed checks so callers can present a complete report."""
        self.failures = failures
        super().__init__("public model gate failed: " + "; ".join(failures))


class PublicModelGateReport(FrozenModel):
    """Deterministic proof summary for one public model artifact."""

    revision: Literal["public-model-gate-v1"] = _EXPECTED_REVISION
    passed: bool
    failures: tuple[str, ...]
    artifact_file_sha256: Sha256 | None = None
    artifact_byte_size: int | None = Field(default=None, gt=0)
    artifact_output_sha256: Sha256
    recomputed_output_sha256: Sha256
    evidence_sha256: Sha256
    coordinate_sha256: Sha256
    layout_version_sha256: Sha256
    public_artifact_count: int = Field(ge=0)
    listenbrainz_artifact_count: int = Field(ge=0)
    musicbrainz_artifact_count: int = Field(ge=0)
    wikidata_artifact_count: int = Field(ge=0)
    genre_count: int = Field(ge=0)
    profile_count: int = Field(ge=0)
    direct_profile_genres: int = Field(ge=0)
    one_hop_profile_genres: int = Field(ge=0)
    direct_membership_count: int = Field(ge=0)
    one_hop_membership_count: int = Field(ge=0)
    neighbor_count: int = Field(ge=0)
    explainable_neighbor_count: int = Field(ge=0)
    neighbor_evidence_coverage: float = Field(ge=0.0, le=1.0)
    layout_count: int = Field(ge=0)
    layout_coordinate_count: int = Field(ge=0)
    layout_coverage: float = Field(ge=0.0, le=1.0)
    profile_genre_coverage: float = Field(ge=0.0, le=1.0)
    forbidden_terms: tuple[str, ...]


def _sha256(value: object) -> Sha256:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, BaseModel):
        yield from _strings(value.model_dump(mode="json"))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _strings(item)


def _forbidden_terms(artifact: PublicModelArtifact) -> tuple[str, ...]:
    text = "\n".join(_strings(artifact)).casefold()
    return tuple(term for term in _BLOCKED_TERMS if term in text)


def _profile_vectors(
    artifact: PublicModelArtifact,
) -> dict[tuple[str, str], dict[str, MembershipScore]]:
    return {
        (profile.profile_kind, profile.genre_id): {
            membership.artist_id: membership for membership in profile.memberships
        }
        for profile in artifact.profiles
    }


@dataclass(frozen=True, slots=True)
class _ProfileCheck:
    failures: tuple[str, ...]
    profile_memberships: int
    direct_memberships: int
    one_hop_memberships: int


def _profile_checks(artifact: PublicModelArtifact) -> _ProfileCheck:
    failures: list[str] = []
    profile_memberships = direct_memberships = one_hop_memberships = 0
    for profile in artifact.profiles:
        count = len(profile.memberships)
        profile_memberships += count
        if profile.profile_kind == "direct":
            direct_memberships += count
        else:
            one_hop_memberships += count
        if len({membership.artist_id for membership in profile.memberships}) != count:
            failures.append(f"profile has duplicate artist memberships: {profile.genre_id}")
        for membership in profile.memberships:
            if membership.genre_id != profile.genre_id:
                failures.append(f"profile membership genre mismatch: {profile.genre_id}")
            component_kinds = {component.component_kind for component in membership.components}
            if profile.profile_kind == "direct" and not component_kinds <= {
                "musicbrainz_genre",
                "musicbrainz_tag",
                "wikidata_p136",
            }:
                failures.append(f"direct profile has non-direct component: {profile.genre_id}")
            if profile.profile_kind == "one_hop" and "listenbrainz_one_hop" not in component_kinds:
                failures.append(f"one-hop profile lacks ListenBrainz evidence: {profile.genre_id}")
    return _ProfileCheck(
        failures=tuple(failures),
        profile_memberships=profile_memberships,
        direct_memberships=direct_memberships,
        one_hop_memberships=one_hop_memberships,
    )


def _neighbor_check(
    neighbor: GenreNeighbor,
    vectors: dict[tuple[str, str], dict[str, MembershipScore]],
) -> tuple[str | None, bool]:
    """Recompute one neighbor and verify its common memberships are traceable."""
    left = vectors.get((neighbor.profile_kind, neighbor.genre_id))
    right = vectors.get((neighbor.profile_kind, neighbor.neighbor_genre_id))
    if left is None or right is None:
        return f"neighbor references a missing profile: {neighbor.genre_id}", False
    if neighbor.genre_id == neighbor.neighbor_genre_id:
        return f"neighbor points to itself: {neighbor.genre_id}", False
    common = set(left) & set(right)
    if len(common) != neighbor.shared_artist_count:
        return f"neighbor shared count mismatch: {neighbor.genre_id}", False
    left_scores = {artist: float(membership.score) for artist, membership in left.items()}
    right_scores = {artist: float(membership.score) for artist, membership in right.items()}
    if neighbor.metric == "weighted_jaccard":
        numerator = sum(min(left_scores[artist], right_scores[artist]) for artist in common)
        denominator = sum(left_scores.values()) + sum(right_scores.values()) - numerator
        expected_score = numerator / denominator
    else:
        numerator = sum(left_scores[artist] * right_scores[artist] for artist in common)
        left_norm = math.sqrt(sum(score * score for score in left_scores.values()))
        right_norm = math.sqrt(sum(score * score for score in right_scores.values()))
        expected_score = numerator / (left_norm * right_norm)
    if not math.isclose(neighbor.score, round(expected_score, 12), abs_tol=5e-12):
        return f"neighbor score mismatch: {neighbor.genre_id}", False
    if not all(left[artist].evidence_refs and right[artist].evidence_refs for artist in common):
        return f"neighbor lacks source traceability: {neighbor.genre_id}", False
    return None, True


def _neighbor_failures(
    artifact: PublicModelArtifact,
) -> tuple[tuple[str, ...], int, int, int]:
    vectors = _profile_vectors(artifact)
    profile_check = _profile_checks(artifact)
    failures = list(profile_check.failures)
    explainable = 0
    grouped_ranks: dict[tuple[str, str, str], list[int]] = {}
    for neighbor in artifact.neighbors:
        key = (neighbor.profile_kind, neighbor.metric, neighbor.genre_id)
        grouped_ranks.setdefault(key, []).append(neighbor.rank)
        failure, is_explainable = _neighbor_check(neighbor, vectors)
        if failure is not None:
            failures.append(failure)
        if is_explainable:
            explainable += 1

    for key, ranks in grouped_ranks.items():
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            failures.append(f"neighbor ranks are not contiguous: {key[2]}")
    return (
        tuple(failures),
        explainable,
        profile_check.profile_memberships,
        profile_check.direct_memberships,
    )


def evaluate_public_model(
    artifact: PublicModelArtifact,
    *,
    artifact_file_sha256: Sha256 | None = None,
    artifact_byte_size: int | None = None,
) -> PublicModelGateReport:
    """Evaluate one independently built artifact without reading any audio or cache."""
    failures: list[str] = []
    forbidden_terms = _forbidden_terms(artifact)
    if forbidden_terms:
        failures.append("forbidden historical source vocabulary: " + ", ".join(forbidden_terms))
    if not artifact.export_allowed:
        failures.append("artifact is not marked exportable")

    genre_ids = {genre.genre_id for genre in artifact.genres}
    direct_profile_genres = {
        profile.genre_id for profile in artifact.profiles if profile.profile_kind == "direct"
    }
    one_hop_profile_genres = {
        profile.genre_id for profile in artifact.profiles if profile.profile_kind == "one_hop"
    }
    if not direct_profile_genres <= genre_ids or not one_hop_profile_genres <= genre_ids:
        failures.append("profile references a genre outside the public identity set")

    neighbor_failures, explainable, profile_memberships, direct_memberships = _neighbor_failures(
        artifact
    )
    failures.extend(neighbor_failures)
    recomputed = public_model_output_sha256(artifact)
    if recomputed != artifact.output_sha256:
        failures.append("logical output hash does not match artifact")

    evidence_payload = artifact.model_dump(
        mode="json", exclude={"layouts", "resources", "output_sha256"}
    )
    coordinate_payload = [
        {
            "layout_key": lens.layout_key,
            "coordinates": [item.model_dump(mode="json") for item in lens.coordinates],
            "unplaced": [item.model_dump(mode="json") for item in lens.unplaced],
        }
        for lens in sorted(artifact.layouts, key=lambda item: item.layout_key)
    ]
    version_payload = [
        {
            "layout_key": lens.layout_key,
            "method": lens.method,
            "method_version": lens.method_version,
            "input_kind": lens.input_kind,
            "metric": lens.metric,
            "seed": lens.seed,
            "input_sha256": lens.input_sha256,
            "output_sha256": lens.output_sha256,
        }
        for lens in sorted(artifact.layouts, key=lambda item: item.layout_key)
    ]
    layout_coordinate_count = sum(len(lens.coordinates) for lens in artifact.layouts)
    expected_layout_entries = len(artifact.layouts) * len(genre_ids)
    layout_coverage = (
        (layout_coordinate_count + sum(len(lens.unplaced) for lens in artifact.layouts))
        / expected_layout_entries
        if expected_layout_entries
        else 1.0
    )
    if layout_coverage != 1.0:
        failures.append("layouts do not account for every public genre")
    for lens in artifact.layouts:
        if not lens.stability.exact_rerun or lens.stability.aligned_coordinate_rms != 0.0:
            failures.append(f"layout is not deterministically repeatable: {lens.layout_key}")
        if lens.quality.placed_genres != len(lens.coordinates):
            failures.append(f"layout quality count mismatch: {lens.layout_key}")

    artifact_counts = Counter(item.source for item in artifact.artifacts)
    neighbor_coverage = explainable / len(artifact.neighbors) if artifact.neighbors else 1.0
    profile_coverage = (
        len(direct_profile_genres | one_hop_profile_genres) / len(genre_ids) if genre_ids else 1.0
    )
    return PublicModelGateReport(
        passed=not failures,
        failures=tuple(failures),
        artifact_file_sha256=artifact_file_sha256,
        artifact_byte_size=artifact_byte_size,
        artifact_output_sha256=artifact.output_sha256,
        recomputed_output_sha256=recomputed,
        evidence_sha256=_sha256(evidence_payload),
        coordinate_sha256=_sha256(coordinate_payload),
        layout_version_sha256=_sha256(version_payload),
        public_artifact_count=len(artifact.artifacts),
        listenbrainz_artifact_count=artifact_counts["listenbrainz"],
        musicbrainz_artifact_count=artifact_counts["musicbrainz"],
        wikidata_artifact_count=artifact_counts["wikidata"],
        genre_count=len(artifact.genres),
        profile_count=len(artifact.profiles),
        direct_profile_genres=len(direct_profile_genres),
        one_hop_profile_genres=len(one_hop_profile_genres),
        direct_membership_count=direct_memberships,
        one_hop_membership_count=profile_memberships - direct_memberships,
        neighbor_count=len(artifact.neighbors),
        explainable_neighbor_count=explainable,
        neighbor_evidence_coverage=neighbor_coverage,
        layout_count=len(artifact.layouts),
        layout_coordinate_count=layout_coordinate_count,
        layout_coverage=layout_coverage,
        profile_genre_coverage=profile_coverage,
        forbidden_terms=forbidden_terms,
    )


def require_public_model_gate(
    artifact: PublicModelArtifact,
    *,
    artifact_file_sha256: Sha256 | None = None,
    artifact_byte_size: int | None = None,
) -> PublicModelGateReport:
    """Return a passing report or fail closed before publication."""
    report = evaluate_public_model(
        artifact,
        artifact_file_sha256=artifact_file_sha256,
        artifact_byte_size=artifact_byte_size,
    )
    if not report.passed:
        raise PublicModelGateError(report.failures)
    return report
