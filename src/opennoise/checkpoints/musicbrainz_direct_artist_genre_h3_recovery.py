"""Bounded, positive-only recovery of exact direct artist--genre pairs in H3.

This evaluator verifies the direct custody object before it opens either the
Spotify bridge or the historical SQLite database.  It only compares exact
``(retained seed_id, lowercase MusicBrainz artist MBID)`` pairs.  Missing H3
pairs are unknown and never become negative labels or a release decision.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import ijson
from pydantic import Field, model_validator

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.history.historical_custody import HistoricalH3RebuildReceipt
from opennoise.ingest.spotify.artifact import (
    iter_accepted_spotify_to_musicbrainz,
    load_receipted_musicbrainz_spotify_bridge,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


_REVISION: Final = "musicbrainz-direct-artist-genre-h3-positive-recovery-v1"
_H3_ROLE: Final = "genre_page_member"
_MAX_H3_OBSERVATIONS: Final = 350_000
_RETAINED_SEED_COUNT: Final = 6_291
_H3_CROSSWALK_SEED_COUNT: Final = 6_289
_HISTORICAL_SEED_PREFIX: Final = "enao-legacy:"


class DirectArtistGenreH3RecoveryError(ValueError):
    """An input does not meet the exact, bounded evaluation contract."""


class DirectArtistGenreH3RecoveryReport(FrozenModel):
    """A report that is expressly excluded from construction and release decisions."""

    revision: Literal["musicbrainz-direct-artist-genre-h3-positive-recovery-v1"] = _REVISION
    evaluation_only: Literal[True] = True
    historical_inputs_used_for_construction: Literal[False] = False
    absence_is_negative: Literal[False] = False
    precision_or_negative_metrics_computed: Literal[False] = False
    release_approval_computed: Literal[False] = False
    custody_receipt_output_sha256: Sha256
    custody_receipt_byte_sha256: Sha256
    reconciliation_byte_sha256: Sha256
    reconciliation_output_sha256: Sha256
    bridge_receipt_byte_sha256: Sha256
    bridge_output_sha256: Sha256
    historical_rebuild_receipt_byte_sha256: Sha256
    historical_database_sha256: Sha256
    custody_seed_count: int = Field(ge=0)
    exact_h3_source_seed_crosswalk_count: Literal[6289] = _H3_CROSSWALK_SEED_COUNT
    accepted_bridge_artist_count: int = Field(ge=0)
    custody_observation_count: int = Field(ge=0)
    custody_distinct_pair_count: int = Field(ge=0)
    bridge_covered_direct_pair_count: int = Field(ge=0)
    scoped_h3_positive_pair_count: int = Field(ge=0)
    h3_raw_observation_count: int = Field(ge=0)
    h3_distinct_positive_pair_count: int = Field(ge=0)
    overlap_pair_count: int = Field(ge=0)
    micro_positive_recovery: float | None = Field(default=None, ge=0, le=1)
    macro_positive_recovery: float | None = Field(default=None, ge=0, le=1)
    evaluated_h3_seed_count: int = Field(ge=0)
    h3_seed_with_hit_count: int = Field(ge=0)
    h3_seed_without_hit_count: int = Field(ge=0)
    custody_seed_without_h3_positive_count: int = Field(ge=0)
    candidate_h3_overlap_fraction: float | None = Field(default=None, ge=0, le=1)
    output_sha256: Sha256

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> DirectArtistGenreH3RecoveryReport:
        if self.overlap_pair_count > self.scoped_h3_positive_pair_count:
            raise ValueError("overlap cannot exceed H3 positive pairs")
        if self.overlap_pair_count > self.bridge_covered_direct_pair_count:
            raise ValueError("overlap cannot exceed direct pairs")
        expected = (
            self.overlap_pair_count / self.scoped_h3_positive_pair_count
            if self.scoped_h3_positive_pair_count
            else None
        )
        if self.micro_positive_recovery != expected:
            raise ValueError("micro positive recovery does not replay pair counts")
        candidate_expected = (
            self.overlap_pair_count / self.bridge_covered_direct_pair_count
            if self.bridge_covered_direct_pair_count
            else None
        )
        if self.candidate_h3_overlap_fraction != candidate_expected:
            raise ValueError("candidate H3 overlap fraction does not replay pair counts")
        if (
            self.h3_seed_with_hit_count + self.h3_seed_without_hit_count
            != self.evaluated_h3_seed_count
        ):
            raise ValueError("per-seed H3 recovery counts do not replay")
        return self


@dataclass(frozen=True, slots=True)
class _H3Pairs:
    raw_observation_count: int
    pairs: set[tuple[str, str]]
    seed_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _CustodyPairs:
    seed_ids: frozenset[str]
    pairs: frozenset[tuple[str, str]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _output_sha256(path: Path, *, label: str) -> str:
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream):
            if prefix == "output_sha256" and event == "string" and isinstance(value, str):
                return value
    raise DirectArtistGenreH3RecoveryError(f"{label} lacks output_sha256")


def _verify_reconciliation(
    path: Path, *, receipt: DirectProperGenreCustodyReceipt
) -> frozenset[str]:
    if (_sha256(path), _output_sha256(path, label="reconciliation")) != (
        receipt.reconciliation_byte_sha256,
        receipt.reconciliation_output_sha256,
    ):
        raise DirectArtistGenreH3RecoveryError(
            "reconciliation does not match direct custody receipt"
        )
    seed_ids: set[str] = set()
    with path.open("rb") as stream:
        for row in ijson.items(stream, "dispositions.item"):
            if not isinstance(row, dict) or not isinstance(
                seed_id := row.get("source_item_id"), str
            ):
                raise DirectArtistGenreH3RecoveryError(
                    "reconciliation disposition lacks source item ID"
                )
            if not seed_id or seed_id in seed_ids:
                raise DirectArtistGenreH3RecoveryError("reconciliation source item IDs are invalid")
            seed_ids.add(seed_id)
    if len(seed_ids) != _RETAINED_SEED_COUNT:
        raise DirectArtistGenreH3RecoveryError(
            "reconciliation does not retain the complete seed universe"
        )
    return frozenset(seed_ids)


def _custody_pairs(
    receipt: DirectProperGenreCustodyReceipt, *, object_store: Path
) -> _CustodyPairs:
    pairs: set[tuple[str, str]] = set()
    seed_ids: set[str] = set()
    for claim in iter_verified_portable_direct_proper_genre_claims(
        receipt, object_store=object_store
    ):
        mbid = claim.artist_mbid
        if str(uuid.UUID(mbid)) != mbid:
            raise DirectArtistGenreH3RecoveryError(
                "direct custody contains a noncanonical artist MBID"
            )
        seed_ids.add(claim.seed_id)
        pairs.add((claim.seed_id, mbid))
    if len(seed_ids) != receipt.seed_count:
        raise DirectArtistGenreH3RecoveryError("direct custody seed count does not replay")
    return _CustodyPairs(frozenset(seed_ids), frozenset(pairs))


def _h3_pairs(
    database: Path,
    *,
    source_sha256: str,
    spotify_to_mbid: dict[str, str],
) -> _H3Pairs:
    pairs: set[tuple[str, str]] = set()
    crosswalk_seed_ids: set[str] = set()
    raw_observation_count = 0
    crosswalk = """
        WITH observed AS (
            SELECT DISTINCT genre_id
              FROM historical_genre_artist_observations
             WHERE observation_role = ? AND source_artifact_sha256 = ?
        )
        SELECT count(*), count(DISTINCT genre.id),
               count(DISTINCT identifier.normalized_value)
          FROM observed
          JOIN genres AS genre ON genre.id = observed.genre_id
          JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
          JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
         WHERE type.type_key = 'source_id'
           AND identifier.namespace = 'enao-legacy'
           AND identifier.normalized_value GLOB 'item[0-9]*'
    """
    query = """
        SELECT identifier.normalized_value, observation.source_artist_id
          FROM historical_genre_artist_observations AS observation
          JOIN genres AS genre ON genre.id = observation.genre_id
          JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
          JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
         WHERE observation.observation_role = ?
           AND observation.source_artifact_sha256 = ?
           AND observation.source_artist_id IS NOT NULL
           AND type.type_key = 'source_id'
           AND identifier.namespace = 'enao-legacy'
           AND identifier.normalized_value GLOB 'item[0-9]*'
         ORDER BY identifier.normalized_value, observation.source_artist_id
    """
    try:
        with closing(sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)) as connection:
            row = connection.execute(crosswalk, (_H3_ROLE, source_sha256)).fetchone()
            if row is None or tuple(int(value) for value in row) != (_H3_CROSSWALK_SEED_COUNT,) * 3:
                raise DirectArtistGenreH3RecoveryError(
                    "H3 source seed crosswalk is not one-to-one and complete"
                )
            for index, (source_seed_id, spotify_id) in enumerate(
                connection.execute(query, (_H3_ROLE, source_sha256)), start=1
            ):
                raw_observation_count = index
                if index > _MAX_H3_OBSERVATIONS:
                    raise DirectArtistGenreH3RecoveryError(
                        "H3 observations exceed evaluation bound"
                    )
                seed_id = str(source_seed_id)
                crosswalk_seed_ids.add(seed_id)
                mbid = spotify_to_mbid.get(str(spotify_id))
                if mbid is not None:
                    if str(uuid.UUID(mbid)) != mbid:
                        raise DirectArtistGenreH3RecoveryError(
                            "bridge contains a noncanonical artist MBID"
                        )
                    pairs.add((seed_id, mbid))
    except sqlite3.Error as error:
        raise DirectArtistGenreH3RecoveryError("H3 SQLite query failed") from error
    return _H3Pairs(
        raw_observation_count=raw_observation_count,
        pairs=pairs,
        seed_ids=frozenset(crosswalk_seed_ids),
    )


def _report_sha256(report: DirectArtistGenreH3RecoveryReport) -> str:
    payload = report.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def evaluate_direct_artist_genre_h3_positive_recovery(  # noqa: PLR0913
    *,
    custody_receipt_path: Path,
    custody_object_store: Path,
    reconciliation_path: Path,
    bridge_path: Path,
    bridge_receipt_path: Path,
    bridge_receipt_sha256: str,
    historical_rebuild_receipt_path: Path,
    historical_rebuild_receipt_sha256: str,
    expected_h3_raw_sha256: str,
    expected_h3_database_sha256: str,
    historical_database_path: Path,
) -> DirectArtistGenreH3RecoveryReport:
    """Compare exact direct pairs with bridge-resolved H3 positive observations."""
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(custody_receipt_path.read_bytes())
    # This completes custody verification before any bridge or H3 input is opened.
    custody = _custody_pairs(receipt, object_store=custody_object_store)
    reconciliation_seeds = _verify_reconciliation(reconciliation_path, receipt=receipt)
    if _sha256(historical_rebuild_receipt_path) != historical_rebuild_receipt_sha256:
        raise DirectArtistGenreH3RecoveryError(
            "historical rebuild receipt does not match trust root"
        )
    h3_receipt = HistoricalH3RebuildReceipt.model_validate_json(
        historical_rebuild_receipt_path.read_bytes()
    )
    if h3_receipt.h3_source_sha256 != expected_h3_raw_sha256:
        raise DirectArtistGenreH3RecoveryError(
            "historical rebuild receipt raw H3 hash is not pinned"
        )
    if h3_receipt.membership_sqlite.sha256 != expected_h3_database_sha256:
        raise DirectArtistGenreH3RecoveryError(
            "historical rebuild receipt SQLite hash is not pinned"
        )
    if _sha256(historical_database_path) != expected_h3_database_sha256:
        raise DirectArtistGenreH3RecoveryError(
            "H3 database does not match historical rebuild receipt"
        )
    bridge = load_receipted_musicbrainz_spotify_bridge(
        bridge_path, bridge_receipt_path, bridge_receipt_sha256
    )
    try:
        spotify_to_mbid = dict(iter_accepted_spotify_to_musicbrainz(bridge))
        accepted_mbids = frozenset(spotify_to_mbid.values())
        direct = {pair for pair in custody.pairs if pair[1] in accepted_mbids}
        h3 = _h3_pairs(
            historical_database_path,
            source_sha256=h3_receipt.h3_source_sha256,
            spotify_to_mbid=spotify_to_mbid,
        )
        bridge_output_sha256 = bridge.header.output_sha256
    finally:
        bridge.close()
    if not h3.seed_ids <= reconciliation_seeds:
        raise DirectArtistGenreH3RecoveryError(
            "H3 source-ID crosswalk has a seed outside reconciliation"
        )
    scoped_h3 = {pair for pair in h3.pairs if pair[0] in custody.seed_ids}
    overlap = direct & scoped_h3
    positives_by_seed: dict[str, set[str]] = defaultdict(set)
    hits_by_seed: dict[str, set[str]] = defaultdict(set)
    for seed_id, mbid in scoped_h3:
        positives_by_seed[seed_id].add(mbid)
    for seed_id, mbid in overlap:
        hits_by_seed[seed_id].add(mbid)
    recoveries = [
        len(hits_by_seed[seed_id]) / len(positives)
        for seed_id, positives in positives_by_seed.items()
    ]
    preliminary = DirectArtistGenreH3RecoveryReport(
        custody_receipt_output_sha256=receipt.output_sha256,
        custody_receipt_byte_sha256=_sha256(custody_receipt_path),
        reconciliation_byte_sha256=_sha256(reconciliation_path),
        reconciliation_output_sha256=receipt.reconciliation_output_sha256,
        bridge_receipt_byte_sha256=_sha256(bridge_receipt_path),
        bridge_output_sha256=bridge_output_sha256,
        historical_rebuild_receipt_byte_sha256=_sha256(historical_rebuild_receipt_path),
        historical_database_sha256=h3_receipt.membership_sqlite.sha256,
        custody_seed_count=len(custody.seed_ids),
        accepted_bridge_artist_count=len(accepted_mbids),
        custody_observation_count=receipt.claim_count,
        custody_distinct_pair_count=len(custody.pairs),
        bridge_covered_direct_pair_count=len(direct),
        scoped_h3_positive_pair_count=len(scoped_h3),
        h3_raw_observation_count=h3.raw_observation_count,
        h3_distinct_positive_pair_count=len(h3.pairs),
        overlap_pair_count=len(overlap),
        micro_positive_recovery=len(overlap) / len(scoped_h3) if scoped_h3 else None,
        macro_positive_recovery=sum(recoveries) / len(recoveries) if recoveries else None,
        evaluated_h3_seed_count=len(positives_by_seed),
        h3_seed_with_hit_count=sum(bool(hits_by_seed[seed_id]) for seed_id in positives_by_seed),
        h3_seed_without_hit_count=sum(not hits_by_seed[seed_id] for seed_id in positives_by_seed),
        custody_seed_without_h3_positive_count=len(custody.seed_ids - set(positives_by_seed)),
        candidate_h3_overlap_fraction=len(overlap) / len(direct) if direct else None,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": _report_sha256(preliminary)})
