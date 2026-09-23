"""Evaluate local peer signals by recovering withheld custody memberships."""

from __future__ import annotations

import hashlib
import heapq
import itertools
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_TOP_K: Final = 10
_RECALL_K: Final = 20
_MINIMUM_TRAIN_ARTISTS: Final = 4
_HOLDOUT_DIVISOR: Final = 5
_MINIMUM_SHARED_ARTISTS: Final = 2
_IDF_SCORE_INDEX: Final = 2
_REVISION: Final = "direct-custody-membership-holdout-v1"


class DirectCustodyMembershipHoldoutError(ValueError):
    """Report an invalid local membership-holdout evaluation input."""


@dataclass(frozen=True, slots=True)
class _RankingTotals:
    """Integer and reciprocal-rank totals for one deterministic ranking rule."""

    recalled: int
    reciprocal_rank_sum: float
    supported: int


@dataclass(frozen=True, slots=True)
class _RankingOutcome:
    """Metrics plus exact supported identities for an intersection comparison."""

    totals: _RankingTotals
    macro_recall: float
    supported_targets: frozenset[tuple[str, str]]
    recalled_targets: frozenset[tuple[str, str]]


class MembershipRankingMetric(FrozenModel):
    """One ranker's results on the common withheld-positive denominator."""

    ranking: Literal[
        "idf_weighted_jaccard_peer_vote",
        "shared_artist_count_peer_vote",
        "global_train_artist_degree",
    ]
    recalled_at_20: int = Field(ge=0)
    micro_recall_at_20: float = Field(ge=0.0, le=1.0)
    macro_recall_at_20: float = Field(ge=0.0, le=1.0)
    mrr_at_20: float = Field(ge=0.0, le=1.0)
    target_supported_by_ranking: int = Field(ge=0)
    target_support_rate: float = Field(ge=0.0, le=1.0)
    conditional_recall_at_20: float = Field(ge=0.0, le=1.0)


class CommonSupportComparison(FrozenModel):
    """Fixed-intersection comparison that removes candidate-support differences."""

    common_supported_target_count: int = Field(ge=0)
    idf_weighted_jaccard_recalled_at_20: int = Field(ge=0)
    shared_artist_count_recalled_at_20: int = Field(ge=0)
    idf_weighted_jaccard_conditional_recall_at_20: float = Field(ge=0.0, le=1.0)
    shared_artist_count_conditional_recall_at_20: float = Field(ge=0.0, le=1.0)


class DirectCustodyMembershipHoldoutReport(FrozenModel):
    """Receipt-bound, source-only held-out artist membership comparison."""

    revision: Literal["direct-custody-membership-holdout-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    graph_receipt_sha256: Sha256
    graph_database_sha256: Sha256
    custody_receipt_sha256: Sha256
    custody_object_sha256: Sha256
    split_rule: Literal["sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"] = (
        "sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"
    )
    minimum_train_artists_per_seed: Literal[4] = _MINIMUM_TRAIN_ARTISTS
    peer_top_k: Literal[10] = _TOP_K
    recall_k: Literal[20] = _RECALL_K
    total_custody_seed_count: int = Field(ge=0)
    eligible_seed_count: int = Field(ge=0)
    ineligible_seed_count: int = Field(ge=0)
    withheld_positive_count: int = Field(ge=0)
    train_membership_count: int = Field(ge=0)
    train_candidate_pair_count: int = Field(ge=0)
    idf_weighted_jaccard: MembershipRankingMetric
    shared_artist_count: MembershipRankingMetric
    global_artist_degree: MembershipRankingMetric
    idf_vs_shared_artist_count_common_support: CommonSupportComparison
    historical_inputs_used: Literal[False] = False
    h3_inputs_used: Literal[False] = False
    tags_or_lastfm_used: Literal[False] = False
    release_rows_used: Literal[False] = False
    missing_target_is_negative: Literal[False] = False
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    output_sha256: Sha256


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_hash(report: DirectCustodyMembershipHoldoutReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _read_memberships(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Read the verified, deduplicated memberships in a stable order."""
    memberships: dict[str, list[str]] = defaultdict(list)
    for seed_id, artist_mbid in connection.execute(
        "SELECT seed_id, artist_mbid FROM seed_artist ORDER BY seed_id, artist_mbid"
    ):
        memberships[str(seed_id)].append(str(artist_mbid))
    return {seed: tuple(artists) for seed, artists in memberships.items()}


def _held_out_artists(seed_id: str, artists: tuple[str, ...]) -> tuple[str, ...]:
    """Choose a fixed positive-only slice while retaining the train minimum."""
    if len(artists) < _MINIMUM_TRAIN_ARTISTS + 1:
        return ()
    count = max(1, len(artists) // _HOLDOUT_DIVISOR)
    count = min(count, len(artists) - _MINIMUM_TRAIN_ARTISTS)
    return tuple(
        sorted(
            artists,
            key=lambda artist: hashlib.sha256(f"{seed_id}\0{artist}".encode()).digest(),
        )[:count]
    )


def _split_memberships(
    memberships: dict[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Produce immutable train and held-out positives for every source seed."""
    train: dict[str, tuple[str, ...]] = {}
    held_out: dict[str, tuple[str, ...]] = {}
    for seed_id, artists in memberships.items():
        held = _held_out_artists(seed_id, artists)
        held_set = frozenset(held)
        train[seed_id] = tuple(artist for artist in artists if artist not in held_set)
        if held:
            held_out[seed_id] = held
    return train, held_out


def _build_peer_rows(
    train: dict[str, tuple[str, ...]],
) -> tuple[
    dict[str, tuple[tuple[str, int, float], ...]],
    dict[str, tuple[tuple[str, int, float], ...]],
    int,
]:
    """Build independent train-only top-ten neighborhoods for both graph signals."""
    artist_seeds: dict[str, list[str]] = defaultdict(list)
    for seed_id, artists in train.items():
        for artist in artists:
            artist_seeds[artist].append(seed_id)
    seed_count = len(train)
    total_weight: dict[str, float] = defaultdict(float)
    shared_weight: dict[tuple[str, str], float] = defaultdict(float)
    shared_count: dict[tuple[str, str], int] = defaultdict(int)
    for artist, seed_ids in artist_seeds.items():
        del artist
        weight = 1.0 + math.log((seed_count + 1) / (len(seed_ids) + 1))
        for seed_id in seed_ids:
            total_weight[seed_id] += weight
        for pair in itertools.combinations(seed_ids, 2):
            shared_count[pair] += 1
            shared_weight[pair] += weight
    idf_rows: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    count_rows: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    candidate_count = 0
    for (left, right), count in shared_count.items():
        if count < _MINIMUM_SHARED_ARTISTS:
            continue
        candidate_count += 1
        score = shared_weight[left, right] / (
            total_weight[left] + total_weight[right] - shared_weight[left, right]
        )
        idf_rows[left].append((right, count, score))
        idf_rows[right].append((left, count, score))
        count_rows[left].append((right, count, score))
        count_rows[right].append((left, count, score))

    def ordered(
        rows: dict[str, list[tuple[str, int, float]]], *, idf: bool
    ) -> dict[str, tuple[tuple[str, int, float], ...]]:
        return {
            seed_id: tuple(
                sorted(
                    values,
                    key=(
                        (lambda row: (-row[2], -row[1], row[0]))
                        if idf
                        else (lambda row: (-row[1], -row[2], row[0]))
                    ),
                )[:_TOP_K]
            )
            for seed_id, values in rows.items()
        }

    return ordered(idf_rows, idf=True), ordered(count_rows, idf=False), candidate_count


def _ranked_target_metrics(
    *,
    held_out: dict[str, tuple[str, ...]],
    train: dict[str, tuple[str, ...]],
    peer_rows: dict[str, tuple[tuple[str, int, float], ...]],
    score_index: Literal[1, 2],
) -> _RankingOutcome:
    """Score withheld positives from a top-ten peer vote without treating absence as false."""
    totals = _RankingTotals(recalled=0, reciprocal_rank_sum=0.0, supported=0)
    per_seed_recall: list[float] = []
    supported_targets: set[tuple[str, str]] = set()
    recalled_targets: set[tuple[str, str]] = set()
    for seed_id, targets in held_out.items():
        votes: dict[str, float] = defaultdict(float)
        for peer_id, count, idf_score in peer_rows.get(seed_id, ()):
            vote = idf_score if score_index == _IDF_SCORE_INDEX else float(count)
            for artist in train[peer_id]:
                votes[artist] += vote
        ranked = {
            artist: rank
            for rank, (artist, _score) in enumerate(
                heapq.nsmallest(_RECALL_K, votes.items(), key=lambda row: (-row[1], row[0])),
                start=1,
            )
        }
        seed_recalled = 0
        for artist in targets:
            if artist not in votes:
                continue
            supported_targets.add((seed_id, artist))
            supported = totals.supported + 1
            rank = ranked.get(artist)
            recalled = totals.recalled + int(rank is not None)
            reciprocal = totals.reciprocal_rank_sum + (0.0 if rank is None else 1 / rank)
            totals = _RankingTotals(
                recalled=recalled, reciprocal_rank_sum=reciprocal, supported=supported
            )
            seed_recalled += int(rank is not None)
            if rank is not None:
                recalled_targets.add((seed_id, artist))
        per_seed_recall.append(seed_recalled / len(targets))
    return _RankingOutcome(
        totals=totals,
        macro_recall=math.fsum(per_seed_recall) / len(per_seed_recall),
        supported_targets=frozenset(supported_targets),
        recalled_targets=frozenset(recalled_targets),
    )


def _global_degree_metrics(
    *, train: dict[str, tuple[str, ...]], held_out: dict[str, tuple[str, ...]]
) -> _RankingOutcome:
    """Use train-only global artist degree as an intentionally non-relational baseline."""
    degree: dict[str, int] = defaultdict(int)
    for artists in train.values():
        for artist in artists:
            degree[artist] += 1
    ranked = {
        artist: rank
        for rank, (artist, _degree) in enumerate(
            heapq.nsmallest(_RECALL_K, degree.items(), key=lambda row: (-row[1], row[0])),
            start=1,
        )
    }
    totals = _RankingTotals(recalled=0, reciprocal_rank_sum=0.0, supported=0)
    per_seed_recall: list[float] = []
    supported_targets: set[tuple[str, str]] = set()
    recalled_targets: set[tuple[str, str]] = set()
    for seed_id, targets in held_out.items():
        seed_recalled = 0
        for artist in targets:
            if artist not in degree:
                continue
            supported_targets.add((seed_id, artist))
            totals = _RankingTotals(
                recalled=totals.recalled + int(artist in ranked),
                reciprocal_rank_sum=totals.reciprocal_rank_sum
                + (0.0 if artist not in ranked else 1 / ranked[artist]),
                supported=totals.supported + 1,
            )
            seed_recalled += int(artist in ranked)
            if artist in ranked:
                recalled_targets.add((seed_id, artist))
        per_seed_recall.append(seed_recalled / len(targets))
    return _RankingOutcome(
        totals=totals,
        macro_recall=math.fsum(per_seed_recall) / len(per_seed_recall),
        supported_targets=frozenset(supported_targets),
        recalled_targets=frozenset(recalled_targets),
    )


def _metric(
    ranking: Literal[
        "idf_weighted_jaccard_peer_vote",
        "shared_artist_count_peer_vote",
        "global_train_artist_degree",
    ],
    outcome: _RankingOutcome,
    denominator: int,
) -> MembershipRankingMetric:
    totals = outcome.totals
    return MembershipRankingMetric(
        ranking=ranking,
        recalled_at_20=totals.recalled,
        micro_recall_at_20=totals.recalled / denominator,
        macro_recall_at_20=outcome.macro_recall,
        mrr_at_20=totals.reciprocal_rank_sum / denominator,
        target_supported_by_ranking=totals.supported,
        target_support_rate=totals.supported / denominator,
        conditional_recall_at_20=totals.recalled / totals.supported if totals.supported else 0.0,
    )


def evaluate_direct_custody_membership_holdout(
    *, database: Path, receipt_path: Path
) -> DirectCustodyMembershipHoldoutReport:
    """Compare graph signals on source-held-out MusicBrainz custody positives only."""
    receipt_bytes = receipt_path.read_bytes()
    receipt = DirectCustodyPeerGraphReceipt.model_validate_json(receipt_bytes)
    verify_direct_custody_peer_graph_receipt(receipt, database=database)
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        memberships = _read_memberships(connection)
    if len(memberships) != receipt.seed_count:
        raise DirectCustodyMembershipHoldoutError("verified graph seed count changed during read")
    train, held_out = _split_memberships(memberships)
    denominator = sum(len(artists) for artists in held_out.values())
    if denominator == 0:
        raise DirectCustodyMembershipHoldoutError("no seed can retain the configured train minimum")
    idf_rows, count_rows, candidate_count = _build_peer_rows(train)
    idf_outcome = _ranked_target_metrics(
        held_out=held_out, train=train, peer_rows=idf_rows, score_index=2
    )
    count_outcome = _ranked_target_metrics(
        held_out=held_out, train=train, peer_rows=count_rows, score_index=1
    )
    degree_outcome = _global_degree_metrics(train=train, held_out=held_out)
    common_supported = idf_outcome.supported_targets & count_outcome.supported_targets
    idf_common_hits = len(idf_outcome.recalled_targets & common_supported)
    count_common_hits = len(count_outcome.recalled_targets & common_supported)
    placeholder = DirectCustodyMembershipHoldoutReport(
        graph_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        graph_database_sha256=_sha256_file(database),
        custody_receipt_sha256=receipt.custody_receipt_sha256,
        custody_object_sha256=receipt.custody_object_sha256,
        total_custody_seed_count=len(memberships),
        eligible_seed_count=len(held_out),
        ineligible_seed_count=len(memberships) - len(held_out),
        withheld_positive_count=denominator,
        train_membership_count=sum(len(artists) for artists in train.values()),
        train_candidate_pair_count=candidate_count,
        idf_weighted_jaccard=_metric("idf_weighted_jaccard_peer_vote", idf_outcome, denominator),
        shared_artist_count=_metric("shared_artist_count_peer_vote", count_outcome, denominator),
        global_artist_degree=_metric("global_train_artist_degree", degree_outcome, denominator),
        idf_vs_shared_artist_count_common_support=CommonSupportComparison(
            common_supported_target_count=len(common_supported),
            idf_weighted_jaccard_recalled_at_20=idf_common_hits,
            shared_artist_count_recalled_at_20=count_common_hits,
            idf_weighted_jaccard_conditional_recall_at_20=idf_common_hits / len(common_supported),
            shared_artist_count_conditional_recall_at_20=count_common_hits / len(common_supported),
        ),
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
