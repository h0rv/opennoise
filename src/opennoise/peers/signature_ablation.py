"""Counterfactual exact-signature ablations for local custody peer review."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphError,
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.signature_concentration import build_signature_concentration_report
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


_TOP_K: Final = 10
_MINIMUM_SHARED_ARTISTS: Final = 2


class ExactSignatureAblationPair(FrozenModel):
    """The effect of removing one complete artist signature on one review pair."""

    left_seed_id: str
    right_seed_id: str
    baseline_shared_artist_count: int = Field(ge=_MINIMUM_SHARED_ARTISTS)
    baseline_left_rank: int | None = Field(default=None, ge=1, le=_TOP_K)
    baseline_right_rank: int | None = Field(default=None, ge=1, le=_TOP_K)
    residual_shared_artist_count: int = Field(ge=0)
    residual_idf_weighted_jaccard: float | None = Field(default=None, ge=0.0, le=1.0)
    residual_left_rank: int | None = Field(default=None, ge=1, le=_TOP_K)
    residual_right_rank: int | None = Field(default=None, ge=1, le=_TOP_K)
    disposition: Literal["cohort_dependent", "cohort_resilient"]

    @model_validator(mode="after")
    def check_disposition(self) -> ExactSignatureAblationPair:
        """Keep the review-only classification mechanical and reproducible."""
        retained_neighbor = (
            self.residual_left_rank is not None or self.residual_right_rank is not None
        )
        expected = (
            "cohort_dependent"
            if self.residual_shared_artist_count < _MINIMUM_SHARED_ARTISTS or not retained_neighbor
            else "cohort_resilient"
        )
        if self.disposition != expected:
            raise ValueError("ablation disposition does not match residual support and ranks")
        if self.residual_shared_artist_count < _MINIMUM_SHARED_ARTISTS:
            if self.residual_idf_weighted_jaccard is not None:
                raise ValueError("non-candidate residual pair cannot carry a graph score")
        elif self.residual_idf_weighted_jaccard is None:
            raise ValueError("candidate residual pair requires a graph score")
        return self


class ExactSignatureAblation(FrozenModel):
    """One full-signature removal and its shadow-graph accounting."""

    dominant_signature: tuple[str, ...] = Field(min_length=1)
    removed_artist_count: int = Field(ge=1)
    removed_seed_artist_claim_count: int = Field(ge=1)
    shadow_candidate_pair_count: int = Field(ge=0)
    endpoint_neighborhoods: tuple[ExactSignatureEndpointNeighborhood, ...]
    pairs: tuple[ExactSignatureAblationPair, ...] = Field(min_length=1)


class ExactSignatureEndpointNeighborhood(FrozenModel):
    """Compact before/after top-ten peer IDs for one ablation endpoint."""

    seed_id: str
    baseline_top_ten: tuple[str, ...] = Field(max_length=_TOP_K)
    shadow_top_ten: tuple[str, ...] = Field(max_length=_TOP_K)


class ExactSignatureAblationReport(FrozenModel):
    """Hash-bound, source-only local review report with no graph mutation."""

    revision: Literal["direct-custody-exact-signature-ablation-v1"] = (
        "direct-custody-exact-signature-ablation-v1"
    )
    scope: Literal["local_research_only"] = "local_research_only"
    graph_receipt_sha256: Sha256
    graph_database_sha256: Sha256
    baseline_candidate_pair_count: int = Field(ge=0)
    baseline_suspect_pair_count: int = Field(ge=0)
    ablations: tuple[ExactSignatureAblation, ...]
    historical_inputs_used: Literal[False] = False
    h3_inputs_used: Literal[False] = False
    tags_or_lastfm_used: Literal[False] = False
    release_rows_used: Literal[False] = False
    automatic_candidate_suppression: Literal[False] = False
    fact_deletion_authorized: Literal[False] = False
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


def _report_hash(report: ExactSignatureAblationReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _memberships(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Read the already materialized source memberships in deterministic order."""
    seed_ids = tuple(
        str(row[0]) for row in connection.execute("SELECT seed_id FROM seed_node ORDER BY seed_id")
    )
    artists: dict[str, tuple[str, ...]] = {}
    current_artist: str | None = None
    current_seeds: list[str] = []
    for artist, seed in connection.execute(
        "SELECT artist_mbid, seed_id FROM seed_artist ORDER BY artist_mbid, seed_id"
    ):
        artist_id = str(artist)
        if current_artist is not None and artist_id != current_artist:
            artists[current_artist] = tuple(current_seeds)
            current_seeds = []
        current_artist = artist_id
        current_seeds.append(str(seed))
    if current_artist is not None:
        artists[current_artist] = tuple(current_seeds)
    return seed_ids, artists


def _baseline_ranks(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], tuple[int | None, int | None]]:
    """Return persisted baseline ranks for each undirected candidate pair."""
    ranks: dict[tuple[str, str], list[int | None]] = {}
    for seed, peer, rank in connection.execute(
        "SELECT seed_id, peer_seed_id, rank FROM peer_neighbor ORDER BY seed_id, peer_seed_id"
    ):
        left, right = sorted((str(seed), str(peer)))
        values = ranks.setdefault((left, right), [None, None])
        values[0 if str(seed) == left else 1] = int(rank)
    return {pair: (values[0], values[1]) for pair, values in ranks.items()}


def _baseline_neighborhoods(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Read the persisted top-ten peer IDs without adding a serving projection."""
    rows: dict[str, list[str]] = defaultdict(list)
    for seed, peer in connection.execute(
        "SELECT seed_id, peer_seed_id FROM peer_neighbor ORDER BY seed_id, rank"
    ):
        rows[str(seed)].append(str(peer))
    return {seed: tuple(peers) for seed, peers in rows.items()}


def _shadow_graph(
    *,
    seed_ids: tuple[str, ...],
    artists: dict[str, tuple[str, ...]],
    removed_signature: tuple[str, ...],
) -> tuple[
    dict[tuple[str, str], int],
    dict[tuple[str, str], tuple[int, float]],
    dict[tuple[str, str], tuple[int | None, int | None]],
    dict[str, tuple[str, ...]],
    int,
    int,
    int,
]:
    """Recompute a no-write source-only graph after removing exactly one signature."""
    active = {
        artist: signature for artist, signature in artists.items() if signature != removed_signature
    }
    weights_by_seed: dict[str, list[float]] = defaultdict(list)
    shared_weights: dict[tuple[str, str], list[float]] = defaultdict(list)
    seed_count = len(seed_ids)
    for signature in active.values():
        weight = 1.0 + math.log((seed_count + 1) / (len(signature) + 1))
        for seed in signature:
            weights_by_seed[seed].append(weight)
        for pair in itertools.combinations(signature, 2):
            shared_weights[pair].append(weight)
    total_weights = {seed: math.fsum(weights_by_seed[seed]) for seed in seed_ids}
    support_counts = {pair: len(weights) for pair, weights in shared_weights.items()}
    candidates: dict[tuple[str, str], tuple[int, float]] = {}
    neighbor_rows: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for pair in sorted(shared_weights):
        shared_count = len(shared_weights[pair])
        if shared_count < _MINIMUM_SHARED_ARTISTS:
            continue
        common_weight = math.fsum(shared_weights[pair])
        left, right = pair
        score = common_weight / (total_weights[left] + total_weights[right] - common_weight)
        candidates[pair] = (shared_count, score)
        neighbor_rows[left].append((right, shared_count, score))
        neighbor_rows[right].append((left, shared_count, score))
    ranks: dict[tuple[str, str], list[int | None]] = {}
    neighborhoods: dict[str, tuple[str, ...]] = {}
    for seed, rows in neighbor_rows.items():
        ordered_rows = sorted(rows, key=lambda row: (-row[2], -row[1], row[0]))[:_TOP_K]
        neighborhoods[seed] = tuple(row[0] for row in ordered_rows)
        for rank, (peer, _shared, _score) in enumerate(ordered_rows, start=1):
            left, right = sorted((seed, peer))
            values = ranks.setdefault((left, right), [None, None])
            values[0 if seed == left else 1] = rank
    removed_artists = len(artists) - len(active)
    removed_claims = sum(
        len(signature) for signature in artists.values() if signature == removed_signature
    )
    return (
        support_counts,
        candidates,
        {pair: (value[0], value[1]) for pair, value in ranks.items()},
        neighborhoods,
        len(candidates),
        removed_artists,
        removed_claims,
    )


def build_exact_signature_ablation_report(
    *, database: Path, receipt_path: Path
) -> ExactSignatureAblationReport:
    """Verify the baseline graph and derive isolated counterfactual ablations."""
    receipt_bytes = receipt_path.read_bytes()
    receipt = DirectCustodyPeerGraphReceipt.model_validate_json(receipt_bytes)
    verify_direct_custody_peer_graph_receipt(receipt, database=database)
    concentration = build_signature_concentration_report(
        database=database, receipt_path=receipt_path
    )
    if concentration.suspect_pair_count != len(concentration.top_suspect_pairs):
        raise DirectCustodyPeerGraphError(
            "signature concentration report is truncated; refusing a partial ablation"
        )
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        seed_ids, artists = _memberships(connection)
        baseline_ranks = _baseline_ranks(connection)
        baseline_neighborhoods = _baseline_neighborhoods(connection)
        baseline_support = {
            (str(left), str(right)): int(shared)
            for left, right, shared in connection.execute(
                "SELECT left_seed_id, right_seed_id, shared_artist_count "
                "FROM pair_edge WHERE disposition = 'candidate'"
            )
        }
    by_signature: dict[tuple[str, ...], list[tuple[str, str]]] = defaultdict(list)
    for pair in concentration.top_suspect_pairs:
        by_signature[pair.dominant_signature].append((pair.left_seed_id, pair.right_seed_id))
    ablations: list[ExactSignatureAblation] = []
    for signature in sorted(by_signature):
        (
            support_counts,
            candidates,
            shadow_ranks,
            shadow_neighborhoods,
            shadow_count,
            removed_artists,
            removed_claims,
        ) = _shadow_graph(seed_ids=seed_ids, artists=artists, removed_signature=signature)
        pairs: list[ExactSignatureAblationPair] = []
        for pair in sorted(by_signature[signature]):
            residual = candidates.get(pair)
            residual_count = support_counts.get(pair, 0)
            residual_score = None if residual is None else residual[1]
            residual_rank = shadow_ranks.get(pair, (None, None))
            disposition = (
                "cohort_dependent"
                if residual_count < _MINIMUM_SHARED_ARTISTS or residual_rank == (None, None)
                else "cohort_resilient"
            )
            pairs.append(
                ExactSignatureAblationPair(
                    left_seed_id=pair[0],
                    right_seed_id=pair[1],
                    baseline_shared_artist_count=baseline_support[pair],
                    baseline_left_rank=baseline_ranks.get(pair, (None, None))[0],
                    baseline_right_rank=baseline_ranks.get(pair, (None, None))[1],
                    residual_shared_artist_count=residual_count,
                    residual_idf_weighted_jaccard=residual_score,
                    residual_left_rank=residual_rank[0],
                    residual_right_rank=residual_rank[1],
                    disposition=disposition,
                )
            )
        ablations.append(
            ExactSignatureAblation(
                dominant_signature=signature,
                removed_artist_count=removed_artists,
                removed_seed_artist_claim_count=removed_claims,
                shadow_candidate_pair_count=shadow_count,
                endpoint_neighborhoods=tuple(
                    ExactSignatureEndpointNeighborhood(
                        seed_id=seed,
                        baseline_top_ten=baseline_neighborhoods.get(seed, ()),
                        shadow_top_ten=shadow_neighborhoods.get(seed, ()),
                    )
                    for seed in sorted({seed for pair in by_signature[signature] for seed in pair})
                ),
                pairs=tuple(pairs),
            )
        )
    placeholder = ExactSignatureAblationReport(
        graph_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        graph_database_sha256=_sha256_file(database),
        baseline_candidate_pair_count=receipt.candidate_pair_count,
        baseline_suspect_pair_count=concentration.suspect_pair_count,
        ablations=tuple(ablations),
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
