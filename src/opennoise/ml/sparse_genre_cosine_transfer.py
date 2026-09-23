"""Leakage-safe sparse cosine transfer from direct genre custody to artists.

This is a local research ablation.  It reads only verified direct-custody
positive labels and privacy-filtered aggregate ListenBrainz co-listen edges;
it neither writes memberships nor supplies a serving or public-model input.
"""

from __future__ import annotations

import hashlib
import heapq
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
    _read_memberships,
    _split_memberships,
)
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_RECALL_K: Final = 20
_TOP_K: Final = 10
_MINIMUM_DISTINCT_USERS: Final = 5
_MAX_COLISTEN_RELATIONS: Final = 50_000
_REVISION: Final = "sparse-genre-cosine-transfer-v1"


@dataclass(frozen=True, slots=True)
class _Outcome:
    recalled_at_10: int
    recalled_at_20: int
    reciprocal_rank_sum: float
    supported: frozenset[tuple[str, str]]
    recalled_at_20_targets: frozenset[tuple[str, str]]
    macro_recall_at_20: float
    recalled_at_20_by_seed: dict[str, int]


class SparseTransferMetric(FrozenModel):
    """Positive-only retrieval metrics on the exact shared target cohort."""

    recalled_at_10: int = Field(ge=0)
    recalled_at_20: int = Field(ge=0)
    micro_recall_at_10: float = Field(ge=0, le=1)
    micro_recall_at_20: float = Field(ge=0, le=1)
    macro_recall_at_20: float = Field(ge=0, le=1)
    mrr_at_20: float = Field(ge=0, le=1)
    supported_target_count: int = Field(ge=0)
    target_support_rate: float = Field(ge=0, le=1)


class SparseGenreCosineTransferReport(FrozenModel):
    """Receipt-bound cosine normalization ablation, never a membership artifact."""

    revision: Literal["sparse-genre-cosine-transfer-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    direct_graph_receipt_sha256: Sha256
    direct_graph_database_sha256: Sha256
    colisten_receipt_sha256: Sha256
    colisten_database_sha256: Sha256
    split_rule: Literal["sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"] = (
        "sha256(seed_id,NUL,artist_mbid): lowest one fifth per eligible seed"
    )
    full_heldout_positive_count: int = Field(ge=0)
    full_heldout_seed_count: int = Field(ge=0)
    matched_heldout_positive_count: int = Field(ge=0)
    matched_seed_count: int = Field(ge=0)
    weighted_edge_formula: Literal["log1p(distinct_users)"] = "log1p(distinct_users)"
    cosine_formula: Literal["edge_weight / sqrt(left_strength * right_strength)"] = (
        "edge_weight / sqrt(left_strength * right_strength)"
    )
    raw_colisten_full_heldout: SparseTransferMetric
    cosine_normalized_full_heldout: SparseTransferMetric
    raw_colisten_endpoint_matched: SparseTransferMetric
    cosine_normalized_endpoint_matched: SparseTransferMetric
    common_supported_target_count: int = Field(ge=0)
    raw_common_recalled_at_20: int = Field(ge=0)
    cosine_common_recalled_at_20: int = Field(ge=0)
    cosine_improved_seed_count: int = Field(ge=0)
    cosine_worsened_seed_count: int = Field(ge=0)
    cosine_tied_seed_count: int = Field(ge=0)
    historical_inputs_used: Literal[False] = False
    h3_inputs_used: Literal[False] = False
    tags_or_lastfm_used: Literal[False] = False
    release_rows_used: Literal[False] = False
    audio_inputs_used: Literal[False] = False
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


def _report_hash(report: SparseGenreCosineTransferReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _relations(database: Path) -> dict[str, tuple[tuple[str, float], ...]]:
    """Read only thresholded aggregate edges and convert their weights once."""
    rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for left, right, users in connection.execute(
            "SELECT left_artist_mbid, right_artist_mbid, distinct_user_count FROM colisten_relation"
        ):
            weight = math.log1p(int(users))
            left_text, right_text = str(left), str(right)
            rows[left_text].append((right_text, weight))
            rows[right_text].append((left_text, weight))
    return {artist: tuple(neighbors) for artist, neighbors in rows.items()}


def _endpoint_targets(
    heldout: Mapping[str, tuple[str, ...]],
    relations: Mapping[str, tuple[tuple[str, float], ...]],
) -> dict[str, tuple[str, ...]]:
    return {
        seed: tuple(artist for artist in artists if artist in relations)
        for seed, artists in heldout.items()
        if any(artist in relations for artist in artists)
    }


def _strengths(
    relations: Mapping[str, tuple[tuple[str, float], ...]],
) -> dict[str, float]:
    return {
        artist: math.fsum(weight for _neighbor, weight in neighbors)
        for artist, neighbors in relations.items()
    }


def _scores(
    *,
    seed_id: str,
    train: Mapping[str, tuple[str, ...]],
    relations: Mapping[str, tuple[tuple[str, float], ...]],
    strengths: Mapping[str, float] | None,
) -> dict[str, float]:
    """Vote from train artists; optional cosine normalization is graph-only."""
    known = frozenset(train[seed_id])
    scores: dict[str, float] = defaultdict(float)
    for source in known:
        for candidate, weight in relations.get(source, ()):
            if candidate in known:
                continue
            contribution = weight
            if strengths is not None:
                contribution /= math.sqrt(strengths[source] * strengths[candidate])
            scores[candidate] += contribution
    return scores


def _outcome(
    *,
    targets: Mapping[str, tuple[str, ...]],
    train: Mapping[str, tuple[str, ...]],
    relations: Mapping[str, tuple[tuple[str, float], ...]],
    strengths: Mapping[str, float] | None,
) -> _Outcome:
    supported: set[tuple[str, str]] = set()
    recalled: set[tuple[str, str]] = set()
    recalled_at_10 = recalled_at_20 = 0
    reciprocal_rank_sum = 0.0
    macro: list[float] = []
    recalled_by_seed: dict[str, int] = {}
    for seed_id, artists in targets.items():
        scores = _scores(seed_id=seed_id, train=train, relations=relations, strengths=strengths)
        ranks = {
            artist: rank
            for rank, (artist, _score) in enumerate(
                heapq.nsmallest(_RECALL_K, scores.items(), key=lambda row: (-row[1], row[0])),
                start=1,
            )
        }
        seed_hits = 0
        for artist in artists:
            pair = (seed_id, artist)
            if artist in scores:
                supported.add(pair)
            if (rank := ranks.get(artist)) is not None:
                recalled.add(pair)
                recalled_at_20 += 1
                seed_hits += 1
                reciprocal_rank_sum += 1 / rank
                if rank <= _TOP_K:
                    recalled_at_10 += 1
        macro.append(seed_hits / len(artists))
        recalled_by_seed[seed_id] = seed_hits
    return _Outcome(
        recalled_at_10=recalled_at_10,
        recalled_at_20=recalled_at_20,
        reciprocal_rank_sum=reciprocal_rank_sum,
        supported=frozenset(supported),
        recalled_at_20_targets=frozenset(recalled),
        macro_recall_at_20=math.fsum(macro) / len(macro),
        recalled_at_20_by_seed=recalled_by_seed,
    )


def _metric(outcome: _Outcome, denominator: int) -> SparseTransferMetric:
    return SparseTransferMetric(
        recalled_at_10=outcome.recalled_at_10,
        recalled_at_20=outcome.recalled_at_20,
        micro_recall_at_10=outcome.recalled_at_10 / denominator,
        micro_recall_at_20=outcome.recalled_at_20 / denominator,
        macro_recall_at_20=outcome.macro_recall_at_20,
        mrr_at_20=outcome.reciprocal_rank_sum / denominator,
        supported_target_count=len(outcome.supported),
        target_support_rate=len(outcome.supported) / denominator,
    )


def evaluate_sparse_genre_cosine_transfer(
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    colisten_database: Path,
    colisten_receipt_path: Path,
) -> SparseGenreCosineTransferReport:
    """Evaluate raw and cosine-normalized sparse transfer without label leakage."""
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
    targets = _endpoint_targets(heldout, relations)
    denominator = sum(len(artists) for artists in targets.values())
    if not denominator:
        raise ValueError("no held-out direct-custody positive is a co-listen endpoint")
    full_denominator = sum(len(artists) for artists in heldout.values())
    raw_full = _outcome(targets=heldout, train=train, relations=relations, strengths=None)
    cosine_full = _outcome(
        targets=heldout, train=train, relations=relations, strengths=_strengths(relations)
    )
    raw = _outcome(targets=targets, train=train, relations=relations, strengths=None)
    cosine = _outcome(
        targets=targets, train=train, relations=relations, strengths=_strengths(relations)
    )
    common = raw.supported & cosine.supported
    cosine_improved = sum(
        cosine.recalled_at_20_by_seed[seed] > raw.recalled_at_20_by_seed[seed] for seed in targets
    )
    cosine_worsened = sum(
        cosine.recalled_at_20_by_seed[seed] < raw.recalled_at_20_by_seed[seed] for seed in targets
    )
    placeholder = SparseGenreCosineTransferReport(
        direct_graph_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_graph_database_sha256=_sha256_file(direct_database),
        colisten_receipt_sha256=hashlib.sha256(colisten_bytes).hexdigest(),
        colisten_database_sha256=_sha256_file(colisten_database),
        full_heldout_positive_count=full_denominator,
        full_heldout_seed_count=len(heldout),
        matched_heldout_positive_count=denominator,
        matched_seed_count=len(targets),
        raw_colisten_full_heldout=_metric(raw_full, full_denominator),
        cosine_normalized_full_heldout=_metric(cosine_full, full_denominator),
        raw_colisten_endpoint_matched=_metric(raw, denominator),
        cosine_normalized_endpoint_matched=_metric(cosine, denominator),
        common_supported_target_count=len(common),
        raw_common_recalled_at_20=len(raw.recalled_at_20_targets & common),
        cosine_common_recalled_at_20=len(cosine.recalled_at_20_targets & common),
        cosine_improved_seed_count=cosine_improved,
        cosine_worsened_seed_count=cosine_worsened,
        cosine_tied_seed_count=len(targets) - cosine_improved - cosine_worsened,
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
