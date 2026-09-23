"""Local-only Last.fm pair retrieval on the fixed direct-custody fold."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.analysis.lastfm_360k import load_lastfm_360k_sealed_v1_envelope
from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)
from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_colisten_holdout import (
    _endpoint_targets,
    _global_outcome,
    _metric,
    _Outcome,
    _outcome,
    _scores_from_idf_peer,
    _sha256_file,
    _split_memberships,
)
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.direct_custody_membership_holdout import _build_peer_rows, _read_memberships
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_TOP_K = 20
_DIRECT_IDF_PEER_CAP = 10


class LastFmDirectCustodyMetric(FrozenModel):
    """One aggregate-only retrieval measurement."""

    denominator: int = Field(ge=0)
    supported_target_count: int = Field(ge=0)
    recalled_at_20: int = Field(ge=0)
    recall_at_20: float = Field(ge=0, le=1)


class LastFmDirectCustodyControlCohort(FrozenModel):
    """Same-target local controls for one endpoint-conditioned cohort."""

    target_count: int = Field(ge=0)
    lastfm_pair_transfer: LastFmDirectCustodyMetric
    direct_train_artist_popularity: LastFmDirectCustodyMetric
    direct_idf_peer: LastFmDirectCustodyMetric
    lastfm_graph_weighted_degree: LastFmDirectCustodyMetric


class SeparateSignalTopTwentyOverlap(FrozenModel):
    """Top-twenty hit overlap from separately ranked Last.fm and ListenBrainz arms."""

    target_count: int = Field(ge=0)
    both: int = Field(ge=0)
    lastfm_only: int = Field(ge=0)
    listenbrainz_only: int = Field(ge=0)
    neither: int = Field(ge=0)

    @model_validator(mode="after")
    def _verify_partition(self) -> SeparateSignalTopTwentyOverlap:
        if (
            self.both + self.lastfm_only + self.listenbrainz_only + self.neither
            != self.target_count
        ):
            raise ValueError("separate-signal hit overlap does not partition its target cohort")
        return self


class LastFmDirectCustodyHoldout(FrozenModel):
    """Pinned local Last.fm evaluation with no membership or genre output."""

    revision: Literal["lastfm-direct-custody-holdout-v2"] = "lastfm-direct-custody-holdout-v2"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    genre_claim_made: Literal[False] = False
    historical_inputs_used: Literal[False] = False
    lastfm_artifact_sha256: Sha256
    lastfm_companion_receipt_sha256: Sha256
    lastfm_database_sha256: Sha256
    direct_receipt_sha256: Sha256
    direct_database_sha256: Sha256
    privacy_pair_floor: int = Field(ge=5)
    ranking_top_k: Literal[20] = _TOP_K
    direct_idf_peer_candidate_cap: Literal[10] = _DIRECT_IDF_PEER_CAP
    direct_controls_use_fixed_fold_train_only: Literal[True] = True
    known_train_artists_excluded_from_every_ranking: Literal[True] = True
    lastfm_graph_control_uses_direct_custody_memberships: Literal[False] = False
    lastfm_graph_weighted_degree_rule: Literal["sum_log1p_distinct_user_count_per_endpoint"] = (
        "sum_log1p_distinct_user_count_per_endpoint"
    )
    full: LastFmDirectCustodyMetric
    endpoint_matched: LastFmDirectCustodyMetric
    common_endpoint_lastfm: LastFmDirectCustodyMetric | None = None
    common_endpoint_listenbrainz: LastFmDirectCustodyMetric | None = None
    lastfm_endpoint_controls: LastFmDirectCustodyControlCohort
    common_endpoint_controls: LastFmDirectCustodyControlCohort | None = None
    common_endpoint_top_twenty_overlap: SeparateSignalTopTwentyOverlap | None = None
    output_sha256: Sha256

    @model_validator(mode="after")
    def _verify_hash(self) -> LastFmDirectCustodyHoldout:
        payload = self.model_dump(mode="json", exclude={"output_sha256"})
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.output_sha256 != expected:
            raise ValueError("Last.fm holdout output hash does not replay")
        return self


def evaluate_lastfm_direct_custody_holdout(  # noqa: PLR0913
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    lastfm_artifact_path: Path,
    lastfm_companion_receipt_path: Path,
    lastfm_database_path: Path,
    listenbrainz_database_path: Path | None = None,
    listenbrainz_receipt_path: Path | None = None,
) -> LastFmDirectCustodyHoldout:
    """Evaluate a fixed direct-custody fold using only retained Last.fm pairs."""
    direct_bytes = direct_receipt_path.read_bytes()
    direct = DirectCustodyPeerGraphReceipt.model_validate_json(direct_bytes)
    verify_direct_custody_peer_graph_receipt(direct, database=direct_database)
    envelope = load_lastfm_360k_sealed_v1_envelope(
        artifact_path=lastfm_artifact_path,
        companion_receipt_path=lastfm_companion_receipt_path,
        database_path=lastfm_database_path,
    )
    with closing(sqlite3.connect(f"{direct_database.resolve().as_uri()}?mode=ro", uri=True)) as db:
        memberships = _read_memberships(db)
    train, heldout = _split_memberships(memberships)
    idf_peer_rows, _ignored_count_rows, _ignored_candidate_count = _build_peer_rows(train)
    relations = _relations(lastfm_database_path)
    lastfm_weighted_degree = _weighted_degree(relations)
    full = _evaluate(heldout, train, relations)
    matched_targets = _endpoint_targets(heldout, relations)
    matched = _evaluate(matched_targets, train, relations)
    matched_controls = _control_cohort(
        matched_targets, train, relations, idf_peer_rows, lastfm_weighted_degree
    )
    common_lastfm = common_listenbrainz = None
    common_controls = None
    common_overlap = None
    if listenbrainz_database_path is not None and listenbrainz_receipt_path is not None:
        overlay = load_colisten_overlay(listenbrainz_receipt_path)
        certify_colisten_overlay_sources(
            CoListenOverlaySources(listenbrainz_database_path, overlay)
        )
        listenbrainz_relations = _listenbrainz_relations(listenbrainz_database_path)
        common_targets = _endpoint_targets(
            _endpoint_targets(heldout, relations), listenbrainz_relations
        )
        common_lastfm_outcome = _outcome(
            targets=common_targets,
            score_for_seed=lambda seed: _scores_from_relations(seed, train, relations),
        )
        common_listenbrainz_outcome = _outcome(
            targets=common_targets,
            score_for_seed=lambda seed: _scores_from_relations(seed, train, listenbrainz_relations),
        )
        common_denominator = sum(map(len, common_targets.values()))
        common_lastfm = _as_metric(common_lastfm_outcome, common_denominator)
        common_listenbrainz = _as_metric(common_listenbrainz_outcome, common_denominator)
        common_controls = _control_cohort(
            common_targets, train, relations, idf_peer_rows, lastfm_weighted_degree
        )
        common_overlap = _top_twenty_overlap(
            target_count=common_denominator,
            lastfm_hits=common_lastfm_outcome.recalled20_targets,
            listenbrainz_hits=common_listenbrainz_outcome.recalled20_targets,
        )
    placeholder = LastFmDirectCustodyHoldout.model_construct(
        lastfm_artifact_sha256=envelope.original_artifact_sha256,
        lastfm_companion_receipt_sha256=_sha256_file(lastfm_companion_receipt_path),
        lastfm_database_sha256=_sha256_file(lastfm_database_path),
        direct_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_database_sha256=_sha256_file(direct_database),
        privacy_pair_floor=envelope.companion_receipt.working_database_pair_floor,
        full=full,
        endpoint_matched=matched,
        common_endpoint_lastfm=common_lastfm,
        common_endpoint_listenbrainz=common_listenbrainz,
        lastfm_endpoint_controls=matched_controls,
        common_endpoint_controls=common_controls,
        common_endpoint_top_twenty_overlap=common_overlap,
        output_sha256="0" * 64,
    )
    payload = placeholder.model_dump(mode="json")
    payload["output_sha256"] = hashlib.sha256(
        json.dumps(
            placeholder.model_dump(mode="json", exclude={"output_sha256"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return LastFmDirectCustodyHoldout.model_validate(payload)


def _relations(path: Path) -> dict[str, tuple[tuple[str, int], ...]]:
    result: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        for left, right, users in db.execute(
            "SELECT left_artist, right_artist, distinct_user_count FROM pair_support"
        ):
            result[str(left)].append((str(right), int(users)))
            result[str(right)].append((str(left), int(users)))
    return {artist: tuple(neighbors) for artist, neighbors in result.items()}


def _listenbrainz_relations(path: Path) -> dict[str, tuple[tuple[str, int], ...]]:
    result: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        for left, right, users in db.execute(
            "SELECT left_artist_mbid, right_artist_mbid, distinct_user_count FROM colisten_relation"
        ):
            result[str(left)].append((str(right), int(users)))
            result[str(right)].append((str(left), int(users)))
    return {artist: tuple(neighbors) for artist, neighbors in result.items()}


def _evaluate(
    targets: dict[str, tuple[str, ...]],
    train: dict[str, tuple[str, ...]],
    relations: dict[str, tuple[tuple[str, int], ...]],
) -> LastFmDirectCustodyMetric:
    denominator = sum(map(len, targets.values()))
    if not denominator:
        return LastFmDirectCustodyMetric(
            denominator=0, supported_target_count=0, recalled_at_20=0, recall_at_20=0
        )

    outcome = _outcome(
        targets=targets,
        score_for_seed=lambda seed: _scores_from_relations(seed, train, relations),
    )
    metric = _metric(outcome, denominator)
    return LastFmDirectCustodyMetric(
        denominator=denominator,
        supported_target_count=metric.supported_target_count,
        recalled_at_20=metric.recalled_at_20,
        recall_at_20=metric.micro_recall_at_20,
    )


def _scores_from_relations(
    seed: str,
    train: dict[str, tuple[str, ...]],
    relations: dict[str, tuple[tuple[str, int], ...]],
) -> dict[str, float]:
    """Score one seed from an aggregate relation source and exclude its train artists."""
    known = frozenset(train[seed])
    scores: dict[str, float] = defaultdict(float)
    for artist in known:
        for candidate, support in relations.get(artist, ()):
            if candidate not in known:
                scores[candidate] += math.log1p(support)
    return scores


def _control_cohort(
    targets: dict[str, tuple[str, ...]],
    train: dict[str, tuple[str, ...]],
    relations: dict[str, tuple[tuple[str, int], ...]],
    idf_peer_rows: dict[str, tuple[tuple[str, int, float], ...]],
    lastfm_weighted_degree: dict[str, float],
) -> LastFmDirectCustodyControlCohort:
    """Evaluate Last.fm and fixed-fold controls on exactly the supplied targets."""
    target_count = sum(map(len, targets.values()))
    lastfm = _evaluate(targets, train, relations)
    idf_outcome = _outcome(
        targets=targets,
        score_for_seed=lambda seed: _scores_from_idf_peer(seed, train, idf_peer_rows),
    )
    popularity_outcome = _global_outcome(targets, train)
    graph_popularity_outcome = _outcome(
        targets=targets,
        score_for_seed=lambda seed: _scores_from_weighted_degree(
            seed, train, lastfm_weighted_degree
        ),
    )
    return LastFmDirectCustodyControlCohort(
        target_count=target_count,
        lastfm_pair_transfer=lastfm,
        direct_train_artist_popularity=_as_metric(popularity_outcome, target_count),
        direct_idf_peer=_as_metric(idf_outcome, target_count),
        lastfm_graph_weighted_degree=_as_metric(graph_popularity_outcome, target_count),
    )


def _as_metric(outcome: _Outcome, denominator: int) -> LastFmDirectCustodyMetric:
    """Convert the established retrieval outcome without widening this report's schema."""
    metric = _metric(outcome, denominator)
    return LastFmDirectCustodyMetric(
        denominator=denominator,
        supported_target_count=metric.supported_target_count,
        recalled_at_20=metric.recalled_at_20,
        recall_at_20=metric.micro_recall_at_20,
    )


def _top_twenty_overlap(
    *,
    target_count: int,
    lastfm_hits: frozenset[tuple[str, str]],
    listenbrainz_hits: frozenset[tuple[str, str]],
) -> SeparateSignalTopTwentyOverlap:
    """Report separate ranker hit overlap without combining their scores or relations."""
    both = lastfm_hits & listenbrainz_hits
    return SeparateSignalTopTwentyOverlap(
        target_count=target_count,
        both=len(both),
        lastfm_only=len(lastfm_hits - both),
        listenbrainz_only=len(listenbrainz_hits - both),
        neither=target_count - len(lastfm_hits | listenbrainz_hits),
    )


def _weighted_degree(
    relations: dict[str, tuple[tuple[str, int], ...]],
) -> dict[str, float]:
    """Sum retained Last.fm pair support by endpoint without reading custody targets."""
    return {
        artist: math.fsum(math.log1p(support) for _neighbor, support in neighbors)
        for artist, neighbors in relations.items()
    }


def _scores_from_weighted_degree(
    seed: str,
    train: dict[str, tuple[str, ...]],
    weighted_degree: dict[str, float],
) -> dict[str, float]:
    """Rank aggregate endpoints by graph-only weighted degree, excluding seed training artists."""
    known = frozenset(train[seed])
    return {artist: score for artist, score in weighted_degree.items() if artist not in known}
