"""Measure bounded exact-credit playlist pair support in local custody only.

The measurement is deliberately limited to the receipt-bound recording sample
already resolved by the MusicBrainz artist-credit bridge.  It makes no claim
about a playlist's curator, quality, genre, or population-level similarity.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from itertools import combinations
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.analysis.lastfm_360k import (
    LastFm360kProbeError,
    load_lastfm_360k_sealed_v1_envelope,
)
from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,
)
from opennoise.analysis.listenbrainz_playlist_user_created_cohort import (
    ListenBrainzUserCreatedPlaylistCohort,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_MAXIMUM_PLAYLISTS = 50
_MAXIMUM_PAIR_POTENTIALS = 100_000
_REPEATED_PAIR_PLAYLIST_FLOOR = 2

type ArtistPair = tuple[str, str]


class PlaylistSignalQualityError(ValueError):
    """The exact-credit local signal audit cannot safely continue."""


class PlaylistExactCreditPairCoverage(FrozenModel):
    """Counts derived only from exact artist credits in the bridge sample."""

    sampled_playlist_count: int = Field(ge=1, le=_MAXIMUM_PLAYLISTS)
    selected_recording_occurrence_count: int = Field(ge=0)
    exact_credit_recording_occurrence_count: int = Field(ge=0)
    exact_credit_artist_count: int = Field(ge=0)
    within_playlist_artist_pair_observation_count: int = Field(ge=0)
    distinct_within_playlist_artist_pair_count: int = Field(ge=0)
    pairs_supported_by_two_or_more_playlists: int = Field(ge=0)
    maximum_distinct_playlist_support_per_pair: int = Field(ge=0)


class PlaylistLastFmPairComparison(FrozenModel):
    """Counts-only overlap with an already sealed local Last.fm aggregate."""

    performed: Literal[True] = True
    artifact_sha256: Sha256
    companion_receipt_sha256: Sha256
    database_sha256: Sha256
    privacy_pair_floor: int = Field(ge=5)
    exact_credit_pairs_found_in_lastfm: int = Field(ge=0)
    exact_credit_pair_lastfm_support_rate: float = Field(ge=0.0, le=1.0)
    maximum_lastfm_distinct_user_support: int = Field(ge=0)


class PlaylistSignalQualityAudit(FrozenModel):
    """Self-hashing local audit of one account-scoped exact-credit sample."""

    revision: Literal["listenbrainz-playlist-signal-quality-audit-v1"] = (
        "listenbrainz-playlist-signal-quality-audit-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    independent_genre_evaluation_eligible: Literal[False] = False
    human_curation_claim_made: Literal[False] = False
    manual_or_editorial_curation_claim_made: Literal[False] = False
    cross_account_claim_made: Literal[False] = False
    source_scope: Literal["within_one_service_listed_account_playlist_cohort"] = (
        "within_one_service_listed_account_playlist_cohort"
    )
    curator_state: Literal["unknown_for_every_sampled_playlist"] = (
        "unknown_for_every_sampled_playlist"
    )
    cohort_sha256: Sha256
    artist_bridge_sha256: Sha256
    source_playlist_bundle_sha256: Sha256
    pair_support_definition: Literal[
        "distinct_playlists_within_the_exact_credit_recording_sample"
    ] = "distinct_playlists_within_the_exact_credit_recording_sample"
    exact_credit_coverage: PlaylistExactCreditPairCoverage
    lastfm_comparison: PlaylistLastFmPairComparison | None = None
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_replayable_and_bounded_claims(self) -> PlaylistSignalQualityAudit:
        """Keep the report hash and the source limitations inseparable."""
        if self.output_sha256 != _report_hash(self):
            raise ValueError("playlist signal audit hash does not match receipt content")
        return self


def audit_playlist_signal_quality(  # noqa: PLR0913
    *,
    cohort_path: Path,
    expected_cohort_sha256: str,
    artist_bridge_path: Path,
    expected_artist_bridge_sha256: str,
    lastfm_artifact_path: Path | None = None,
    lastfm_companion_receipt_path: Path | None = None,
    lastfm_database_path: Path | None = None,
) -> PlaylistSignalQualityAudit:
    """Measure exact-credit playlist support and optionally compare sealed local support."""
    cohort_bytes, cohort = _load_cohort(cohort_path, expected_cohort_sha256)
    bridge_bytes, bridge = _load_bridge(artist_bridge_path, expected_artist_bridge_sha256)
    _verify_bridge_belongs_to_cohort(cohort, bridge)
    pairs_by_playlist = _pairs_by_playlist(bridge)
    coverage = _coverage(bridge, pairs_by_playlist)
    lastfm = _lastfm_comparison(
        pairs_by_playlist,
        artifact_path=lastfm_artifact_path,
        companion_receipt_path=lastfm_companion_receipt_path,
        database_path=lastfm_database_path,
    )
    placeholder = PlaylistSignalQualityAudit.model_construct(
        cohort_sha256=_sha256_bytes(cohort_bytes),
        artist_bridge_sha256=_sha256_bytes(bridge_bytes),
        source_playlist_bundle_sha256=cohort.source_snapshot_bundle_file_sha256,
        exact_credit_coverage=coverage,
        lastfm_comparison=lastfm,
        output_sha256="0" * 64,
    )
    payload = placeholder.model_dump(mode="json")
    payload["output_sha256"] = _report_hash(placeholder)
    return PlaylistSignalQualityAudit.model_validate(payload)


def _load_pinned_bytes(path: Path, expected_sha256: str, kind: str) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise PlaylistSignalQualityError(f"{kind} receipt is unavailable") from error
    if _sha256_bytes(payload) != expected_sha256:
        raise PlaylistSignalQualityError(f"{kind} receipt does not match required hash")
    return payload


def _load_cohort(
    path: Path, expected_sha256: str
) -> tuple[bytes, ListenBrainzUserCreatedPlaylistCohort]:
    payload = _load_pinned_bytes(path, expected_sha256, "cohort")
    try:
        return payload, ListenBrainzUserCreatedPlaylistCohort.model_validate_json(payload)
    except ValueError as error:
        raise PlaylistSignalQualityError("cohort receipt is invalid") from error


def _load_bridge(
    path: Path, expected_sha256: str
) -> tuple[bytes, ListenBrainzPlaylistArtistBridgeArtifact]:
    payload = _load_pinned_bytes(path, expected_sha256, "bridge")
    try:
        return payload, ListenBrainzPlaylistArtistBridgeArtifact.model_validate_json(payload)
    except ValueError as error:
        raise PlaylistSignalQualityError("bridge receipt is invalid") from error


def _verify_bridge_belongs_to_cohort(
    cohort: ListenBrainzUserCreatedPlaylistCohort,
    bridge: ListenBrainzPlaylistArtistBridgeArtifact,
) -> None:
    selection = bridge.selection_receipt
    if selection.source_playlist_bundle_file_sha256 != cohort.source_snapshot_bundle_file_sha256:
        raise PlaylistSignalQualityError("artist bridge belongs to a different playlist bundle")
    if (
        tuple(pin.playlist_mbid for pin in selection.ordered_playlist_sources)
        != cohort.cohort_playlist_mbids
    ):
        raise PlaylistSignalQualityError("artist bridge does not preserve cohort playlist order")
    if cohort.human_curation_established or cohort.manual_or_editorial_curation_established:
        raise PlaylistSignalQualityError("cohort must retain route-only curation limits")
    if any(pin.curator_kind != "unknown" for pin in selection.ordered_playlist_sources):
        raise PlaylistSignalQualityError("artist bridge curator state is not route-only unknown")


def _pairs_by_playlist(
    bridge: ListenBrainzPlaylistArtistBridgeArtifact,
) -> dict[str, frozenset[ArtistPair]]:
    artists_by_recording = {
        lookup.requested_recording_id: tuple(
            str(artist) for artist in lookup.artist_credit_artist_ids
        )
        for lookup in bridge.lookups
        if lookup.outcome == "exact_match" and lookup.artist_credit_artist_ids
    }
    result: dict[str, frozenset[ArtistPair]] = {}
    for selected in bridge.selection_receipt.selected_recording_order_by_playlist:
        artists = frozenset(
            artist
            for recording_id in selected.selected_recording_ids
            for artist in artists_by_recording.get(recording_id, ())
        )
        result[str(selected.playlist_mbid)] = frozenset(
            _pair(left, right) for left, right in combinations(sorted(artists), 2)
        )
    return result


def _coverage(
    bridge: ListenBrainzPlaylistArtistBridgeArtifact,
    pairs_by_playlist: dict[str, frozenset[ArtistPair]],
) -> PlaylistExactCreditPairCoverage:
    pair_support: dict[ArtistPair, int] = defaultdict(int)
    for pairs in pairs_by_playlist.values():
        for pair in pairs:
            pair_support[pair] += 1
    pair_count = len(pair_support)
    if pair_count > _MAXIMUM_PAIR_POTENTIALS:
        raise PlaylistSignalQualityError("exact-credit pair measurement exceeds local bound")
    exact_artists = {
        str(artist)
        for lookup in bridge.lookups
        if lookup.outcome == "exact_match"
        for artist in lookup.artist_credit_artist_ids
    }
    exact_credit_recording_ids = {
        lookup.requested_recording_id
        for lookup in bridge.lookups
        if lookup.outcome == "exact_match" and lookup.artist_credit_artist_ids
    }
    return PlaylistExactCreditPairCoverage(
        sampled_playlist_count=len(pairs_by_playlist),
        selected_recording_occurrence_count=sum(
            len(item.selected_recording_ids)
            for item in bridge.selection_receipt.selected_recording_order_by_playlist
        ),
        exact_credit_recording_occurrence_count=sum(
            recording_id in exact_credit_recording_ids
            for item in bridge.selection_receipt.selected_recording_order_by_playlist
            for recording_id in item.selected_recording_ids
        ),
        exact_credit_artist_count=len(exact_artists),
        within_playlist_artist_pair_observation_count=sum(
            len(pairs) for pairs in pairs_by_playlist.values()
        ),
        distinct_within_playlist_artist_pair_count=pair_count,
        pairs_supported_by_two_or_more_playlists=sum(
            value >= _REPEATED_PAIR_PLAYLIST_FLOOR for value in pair_support.values()
        ),
        maximum_distinct_playlist_support_per_pair=max(pair_support.values(), default=0),
    )


def _lastfm_comparison(
    pairs_by_playlist: dict[str, frozenset[ArtistPair]],
    *,
    artifact_path: Path | None,
    companion_receipt_path: Path | None,
    database_path: Path | None,
) -> PlaylistLastFmPairComparison | None:
    if artifact_path is None and companion_receipt_path is None and database_path is None:
        return None
    if artifact_path is None or companion_receipt_path is None or database_path is None:
        raise PlaylistSignalQualityError("Last.fm comparison needs all three sealed local inputs")
    pairs = frozenset(pair for values in pairs_by_playlist.values() for pair in values)
    try:
        envelope = load_lastfm_360k_sealed_v1_envelope(
            artifact_path=artifact_path,
            companion_receipt_path=companion_receipt_path,
            database_path=database_path,
        )
        supports = _read_pair_support(database_path, pairs)
    except (LastFm360kProbeError, OSError, sqlite3.Error, ValueError) as error:
        raise PlaylistSignalQualityError("sealed Last.fm aggregate verification failed") from error
    database_sha256 = _sha256_file(database_path)
    if database_sha256 != envelope.companion_receipt.working_database_sha256:
        raise PlaylistSignalQualityError("Last.fm aggregate changed while measuring")
    return PlaylistLastFmPairComparison(
        artifact_sha256=_sha256_file(artifact_path),
        companion_receipt_sha256=_sha256_file(companion_receipt_path),
        database_sha256=database_sha256,
        privacy_pair_floor=envelope.companion_receipt.working_database_pair_floor,
        exact_credit_pairs_found_in_lastfm=len(supports),
        exact_credit_pair_lastfm_support_rate=len(supports) / len(pairs) if pairs else 0.0,
        maximum_lastfm_distinct_user_support=max(supports.values(), default=0),
    )


def _read_pair_support(path: Path, pairs: Iterable[ArtistPair]) -> dict[ArtistPair, int]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as database:
        return {
            pair: int(row[0])
            for pair in pairs
            if (
                row := database.execute(
                    """SELECT distinct_user_count FROM pair_support
                       WHERE left_artist = ? AND right_artist = ?""",
                    pair,
                ).fetchone()
            )
            is not None
        }


def _pair(left: str, right: str) -> ArtistPair:
    return (left, right) if left < right else (right, left)


def _sha256_bytes(payload: bytes) -> Sha256:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_hash(report: PlaylistSignalQualityAudit) -> Sha256:
    return _sha256_bytes(
        json.dumps(
            report.model_dump(mode="json", exclude={"output_sha256"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
