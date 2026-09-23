"""Capacity-controlled direct-custody co-listen retrieval evaluation."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
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
from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_colisten_holdout import (
    RetrievalMetric,
    _endpoint_targets,
    _global_outcome,
    _metric,
    _Outcome,
    _outcome,
    _relations,
    _scores_from_colisten,
    _scores_from_idf_peer,
)
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.direct_custody_membership_holdout import (
    _build_peer_rows,
    _read_memberships,
    _split_memberships,
)
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_MIN_SHARED: Final = 2
_COLISTEN_NEIGHBOR_CAP: Final = 10
_MINIMUM_DISTINCT_USERS: Final = 5
_MAX_COLISTEN_RELATIONS: Final = 50_000
_REVISION: Final = "direct-custody-colisten-capacity-holdout-v1"


class CapacityArm(FrozenModel):
    """One fixed retrieval arm, reported for all and split-cold target strata."""

    all_matched_targets: RetrievalMetric
    artist_seen_elsewhere_in_train: RetrievalMetric | None
    artist_cold: RetrievalMetric | None


class CapacityHoldoutReport(FrozenModel):
    """Source-bound local comparison that does not modify any candidate artifact."""

    revision: Literal["direct-custody-colisten-capacity-holdout-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    direct_graph_receipt_sha256: Sha256
    direct_graph_database_sha256: Sha256
    colisten_receipt_sha256: Sha256
    colisten_database_sha256: Sha256
    direct_peer_expansion: Literal["all_train_candidate_peers"] = "all_train_candidate_peers"
    colisten_relation_cap_per_train_artist: Literal[10] = _COLISTEN_NEIGHBOR_CAP
    known_train_artists_excluded_from_every_ranking: Literal[True] = True
    matched_heldout_positive_count: int = Field(ge=0)
    artist_seen_elsewhere_in_train_target_count: int = Field(ge=0)
    artist_cold_target_count: int = Field(ge=0)
    train_candidate_peer_pair_count: int = Field(ge=0)
    colisten_all_relations: CapacityArm
    colisten_capped_relations: CapacityArm
    idf_peer_top_ten: CapacityArm
    idf_peer_all_candidates: CapacityArm
    global_artist_degree: CapacityArm
    common_support_colisten_all_and_peer_all_count: int = Field(ge=0)
    colisten_all_common_recalled_at_20: int = Field(ge=0)
    peer_all_common_recalled_at_20: int = Field(ge=0)
    historical_inputs_used: Literal[False] = False
    h3_inputs_used: Literal[False] = False
    tags_or_lastfm_used: Literal[False] = False
    release_rows_used: Literal[False] = False
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


def _hash(report: CapacityHoldoutReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _all_idf_peer_rows(
    train: dict[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[tuple[str, int, float], ...]], int]:
    """Rebuild every train-only candidate peer without the top-ten truncation."""
    artist_seeds: dict[str, list[str]] = defaultdict(list)
    for seed, artists in train.items():
        for artist in artists:
            artist_seeds[artist].append(seed)
    total: dict[str, float] = defaultdict(float)
    shared: dict[tuple[str, str], float] = defaultdict(float)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for seeds in artist_seeds.values():
        weight = 1 + math.log((len(train) + 1) / (len(seeds) + 1))
        for seed in seeds:
            total[seed] += weight
        for pair in itertools.combinations(seeds, 2):
            counts[pair] += 1
            shared[pair] += weight
    rows: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    candidate_count = 0
    for (left, right), count in counts.items():
        if count < _MIN_SHARED:
            continue
        candidate_count += 1
        score = shared[left, right] / (total[left] + total[right] - shared[left, right])
        rows[left].append((right, count, score))
        rows[right].append((left, count, score))
    return (
        {
            seed: tuple(sorted(values, key=lambda row: (-row[2], -row[1], row[0])))
            for seed, values in rows.items()
        },
        candidate_count,
    )


def _capped_relations(
    relations: dict[str, tuple[tuple[str, int], ...]],
) -> dict[str, tuple[tuple[str, int], ...]]:
    """Keep a predeclared ten strongest aggregate neighbors per source artist."""
    return {
        artist: tuple(sorted(rows, key=lambda row: (-row[1], row[0]))[:_COLISTEN_NEIGHBOR_CAP])
        for artist, rows in relations.items()
    }


def _arm(
    *,
    targets: dict[str, tuple[str, ...]],
    seen: dict[str, tuple[str, ...]],
    cold: dict[str, tuple[str, ...]],
    score_for_seed: Callable[[str], dict[str, float]],
    denominator: int,
) -> tuple[CapacityArm, _Outcome]:
    """Evaluate one callable arm over all, artist-seen, and artist-cold positives."""
    all_outcome = _outcome(targets=targets, score_for_seed=score_for_seed)
    seen_count = sum(len(artists) for artists in seen.values())
    cold_count = sum(len(artists) for artists in cold.values())
    arm = CapacityArm(
        all_matched_targets=_metric(all_outcome, denominator),
        artist_seen_elsewhere_in_train=(
            _metric(_outcome(targets=seen, score_for_seed=score_for_seed), seen_count)
            if seen_count
            else None
        ),
        artist_cold=(
            _metric(_outcome(targets=cold, score_for_seed=score_for_seed), cold_count)
            if cold_count
            else None
        ),
    )
    return arm, all_outcome


def evaluate_direct_custody_colisten_capacity_holdout(
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    colisten_database: Path,
    colisten_receipt_path: Path,
) -> CapacityHoldoutReport:
    """Run the predeclared capacity comparison over verified local-only inputs."""
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
        raise ValueError("co-listen receipt admits historical construction input")
    with closing(sqlite3.connect(f"{direct_database.resolve().as_uri()}?mode=ro", uri=True)) as db:
        memberships = _read_memberships(db)
    train, heldout = _split_memberships(memberships)
    relations = _relations(colisten_database)
    if sum(len(neighbors) for neighbors in relations.values()) // 2 > _MAX_COLISTEN_RELATIONS:
        raise ValueError("co-listen relation count exceeds local evaluation bound")
    targets = _endpoint_targets(heldout, relations)
    denominator = sum(len(values) for values in targets.values())
    if not denominator:
        raise ValueError("no held-out positive is a co-listen endpoint")
    train_artists = frozenset(artist for values in train.values() for artist in values)
    seen = {
        seed: tuple(artist for artist in values if artist in train_artists)
        for seed, values in targets.items()
    }
    cold = {
        seed: tuple(artist for artist in values if artist not in train_artists)
        for seed, values in targets.items()
    }
    seen = {seed: values for seed, values in seen.items() if values}
    cold = {seed: values for seed, values in cold.items() if values}
    peer_top_ten, _ignored, _candidate_count = _build_peer_rows(train)
    peer_all, candidate_count = _all_idf_peer_rows(train)
    co_all, co_outcome = _arm(
        targets=targets,
        seen=seen,
        cold=cold,
        score_for_seed=lambda seed: _scores_from_colisten(seed, train, relations),
        denominator=denominator,
    )
    capped_relations = _capped_relations(relations)
    co_capped, _ = _arm(
        targets=targets,
        seen=seen,
        cold=cold,
        score_for_seed=lambda seed: _scores_from_colisten(seed, train, capped_relations),
        denominator=denominator,
    )
    peer_ten, _ = _arm(
        targets=targets,
        seen=seen,
        cold=cold,
        score_for_seed=lambda seed: _scores_from_idf_peer(seed, train, peer_top_ten),
        denominator=denominator,
    )
    peer_full, peer_outcome = _arm(
        targets=targets,
        seen=seen,
        cold=cold,
        score_for_seed=lambda seed: _scores_from_idf_peer(seed, train, peer_all),
        denominator=denominator,
    )
    global_outcome = _global_outcome(targets, train)
    global_arm = CapacityArm(
        all_matched_targets=_metric(global_outcome, denominator),
        artist_seen_elsewhere_in_train=(
            _metric(_global_outcome(seen, train), sum(map(len, seen.values()))) if seen else None
        ),
        artist_cold=(
            _metric(_global_outcome(cold, train), sum(map(len, cold.values()))) if cold else None
        ),
    )
    common = co_outcome.supported & peer_outcome.supported
    placeholder = CapacityHoldoutReport(
        direct_graph_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_graph_database_sha256=_sha256_file(direct_database),
        colisten_receipt_sha256=hashlib.sha256(colisten_bytes).hexdigest(),
        colisten_database_sha256=_sha256_file(colisten_database),
        matched_heldout_positive_count=denominator,
        artist_seen_elsewhere_in_train_target_count=sum(map(len, seen.values())),
        artist_cold_target_count=sum(map(len, cold.values())),
        train_candidate_peer_pair_count=candidate_count,
        colisten_all_relations=co_all,
        colisten_capped_relations=co_capped,
        idf_peer_top_ten=peer_ten,
        idf_peer_all_candidates=peer_full,
        global_artist_degree=global_arm,
        common_support_colisten_all_and_peer_all_count=len(common),
        colisten_all_common_recalled_at_20=len(co_outcome.recalled20_targets & common),
        peer_all_common_recalled_at_20=len(peer_outcome.recalled20_targets & common),
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _hash(placeholder)})
