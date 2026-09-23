"""Local-only fixed rank fusion on the Last.fm and ListenBrainz common cohort."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.analysis.lastfm_360k import load_lastfm_360k_sealed_v1_envelope
from opennoise.analysis.lastfm_direct_custody_holdout import (
    _listenbrainz_relations,
    _relations,
    _scores_from_relations,
)
from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)
from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_colisten_holdout import (
    _endpoint_targets,
    _sha256_file,
    _split_memberships,
    _top_twenty,
)
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.direct_custody_membership_holdout import _read_memberships
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_TOP_K: Final = 20
_MAX_COMBINED_CANDIDATES: Final = _TOP_K * 2
_REVISION: Final = "lastfm-listenbrainz-rank-fusion-holdout-v1"


class RankFusionMetric(FrozenModel):
    """Positive-only recovery count for one fixed candidate list."""

    recalled_target_count: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)


class LastFmListenBrainzRankFusionHoldout(FrozenModel):
    """Receipt-bound local rank fusion that never merges source relations."""

    revision: Literal["lastfm-listenbrainz-rank-fusion-holdout-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    membership_output_written: Literal[False] = False
    genre_claim_made: Literal[False] = False
    source_graph_edges_merged: Literal[False] = False
    direct_custody_train_only: Literal[True] = True
    known_train_artists_excluded_from_every_ranking: Literal[True] = True
    source_top_k: Literal[20] = _TOP_K
    final_top_k: Literal[20] = _TOP_K
    maximum_combined_candidate_count: Literal[40] = _MAX_COMBINED_CANDIDATES
    fusion_rule: Literal["sum_reciprocal_source_rank"] = "sum_reciprocal_source_rank"
    direct_receipt_sha256: Sha256
    direct_database_sha256: Sha256
    lastfm_artifact_sha256: Sha256
    lastfm_companion_receipt_sha256: Sha256
    lastfm_database_sha256: Sha256
    listenbrainz_receipt_sha256: Sha256
    listenbrainz_database_sha256: Sha256
    common_endpoint_target_count: int = Field(ge=0)
    lastfm_top_twenty: RankFusionMetric
    listenbrainz_top_twenty: RankFusionMetric
    reciprocal_rank_fusion_top_twenty: RankFusionMetric
    candidate_union_upper_bound_at_forty: RankFusionMetric
    output_sha256: Sha256

    @model_validator(mode="after")
    def _verify_hash(self) -> LastFmListenBrainzRankFusionHoldout:
        expected = hashlib.sha256(
            _canonical(self.model_dump(mode="json", exclude={"output_sha256"}))
        ).hexdigest()
        if self.output_sha256 != expected:
            raise ValueError("rank fusion output hash does not replay")
        return self


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _metric(recalled_target_count: int, denominator: int) -> RankFusionMetric:
    return RankFusionMetric(
        recalled_target_count=recalled_target_count,
        recall=recalled_target_count / denominator if denominator else 0.0,
    )


def _finalize(
    placeholder: LastFmListenBrainzRankFusionHoldout,
) -> LastFmListenBrainzRankFusionHoldout:
    """Hash an unchecked construction placeholder before validating its receipt."""
    payload = placeholder.model_dump(mode="json")
    payload["output_sha256"] = hashlib.sha256(
        _canonical(placeholder.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()
    return LastFmListenBrainzRankFusionHoldout.model_validate(payload)


def _fused_ranks(
    lastfm_ranks: dict[str, int], listenbrainz_ranks: dict[str, int]
) -> dict[str, int]:
    """Fuse two pre-capped rank lists without inspecting targets or source edges."""
    scores: dict[str, float] = {}
    for artist, rank in lastfm_ranks.items():
        scores[artist] = scores.get(artist, 0.0) + 1 / rank
    for artist, rank in listenbrainz_ranks.items():
        scores[artist] = scores.get(artist, 0.0) + 1 / rank
    return _top_twenty(scores)


def _recalled(
    targets: dict[str, tuple[str, ...]],
    ranks_for_seed: dict[str, dict[str, int]],
) -> int:
    return sum(
        artist in ranks_for_seed[seed] for seed, artists in targets.items() for artist in artists
    )


def _union_recalled(
    targets: dict[str, tuple[str, ...]],
    lastfm_ranks: dict[str, dict[str, int]],
    listenbrainz_ranks: dict[str, dict[str, int]],
) -> int:
    return sum(
        artist in lastfm_ranks[seed] or artist in listenbrainz_ranks[seed]
        for seed, artists in targets.items()
        for artist in artists
    )


def evaluate_lastfm_listenbrainz_rank_fusion_holdout(  # noqa: PLR0913
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    lastfm_artifact_path: Path,
    lastfm_companion_receipt_path: Path,
    lastfm_database_path: Path,
    listenbrainz_database_path: Path,
    listenbrainz_receipt_path: Path,
) -> LastFmListenBrainzRankFusionHoldout:
    """Evaluate one fixed reciprocal-rank rule on the shared endpoint cohort."""
    direct_bytes = direct_receipt_path.read_bytes()
    direct = DirectCustodyPeerGraphReceipt.model_validate_json(direct_bytes)
    verify_direct_custody_peer_graph_receipt(direct, database=direct_database)
    envelope = load_lastfm_360k_sealed_v1_envelope(
        artifact_path=lastfm_artifact_path,
        companion_receipt_path=lastfm_companion_receipt_path,
        database_path=lastfm_database_path,
    )
    listenbrainz_bytes = listenbrainz_receipt_path.read_bytes()
    overlay = load_colisten_overlay(listenbrainz_receipt_path)
    certify_colisten_overlay_sources(CoListenOverlaySources(listenbrainz_database_path, overlay))
    with closing(sqlite3.connect(f"{direct_database.resolve().as_uri()}?mode=ro", uri=True)) as db:
        memberships = _read_memberships(db)
    train, heldout = _split_memberships(memberships)
    lastfm_relations = _relations(lastfm_database_path)
    listenbrainz_relations = _listenbrainz_relations(listenbrainz_database_path)
    common_targets = _endpoint_targets(
        _endpoint_targets(heldout, lastfm_relations), listenbrainz_relations
    )
    denominator = sum(map(len, common_targets.values()))
    if not denominator:
        raise ValueError("no held-out positive is a common Last.fm and ListenBrainz endpoint")
    lastfm_ranks = {
        seed: _top_twenty(_scores_from_relations(seed, train, lastfm_relations))
        for seed in common_targets
    }
    listenbrainz_ranks = {
        seed: _top_twenty(_scores_from_relations(seed, train, listenbrainz_relations))
        for seed in common_targets
    }
    fused_ranks = {
        seed: _fused_ranks(lastfm_ranks[seed], listenbrainz_ranks[seed]) for seed in common_targets
    }
    placeholder = LastFmListenBrainzRankFusionHoldout.model_construct(
        direct_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_database_sha256=_sha256_file(direct_database),
        lastfm_artifact_sha256=envelope.original_artifact_sha256,
        lastfm_companion_receipt_sha256=_sha256_file(lastfm_companion_receipt_path),
        lastfm_database_sha256=_sha256_file(lastfm_database_path),
        listenbrainz_receipt_sha256=hashlib.sha256(listenbrainz_bytes).hexdigest(),
        listenbrainz_database_sha256=_sha256_file(listenbrainz_database_path),
        common_endpoint_target_count=denominator,
        lastfm_top_twenty=_metric(_recalled(common_targets, lastfm_ranks), denominator),
        listenbrainz_top_twenty=_metric(_recalled(common_targets, listenbrainz_ranks), denominator),
        reciprocal_rank_fusion_top_twenty=_metric(
            _recalled(common_targets, fused_ranks), denominator
        ),
        candidate_union_upper_bound_at_forty=_metric(
            _union_recalled(common_targets, lastfm_ranks, listenbrainz_ranks), denominator
        ),
        output_sha256="0" * 64,
    )
    return _finalize(placeholder)
