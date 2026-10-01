"""Offline static release credits and track metadata beside exact direct observations.

An artist credit supplies release context, never a genre membership. This local
projection has no native release genres or album-supported seed evidence.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.musicbrainz_credit_portable_release import (
    PortableMusicBrainzCreditReleaseReceipt,
    PortableMusicBrainzCreditSource,
    restore_portable_musicbrainz_credit_catalog,
)
from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    ArtistCreditRefreshCandidateArtifact,
)
from opennoise.ingest.musicbrainz.release_hydration import (
    MusicBrainzReleaseHydrationArtifact,
)
from opennoise.storage import LocalObjectStore

if TYPE_CHECKING:
    from opennoise.ingest.musicbrainz.artist_credit_enrichment import CachedArtistCreditRelation

_ROOT: Final = Path(__file__).resolve().parents[3]
_RECEIPT: Final = (
    _ROOT / "config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json"
)
_STORE: Final = _ROOT / "data/release/musicbrainz-credit-catalog-v1/objects"
_GENRE_LIMIT: Final = 12
_DECLARATIONS: Final = {
    "revision": "local-musicbrainz-release-credit-context-v1",
    "scope": "local_research_only",
    "public_export_authorized": False,
    "artist_membership_inferred_from_context": False,
    "release_genre_membership_inferred_from_artist": False,
    "membership_claims_added": 0,
    "native_release_genres_available": False,
    "album_supported_seed_evidence": [],
    "heading": "Releases credited to source artists",
    "ordering": "exact_release_uuid_order_not_relevance",
    "identity_join": "exact_musicbrainz_uuid_only",
    "content_policy": "core_metadata_only_no_audio_preview_artwork_or_genres",
    "license": "CC0-1.0",
}


def _verified_source(
    receipt_path: Path, store_directory: Path
) -> tuple[PortableMusicBrainzCreditReleaseReceipt, PortableMusicBrainzCreditSource]:
    receipt = PortableMusicBrainzCreditReleaseReceipt.model_validate_json(receipt_path.read_bytes())
    store = LocalObjectStore(store_directory)
    metadata = store.inspect(receipt.source.key)
    if (metadata.sha256, metadata.byte_size) != (receipt.source.sha256, receipt.source.byte_size):
        raise CandidateCatalogError("portable release source bytes differ from its custody receipt")
    with tempfile.TemporaryDirectory(prefix="musicbrainz-release-context-") as temporary:
        root = Path(temporary)
        restore_portable_musicbrainz_credit_catalog(
            receipt,
            store=store,
            candidate_database=root / "catalog.sqlite",
            candidate_report=root / "report.json",
        )
        store.pull(receipt.source.key, root / "source.json")
        source = PortableMusicBrainzCreditSource.model_validate_json(
            (root / "source.json").read_bytes()
        )
    expected = (
        receipt.source_projection_count,
        receipt.hydration_artifact_sha256,
        receipt.credit_artifact_sha256,
        receipt.candidate_database_sha256,
        receipt.candidate_report_sha256,
    )
    if (
        len(source.projections),
        source.hydration_artifact_sha256,
        source.credit_artifact_sha256,
        source.candidate_database_sha256,
        source.candidate_report_sha256,
    ) != expected:
        raise CandidateCatalogError(
            "portable release source does not replay its complete custody chain"
        )
    return receipt, source


def _credit_payload(relation: CachedArtistCreditRelation) -> dict[str, object]:
    return {
        "members": [member.model_dump(mode="json") for member in relation.members],
        "source_endpoint": relation.source_endpoint,
        "projection_sha256": relation.projection_sha256,
        "observed_response_sha256": relation.observed_response_sha256,
    }


def _release_rows(source: PortableMusicBrainzCreditSource) -> list[dict[str, object]]:
    credit_artifact = ArtistCreditRefreshCandidateArtifact.model_validate_json(
        source.credit_artifact_json
    )
    by_identity = {(row.entity_kind, str(row.entity_id)): row for row in credit_artifact.credits}
    hydration = MusicBrainzReleaseHydrationArtifact.model_validate_json(
        source.hydration_artifact_json
    )
    core_by_release = {str(row.release_id): row for row in hydration.releases}
    rows: list[dict[str, object]] = []
    for projection in source.projections:
        release = core_by_release[projection.endpoint.removeprefix("release/")]
        release_credit = by_identity[("release", str(release.release_id))]
        tracks: list[dict[str, object]] = []
        artist_roles: dict[str, set[str]] = {}
        for member in release_credit.members:
            artist_roles.setdefault(str(member.artist_id), set()).add("release_artist_credit")
        for medium in sorted(release.media, key=lambda row: row.position):
            for track in sorted(medium.tracks, key=lambda row: row.position):
                recording_credit = by_identity[("recording", str(track.recording_id))]
                for member in recording_credit.members:
                    artist_roles.setdefault(str(member.artist_id), set()).add(
                        "recording_artist_credit"
                    )
                tracks.append(
                    {
                        "track_mbid": str(track.track_id),
                        "recording_mbid": str(track.recording_id),
                        "medium_position": medium.position,
                        "position": track.position,
                        "number": track.number,
                        "title": track.title,
                        "recording_title": None,
                        "duration_ms": track.duration_ms,
                        "recording_duration_ms": track.recording_duration_ms,
                        "recording_artist_credit": _credit_payload(recording_credit),
                        "semantics": "track_metadata_not_playable_media",
                    }
                )
        rows.append(
            {
                "release_mbid": str(release.release_id),
                "release_group_mbid": str(release.release_group_id),
                "title": release.title,
                "release_group_title": release.release_group_title,
                "date": release.date,
                "year": int(release.date[:4])
                if release.date and re.match(r"^\d{4}", release.date)
                else None,
                "year_scope": "concrete_release_date_not_original_album_date",
                "country": release.country,
                "status": release.status,
                "release_artist_credit": _credit_payload(release_credit),
                "media": [
                    {
                        "position": medium.position,
                        "format": medium.format,
                        "track_count": medium.track_count,
                    }
                    for medium in release.media
                ],
                "tracks": tracks,
                "credited_artists": [
                    {"artist_mbid": identity, "credit_roles": sorted(roles)}
                    for identity, roles in sorted(artist_roles.items())
                ],
                "source_endpoint": projection.endpoint,
                "projection_sha256": projection.projection_sha256,
                "observed_response_sha256": projection.response_sha256,
                "core_metadata_artifact_sha256": source.hydration_artifact_sha256,
                "core_metadata_response_sha256": next(
                    evidence.response_sha256
                    for evidence in release.evidence
                    if evidence.endpoint == projection.endpoint
                ),
            }
        )
    return rows


def _direct_claims(
    directory: Path, credited_artist_ids: set[str]
) -> dict[str, dict[str, list[dict[str, object]]]]:
    database = directory / "catalog.sqlite"
    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for seed, artist, genre, record, sha, reference in connection.execute(
            "SELECT seed_id,artist_mbid,musicbrainz_genre_id,source_record_id,"
            "source_record_sha256,source_evidence_ref FROM direct_claim "
            "ORDER BY seed_id,artist_mbid,musicbrainz_genre_id,"
            "source_record_sha256,source_evidence_ref"
        ):
            if str(artist) not in credited_artist_ids:
                continue
            grouped.setdefault(str(artist), {}).setdefault(str(seed), []).append(
                {
                    "seed_id": seed,
                    "artist_mbid": artist,
                    "musicbrainz_genre_id": genre,
                    "facet": "artist_direct_proper_genre",
                    "source_record_id": record,
                    "source_record_sha256": sha,
                    "source_evidence_ref": reference,
                }
            )
    return grouped


def _payloads(
    catalog_directory: Path, credit_receipt_path: Path, credit_object_store: Path
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    receipt, source = _verified_source(credit_receipt_path, credit_object_store)
    releases = _release_rows(source)
    credited_artist_ids = {
        str(credit["artist_mbid"])
        for row in releases
        for credit in TypeAdapter(list[dict[str, object]]).validate_python(row["credited_artists"])
    }
    direct = _direct_claims(catalog_directory, credited_artist_ids)
    bindings: dict[str, object] = {
        "direct_catalog_output_sha256": catalog.output_sha256,
        "direct_object_sha256": catalog.direct_object_sha256,
        "credit_receipt_byte_sha256": sha256_file(credit_receipt_path)[0],
        "credit_source_sha256": receipt.source_sha256,
        "credit_database_sha256": receipt.candidate_database_sha256,
        "credit_artifact_sha256": receipt.credit_artifact_sha256,
    }
    artist_releases: dict[str, list[dict[str, object]]] = {}
    genre_releases: dict[str, list[dict[str, object]]] = {}
    for release in releases:
        credited = TypeAdapter(list[dict[str, object]]).validate_python(release["credited_artists"])
        matched_by_seed: dict[str, list[dict[str, object]]] = {}
        for credit in credited:
            identity = str(credit["artist_mbid"])
            if identity not in direct:
                continue
            artist_releases.setdefault(identity, []).append(
                {
                    **release,
                    "queried_artist_mbid": identity,
                    "queried_artist_credit_roles": credit["credit_roles"],
                }
            )
            for seed, observations in direct[identity].items():
                matched_by_seed.setdefault(seed, []).append(
                    {
                        "artist_mbid": identity,
                        "credit_roles": credit["credit_roles"],
                        "direct_artist_seed_observations": observations,
                    }
                )
        for seed, matched in matched_by_seed.items():
            genre_releases.setdefault(seed, []).append(
                {
                    **release,
                    "matched_source_artists": matched,
                    "relation": "release_credit_to_artist_with_separate_direct_seed_observation",
                }
            )
    payloads = _context_payloads(artist_releases, genre_releases, bindings)
    summary = {
        **_DECLARATIONS,
        **bindings,
        "source_release_count": len(releases),
        "source_release_group_count": len({str(row["release_group_mbid"]) for row in releases}),
        "source_recording_count": len(
            {
                str(track["recording_mbid"])
                for row in releases
                for track in TypeAdapter(list[dict[str, object]]).validate_python(row["tracks"])
            }
        ),
        "source_track_count": sum(
            len(TypeAdapter(list[object]).validate_python(row["tracks"])) for row in releases
        ),
        "credited_direct_artist_count": len(artist_releases),
        "direct_artists_without_retained_release_context": catalog.artist_count
        - len(artist_releases),
        "seed_count_with_credit_context": len(genre_releases),
        "seeds_without_retained_release_context": catalog.seed_count - len(genre_releases),
        "release_count_with_direct_artist_credit": len(
            {str(row["release_mbid"]) for rows in artist_releases.values() for row in rows}
        ),
        "artist_paths": {
            identity: f"artist-releases/{identity}.json" for identity in sorted(artist_releases)
        },
        "genre_paths": {
            seed: f"genre-release-examples/{seed}.json" for seed in sorted(genre_releases)
        },
        "missing_context_status": "unavailable_in_retained_source_slice",
    }
    return payloads, summary


def _context_payloads(
    artists: dict[str, list[dict[str, object]]],
    genres: dict[str, list[dict[str, object]]],
    bindings: dict[str, object],
) -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for identity, rows in sorted(artists.items()):
        payloads[f"artist-releases/{identity}.json"] = {
            **_DECLARATIONS,
            **bindings,
            "artist_mbid": identity,
            "status": "available_retained_credit_metadata",
            "total_release_count": len(rows),
            "releases": rows,
        }
    for seed, rows in sorted(genres.items()):
        if seed in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.:-]+", seed):
            raise CandidateCatalogError("direct seed identity is unsafe for a static metadata path")
        payloads[f"genre-release-examples/{seed}.json"] = {
            **_DECLARATIONS,
            **bindings,
            "seed_id": seed,
            "status": "available_retained_artist_credit_context",
            "total_release_count": len(rows),
            "remaining_release_count": max(0, len(rows) - _GENRE_LIMIT),
            "releases": rows[:_GENRE_LIMIT],
        }
    return payloads


def write_artist_release_contexts(
    *,
    direct_catalog_directory: Path,
    output_directory: Path,
    credit_receipt_path: Path = _RECEIPT,
    credit_object_store: Path = _STORE,
) -> dict[str, object]:
    """Write new local static files after verifying both independent custody inputs."""
    require_local_candidate_destination(output_directory)
    payloads, summary = _payloads(
        direct_catalog_directory, credit_receipt_path, credit_object_store
    )
    paths = [output_directory / path for path in payloads]
    receipt_path = output_directory / "release-context-receipt.json"
    if any(path.exists() or path.is_symlink() for path in (*paths, receipt_path)):
        raise CandidateCatalogError("refusing to replace an existing release context artifact")
    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, object]] = []
    for path, payload in payloads.items():
        destination = output_directory / path
        require_local_candidate_destination(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json(payload) + b"\n"
        with destination.open("xb") as stream:
            stream.write(raw)
        sha, size = sha256_file(destination)
        artifacts.append({"path": path, "sha256": sha, "byte_size": size})
    summary["artifacts"] = artifacts
    summary["output_sha256"] = sha256_json(summary)
    with receipt_path.open("xb") as stream:
        stream.write(canonical_json(summary) + b"\n")
    return summary


def verify_artist_release_contexts(
    *,
    direct_catalog_directory: Path,
    output_directory: Path,
    credit_receipt_path: Path = _RECEIPT,
    credit_object_store: Path = _STORE,
) -> dict[str, object]:
    """Recompute source-only projections and require byte-identical static assets."""
    payloads, summary = _payloads(
        direct_catalog_directory, credit_receipt_path, credit_object_store
    )
    artifacts: list[dict[str, object]] = []
    for relative, payload in payloads.items():
        path = output_directory / relative
        if path.read_bytes() != canonical_json(payload) + b"\n":
            raise CandidateCatalogError(
                "release context does not replay from exact custodied metadata"
            )
        sha, size = sha256_file(path)
        artifacts.append({"path": relative, "sha256": sha, "byte_size": size})
    summary["artifacts"] = artifacts
    summary["output_sha256"] = sha256_json(summary)
    actual = json.loads((output_directory / "release-context-receipt.json").read_bytes())
    if actual != summary:
        raise CandidateCatalogError(
            "release context receipt or source-role declarations do not replay"
        )
    return summary
