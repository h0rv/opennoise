"""Compare repeated local JSPF coappearance with sealed Last.fm aggregate support.

This evaluator is a local research receipt. It derives positives from the
ListenBrainz JSPF receipt before opening the Last.fm database, uses exact
MusicBrainz artist UUIDs only, and never emits artists, pairs, or rankings.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from itertools import combinations
from math import fsum
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.analysis.lastfm_360k import (
    LastFm360kProbeError,
    load_lastfm_360k_sealed_v1_envelope,
)
from opennoise.analysis.listenbrainz_playlist_embedded_artist_ids import (
    ListenBrainzPlaylistEmbeddedArtistIdsArtifact,
)
from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this annotation at definition.
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path
    from uuid import UUID

_REVISION: Final = "listenbrainz-playlist-lastfm-360k-matched-holdout-v1"
_REPEAT_PLAYLIST_FLOOR: Final = 2
_BASELINE_SEED: Final = "listenbrainz-playlist-lastfm-360k-matched-holdout-v1"
_MAXIMUM_ARTISTS: Final = 1_000
_MAXIMUM_PAIR_POTENTIALS: Final = 1_000_000


class PlaylistLastFmHoldoutError(ValueError):
    """Report an unsafe or mismatched local holdout input."""


class PlaylistDerivedReceiptPin(FrozenModel):
    """Require the exact derived JSPF receipt before it enters the evaluator."""

    expected_playlist_receipt_sha256: Sha256


class PlaylistLastFmHoldoutSettings(FrozenModel):
    """Predeclare the positive rule and fixed ranking comparison."""

    revision: Literal["listenbrainz-playlist-lastfm-360k-matched-holdout-settings-v1"] = (
        "listenbrainz-playlist-lastfm-360k-matched-holdout-settings-v1"
    )
    positive_rule: Literal["unordered_artist_pair_repeated_in_at_least_two_distinct_playlists"] = (
        "unordered_artist_pair_repeated_in_at_least_two_distinct_playlists"
    )
    minimum_distinct_playlists_per_positive: Literal[2] = _REPEAT_PLAYLIST_FLOOR
    candidate_rule: Literal["all_other_exact_jspf_artist_mbids"] = (
        "all_other_exact_jspf_artist_mbids"
    )
    lastfm_score: Literal["privacy_filtered_distinct_user_count_or_zero"] = (
        "privacy_filtered_distinct_user_count_or_zero"
    )
    score_tie_breaker: Literal["sha256_seeded_exact_artist_mbid_order"] = (
        "sha256_seeded_exact_artist_mbid_order"
    )
    baseline: Literal["sha256_seeded_exact_artist_mbid_order"] = (
        "sha256_seeded_exact_artist_mbid_order"
    )
    baseline_seed: Literal["listenbrainz-playlist-lastfm-360k-matched-holdout-v1"] = _BASELINE_SEED
    ranking_cutoffs: tuple[Literal[1], Literal[5], Literal[10]] = (1, 5, 10)
    maximum_artist_count: int = Field(default=_MAXIMUM_ARTISTS, ge=2, le=_MAXIMUM_ARTISTS)
    maximum_pair_potentials: int = Field(
        default=_MAXIMUM_PAIR_POTENTIALS, ge=1, le=_MAXIMUM_PAIR_POTENTIALS
    )


class PairOverlap(FrozenModel):
    """Aggregate overlap between source-only pair potentials and Last.fm support."""

    jspf_artist_count: int = Field(ge=0)
    pair_endpoint_artist_count: int = Field(ge=0)
    jspf_pair_potential_count: int = Field(ge=0)
    repeat_positive_pair_count: int = Field(ge=0)
    lastfm_supported_jspf_pair_count: int = Field(ge=0)
    lastfm_supported_jspf_pair_rate: float = Field(ge=0.0, le=1.0)
    lastfm_recovered_positive_pair_count: int = Field(ge=0)
    lastfm_unsupported_positive_pair_count: int = Field(ge=0)
    lastfm_recovered_positive_pair_rate: float = Field(ge=0.0, le=1.0)


class RankingMetrics(FrozenModel):
    """Pair-level recovery and per-anchor ranking metrics on fixed positives."""

    positive_anchor_count: int = Field(ge=0)
    directed_positive_count: int = Field(ge=0)
    candidate_count_per_anchor: int = Field(ge=0)
    recalled_at_1: int = Field(ge=0)
    recalled_at_5: int = Field(ge=0)
    recalled_at_10: int = Field(ge=0)
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    macro_recall_at_1: float = Field(ge=0.0, le=1.0)
    macro_recall_at_5: float = Field(ge=0.0, le=1.0)
    macro_recall_at_10: float = Field(ge=0.0, le=1.0)
    mean_reciprocal_rank: float = Field(ge=0.0, le=1.0)
    mean_positive_rank: float = Field(ge=1.0)


class PlaylistLastFmMatchedHoldout(FrozenModel):
    """Receipt-bound local-only evaluation with no production authorization."""

    revision: Literal["listenbrainz-playlist-lastfm-360k-matched-holdout-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    genre_truth_used: Literal[False] = False
    cross_account_claim_made: Literal[False] = False
    human_curation_claim_made: Literal[False] = False
    playlist_receipt_is_derived_measurement: Literal[True] = True
    raw_jspf_replay_performed: Literal[False] = False
    playlist_coappearance_scope: Literal["within_one_account_playlist_cohort_only"]
    expected_playlist_receipt_sha256: Sha256
    playlist_receipt_sha256: Sha256
    playlist_bundle_sha256: Sha256
    lastfm_artifact_sha256: Sha256
    lastfm_companion_receipt_sha256: Sha256
    lastfm_database_sha256: Sha256
    lastfm_pair_floor: int = Field(ge=5)
    settings: PlaylistLastFmHoldoutSettings
    overlap: PairOverlap
    lastfm_ranking: RankingMetrics
    deterministic_baseline: RankingMetrics
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_replayable_output_hash(self) -> PlaylistLastFmMatchedHoldout:
        """Reject a receipt whose declared logical hash does not replay."""
        if self.expected_playlist_receipt_sha256 != self.playlist_receipt_sha256:
            raise ValueError("playlist receipt hash does not match the required input pin")
        if self.output_sha256 != _report_hash(self):
            raise ValueError("holdout output hash does not match its receipt content")
        return self


type ArtistPair = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _PositiveCohort:
    artists: tuple[str, ...]
    pair_potentials: frozenset[ArtistPair]
    positives: frozenset[ArtistPair]
    positive_targets: dict[str, frozenset[str]]


def evaluate_playlist_lastfm_matched_holdout(  # noqa: PLR0913  # Explicit sealed local inputs.
    *,
    playlist_receipt_path: Path,
    expected_playlist_receipt_sha256: str,
    lastfm_artifact_path: Path,
    lastfm_companion_receipt_path: Path,
    lastfm_database_path: Path,
    settings: PlaylistLastFmHoldoutSettings | None = None,
) -> PlaylistLastFmMatchedHoldout:
    """Evaluate receipt-derived JSPF positives against the sealed Last.fm aggregate."""
    resolved_settings = settings or PlaylistLastFmHoldoutSettings()
    pin = PlaylistDerivedReceiptPin(
        expected_playlist_receipt_sha256=expected_playlist_receipt_sha256
    )
    playlist_bytes, playlist = _load_pinned_playlist_receipt(
        playlist_receipt_path, expected_sha256=pin.expected_playlist_receipt_sha256
    )
    cohort = _positive_cohort(playlist, resolved_settings)
    try:
        lastfm = load_lastfm_360k_sealed_v1_envelope(
            artifact_path=lastfm_artifact_path,
            companion_receipt_path=lastfm_companion_receipt_path,
            database_path=lastfm_database_path,
        )
    except (LastFm360kProbeError, OSError, ValueError) as error:
        raise PlaylistLastFmHoldoutError("Last.fm aggregate receipt verification failed") from error
    supports = _read_pair_support(lastfm_database_path, cohort.pair_potentials)
    database_sha256 = _sha256_file(lastfm_database_path)
    if database_sha256 != lastfm.companion_receipt.working_database_sha256:
        raise PlaylistLastFmHoldoutError("Last.fm aggregate changed while evaluating")
    overlap = _overlap(cohort, supports)
    lastfm_metrics = _ranking_metrics(cohort, supports, use_lastfm_score=True)
    baseline_metrics = _ranking_metrics(cohort, supports, use_lastfm_score=False)
    placeholder = PlaylistLastFmMatchedHoldout.model_construct(
        playlist_coappearance_scope=playlist.coappearance_scope,
        expected_playlist_receipt_sha256=pin.expected_playlist_receipt_sha256,
        playlist_receipt_sha256=_sha256_bytes(playlist_bytes),
        playlist_bundle_sha256=playlist.source_playlist_bundle_file_sha256,
        lastfm_artifact_sha256=_sha256_file(lastfm_artifact_path),
        lastfm_companion_receipt_sha256=_sha256_file(lastfm_companion_receipt_path),
        lastfm_database_sha256=database_sha256,
        lastfm_pair_floor=lastfm.companion_receipt.working_database_pair_floor,
        settings=resolved_settings,
        overlap=overlap,
        lastfm_ranking=lastfm_metrics,
        deterministic_baseline=baseline_metrics,
        output_sha256="0" * 64,
    )
    payload = placeholder.model_dump(mode="json")
    payload["output_sha256"] = _report_hash(placeholder)
    return PlaylistLastFmMatchedHoldout.model_validate_json(json.dumps(payload))


def _load_pinned_playlist_receipt(
    path: Path, *, expected_sha256: Sha256
) -> tuple[bytes, ListenBrainzPlaylistEmbeddedArtistIdsArtifact]:
    """Hash raw receipt bytes before parsing the existing derived measurement."""
    try:
        receipt_bytes = path.read_bytes()
    except OSError as error:
        raise PlaylistLastFmHoldoutError("playlist source receipt is unavailable") from error
    if _sha256_bytes(receipt_bytes) != expected_sha256:
        raise PlaylistLastFmHoldoutError("playlist source receipt does not match the required hash")
    try:
        receipt = ListenBrainzPlaylistEmbeddedArtistIdsArtifact.model_validate_json(receipt_bytes)
    except ValueError as error:
        raise PlaylistLastFmHoldoutError("playlist source receipt is invalid") from error
    return receipt_bytes, receipt


def _positive_cohort(
    receipt: ListenBrainzPlaylistEmbeddedArtistIdsArtifact,
    settings: PlaylistLastFmHoldoutSettings,
) -> _PositiveCohort:
    playlist_ids_by_pair = _playlist_ids_by_pair(receipt)
    pair_potentials = frozenset(playlist_ids_by_pair)
    artists = tuple(
        sorted(
            {
                str(artist)
                for occurrence in receipt.claims_by_occurrence
                for artist in occurrence.source_claimed_artist_mbids
            }
        )
    )
    pair_endpoint_artists = {artist for pair in pair_potentials for artist in pair}
    if not pair_endpoint_artists <= set(artists):
        raise PlaylistLastFmHoldoutError("JSPF pair endpoint is absent from source artist universe")
    if len(artists) > settings.maximum_artist_count:
        raise PlaylistLastFmHoldoutError("JSPF artist cohort exceeds local bound")
    if len(pair_potentials) > settings.maximum_pair_potentials:
        raise PlaylistLastFmHoldoutError("JSPF pair cohort exceeds local bound")
    positives = frozenset(
        pair
        for pair, playlist_ids in playlist_ids_by_pair.items()
        if len(playlist_ids) >= settings.minimum_distinct_playlists_per_positive
    )
    if not positives:
        raise PlaylistLastFmHoldoutError("JSPF receipt has no predeclared repeat positives")
    targets: dict[str, set[str]] = defaultdict(set)
    for left_artist, right_artist in positives:
        targets[left_artist].add(right_artist)
        targets[right_artist].add(left_artist)
    return _PositiveCohort(
        artists=artists,
        pair_potentials=pair_potentials,
        positives=positives,
        positive_targets={artist: frozenset(values) for artist, values in targets.items()},
    )


def _playlist_ids_by_pair(
    receipt: ListenBrainzPlaylistEmbeddedArtistIdsArtifact,
) -> dict[ArtistPair, set[UUID]]:
    by_playlist: dict[UUID, list[tuple[UUID, tuple[UUID, ...]]]] = defaultdict(list)
    for occurrence in receipt.claims_by_occurrence:
        by_playlist[occurrence.playlist_mbid].append(
            (occurrence.recording_mbid, occurrence.source_claimed_artist_mbids)
        )
    playlist_ids_by_pair: dict[ArtistPair, set[UUID]] = defaultdict(set)
    for playlist_id, occurrences in by_playlist.items():
        for (left_recording, left_artists), (right_recording, right_artists) in combinations(
            occurrences, 2
        ):
            if left_recording == right_recording:
                continue
            for left_artist in left_artists:
                for right_artist in right_artists:
                    if left_artist != right_artist:
                        playlist_ids_by_pair[_pair(str(left_artist), str(right_artist))].add(
                            playlist_id
                        )
    return playlist_ids_by_pair


def _read_pair_support(database_path: Path, pairs: Iterable[ArtistPair]) -> dict[ArtistPair, int]:
    supports: dict[ArtistPair, int] = {}
    try:
        with closing(
            sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
        ) as database:
            for pair in pairs:
                row = database.execute(
                    """SELECT distinct_user_count FROM pair_support
                       WHERE left_artist = ? AND right_artist = ?""",
                    pair,
                ).fetchone()
                if row is not None:
                    supports[pair] = int(row[0])
    except sqlite3.Error as error:
        raise PlaylistLastFmHoldoutError("cannot read sealed Last.fm pair aggregate") from error
    return supports


def _overlap(cohort: _PositiveCohort, supports: dict[ArtistPair, int]) -> PairOverlap:
    all_supported = len(supports)
    recovered = sum(pair in supports for pair in cohort.positives)
    return PairOverlap(
        jspf_artist_count=len(cohort.artists),
        pair_endpoint_artist_count=len(
            {artist for pair in cohort.pair_potentials for artist in pair}
        ),
        jspf_pair_potential_count=len(cohort.pair_potentials),
        repeat_positive_pair_count=len(cohort.positives),
        lastfm_supported_jspf_pair_count=all_supported,
        lastfm_supported_jspf_pair_rate=all_supported / len(cohort.pair_potentials),
        lastfm_recovered_positive_pair_count=recovered,
        lastfm_unsupported_positive_pair_count=len(cohort.positives) - recovered,
        lastfm_recovered_positive_pair_rate=recovered / len(cohort.positives),
    )


def _ranking_metrics(
    cohort: _PositiveCohort, supports: dict[ArtistPair, int], *, use_lastfm_score: bool
) -> RankingMetrics:
    positive_count = sum(len(targets) for targets in cohort.positive_targets.values())
    recalled = {1: 0, 5: 0, 10: 0}
    macro = {1: [], 5: [], 10: []}
    reciprocal_ranks: list[float] = []
    positive_ranks: list[int] = []
    for anchor, targets in cohort.positive_targets.items():
        ranking = _rank_candidates(
            anchor, cohort.artists, supports, use_lastfm_score=use_lastfm_score
        )
        ranks = {artist: index for index, artist in enumerate(ranking, start=1)}
        for cutoff in recalled:
            hits = sum(ranks[target] <= cutoff for target in targets)
            recalled[cutoff] += hits
            macro[cutoff].append(hits / len(targets))
        for target in targets:
            rank = ranks[target]
            reciprocal_ranks.append(1 / rank)
            positive_ranks.append(rank)
    return RankingMetrics(
        positive_anchor_count=len(cohort.positive_targets),
        directed_positive_count=positive_count,
        candidate_count_per_anchor=len(cohort.artists) - 1,
        recalled_at_1=recalled[1],
        recalled_at_5=recalled[5],
        recalled_at_10=recalled[10],
        recall_at_1=recalled[1] / positive_count,
        recall_at_5=recalled[5] / positive_count,
        recall_at_10=recalled[10] / positive_count,
        macro_recall_at_1=fsum(macro[1]) / len(macro[1]),
        macro_recall_at_5=fsum(macro[5]) / len(macro[5]),
        macro_recall_at_10=fsum(macro[10]) / len(macro[10]),
        mean_reciprocal_rank=fsum(reciprocal_ranks) / positive_count,
        mean_positive_rank=fsum(positive_ranks) / positive_count,
    )


def _rank_candidates(
    anchor: str,
    artists: tuple[str, ...],
    supports: dict[ArtistPair, int],
    *,
    use_lastfm_score: bool,
) -> tuple[str, ...]:
    candidates = (artist for artist in artists if artist != anchor)
    if use_lastfm_score:
        return tuple(
            sorted(
                candidates,
                key=lambda artist: (
                    -supports.get(_pair(anchor, artist), 0),
                    _baseline_order(anchor, artist),
                    artist,
                ),
            )
        )
    return tuple(sorted(candidates, key=lambda artist: (_baseline_order(anchor, artist), artist)))


def _baseline_order(anchor: str, candidate: str) -> str:
    return hashlib.sha256(f"{_BASELINE_SEED}\0{anchor}\0{candidate}".encode()).hexdigest()


def _pair(left_artist: str, right_artist: str) -> ArtistPair:
    return (
        (left_artist, right_artist) if left_artist < right_artist else (right_artist, left_artist)
    )


def _sha256_bytes(data: bytes) -> Sha256:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_hash(report: PlaylistLastFmMatchedHoldout) -> Sha256:
    canonical = json.dumps(
        report.model_dump(mode="json", exclude={"output_sha256"}),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _sha256_bytes(canonical)
