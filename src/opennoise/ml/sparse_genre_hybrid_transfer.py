"""Evaluate a fixed rank fusion of direct peers and cosine co-listen votes.

This local research evaluation reads verified direct-custody memberships and a
privacy-filtered aggregate co-listen graph. It does not write memberships or
provide a serving or public-model input.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)
from opennoise.ml.sparse_genre_cosine_transfer import _relations, _scores, _sha256_file, _strengths
from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_colisten_capacity_holdout import _all_idf_peer_rows
from opennoise.peers.direct_custody_colisten_holdout import (
    RetrievalMetric,
    _metric,
    _outcome,
)
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.direct_custody_membership_holdout import _read_memberships, _split_memberships
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_RECALL_K: Final = 20
_RRF_OFFSET: Final = 60
_MINIMUM_DISTINCT_USERS: Final = 5
_MAX_COLISTEN_RELATIONS: Final = 50_000
_SLICE_SEED_COUNT: Final = 137
_MINIMUM_TRAIN_ARTISTS: Final = 4
_REVISION: Final = "sparse-genre-hybrid-transfer-v1"


class HybridCohortReport(FrozenModel):
    """Three fixed rankers on one positive-only cohort with the same top-20 output cap."""

    heldout_positive_count: int = Field(ge=1)
    seed_count: int = Field(ge=1)
    direct_idf_peer: RetrievalMetric
    cosine_colisten: RetrievalMetric
    hybrid_rank_fusion: RetrievalMetric
    direct_cosine_common_supported_target_count: int = Field(ge=0)
    union_supported_target_count: int = Field(ge=0)
    direct_only_supported_target_count: int = Field(ge=0)
    cosine_only_supported_target_count: int = Field(ge=0)
    hybrid_recalled_at_20_from_direct_only_support: int = Field(ge=0)
    hybrid_recalled_at_20_from_cosine_only_support: int = Field(ge=0)
    hybrid_recalled_at_20_from_common_support: int = Field(ge=0)
    hybrid_recalled_at_20_not_recalled_by_either_control: int = Field(ge=0)


class SparseGenreHybridTransferReport(FrozenModel):
    """Receipt-bound local rank-fusion result that cannot authorize model changes."""

    revision: Literal["sparse-genre-hybrid-transfer-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    direct_graph_receipt_sha256: Sha256
    direct_graph_database_sha256: Sha256
    colisten_receipt_sha256: Sha256
    colisten_database_sha256: Sha256
    split_rule: Literal["sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"] = (
        "sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"
    )
    direct_peer_expansion: Literal["all_train_candidate_peers"] = "all_train_candidate_peers"
    train_candidate_peer_pair_count: int = Field(ge=0)
    output_candidate_cap_per_seed: Literal[20] = _RECALL_K
    fusion_candidate_cap_per_arm: Literal[20] = _RECALL_K
    tie_break: Literal["score descending, artist_mbid ascending"] = (
        "score descending, artist_mbid ascending"
    )
    fusion_rule: Literal[
        "reciprocal_rank_fusion: 1 / (60 + rank) from each arm's top 20 candidates"
    ] = "reciprocal_rank_fusion: 1 / (60 + rank) from each arm's top 20 candidates"
    fusion_target_tuned: Literal[False] = False
    full_heldout: HybridCohortReport
    endpoint_matched: HybridCohortReport
    broad_seed_slice: HybridCohortReport
    niche_seed_slice: HybridCohortReport
    historical_inputs_used: Literal[False] = False
    h3_inputs_used: Literal[False] = False
    tags_or_lastfm_used: Literal[False] = False
    release_rows_used: Literal[False] = False
    audio_inputs_used: Literal[False] = False
    raw_listens_or_listener_identifiers_used: Literal[False] = False
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    output_sha256: Sha256


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _report_hash(report: SparseGenreHybridTransferReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _ordered_ranks(scores: Mapping[str, float]) -> dict[str, int]:
    return {
        artist: rank
        for rank, (artist, _score) in enumerate(
            heapq.nsmallest(_RECALL_K, scores.items(), key=lambda row: (-row[1], row[0])), start=1
        )
    }


def _fused_scores(
    direct_scores: Mapping[str, float], cosine_scores: Mapping[str, float]
) -> dict[str, float]:
    """Use fixed reciprocal-rank fusion without comparing source score scales."""
    fused: dict[str, float] = defaultdict(float)
    for scores in (direct_scores, cosine_scores):
        for artist, rank in _ordered_ranks(scores).items():
            fused[artist] += 1 / (_RRF_OFFSET + rank)
    return dict(fused)


def _direct_scores(
    *,
    seed: str,
    train: Mapping[str, tuple[str, ...]],
    peer_rows: Mapping[str, tuple[tuple[str, int, float], ...]],
) -> dict[str, float]:
    """Expand the verified sparse direct-peer index without copying it per seed."""
    known = frozenset(train[seed])
    scores: dict[str, float] = defaultdict(float)
    for peer, _shared, score in peer_rows.get(seed, ()):
        for candidate in train[peer]:
            if candidate not in known:
                scores[candidate] += score
    return dict(scores)


def _seed_slices(
    memberships: Mapping[str, tuple[str, ...]],
) -> tuple[frozenset[str], frozenset[str]]:
    """Choose size groups before retrieval from the fixed direct-custody input."""
    eligible = {
        seed: artists
        for seed, artists in memberships.items()
        if len(artists) >= _MINIMUM_TRAIN_ARTISTS + 1
    }
    broad = tuple(sorted(eligible, key=lambda seed: (-len(eligible[seed]), seed)))
    niche = tuple(sorted(eligible, key=lambda seed: (len(eligible[seed]), seed)))
    if len(broad) < _SLICE_SEED_COUNT * 2:
        raise ValueError("not enough eligible seeds for fixed broad and niche slices")
    return frozenset(broad[:_SLICE_SEED_COUNT]), frozenset(niche[:_SLICE_SEED_COUNT])


def _subset(
    targets: Mapping[str, tuple[str, ...]], seeds: frozenset[str]
) -> dict[str, tuple[str, ...]]:
    return {seed: artists for seed, artists in targets.items() if seed in seeds}


def _endpoint_targets(
    heldout: Mapping[str, tuple[str, ...]], relations: Mapping[str, tuple[tuple[str, float], ...]]
) -> dict[str, tuple[str, ...]]:
    return {
        seed: tuple(artist for artist in artists if artist in relations)
        for seed, artists in heldout.items()
        if any(artist in relations for artist in artists)
    }


def _cohort(
    *,
    targets: Mapping[str, tuple[str, ...]],
    direct_scores: Mapping[str, dict[str, float]],
    cosine_scores: Mapping[str, dict[str, float]],
    hybrid_scores: Mapping[str, dict[str, float]],
) -> HybridCohortReport:
    """Evaluate source controls and their fixed fusion on one shared target cohort."""
    denominator = sum(len(artists) for artists in targets.values())
    if not denominator:
        raise ValueError("cohort has no held-out positives")
    direct = _outcome(targets=dict(targets), score_for_seed=lambda seed: direct_scores[seed])
    cosine = _outcome(targets=dict(targets), score_for_seed=lambda seed: cosine_scores[seed])
    hybrid = _outcome(targets=dict(targets), score_for_seed=lambda seed: hybrid_scores[seed])
    common = direct.supported & cosine.supported
    direct_only = direct.supported - cosine.supported
    cosine_only = cosine.supported - direct.supported
    novel = hybrid.recalled20_targets - (direct.recalled20_targets | cosine.recalled20_targets)
    return HybridCohortReport(
        heldout_positive_count=denominator,
        seed_count=len(targets),
        direct_idf_peer=_metric(direct, denominator),
        cosine_colisten=_metric(cosine, denominator),
        hybrid_rank_fusion=_metric(hybrid, denominator),
        direct_cosine_common_supported_target_count=len(common),
        union_supported_target_count=len(direct.supported | cosine.supported),
        direct_only_supported_target_count=len(direct_only),
        cosine_only_supported_target_count=len(cosine_only),
        hybrid_recalled_at_20_from_direct_only_support=len(hybrid.recalled20_targets & direct_only),
        hybrid_recalled_at_20_from_cosine_only_support=len(hybrid.recalled20_targets & cosine_only),
        hybrid_recalled_at_20_from_common_support=len(hybrid.recalled20_targets & common),
        hybrid_recalled_at_20_not_recalled_by_either_control=len(novel),
    )


def evaluate_sparse_genre_hybrid_transfer(
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    colisten_database: Path,
    colisten_receipt_path: Path,
) -> SparseGenreHybridTransferReport:
    """Run a fixed fold-zero local rank fusion with verified source boundaries."""
    direct_bytes = direct_receipt_path.read_bytes()
    direct = DirectCustodyPeerGraphReceipt.model_validate_json(direct_bytes)
    verify_direct_custody_peer_graph_receipt(direct, database=direct_database)
    colisten_bytes = colisten_receipt_path.read_bytes()
    colisten = load_colisten_overlay(colisten_receipt_path)
    certify_colisten_overlay_sources(CoListenOverlaySources(colisten_database, colisten))
    if (
        colisten.coverage.historical_input_used_for_construction
        or colisten.privacy.minimum_distinct_user_count != _MINIMUM_DISTINCT_USERS
    ):
        raise ValueError("co-listen receipt does not satisfy the fixed privacy/source boundary")
    with closing(sqlite3.connect(f"{direct_database.resolve().as_uri()}?mode=ro", uri=True)) as db:
        memberships = _read_memberships(db)
    train, heldout = _split_memberships(memberships)
    relations = _relations(colisten_database)
    if sum(len(neighbors) for neighbors in relations.values()) // 2 > _MAX_COLISTEN_RELATIONS:
        raise ValueError("co-listen relation count exceeds local evaluation bound")
    peer_rows, peer_pair_count = _all_idf_peer_rows(train)
    strengths = _strengths(relations)
    direct_scores = {
        seed: _direct_scores(seed=seed, train=train, peer_rows=peer_rows) for seed in heldout
    }
    cosine_scores = {
        seed: _scores(seed_id=seed, train=train, relations=relations, strengths=strengths)
        for seed in heldout
    }
    hybrid_scores = {
        seed: _fused_scores(direct_scores[seed], cosine_scores[seed]) for seed in heldout
    }
    matched = _endpoint_targets(heldout, relations)
    broad, niche = _seed_slices(memberships)
    placeholder = SparseGenreHybridTransferReport(
        direct_graph_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_graph_database_sha256=_sha256_file(direct_database),
        colisten_receipt_sha256=hashlib.sha256(colisten_bytes).hexdigest(),
        colisten_database_sha256=_sha256_file(colisten_database),
        train_candidate_peer_pair_count=peer_pair_count,
        full_heldout=_cohort(
            targets=heldout,
            direct_scores=direct_scores,
            cosine_scores=cosine_scores,
            hybrid_scores=hybrid_scores,
        ),
        endpoint_matched=_cohort(
            targets=matched,
            direct_scores=direct_scores,
            cosine_scores=cosine_scores,
            hybrid_scores=hybrid_scores,
        ),
        broad_seed_slice=_cohort(
            targets=_subset(matched, broad),
            direct_scores=direct_scores,
            cosine_scores=cosine_scores,
            hybrid_scores=hybrid_scores,
        ),
        niche_seed_slice=_cohort(
            targets=_subset(matched, niche),
            direct_scores=direct_scores,
            cosine_scores=cosine_scores,
            hybrid_scores=hybrid_scores,
        ),
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
