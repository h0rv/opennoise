"""Query verified local MusicBrainz Album examples by exact genre or artist MBID."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from opennoise.ingest.musicbrainz.release_group_album_examples import (
    AlbumExample,
    ReleaseGroupAlbumExamplesReport,
    SeedAlbumExamples,
    verify_release_group_album_examples,
)
from opennoise.serving.local.musicbrainz_artist_metadata import (
    CertifiedLocalArtistMetadataSources,
    LocalArtistMetadataSources,
    certify_local_artist_metadata_sources,
    exact_certified_canonical_names,
    load_artist_metadata_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path


class AlbumDiscoveryError(ValueError):
    """Raised when local Album examples or optional artist metadata cannot be verified."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class AlbumDiscoveryCredit(_FrozenModel):
    """A credited artist ID and an optional exact, verified canonical name."""

    artist_mbid: str
    canonical_name: str | None
    role: str = "credited_artist_context"


class AlbumDiscoveryResult(_FrozenModel):
    """An Album example with its source roles and limits stated explicitly."""

    matched_by: str
    query: str
    seed_source_item_id: str
    normalized_seed_name: str
    genre_name: str
    genre_mbid: str
    genre_vote_count: int
    source_type: str
    record_content_sha256: str
    album_title: str
    first_release_date: str | None
    release_group_mbid: str
    secondary_types: tuple[str, ...]
    credited_artists: tuple[AlbumDiscoveryCredit, ...]
    genre_role: str = "native_proper_genre_observation"
    album_role: str = "ranked_source_context_example"
    defines_genre: bool = False
    asserts_artist_membership: bool = False


class AlbumDiscoveryResponse(_FrozenModel):
    """Deterministic local-only query response."""

    revision: str = "musicbrainz-album-discovery-query-v1"
    local_only: bool = True
    source_report_sha256: str
    result_count: int
    results: tuple[AlbumDiscoveryResult, ...]


def load_album_examples_report(path: Path) -> ReleaseGroupAlbumExamplesReport:
    """Load and replay the logical hash of one local Album example report."""
    try:
        report = ReleaseGroupAlbumExamplesReport.model_validate_json(path.read_bytes())
        verify_release_group_album_examples(report)
    except (OSError, ValueError) as error:
        raise AlbumDiscoveryError("Album examples report is invalid") from error
    return report


def load_verified_artist_metadata(
    database: Path, artifact_path: Path
) -> CertifiedLocalArtistMetadataSources:
    """Load and certify an optional local exact-ID artist metadata database."""
    try:
        artifact = load_artist_metadata_artifact(artifact_path)
        return certify_local_artist_metadata_sources(LocalArtistMetadataSources(database, artifact))
    except (OSError, ValueError) as error:
        raise AlbumDiscoveryError("artist metadata is invalid") from error


def query_album_examples(
    report: ReleaseGroupAlbumExamplesReport,
    *,
    genre_name: str | None = None,
    artist_mbid: str | None = None,
    artist_metadata: CertifiedLocalArtistMetadataSources | None = None,
) -> AlbumDiscoveryResponse:
    """Return report-ordered exact-name or exact credited-artist matches."""
    verify_release_group_album_examples(report)
    if (genre_name is None) == (artist_mbid is None):
        raise AlbumDiscoveryError("provide exactly one exact genre name or artist MBID")
    if artist_mbid is not None and artist_metadata is not None and not artist_metadata.is_valid():
        raise AlbumDiscoveryError("artist metadata is not startup-certified")

    matched_by = "genre_name" if genre_name is not None else "artist_mbid"
    query = genre_name if genre_name is not None else artist_mbid
    if query is None:
        raise AlbumDiscoveryError("query value is missing")
    matched_examples: list[tuple[SeedAlbumExamples, AlbumExample]] = []
    for seed in report.seed_rows:
        for example in seed.examples:
            if genre_name is not None:
                matches = example.genre_name == genre_name
            else:
                matches = artist_mbid in tuple(
                    credit.artist_mbid for credit in example.credited_artist_mbids
                )
            if not matches:
                continue
            matched_examples.append((seed, example))

    artist_mbids = tuple(
        dict.fromkeys(
            credit.artist_mbid
            for _, example in matched_examples
            for credit in example.credited_artist_mbids
        )
    )
    canonical_names = (
        exact_certified_canonical_names(artist_metadata, artist_mbids)
        if artist_metadata is not None
        else {}
    )
    results: list[AlbumDiscoveryResult] = []
    for seed, example in matched_examples:
        artist_entries = tuple(
            AlbumDiscoveryCredit(
                artist_mbid=credit.artist_mbid,
                canonical_name=canonical_names.get(credit.artist_mbid),
            )
            for credit in example.credited_artist_mbids
        )
        results.append(
            AlbumDiscoveryResult(
                matched_by=matched_by,
                query=query,
                seed_source_item_id=seed.seed_source_item_id,
                normalized_seed_name=seed.normalized_seed_name,
                genre_name=example.genre_name,
                genre_mbid=example.genre_mbid,
                genre_vote_count=example.genre_vote_count,
                source_type=example.source_type,
                record_content_sha256=example.record_content_sha256,
                album_title=example.title,
                first_release_date=example.first_release_date,
                release_group_mbid=example.release_group_mbid,
                secondary_types=example.secondary_types,
                credited_artists=artist_entries,
            )
        )
    return AlbumDiscoveryResponse(
        source_report_sha256=report.output_sha256,
        result_count=len(results),
        results=tuple(results),
    )


def response_json(response: AlbumDiscoveryResponse) -> str:
    """Serialize a response as stable compact JSON."""
    return json.dumps(
        response.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
