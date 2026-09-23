"""Local-only review proposals from retained tag rows and sealed pair counts.

This module never treats a MusicBrainz tag row as artist membership.  It uses
exact MusicBrainz artist IDs only to join two retained sources and emits review
proposals, never placements, coordinates, facts, or model input.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

import ijson
from pydantic import ConfigDict, Field, model_validator

from opennoise.analysis.lastfm_360k import load_lastfm_360k_sealed_v1_envelope
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "musicbrainz-unplaced-colisten-review-edges-v1"
_MAX_TAG_ROWS: Final = 500_000
_MAX_SCOPED_ARTISTS: Final = 1_000
_MAX_SEED_LABELS_PER_ARTIST: Final = 10
_MINIMUM_DISTINCT_ARTIST_PAIRS: Final = 2
_MAX_PROPOSALS_PER_UNPLACED: Final = 3
_MAX_PROPOSALS_PER_PLACED: Final = 10
_UNPLACED_DENOMINATOR: Final = 3_346
_REVIEW_FRONTIER_SIZE: Final = 414
_LASTFM_PAIR_FLOOR: Final = 5
_PINNED_LAYOUT_SHA256: Final = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_PINNED_SOURCE_TAG_ARTIFACT_SHA256: Final = (
    "481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe"
)
_PINNED_REVIEW_CANDIDATE_SHA256: Final = (
    "b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028"
)


class MusicBrainzUnplacedCoListenError(ValueError):
    """The local-only source join cannot safely continue."""


class CoListenReviewSettings(FrozenModel):
    """Predeclared selection, scoring, and hub controls."""

    revision: Literal["musicbrainz-unplaced-colisten-review-edge-settings-v1"] = (
        "musicbrainz-unplaced-colisten-review-edge-settings-v1"
    )
    source_tag_rule: Literal["facet_tag_and_literal_exact_seed_name_match"] = (
        "facet_tag_and_literal_exact_seed_name_match"
    )
    pair_rule: Literal["sealed_lastfm_pair_support_at_or_above_receipt_floor"] = (
        "sealed_lastfm_pair_support_at_or_above_receipt_floor"
    )
    minimum_distinct_artist_pair_supports: Literal[2] = _MINIMUM_DISTINCT_ARTIST_PAIRS
    score_rule: Literal["sum_log2_one_plus_pair_users_divided_by_source_label_degrees"] = (
        "sum_log2_one_plus_pair_users_divided_by_source_label_degrees"
    )
    maximum_seed_labels_per_source_artist: Literal[10] = _MAX_SEED_LABELS_PER_ARTIST
    source_artist_degree_rule: Literal["strictly_less_than_maximum"] = "strictly_less_than_maximum"
    maximum_proposals_per_unplaced_seed: Literal[3] = _MAX_PROPOSALS_PER_UNPLACED
    maximum_proposals_per_placed_seed: Literal[10] = _MAX_PROPOSALS_PER_PLACED
    maximum_tag_rows: int = Field(default=_MAX_TAG_ROWS, ge=1, le=_MAX_TAG_ROWS)
    maximum_scoped_source_artists: int = Field(
        default=_MAX_SCOPED_ARTISTS, ge=1, le=_MAX_SCOPED_ARTISTS
    )


class CoListenReviewProposal(FrozenModel):
    """A source-derived review route, rather than a genre relation or placement."""

    unplaced_seed_id: str = Field(min_length=1)
    placed_seed_id: str = Field(min_length=1)
    distinct_exact_artist_pair_support_count: int = Field(ge=_MINIMUM_DISTINCT_ARTIST_PAIRS)
    summed_pair_user_support: int = Field(ge=10)
    score: float = Field(gt=0.0)


class CoListenReviewCoverage(FrozenModel):
    """Counts that keep candidate reach separate from placement."""

    all_unplaced_seed_count: int = Field(ge=0)
    retained_direct_tag_lower_bound_seed_count: int = Field(ge=0)
    literal_exact_direct_tag_seed_count: int = Field(ge=0)
    literal_exact_source_artist_count: int = Field(ge=0)
    source_artists_after_hub_filter_count: int = Field(ge=0)
    scoped_unplaced_seeds_with_any_pair_join: int = Field(ge=0)
    scoped_unplaced_seeds_with_two_distinct_artist_pair_supports: int = Field(ge=0)
    qualifying_proposal_count_before_caps: int = Field(ge=0)
    proposed_edge_count_after_caps: int = Field(ge=0)
    proposed_unplaced_seed_count_after_caps: int = Field(ge=0)
    proposed_placed_seed_count_after_caps: int = Field(ge=0)
    review_candidate_frontier_unplaced_seed_count: Literal[414] = _REVIEW_FRONTIER_SIZE
    overlap_with_review_candidate_frontier: int = Field(ge=0)
    novel_beyond_review_candidate_frontier: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_denominators(self) -> CoListenReviewCoverage:
        if self.retained_direct_tag_lower_bound_seed_count > self.all_unplaced_seed_count:
            raise ValueError("retained source-positive seed count exceeds unplaced denominator")
        if (
            self.literal_exact_direct_tag_seed_count
            > self.retained_direct_tag_lower_bound_seed_count
        ):
            raise ValueError("literal-exact count exceeds retained source-positive count")
        if self.proposed_unplaced_seed_count_after_caps != (
            self.overlap_with_review_candidate_frontier
            + self.novel_beyond_review_candidate_frontier
        ):
            raise ValueError("review-frontier overlap does not partition proposed unplaced seeds")
        return self


class MusicBrainzUnplacedCoListenReport(FrozenModel):
    """Hash-bound, local-only result that cannot authorize a placement."""

    revision: Literal["musicbrainz-unplaced-colisten-review-edges-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    factual_artist_membership_asserted: Literal[False] = False
    placement_asserted: Literal[False] = False
    historical_every_noise_relationships_or_coordinates_read: Literal[False] = False
    lastfm_user_identifiers_read: Literal[False] = False
    settings: CoListenReviewSettings
    layout_sha256: Sha256
    source_tag_artifact_sha256: Sha256
    lastfm_artifact_sha256: Sha256
    lastfm_companion_receipt_sha256: Sha256
    lastfm_database_sha256: Sha256
    lastfm_pair_floor: int = Field(ge=5)
    coverage: CoListenReviewCoverage
    proposals: tuple[CoListenReviewProposal, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def _check_output_hash_and_proposals(self) -> MusicBrainzUnplacedCoListenReport:
        if self.output_sha256 != _logical_hash(self):
            raise ValueError("report output hash does not match report content")
        proposal_seeds = {proposal.unplaced_seed_id for proposal in self.proposals}
        if len(proposal_seeds) != self.coverage.proposed_unplaced_seed_count_after_caps:
            raise ValueError("proposal seed count does not match coverage")
        return self


class _Layout(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    coordinates: tuple[dict[str, object], ...]
    unplaced: tuple[dict[str, object], ...]


class _TagRead(FrozenModel):
    """Typed result of the retained source scan before any co-listen join."""

    literal_labels_by_artist: dict[str, frozenset[str]]
    retained_source_positive_unplaced_seed_ids: frozenset[str]


def evaluate_musicbrainz_unplaced_colisten_edges(  # noqa: PLR0913
    *,
    layout_path: Path,
    source_tag_artifact_path: Path,
    lastfm_artifact_path: Path,
    lastfm_companion_receipt_path: Path,
    lastfm_database_path: Path,
    review_candidate_path: Path,
    settings: CoListenReviewSettings | None = None,
) -> MusicBrainzUnplacedCoListenReport:
    """Join retained exact IDs and return bounded review-only proposed edges."""
    config = settings or CoListenReviewSettings()
    _require_pinned_hash(layout_path, _PINNED_LAYOUT_SHA256, "layout")
    _require_pinned_hash(source_tag_artifact_path, _PINNED_SOURCE_TAG_ARTIFACT_SHA256, "source tag")
    _require_pinned_hash(review_candidate_path, _PINNED_REVIEW_CANDIDATE_SHA256, "review candidate")
    placed_ids, unplaced_ids = _read_layout_ids(layout_path)
    review_frontier = _read_review_frontier(review_candidate_path, unplaced_ids)
    source_read = _read_literal_tag_labels(
        source_tag_artifact_path, placed_ids | unplaced_ids, unplaced_ids, config
    )
    artist_labels = source_read.literal_labels_by_artist
    scoped_artist_labels = {
        artist_id: labels & unplaced_ids
        for artist_id, labels in artist_labels.items()
        if labels & unplaced_ids and len(labels) < config.maximum_seed_labels_per_source_artist
    }
    if len(scoped_artist_labels) > config.maximum_scoped_source_artists:
        raise MusicBrainzUnplacedCoListenError("scoped source artist bound exceeded")
    literal_exact_unplaced = {
        seed_id for labels in artist_labels.values() for seed_id in labels & unplaced_ids
    }
    routes = _read_pair_routes(
        lastfm_database_path, scoped_artist_labels, artist_labels, placed_ids
    )
    qualifying = _qualifying_proposals(
        routes,
        {artist_id: len(labels) for artist_id, labels in artist_labels.items()},
        config,
    )
    proposals = _cap_proposals(qualifying, config)
    report = MusicBrainzUnplacedCoListenReport.model_construct(
        settings=config,
        layout_sha256=_sha256_file(layout_path),
        source_tag_artifact_sha256=_sha256_file(source_tag_artifact_path),
        lastfm_artifact_sha256=_sha256_file(lastfm_artifact_path),
        lastfm_companion_receipt_sha256=_sha256_file(lastfm_companion_receipt_path),
        lastfm_database_sha256=_sha256_file(lastfm_database_path),
        lastfm_pair_floor=_verified_pair_floor(
            lastfm_artifact_path, lastfm_companion_receipt_path, lastfm_database_path
        ),
        coverage=CoListenReviewCoverage(
            all_unplaced_seed_count=len(unplaced_ids),
            retained_direct_tag_lower_bound_seed_count=len(
                source_read.retained_source_positive_unplaced_seed_ids
            ),
            literal_exact_direct_tag_seed_count=len(literal_exact_unplaced),
            literal_exact_source_artist_count=len(
                {artist for artist, labels in artist_labels.items() if labels & unplaced_ids}
            ),
            source_artists_after_hub_filter_count=len(scoped_artist_labels),
            scoped_unplaced_seeds_with_any_pair_join=len({left for left, _right in routes}),
            scoped_unplaced_seeds_with_two_distinct_artist_pair_supports=len(
                {proposal.unplaced_seed_id for proposal in qualifying}
            ),
            qualifying_proposal_count_before_caps=len(qualifying),
            proposed_edge_count_after_caps=len(proposals),
            proposed_unplaced_seed_count_after_caps=len(
                {proposal.unplaced_seed_id for proposal in proposals}
            ),
            proposed_placed_seed_count_after_caps=len(
                {proposal.placed_seed_id for proposal in proposals}
            ),
            overlap_with_review_candidate_frontier=len(
                {proposal.unplaced_seed_id for proposal in proposals} & review_frontier
            ),
            novel_beyond_review_candidate_frontier=len(
                {proposal.unplaced_seed_id for proposal in proposals} - review_frontier
            ),
        ),
        proposals=proposals,
        output_sha256="0" * 64,
    )
    payload = report.model_dump(mode="json")
    payload["output_sha256"] = _logical_hash(report)
    return MusicBrainzUnplacedCoListenReport.model_validate_json(json.dumps(payload))


def _read_layout_ids(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    raw = _Layout.model_validate_json(path.read_bytes())
    placed = _row_ids(raw.coordinates, "coordinates")
    unplaced = _row_ids(raw.unplaced, "unplaced")
    if placed & unplaced:
        raise MusicBrainzUnplacedCoListenError("layout contains IDs in both states")
    if len(unplaced) != _UNPLACED_DENOMINATOR:
        raise MusicBrainzUnplacedCoListenError(
            "layout does not retain the 3,346 unplaced denominator"
        )
    return frozenset(placed), frozenset(unplaced)


def _row_ids(rows: tuple[dict[str, object], ...], label: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        value = row.get("seed_id")
        if not isinstance(value, str) or not value:
            raise MusicBrainzUnplacedCoListenError(f"{label} row lacks a seed ID")
        if value in result:
            raise MusicBrainzUnplacedCoListenError(f"{label} contains a repeated seed ID")
        result.add(value)
    return result


def _read_literal_tag_labels(
    path: Path,
    universe: frozenset[str],
    unplaced_ids: frozenset[str],
    settings: CoListenReviewSettings,
) -> _TagRead:
    labels: dict[str, set[str]] = defaultdict(set)
    retained_positive_unplaced: set[str] = set()
    row_count = 0
    with path.open("rb") as stream:
        for raw in ijson.items(stream, "evidence.item"):
            if not isinstance(raw, dict) or raw.get("facet") != "tag":
                continue
            row_count += 1
            if row_count > settings.maximum_tag_rows:
                raise MusicBrainzUnplacedCoListenError("source tag row bound exceeded")
            raw_seed_id = raw.get("seed_source_item_id")
            if isinstance(raw_seed_id, str) and raw_seed_id in unplaced_ids:
                retained_positive_unplaced.add(raw_seed_id)
            match raw.get("artist_id"), raw.get("seed_source_item_id"), raw.get("match_kind"):
                case str() as artist_id, str() as seed_id, "exact":
                    if raw.get("target_name") == raw.get("seed_name") and seed_id in universe:
                        labels[artist_id].add(seed_id)
                case _:
                    continue
    return _TagRead(
        literal_labels_by_artist={
            artist_id: frozenset(seed_ids) for artist_id, seed_ids in labels.items()
        },
        retained_source_positive_unplaced_seed_ids=frozenset(retained_positive_unplaced),
    )


def _read_pair_routes(
    database_path: Path,
    unplaced_labels: dict[str, frozenset[str]],
    all_labels: dict[str, frozenset[str]],
    placed_ids: frozenset[str],
) -> dict[tuple[str, str], dict[tuple[str, str], int]]:
    routes: dict[tuple[str, str], dict[tuple[str, str], int]] = defaultdict(dict)
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as database:
            for left_artist, right_artist, user_count in database.execute(
                "SELECT left_artist, right_artist, distinct_user_count "
                "FROM pair_support ORDER BY left_artist, right_artist"
            ):
                if not isinstance(left_artist, str) or not isinstance(right_artist, str):
                    raise MusicBrainzUnplacedCoListenError("pair endpoint is not text")
                if not isinstance(user_count, int) or user_count < _LASTFM_PAIR_FLOOR:
                    raise MusicBrainzUnplacedCoListenError("pair support is below the sealed floor")
                _add_pair_routes(
                    routes,
                    unplaced_labels,
                    all_labels,
                    placed_ids,
                    left_artist,
                    right_artist,
                    user_count,
                )
                _add_pair_routes(
                    routes,
                    unplaced_labels,
                    all_labels,
                    placed_ids,
                    right_artist,
                    left_artist,
                    user_count,
                )
    except sqlite3.Error as error:
        raise MusicBrainzUnplacedCoListenError("cannot read sealed Last.fm aggregate") from error
    return routes


def _add_pair_routes(  # noqa: PLR0913, PLR0917
    routes: dict[tuple[str, str], dict[tuple[str, str], int]],
    unplaced_labels: dict[str, frozenset[str]],
    all_labels: dict[str, frozenset[str]],
    placed_ids: frozenset[str],
    unplaced_artist: str,
    placed_artist: str,
    user_count: int,
) -> None:
    source_labels = unplaced_labels.get(unplaced_artist)
    placed_labels = all_labels.get(placed_artist)
    if source_labels is None or placed_labels is None:
        return
    for unplaced_seed in sorted(source_labels):
        for placed_seed in sorted(placed_labels & placed_ids):
            routes[(unplaced_seed, placed_seed)][(unplaced_artist, placed_artist)] = user_count


def _qualifying_proposals(
    routes: dict[tuple[str, str], dict[tuple[str, str], int]],
    artist_label_degrees: dict[str, int],
    settings: CoListenReviewSettings,
) -> tuple[CoListenReviewProposal, ...]:
    proposals: list[CoListenReviewProposal] = []
    for (unplaced_seed, placed_seed), pairs in sorted(routes.items()):
        if len(pairs) < settings.minimum_distinct_artist_pair_supports:
            continue
        score = math.fsum(
            math.log2(1 + user_count) / (artist_label_degrees[left] * artist_label_degrees[right])
            for (left, right), user_count in sorted(pairs.items())
        )
        proposals.append(
            CoListenReviewProposal(
                unplaced_seed_id=unplaced_seed,
                placed_seed_id=placed_seed,
                distinct_exact_artist_pair_support_count=len(pairs),
                summed_pair_user_support=sum(pairs.values()),
                score=score,
            )
        )
    return tuple(
        sorted(
            proposals,
            key=lambda proposal: (
                -proposal.score,
                proposal.unplaced_seed_id,
                proposal.placed_seed_id,
            ),
        )
    )


def _cap_proposals(
    proposals: tuple[CoListenReviewProposal, ...], settings: CoListenReviewSettings
) -> tuple[CoListenReviewProposal, ...]:
    unplaced_counts: dict[str, int] = defaultdict(int)
    placed_counts: dict[str, int] = defaultdict(int)
    selected: list[CoListenReviewProposal] = []
    for proposal in proposals:
        if (
            unplaced_counts[proposal.unplaced_seed_id]
            >= settings.maximum_proposals_per_unplaced_seed
            or placed_counts[proposal.placed_seed_id] >= settings.maximum_proposals_per_placed_seed
        ):
            continue
        selected.append(proposal)
        unplaced_counts[proposal.unplaced_seed_id] += 1
        placed_counts[proposal.placed_seed_id] += 1
    return tuple(selected)


def _read_review_frontier(path: Path, unplaced_ids: frozenset[str]) -> frozenset[str]:
    raw: object = json.loads(path.read_bytes())
    if not isinstance(raw, dict) or raw.get("historical_inputs_used") is not False:
        raise MusicBrainzUnplacedCoListenError("review candidate must declare no historical inputs")
    edges = raw.get("edges")
    if not isinstance(edges, list):
        raise MusicBrainzUnplacedCoListenError("review candidate lacks edges")
    frontier: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise MusicBrainzUnplacedCoListenError("review candidate edge is malformed")
        for key in ("source_genre_id", "target_genre_id"):
            value = edge.get(key)
            if isinstance(value, str) and value in unplaced_ids:
                frontier.add(value)
    if len(frontier) != _REVIEW_FRONTIER_SIZE:
        raise MusicBrainzUnplacedCoListenError(
            "review candidate does not retain its 414-seed frontier"
        )
    return frozenset(frontier)


def _verified_pair_floor(artifact_path: Path, receipt_path: Path, database_path: Path) -> int:
    envelope = load_lastfm_360k_sealed_v1_envelope(
        artifact_path=artifact_path,
        companion_receipt_path=receipt_path,
        database_path=database_path,
    )
    return envelope.companion_receipt.working_database_pair_floor


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_pinned_hash(path: Path, expected: str, label: str) -> None:
    if _sha256_file(path) != expected:
        raise MusicBrainzUnplacedCoListenError(f"{label} does not match the pinned input hash")


def _logical_hash(report: MusicBrainzUnplacedCoListenReport) -> str:
    payload = report.model_dump(mode="json")
    payload["output_sha256"] = "0" * 64
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def write_report_no_replace(path: Path, report: MusicBrainzUnplacedCoListenReport) -> None:
    """Create a report once, without replacing a concurrent or prior measurement."""
    if "dist" in path.resolve().parts:
        raise MusicBrainzUnplacedCoListenError("experimental report cannot be written under dist")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True).encode())
        stream.write(b"\n")
