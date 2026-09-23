"""Repeat the sparse cosine retrieval check on fixed custody holdout folds.

This local research module reads the same verified direct-custody positives and
privacy-filtered aggregate co-listen edges as the original cosine ablation. It
does not write memberships or expose results to serving.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)
from opennoise.ml.sparse_genre_cosine_transfer import (
    SparseTransferMetric,
    _endpoint_targets,
    _metric,
    _outcome,
    _relations,
    _sha256_file,
    _strengths,
)
from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.direct_custody_membership_holdout import _read_memberships
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_FOLD_COUNT: Final = 5
_MINIMUM_TRAIN_ARTISTS: Final = 4
_MINIMUM_DISTINCT_USERS: Final = 5
_MAX_COLISTEN_RELATIONS: Final = 50_000
_SLICE_SEED_COUNT: Final = 137
_REVISION: Final = "sparse-genre-cosine-robustness-v1"


class SparseCosineCohortReport(FrozenModel):
    """A fixed target cohort evaluated by both rankings without support changes."""

    heldout_positive_count: int = Field(ge=1)
    seed_count: int = Field(ge=1)
    raw_colisten: SparseTransferMetric
    cosine_normalized: SparseTransferMetric
    common_supported_target_count: int = Field(ge=0)
    raw_common_recalled_at_20: int = Field(ge=0)
    cosine_common_recalled_at_20: int = Field(ge=0)


class SparseCosineFoldReport(FrozenModel):
    """One deterministic holdout fold and two predeclared seed-size slices."""

    fold_index: int = Field(ge=0, lt=_FOLD_COUNT)
    full_heldout: SparseCosineCohortReport
    endpoint_matched: SparseCosineCohortReport
    broad_seed_slice: SparseCosineCohortReport
    niche_seed_slice: SparseCosineCohortReport


class SparseGenreCosineRobustnessReport(FrozenModel):
    """Receipt-bound repeatability result for local cosine ranking research."""

    revision: Literal["sparse-genre-cosine-robustness-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    direct_graph_receipt_sha256: Sha256
    direct_graph_database_sha256: Sha256
    colisten_receipt_sha256: Sha256
    colisten_database_sha256: Sha256
    fold_count: Literal[5] = _FOLD_COUNT
    split_rule: Literal[
        "sha256(seed_id,NUL,artist_mbid): five disjoint lowest-fifth rank blocks per eligible seed"
    ] = "sha256(seed_id,NUL,artist_mbid): five disjoint lowest-fifth rank blocks per eligible seed"
    minimum_train_artists_per_seed: Literal[4] = _MINIMUM_TRAIN_ARTISTS
    broad_niche_rule: Literal[
        "top and bottom 137 eligible seeds by direct-custody membership count, then seed_id"
    ] = "top and bottom 137 eligible seeds by direct-custody membership count, then seed_id"
    broad_niche_seed_count: Literal[137] = _SLICE_SEED_COUNT
    folds: tuple[SparseCosineFoldReport, ...]
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


def _report_hash(report: SparseGenreCosineRobustnessReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _eligible_memberships(
    memberships: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    return {
        seed_id: artists
        for seed_id, artists in memberships.items()
        if len(artists) >= _MINIMUM_TRAIN_ARTISTS + 1
    }


def _split_fold(
    memberships: Mapping[str, tuple[str, ...]], *, fold_index: int
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Withhold one disjoint fifth-sized hash-ranked block per eligible seed."""
    if not 0 <= fold_index < _FOLD_COUNT:
        raise ValueError(f"fold index must be from 0 to {_FOLD_COUNT - 1}")
    train: dict[str, tuple[str, ...]] = {}
    heldout: dict[str, tuple[str, ...]] = {}
    for seed_id, artists in _eligible_memberships(memberships).items():
        heldout_count = len(artists) // _FOLD_COUNT
        ordered = tuple(
            sorted(
                artists,
                key=lambda artist: hashlib.sha256(f"{seed_id}\0{artist}".encode()).digest(),
            )
        )
        start = fold_index * heldout_count
        selected = ordered[start : start + heldout_count]
        selected_set = frozenset(selected)
        train[seed_id] = tuple(artist for artist in artists if artist not in selected_set)
        heldout[seed_id] = selected
    return train, heldout


def _seed_slices(
    memberships: Mapping[str, tuple[str, ...]],
) -> tuple[frozenset[str], frozenset[str]]:
    """Choose fixed broad and niche seed groups without looking at ranking results."""
    eligible = _eligible_memberships(memberships)
    if len(eligible) < _SLICE_SEED_COUNT * 2:
        raise ValueError("not enough eligible seeds for fixed broad and niche slices")
    broad = tuple(sorted(eligible, key=lambda seed_id: (-len(eligible[seed_id]), seed_id)))
    niche = tuple(sorted(eligible, key=lambda seed_id: (len(eligible[seed_id]), seed_id)))
    return frozenset(broad[:_SLICE_SEED_COUNT]), frozenset(niche[:_SLICE_SEED_COUNT])


def _subset(
    targets: Mapping[str, tuple[str, ...]], seeds: frozenset[str]
) -> dict[str, tuple[str, ...]]:
    return {seed_id: artists for seed_id, artists in targets.items() if seed_id in seeds}


def _cohort(
    *,
    targets: Mapping[str, tuple[str, ...]],
    train: Mapping[str, tuple[str, ...]],
    relations: Mapping[str, tuple[tuple[str, float], ...]],
    strengths: Mapping[str, float],
) -> SparseCosineCohortReport:
    """Score exactly one positive-only target cohort under the two fixed arms."""
    denominator = sum(len(artists) for artists in targets.values())
    if not denominator:
        raise ValueError("cohort has no endpoint-matched held-out positives")
    raw = _outcome(targets=targets, train=train, relations=relations, strengths=None)
    cosine = _outcome(targets=targets, train=train, relations=relations, strengths=strengths)
    common = raw.supported & cosine.supported
    return SparseCosineCohortReport(
        heldout_positive_count=denominator,
        seed_count=len(targets),
        raw_colisten=_metric(raw, denominator),
        cosine_normalized=_metric(cosine, denominator),
        common_supported_target_count=len(common),
        raw_common_recalled_at_20=len(raw.recalled_at_20_targets & common),
        cosine_common_recalled_at_20=len(cosine.recalled_at_20_targets & common),
    )


def evaluate_sparse_genre_cosine_robustness(
    *,
    direct_database: Path,
    direct_receipt_path: Path,
    colisten_database: Path,
    colisten_receipt_path: Path,
) -> SparseGenreCosineRobustnessReport:
    """Evaluate all fixed folds using verified source-isolated local inputs only."""
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
    relations = _relations(colisten_database)
    if sum(len(neighbors) for neighbors in relations.values()) // 2 > _MAX_COLISTEN_RELATIONS:
        raise ValueError("co-listen relation count exceeds local evaluation bound")
    strengths = _strengths(relations)
    broad_seeds, niche_seeds = _seed_slices(memberships)
    folds: list[SparseCosineFoldReport] = []
    for fold_index in range(_FOLD_COUNT):
        train, heldout = _split_fold(memberships, fold_index=fold_index)
        targets = _endpoint_targets(heldout, relations)
        folds.append(
            SparseCosineFoldReport(
                fold_index=fold_index,
                full_heldout=_cohort(
                    targets=heldout, train=train, relations=relations, strengths=strengths
                ),
                endpoint_matched=_cohort(
                    targets=targets, train=train, relations=relations, strengths=strengths
                ),
                broad_seed_slice=_cohort(
                    targets=_subset(targets, broad_seeds),
                    train=train,
                    relations=relations,
                    strengths=strengths,
                ),
                niche_seed_slice=_cohort(
                    targets=_subset(targets, niche_seeds),
                    train=train,
                    relations=relations,
                    strengths=strengths,
                ),
            )
        )
    placeholder = SparseGenreCosineRobustnessReport(
        direct_graph_receipt_sha256=hashlib.sha256(direct_bytes).hexdigest(),
        direct_graph_database_sha256=_sha256_file(direct_database),
        colisten_receipt_sha256=hashlib.sha256(colisten_bytes).hexdigest(),
        colisten_database_sha256=_sha256_file(colisten_database),
        folds=tuple(folds),
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
