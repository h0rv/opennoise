"""Audit exact artist seed-membership signatures in a local peer graph."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.peers.direct_custody_graph import (
    DirectCustodyPeerGraphError,
    DirectCustodyPeerGraphReceipt,
    verify_direct_custody_peer_graph_receipt,
)
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_TOP_SUSPECT_LIMIT: Final = 50
_SUSPECT_MIN_SHARED_ARTISTS: Final = 1_000
_SUSPECT_MIN_DOMINANT_SHARE: Final = 0.90


class SignatureConcentrationPair(FrozenModel):
    """One candidate pair with its strongest exact membership class."""

    left_seed_id: str
    right_seed_id: str
    shared_artist_count: int = Field(ge=2)
    dominant_signature: tuple[str, ...]
    dominant_signature_artist_count: int = Field(ge=1)
    dominant_signature_share: float = Field(ge=0.0, le=1.0)
    suspect: bool

    @model_validator(mode="after")
    def check_concentration_accounting(self) -> SignatureConcentrationPair:
        """Keep the reported share and flag consistent with pair support."""
        if self.dominant_signature_artist_count > self.shared_artist_count:
            raise ValueError("dominant signature support exceeds shared artist support")
        expected_share = self.dominant_signature_artist_count / self.shared_artist_count
        if self.dominant_signature_share != expected_share:
            raise ValueError("dominant signature share does not match its support counts")
        expected_suspect = (
            self.shared_artist_count >= _SUSPECT_MIN_SHARED_ARTISTS
            and expected_share >= _SUSPECT_MIN_DOMINANT_SHARE
        )
        if self.suspect != expected_suspect:
            raise ValueError("suspect flag does not match the configured review threshold")
        return self


class SignatureConcentrationReport(FrozenModel):
    """Bounded source-only report; findings require human review."""

    revision: Literal["direct-custody-artist-signature-concentration-v1"]
    scope: Literal["local_research_only"] = "local_research_only"
    graph_receipt_sha256: Sha256
    graph_database_sha256: Sha256
    candidate_pair_count: int = Field(ge=0)
    suspect_pair_count: int = Field(ge=0)
    suspect_min_shared_artist_count: int = _SUSPECT_MIN_SHARED_ARTISTS
    suspect_min_dominant_signature_share: float = _SUSPECT_MIN_DOMINANT_SHARE
    top_suspect_pairs: tuple[SignatureConcentrationPair, ...]
    review_needed: Literal[True] = True
    automatic_candidate_suppression: Literal[False] = False
    fact_deletion_authorized: Literal[False] = False
    public_export_authorized: Literal[False] = False
    output_sha256: Sha256


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_hash(report: SignatureConcentrationReport) -> Sha256:
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _candidate_concentrations(
    connection: sqlite3.Connection,
) -> tuple[int, int, tuple[SignatureConcentrationPair, ...]]:
    """Compute each candidate's strongest exact artist seed-membership class."""
    signatures: dict[str, tuple[str, ...]] = {}
    current_artist: str | None = None
    current_seeds: list[str] = []
    for artist, seed in connection.execute(
        "SELECT artist_mbid, seed_id FROM seed_artist ORDER BY artist_mbid, seed_id"
    ):
        artist_id, seed_id = str(artist), str(seed)
        if current_artist is not None and artist_id != current_artist:
            signatures[current_artist] = tuple(current_seeds)
            current_seeds = []
        current_artist = artist_id
        current_seeds.append(seed_id)
    if current_artist is not None:
        signatures[current_artist] = tuple(current_seeds)
    counts: dict[tuple[str, str], Counter[tuple[str, ...]]] = {}
    shared: dict[tuple[str, str], int] = {}
    expected_shared: dict[tuple[str, str], int] = {}
    for left, right, stored_shared, artist in connection.execute(
        """
        SELECT edge.left_seed_id, edge.right_seed_id, edge.shared_artist_count,
               left_membership.artist_mbid
        FROM pair_edge AS edge
        JOIN seed_artist AS left_membership
          ON left_membership.seed_id = edge.left_seed_id
        JOIN seed_artist AS right_membership
          ON right_membership.seed_id = edge.right_seed_id
         AND right_membership.artist_mbid = left_membership.artist_mbid
        WHERE edge.disposition = 'candidate'
        ORDER BY edge.left_seed_id, edge.right_seed_id, left_membership.artist_mbid
        """
    ):
        pair = (str(left), str(right))
        expected_shared[pair] = int(stored_shared)
        artist_id = str(artist)
        signature = signatures.get(artist_id)
        if signature is None:
            raise DirectCustodyPeerGraphError("seed artist has no exact membership signature")
        counts.setdefault(pair, Counter())[signature] += 1
        shared[pair] = shared.get(pair, 0) + 1

    candidates: list[SignatureConcentrationPair] = []
    suspect_count = 0
    candidate_count = 0
    for pair in sorted(counts):
        candidate_count += 1
        signature_counts = counts[pair]
        dominant_signature, dominant_count = min(
            signature_counts.items(), key=lambda item: (-item[1], item[0])
        )
        shared_count = shared[pair]
        if shared_count != expected_shared[pair]:
            raise DirectCustodyPeerGraphError(
                "candidate shared-artist support differs from its stored graph count"
            )
        share = dominant_count / shared_count
        suspect = (
            shared_count >= _SUSPECT_MIN_SHARED_ARTISTS and share >= _SUSPECT_MIN_DOMINANT_SHARE
        )
        if suspect:
            suspect_count += 1
            candidates.append(
                SignatureConcentrationPair(
                    left_seed_id=pair[0],
                    right_seed_id=pair[1],
                    shared_artist_count=shared_count,
                    dominant_signature=dominant_signature,
                    dominant_signature_artist_count=dominant_count,
                    dominant_signature_share=share,
                    suspect=True,
                )
            )
    candidates.sort(
        key=lambda pair: (
            -pair.dominant_signature_share,
            -pair.dominant_signature_artist_count,
            -pair.shared_artist_count,
            pair.left_seed_id,
            pair.right_seed_id,
        )
    )
    stored_candidate_count = int(
        connection.execute(
            "SELECT count(*) FROM pair_edge WHERE disposition = 'candidate'"
        ).fetchone()[0]
    )
    if candidate_count != stored_candidate_count:
        raise DirectCustodyPeerGraphError("not every candidate pair had shared artist support")
    return candidate_count, suspect_count, tuple(candidates[:_TOP_SUSPECT_LIMIT])


def build_signature_concentration_report(
    *, database: Path, receipt_path: Path
) -> SignatureConcentrationReport:
    """Verify graph receipt/database, then derive a bounded signature report."""
    receipt_bytes = receipt_path.read_bytes()
    receipt = DirectCustodyPeerGraphReceipt.model_validate_json(receipt_bytes)
    verify_direct_custody_peer_graph_receipt(receipt, database=database)
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        candidate_count, suspect_count, top_suspects = _candidate_concentrations(connection)
    if candidate_count != receipt.candidate_pair_count:
        raise DirectCustodyPeerGraphError(
            "candidate pair count differs from the verified graph receipt"
        )
    placeholder = SignatureConcentrationReport(
        revision="direct-custody-artist-signature-concentration-v1",
        graph_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        graph_database_sha256=_sha256_file(database),
        candidate_pair_count=candidate_count,
        suspect_pair_count=suspect_count,
        top_suspect_pairs=top_suspects,
        output_sha256="0" * 64,
    )
    return placeholder.model_copy(update={"output_sha256": _report_hash(placeholder)})
