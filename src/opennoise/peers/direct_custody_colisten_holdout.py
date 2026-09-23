"""Compare train-only co-listen and direct peer retrieval on custody positives."""

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

from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)
from opennoise.models import FrozenModel
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

_TOP_K: Final = 10
_RECALL_K: Final = 20
_MINIMUM_DISTINCT_USERS: Final = 5
_MAX_COLISTEN_RELATIONS: Final = 50_000
_REVISION: Final = "direct-custody-colisten-holdout-v1"


@dataclass(frozen=True, slots=True)
class _Outcome:
    recalled10: int
    recalled20: int
    reciprocal_sum: float
    supported: frozenset[tuple[str, str]]
    recalled20_targets: frozenset[tuple[str, str]]
    macro10: float
    macro20: float


class RetrievalMetric(FrozenModel):
    """One retrieval arm on the shared co-listen-endpoint positive cohort."""

    recalled_at_10: int = Field(ge=0)
    recalled_at_20: int = Field(ge=0)
    micro_recall_at_10: float = Field(ge=0.0, le=1.0)
    micro_recall_at_20: float = Field(ge=0.0, le=1.0)
    macro_recall_at_10: float = Field(ge=0.0, le=1.0)
    macro_recall_at_20: float = Field(ge=0.0, le=1.0)
    mrr_at_20: float = Field(ge=0.0, le=1.0)
    supported_target_count: int = Field(ge=0)
    target_support_rate: float = Field(ge=0.0, le=1.0)


class DirectCustodyCoListenHoldout(FrozenModel):
    """Local-only matched retrieval comparison with all positives held out first."""

    revision: Literal["direct-custody-colisten-holdout-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    direct_graph_receipt_sha256: Sha256
    direct_graph_database_sha256: Sha256
    colisten_receipt_sha256: Sha256
    colisten_database_sha256: Sha256
    split_rule: Literal["sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"] = (
        "sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"
    )
    known_train_artists_excluded_from_every_ranking: Literal[True] = True
    custody_seed_count: int = Field(ge=0)
    split_eligible_seed_count: int = Field(ge=0)
    colisten_endpoint_artist_count: int = Field(ge=0)
    matched_heldout_positive_count: int = Field(ge=0)
    matched_seed_count: int = Field(ge=0)
    artist_seen_elsewhere_in_train_target_count: int = Field(ge=0)
    artist_cold_target_count: int = Field(ge=0)
    colisten_transfer: RetrievalMetric
    idf_peer: RetrievalMetric
    global_artist_degree: RetrievalMetric
    common_supported_target_count: int = Field(ge=0)
    colisten_common_recalled_at_20: int = Field(ge=0)
    idf_common_recalled_at_20: int = Field(ge=0)
    global_common_recalled_at_20: int = Field(ge=0)
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


def _report_hash(report: DirectCustodyCoListenHoldout) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _relations(database: Path) -> dict[str, tuple[tuple[str, int], ...]]:
    rows: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for left, right, users in connection.execute(
            "SELECT left_artist_mbid, right_artist_mbid, distinct_user_count FROM colisten_relation"
        ):
            left_text, right_text, count = str(left), str(right), int(users)
            rows[left_text].append((right_text, count))
            rows[right_text].append((left_text, count))
    return {artist: tuple(neighbors) for artist, neighbors in rows.items()}


def _endpoint_targets(
    heldout: dict[str, tuple[str, ...]], relations: dict[str, tuple[tuple[str, int], ...]]
) -> dict[str, tuple[str, ...]]:
    """Keep only held-out positives whose artist identity is an admitted endpoint."""
    matched = {
        seed: tuple(artist for artist in artists if artist in relations)
        for seed, artists in heldout.items()
    }
    return {seed: artists for seed, artists in matched.items() if artists}


def _scores_from_colisten(
    seed_id: str,
    train: dict[str, tuple[str, ...]],
    relations: dict[str, tuple[tuple[str, int], ...]],
) -> dict[str, float]:
    known = frozenset(train[seed_id])
    scores: dict[str, float] = defaultdict(float)
    for source in known:
        for candidate, users in relations.get(source, ()):
            if candidate not in known:
                scores[candidate] += math.log1p(users)
    return scores


def _scores_from_idf_peer(
    seed_id: str,
    train: dict[str, tuple[str, ...]],
    peer_rows: dict[str, tuple[tuple[str, int, float], ...]],
) -> dict[str, float]:
    known = frozenset(train[seed_id])
    scores: dict[str, float] = defaultdict(float)
    for peer, _count, score in peer_rows.get(seed_id, ()):
        for candidate in train[peer]:
            if candidate not in known:
                scores[candidate] += score
    return scores


def _top_twenty(scores: dict[str, float]) -> dict[str, int]:
    return {
        artist: rank
        for rank, (artist, _score) in enumerate(
            heapq.nsmallest(_RECALL_K, scores.items(), key=lambda row: (-row[1], row[0])), start=1
        )
    }


def _outcome(
    *,
    targets: dict[str, tuple[str, ...]],
    score_for_seed: Callable[[str], dict[str, float]],
) -> _Outcome:
    supported: set[tuple[str, str]] = set()
    hits20: set[tuple[str, str]] = set()
    hits10 = hits20_count = 0
    reciprocal = 0.0
    macro10: list[float] = []
    macro20: list[float] = []
    for seed, artists in targets.items():
        scores = score_for_seed(seed)
        ranks = _top_twenty(scores)
        seed10 = seed20 = 0
        for artist in artists:
            pair = (seed, artist)
            if artist in scores:
                supported.add(pair)
            rank = ranks.get(artist)
            if rank is not None:
                hits20.add(pair)
                hits20_count += 1
                seed20 += 1
                reciprocal += 1 / rank
                if rank <= _TOP_K:
                    hits10 += 1
                    seed10 += 1
        macro10.append(seed10 / len(artists))
        macro20.append(seed20 / len(artists))
    return _Outcome(
        recalled10=hits10,
        recalled20=hits20_count,
        reciprocal_sum=reciprocal,
        supported=frozenset(supported),
        recalled20_targets=frozenset(hits20),
        macro10=math.fsum(macro10) / len(macro10),
        macro20=math.fsum(macro20) / len(macro20),
    )


def _global_outcome(
    targets: dict[str, tuple[str, ...]], train: dict[str, tuple[str, ...]]
) -> _Outcome:
    degree: dict[str, int] = defaultdict(int)
    for artists in train.values():
        for artist in artists:
            degree[artist] += 1
    ordered = tuple(sorted(degree, key=lambda artist: (-degree[artist], artist)))
    supported: set[tuple[str, str]] = set()
    hits20: set[tuple[str, str]] = set()
    hits10 = hits20_count = 0
    reciprocal = 0.0
    macro10: list[float] = []
    macro20: list[float] = []
    for seed, artists in targets.items():
        known = frozenset(train[seed])
        ranks = {
            artist: rank
            for rank, artist in enumerate(
                itertools.islice((artist for artist in ordered if artist not in known), _RECALL_K),
                start=1,
            )
        }
        seed10 = seed20 = 0
        for artist in artists:
            pair = (seed, artist)
            if artist in degree:
                supported.add(pair)
            rank = ranks.get(artist)
            if rank is not None:
                hits20.add(pair)
                hits20_count += 1
                seed20 += 1
                reciprocal += 1 / rank
                if rank <= _TOP_K:
                    hits10 += 1
                    seed10 += 1
        macro10.append(seed10 / len(artists))
        macro20.append(seed20 / len(artists))
    return _Outcome(
        recalled10=hits10,
        recalled20=hits20_count,
        reciprocal_sum=reciprocal,
        supported=frozenset(supported),
        recalled20_targets=frozenset(hits20),
        macro10=math.fsum(macro10) / len(macro10),
        macro20=math.fsum(macro20) / len(macro20),
    )


def _metric(outcome: _Outcome, denominator: int) -> RetrievalMetric:
    return RetrievalMetric(
        recalled_at_10=outcome.recalled10,
        recalled_at_20=outcome.recalled20,
        micro_recall_at_10=outcome.recalled10 / denominator,
        micro_recall_at_20=outcome.recalled20 / denominator,
        macro_recall_at_10=outcome.macro10,
        macro_recall_at_20=outcome.macro20,
        mrr_at_20=outcome.reciprocal_sum / denominator,
        supported_target_count=len(outcome.supported),
        target_support_rate=len(outcome.supported) / denominator,
    )


def evaluate_direct_custody_colisten_holdout(
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    colisten_database: Path,
    colisten_receipt_path: Path,
) -> DirectCustodyCoListenHoldout:
    """Evaluate only exact direct-custody positives with co-listen endpoint identities."""
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
    with closing(
        sqlite3.connect(f"{direct_database.resolve().as_uri()}?mode=ro", uri=True)
    ) as connection:
        memberships = _read_memberships(connection)
    train, heldout = _split_memberships(memberships)
    relations = _relations(colisten_database)
    if sum(len(neighbors) for neighbors in relations.values()) // 2 > _MAX_COLISTEN_RELATIONS:
        raise ValueError("co-listen relation count exceeds local evaluation bound")
    targets = _endpoint_targets(heldout, relations)
    denominator = sum(len(artists) for artists in targets.values())
    if not denominator:
        raise ValueError("no held-out custody positive has a co-listen endpoint")
    idf_rows, _count_rows, _candidate_count = _build_peer_rows(train)
    train_artists = frozenset(artist for artists in train.values() for artist in artists)
    artist_cold = sum(
        artist not in train_artists for artists in targets.values() for artist in artists
    )
    colisten_outcome = _outcome(
        targets=targets, score_for_seed=lambda seed: _scores_from_colisten(seed, train, relations)
    )
    idf_outcome = _outcome(
        targets=targets, score_for_seed=lambda seed: _scores_from_idf_peer(seed, train, idf_rows)
    )
    global_outcome = _global_outcome(targets, train)
    common = colisten_outcome.supported & idf_outcome.supported & global_outcome.supported
    placeholder = DirectCustodyCoListenHoldout(
        direct_graph_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_graph_database_sha256=_sha256_file(direct_database),
        colisten_receipt_sha256=hashlib.sha256(colisten_bytes).hexdigest(),
        colisten_database_sha256=_sha256_file(colisten_database),
        custody_seed_count=len(memberships),
        split_eligible_seed_count=len(heldout),
        colisten_endpoint_artist_count=len(relations),
        matched_heldout_positive_count=denominator,
        matched_seed_count=len(targets),
        artist_seen_elsewhere_in_train_target_count=denominator - artist_cold,
        artist_cold_target_count=artist_cold,
        colisten_transfer=_metric(colisten_outcome, denominator),
        idf_peer=_metric(idf_outcome, denominator),
        global_artist_degree=_metric(global_outcome, denominator),
        common_supported_target_count=len(common),
        colisten_common_recalled_at_20=len(colisten_outcome.recalled20_targets & common),
        idf_common_recalled_at_20=len(idf_outcome.recalled20_targets & common),
        global_common_recalled_at_20=len(global_outcome.recalled20_targets & common),
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
