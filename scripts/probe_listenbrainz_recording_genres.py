"""Probe native MusicBrainz recording genres for the exact 11-ID overlap."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    exact_recording_ids,
    load_playlist_occurrences,
    require_sha256,
)
from opennoise.ingest.musicbrainz.entity_genre_observation import (
    EntityGenreObservationReport,
    EntityGenreSourceReceipt,
    RetainedEntityGenreResponse,
    build_entity_genre_observation_report,
    verify_entity_genre_observation_report,
    write_local_report_once,
)
from opennoise.ingest.musicbrainz.playlist_recording_genre_probe import (
    PLAYLIST_RECORDING_DENOMINATOR,
    exact_recording_overlap,
    summarize_recording_genres,
)
from opennoise.sources.musicbrainz import MusicBrainzClient

if TYPE_CHECKING:
    from uuid import UUID

_BUNDLE = Path(".cache/listenbrainz-public-playlist-probe-20260923/snapshots.json")
_RAW_PLAYLISTS = Path(".cache/listenbrainz-public-playlist-probe-20260923/raw/sha256")
_CATALOG = Path("data/public.sqlite")
_BUNDLE_SHA256 = "2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c"
_CATALOG_SHA256 = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_CACHE_ROOT = Path(".cache/musicbrainz-playlist-recording-genre-probe-v1")
_RESPONSES = _CACHE_ROOT / "responses"
_REPORT_PATH = _CACHE_ROOT / "report.json"
_SOURCE_PARTITION = "musicbrainz_ws2_playlist_recording_genres_20260923"
_SOURCE_SNAPSHOT = "20260923-local-playlist-recording-genre-query-001"
_USER_AGENT = "opennoise/0.1 (https://github.com/h0rv/opennoise)"
_EXPECTED_OVERLAP_COUNT = 11


def _target_ids() -> tuple[UUID, ...]:
    bundle_hash, _, occurrences = load_playlist_occurrences(_BUNDLE, _RAW_PLAYLISTS)
    require_sha256(bundle_hash, _BUNDLE_SHA256, "playlist bundle")
    if len({item.recording_mbid for item in occurrences}) != PLAYLIST_RECORDING_DENOMINATOR:
        raise ValueError("playlist cohort no longer contains the pinned 527 recording IDs")
    catalog_hash, catalog_ids = exact_recording_ids(_CATALOG)
    require_sha256(catalog_hash, _CATALOG_SHA256, "public MusicBrainz catalog")
    targets = exact_recording_overlap(
        frozenset(item.recording_mbid for item in occurrences), catalog_ids
    )
    if len(targets) != _EXPECTED_OVERLAP_COUNT:
        raise ValueError("exact playlist/catalog UUID overlap is no longer 11 recordings")
    return targets


def _response_path(recording_id: UUID) -> Path:
    return _RESPONSES / f"recording-{recording_id}.json"


def _load_retained(receipt: EntityGenreSourceReceipt) -> RetainedEntityGenreResponse:
    payload = _response_path(receipt.entity_mbid).read_bytes()
    return RetainedEntityGenreResponse(receipt=receipt, payload=payload)


def _load_saved_report() -> EntityGenreObservationReport:
    report = EntityGenreObservationReport.model_validate_json(_REPORT_PATH.read_bytes())
    verify_entity_genre_observation_report(report)
    return report


async def _fetch_report(target_ids: tuple[UUID, ...]) -> EntityGenreObservationReport:
    if _REPORT_PATH.exists() or _REPORT_PATH.is_symlink():
        raise FileExistsError(f"probe report already exists: {_REPORT_PATH}")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as http_client:
        client = MusicBrainzClient(http_client, user_agent=_USER_AGENT)
        retained: list[RetainedEntityGenreResponse] = []
        for recording_id in target_ids:
            response = await client.fetch_recording_response(recording_id)
            if response.recording.id != recording_id:
                raise ValueError("MusicBrainz response recording ID differs from requested UUID")
            receipt = EntityGenreSourceReceipt(
                source_partition=_SOURCE_PARTITION,
                source_snapshot=_SOURCE_SNAPSHOT,
                entity_kind="recording",
                entity_mbid=recording_id,
                request_url=response.request_url,
                response_sha256=hashlib.sha256(response.raw_bytes).hexdigest(),
            )
            retained.append(
                RetainedEntityGenreResponse(receipt=receipt, payload=response.raw_bytes)
            )
    report = build_entity_genre_observation_report(tuple(retained))
    for response in retained:
        write_local_report_once(
            cache_root=_CACHE_ROOT,
            output=_response_path(response.receipt.entity_mbid),
            payload=response.payload,
        )
    write_local_report_once(
        cache_root=_CACHE_ROOT,
        output=_REPORT_PATH,
        payload=(report.model_dump_json() + "\n").encode(),
    )
    return report


def _print_report(report: EntityGenreObservationReport) -> None:
    verify_entity_genre_observation_report(report)
    summary = summarize_recording_genres(report)
    sys.stdout.write(
        f"distinct native recording responses: {summary.observed_recordings}/527\n"
        f"proper recording genre observations: {summary.proper_genre_observations}\n"
        "positive recording tag observations (separate facet): "
        f"{summary.positive_tag_observations}\n"
        "recordings with at least one positive-count proper genre: "
        f"{summary.recordings_with_positive_proper_genre}/527; "
        f">2 recording threshold exceeded: {summary.recording_genre_coverage_threshold_exceeded}\n"
        f"local report: {_REPORT_PATH}\n"
        "export=false serving=false artist-membership-propagation=false\n"
    )


def main() -> int:
    """Fetch once or replay previously retained, receipt-bound responses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="make eleven sequential, rate-limited MusicBrainz recording requests",
    )
    args = parser.parse_args()
    targets = _target_ids()
    if args.fetch:
        report = asyncio.run(_fetch_report(targets))
    else:
        report = _load_saved_report()
        if {item.entity_mbid for item in report.source_receipts} != set(targets):
            raise ValueError("saved report receipts do not match the pinned 11 exact UUIDs")
        retained = tuple(_load_retained(receipt) for receipt in report.source_receipts)
        replayed = build_entity_genre_observation_report(retained)
        if replayed.output_sha256 != report.output_sha256:
            raise ValueError("saved responses do not replay to the sealed observation report")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
