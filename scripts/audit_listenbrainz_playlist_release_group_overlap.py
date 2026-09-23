"""Join the retained playlist cohort to exact local release-group genre/tag facts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    NativeReleaseGroupEvidence,
    PlaylistReleaseGroupOverlap,
    exact_catalog_paths,
    exact_recording_ids,
    join_native_evidence,
    load_playlist_occurrences,
    require_sha256,
    sha256_file,
)
from opennoise.ingest.musicbrainz.entity_genre_observation import write_local_report_once
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    NativeGenreObservation,
    NativeTagObservation,
)
from opennoise.models.pipeline import SourceLimits
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.source_cache import (
    load_source_cache_receipt,
    receipt_sha256,
    verify_source_cache_receipt,
)
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup, _iter_raw_archive

_ARCHIVE_SHA256 = "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"
_ARCHIVE_BYTES = 1_159_485_640
_ARCHIVE_RECEIPT_SHA256 = "2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde"
_MANIFEST_SHA256 = "86c1658c7713ed2629d6f03a364fdfcbaa719cdbea06e79538722217a75f0064"
_BUNDLE_SHA256 = "2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c"
_CANDIDATE_CATALOG_SHA256 = "100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63"
_PUBLIC_CATALOG_SHA256 = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_ARCHIVE = Path(
    ".cache/musicbrainz-release-group-source-objects/source-artifacts/sha256/" + _ARCHIVE_SHA256
)
_BUNDLE = Path(".cache/listenbrainz-public-playlist-probe-20260923/snapshots.json")
_RAW_PLAYLISTS = Path(".cache/listenbrainz-public-playlist-probe-20260923/raw/sha256")
_CATALOG = Path(
    ".cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite"
)
_PUBLIC_CATALOG = Path("data/public.sqlite")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ExactOverlapReport(_FrozenModel):
    """Local-only receipt for exact playlist recording-to-release-group evidence."""

    revision: Literal["listenbrainz-playlist-release-group-overlap-v1"] = (
        "listenbrainz-playlist-release-group-overlap-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    genre_membership_inferred_from_playlist: Literal[False] = False
    playlist_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    playlist_count: int = Field(ge=1)
    playlist_unique_recording_count: int = Field(ge=1)
    curator_status: Literal["unknown"] = "unknown"
    membership_source_role: Literal["listenbrainz_playlist_track"] = "listenbrainz_playlist_track"
    musicbrainz_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_recording_count: int = Field(ge=0)
    exact_recording_overlap_count: int = Field(ge=0)
    exact_release_group_path_count: int = Field(ge=0)
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_catalog_recording_count: int = Field(ge=0)
    public_catalog_exact_recording_overlap_count: int = Field(ge=0)
    release_group_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_group_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_records_seen: int = Field(ge=0)
    archive_records_malformed: int = Field(ge=0)
    archive_records_over_limit: int = Field(ge=0)
    requested_release_group_count: int = Field(ge=0)
    found_release_group_count: int = Field(ge=0)
    target_groups_with_proper_genres: int = Field(ge=0)
    target_proper_genre_observation_count: int = Field(ge=0)
    target_positive_tag_observation_count: int = Field(ge=0)
    overlaps: tuple[PlaylistReleaseGroupOverlap, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def report_sha256(report: ExactOverlapReport) -> str:
    """Return the deterministic report hash excluding its self-reference."""
    payload = json.dumps(
        report.model_dump(mode="json", exclude={"output_sha256"}),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _scan_archive(
    archive: Path, targets: frozenset[UUID]
) -> tuple[tuple[NativeReleaseGroupEvidence, ...], int, int, int]:
    """Read the pinned release-group member and retain facts for exact target IDs only."""
    evidence = []
    seen: set[UUID] = set()
    records_seen = malformed = over_limit = 0
    for raw in _iter_raw_archive(
        archive,
        SourceLimits(max_archive_bytes=2 * 1024**3, max_record_bytes=2 * 1024**2),
        member_name="release-group",
    ):
        records_seen += 1
        if raw.payload is None:
            over_limit += 1
            continue
        try:
            group = MusicBrainzReleaseGroup.model_validate_json(raw.payload)
        except ValueError:
            malformed += 1
            continue
        if group.id not in targets:
            continue
        if group.id in seen:
            raise ValueError(f"release-group archive repeats target UUID {group.id}")
        seen.add(group.id)
        evidence.append(
            NativeReleaseGroupEvidence(
                release_group_mbid=group.id,
                record_content_sha256=raw.sha256,
                proper_genres=tuple(
                    NativeGenreObservation(
                        genre_mbid=str(genre.id), name=genre.name, vote_count=genre.count
                    )
                    for genre in group.genres
                ),
                positive_tags=tuple(
                    NativeTagObservation(name=tag.name, vote_count=tag.count)
                    for tag in group.tags
                    if tag.count is not None and tag.count > 0
                ),
            )
        )
    return tuple(evidence), records_seen, malformed, over_limit


def build_report(  # noqa: PLR0913, PLR0917
    archive: Path,
    bundle_path: Path,
    raw_playlist_directory: Path,
    catalog_path: Path,
    source_cache_receipt_path: Path,
    manifest_path: Path,
) -> ExactOverlapReport:
    """Validate local source receipts, exact-join IDs, and scan target groups."""
    archive_digest = sha256_file(archive)
    require_sha256(archive_digest, _ARCHIVE_SHA256, "release-group archive")
    if archive.stat().st_size != _ARCHIVE_BYTES:
        raise ValueError("release-group archive byte length differs from its pinned source")
    source = load_download_source(manifest_path, "musicbrainz_json_release_group_research_20260905")
    receipt = load_source_cache_receipt(source_cache_receipt_path)
    require_sha256(receipt_sha256(receipt), _ARCHIVE_RECEIPT_SHA256, "source-cache receipt")
    if receipt.declared_manifest_sha256 != _MANIFEST_SHA256:
        raise ValueError("source-cache receipt refers to an unexpected source manifest")
    verify_source_cache_receipt(receipt, (source,), declared_manifest_sha256=_MANIFEST_SHA256)
    bundle_hash, bundle, occurrences = load_playlist_occurrences(
        bundle_path, raw_playlist_directory
    )
    require_sha256(bundle_hash, _BUNDLE_SHA256, "playlist bundle")
    recording_ids = frozenset(item.recording_mbid for item in occurrences)
    catalog_hash, identities = exact_catalog_paths(catalog_path, recording_ids)
    require_sha256(catalog_hash, _CANDIDATE_CATALOG_SHA256, "artist-credit catalog")
    public_hash, public_recordings = exact_recording_ids(_PUBLIC_CATALOG)
    require_sha256(public_hash, _PUBLIC_CATALOG_SHA256, "public catalog")
    candidate_recordings = exact_recording_ids(catalog_path)[1]
    target_groups = frozenset(item.release_group_mbid for item in identities)
    evidence, records_seen, malformed, over_limit = _scan_archive(archive, target_groups)
    overlaps = join_native_evidence(occurrences, identities, evidence)
    preliminary = ExactOverlapReport(
        playlist_bundle_sha256=bundle_hash,
        playlist_count=len(bundle.snapshots),
        playlist_unique_recording_count=len(recording_ids),
        musicbrainz_catalog_sha256=catalog_hash,
        catalog_recording_count=len(candidate_recordings),
        exact_recording_overlap_count=len(recording_ids & candidate_recordings),
        exact_release_group_path_count=len(identities),
        release_group_archive_sha256=archive_digest,
        release_group_archive_bytes=archive.stat().st_size,
        public_catalog_sha256=public_hash,
        public_catalog_recording_count=len(public_recordings),
        public_catalog_exact_recording_overlap_count=len(recording_ids & public_recordings),
        source_cache_receipt_sha256=receipt_sha256(receipt),
        archive_records_seen=records_seen,
        archive_records_malformed=malformed,
        archive_records_over_limit=over_limit,
        requested_release_group_count=len(target_groups),
        found_release_group_count=len(evidence),
        target_groups_with_proper_genres=sum(bool(item.proper_genres) for item in evidence),
        target_proper_genre_observation_count=sum(len(item.proper_genres) for item in evidence),
        target_positive_tag_observation_count=sum(len(item.positive_tags) for item in evidence),
        overlaps=overlaps,
        output_sha256="0" * 64,
    )
    report = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
    if report_sha256(report) != report.output_sha256:
        raise ValueError("overlap report hash failed replay")
    return report


def main() -> int:
    """Write the local-only exact-overlap report once."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=_ARCHIVE)
    parser.add_argument("--playlist-bundle", type=Path, default=_BUNDLE)
    parser.add_argument("--playlist-raw-directory", type=Path, default=_RAW_PLAYLISTS)
    parser.add_argument("--catalog", type=Path, default=_CATALOG)
    parser.add_argument(
        "--source-cache-receipt",
        type=Path,
        default=Path(".cache/musicbrainz-release-group-source-receipt.json"),
    )
    parser.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".cache/listenbrainz-playlist-release-group-overlap-v1/report.json"),
    )
    arguments = parser.parse_args()
    report = build_report(
        arguments.archive,
        arguments.playlist_bundle,
        arguments.playlist_raw_directory,
        arguments.catalog,
        arguments.source_cache_receipt,
        arguments.manifest,
    )
    write_local_report_once(
        cache_root=Path(".cache"),
        output=arguments.output,
        payload=(report.model_dump_json(indent=2) + "\n").encode(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
