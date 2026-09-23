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
    _metric,
    _outcome,
    _sha256_file,
    _split_memberships,
)
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.peers.direct_custody_membership_holdout import _read_memberships
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_TOP_K = 20


class LastFmDirectCustodyMetric(FrozenModel):
    """One aggregate-only retrieval measurement."""

    denominator: int = Field(ge=0)
    supported_target_count: int = Field(ge=0)
    recalled_at_20: int = Field(ge=0)
    recall_at_20: float = Field(ge=0, le=1)


class LastFmDirectCustodyHoldout(FrozenModel):
    """Pinned local Last.fm evaluation with no membership or genre output."""

    revision: Literal["lastfm-direct-custody-holdout-v1"] = "lastfm-direct-custody-holdout-v1"
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
    full: LastFmDirectCustodyMetric
    endpoint_matched: LastFmDirectCustodyMetric
    common_endpoint_lastfm: LastFmDirectCustodyMetric | None = None
    common_endpoint_listenbrainz: LastFmDirectCustodyMetric | None = None
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
    relations = _relations(lastfm_database_path)
    full = _evaluate(heldout, train, relations)
    matched_targets = _endpoint_targets(heldout, relations)
    matched = _evaluate(matched_targets, train, relations)
    common_lastfm = common_listenbrainz = None
    if listenbrainz_database_path is not None and listenbrainz_receipt_path is not None:
        overlay = load_colisten_overlay(listenbrainz_receipt_path)
        certify_colisten_overlay_sources(
            CoListenOverlaySources(listenbrainz_database_path, overlay)
        )
        listenbrainz_relations = _listenbrainz_relations(listenbrainz_database_path)
        common_targets = _endpoint_targets(
            _endpoint_targets(heldout, relations), listenbrainz_relations
        )
        common_lastfm = _evaluate(common_targets, train, relations)
        common_listenbrainz = _evaluate(common_targets, train, listenbrainz_relations)
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

    def score(seed: str) -> dict[str, float]:
        known = frozenset(train[seed])
        scores: dict[str, float] = defaultdict(float)
        for artist in known:
            for candidate, support in relations.get(artist, ()):
                if candidate not in known:
                    scores[candidate] += math.log1p(support)
        return scores

    outcome = _outcome(targets=targets, score_for_seed=score)
    metric = _metric(outcome, denominator)
    return LastFmDirectCustodyMetric(
        denominator=denominator,
        supported_target_count=metric.supported_target_count,
        recalled_at_20=metric.recalled_at_20,
        recall_at_20=metric.micro_recall_at_20,
    )
