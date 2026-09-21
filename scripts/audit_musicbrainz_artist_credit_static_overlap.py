"""Read-only exact-MBID overlap audit for a local artist-credit candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Final
from urllib.parse import urlparse
from uuid import UUID

from opennoise.deployment.static_discovery import StaticDiscoveryPayload

_REVISION: Final = "musicbrainz-artist-credit-static-overlap-v1"
_MBID_LENGTH: Final = 36
_MUSICBRAINZ_ARTIST_URL_PATH_PARTS: Final = 3


class OverlapAuditError(ValueError):
    """Raised when a supposedly exact-ID audit input is malformed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    return sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)


def _musicbrainz_artist_id(url: object) -> str:
    if not isinstance(url, str):
        raise OverlapAuditError("static artist has no MusicBrainz URL")
    parsed = urlparse(url)
    parts = parsed.path.rstrip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "musicbrainz.org"
        or len(parts) != _MUSICBRAINZ_ARTIST_URL_PATH_PARTS
    ):
        raise OverlapAuditError("static artist has an invalid MusicBrainz URL")
    mbid = parts[-1]
    if len(mbid) != _MBID_LENGTH:
        raise OverlapAuditError("static artist URL does not end in an MBID")
    try:
        parsed_mbid = UUID(mbid)
    except ValueError as error:
        raise OverlapAuditError("static artist URL does not end in a canonical MBID") from error
    if str(parsed_mbid) != mbid:
        raise OverlapAuditError("static artist URL does not end in a canonical MBID")
    return mbid


def _load_static(path: Path, public_database_sha256: str) -> StaticDiscoveryPayload:
    try:
        payload = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    except ValueError as error:
        raise OverlapAuditError("static discovery does not match its typed contract") from error
    if payload.availability != "ready":
        raise OverlapAuditError("static discovery is not ready")
    if payload.source is None or payload.source.database_sha256 != public_database_sha256:
        raise OverlapAuditError("static discovery is not bound to the supplied public database")
    if payload.source.observation_kind != "direct_source_claim":
        raise OverlapAuditError("static discovery does not declare direct-source observations")
    return payload


def _candidate_ids(candidate: Path) -> tuple[set[str], set[str], set[str], dict[str, int]]:
    with closing(_read_only_connection(candidate)) as db:
        artist_ids = {
            str(row[0])
            for row in db.execute(
                """SELECT identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   JOIN artists ON artists.id = identifier.entity_id
                   WHERE type.type_key = 'musicbrainz_artist_id'"""
            )
        }
        release_ids = {
            str(row[0])
            for row in db.execute(
                """SELECT identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   JOIN releases ON releases.id = identifier.entity_id
                   WHERE type.type_key = 'musicbrainz_release_id'"""
            )
        }
        recording_ids = {
            str(row[0])
            for row in db.execute(
                """SELECT identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   JOIN recordings ON recordings.id = identifier.entity_id
                   WHERE type.type_key = 'musicbrainz_recording_id'"""
            )
        }
        entity_counts = {
            str(kind): int(count)
            for kind, count in db.execute(
                "SELECT entity_kind, count(*) FROM catalog_entities GROUP BY entity_kind"
            )
        }
    return artist_ids, release_ids, recording_ids, entity_counts


def _public_direct_artist_ids(public: Path) -> set[str]:
    with closing(_read_only_connection(public)) as db:
        return {
            str(row[0])
            for row in db.execute(
                """SELECT DISTINCT identifier.normalized_value
                   FROM displayable_artist_genre_evidence AS evidence
                   JOIN entity_identifiers AS identifier
                     ON identifier.entity_id = evidence.artist_id
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   WHERE evidence.evidence_kind = 'direct_source_claim'
                     AND type.type_key = 'musicbrainz_artist_id'"""
            )
        }


def _public_direct_membership_scope(public: Path, artist_ids: set[str]) -> dict[str, int]:
    if not artist_ids:
        return {"artist_count": 0, "genre_count": 0, "observation_count": 0}
    with closing(_read_only_connection(public)) as db:
        row = db.execute(
            """SELECT count(DISTINCT evidence.artist_id),
                      count(DISTINCT evidence.genre_id), count(*)
               FROM displayable_artist_genre_evidence AS evidence
               JOIN entity_identifiers AS identifier ON identifier.entity_id = evidence.artist_id
               JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
               WHERE evidence.evidence_kind = 'direct_source_claim'
                 AND type.type_key = 'musicbrainz_artist_id'
                 AND identifier.normalized_value IN (SELECT value FROM json_each(?))""",
            (json.dumps(sorted(artist_ids)),),
        ).fetchone()
    if row is None:
        raise OverlapAuditError("public direct membership aggregate unexpectedly returned no row")
    return {
        "artist_count": int(row[0]),
        "genre_count": int(row[1]),
        "observation_count": int(row[2]),
    }


def _static_memberships(payload: StaticDiscoveryPayload) -> tuple[dict[str, set[str]], int, int]:
    artists = payload.artists
    memberships: dict[str, set[str]] = defaultdict(set)
    observation_count = 0
    for artist in artists:
        mbid = _musicbrainz_artist_id(artist.musicbrainz_url)
        for item in artist.memberships:
            memberships[mbid].add(item.node_id)
            observation_count += 1
    return memberships, len(artists), observation_count


def _candidate_metadata_examples(candidate: Path, public_artist_ids: set[str]) -> dict[str, int]:
    """Count local candidate entities with a credited artist already directly public."""
    with closing(_read_only_connection(candidate)) as db:
        rows = db.execute(
            """WITH public_artist(entity_id) AS (
                    SELECT identifier.entity_id
                    FROM entity_identifiers AS identifier
                    JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                    WHERE type.type_key = 'musicbrainz_artist_id'
                      AND identifier.normalized_value IN (
                          SELECT value FROM json_each(?)
                      )
                ), credited_entity(entity_id) AS (
                    SELECT DISTINCT credit.entity_id
                    FROM entity_artist_credits AS credit
                    JOIN artist_credit_members AS member
                      ON member.artist_credit_id = credit.artist_credit_id
                    JOIN public_artist ON public_artist.entity_id = member.artist_id
                )
                SELECT entity.entity_kind, count(*)
                FROM credited_entity
                JOIN catalog_entities AS entity ON entity.id = credited_entity.entity_id
                WHERE entity.entity_kind IN ('release', 'recording')
                GROUP BY entity.entity_kind""",
            (json.dumps(sorted(public_artist_ids)),),
        ).fetchall()
    return {str(kind): int(count) for kind, count in rows}


def audit(candidate: Path, public: Path, static: Path) -> dict[str, object]:
    """Return a deterministic, non-publishing audit based solely on exact MBIDs."""
    candidate_hash = _sha256(candidate)
    public_hash = _sha256(public)
    static_hash = _sha256(static)
    static_payload = _load_static(static, public_hash)
    candidate_artists, candidate_releases, candidate_recordings, entity_counts = _candidate_ids(
        candidate
    )
    public_direct = _public_direct_artist_ids(public)
    static_by_artist, static_artist_count, static_observation_count = _static_memberships(
        static_payload
    )
    static_ids = set(static_by_artist)
    static_overlap = candidate_artists & static_ids
    public_direct_overlap = candidate_artists & public_direct
    public_direct_scope = _public_direct_membership_scope(public, public_direct_overlap)
    static_genres = set()
    for mbid in static_overlap:
        static_genres.update(static_by_artist[mbid])
    examples = _candidate_metadata_examples(candidate, static_overlap) if static_overlap else {}
    return {
        "revision": _REVISION,
        "inputs": {
            "candidate_database_sha256": candidate_hash,
            "public_database_sha256": public_hash,
            "static_discovery_sha256": static_hash,
        },
        "candidate": {
            "artist_mbid_count": len(candidate_artists),
            "release_mbid_count": len(candidate_releases),
            "recording_mbid_count": len(candidate_recordings),
            "entity_counts": dict(sorted(entity_counts.items())),
        },
        "static_discovery": {
            "artist_count": static_artist_count,
            "direct_observation_count": static_observation_count,
            "artist_mbid_count": len(static_ids),
        },
        "exact_artist_overlap": {
            "candidate_artist_count": len(candidate_artists),
            "public_direct_artist_count": len(public_direct),
            "static_artist_count": len(static_ids),
            "public_direct_overlap_artist_count": len(public_direct_overlap),
            "public_direct_overlap_genre_count": public_direct_scope["genre_count"],
            "public_direct_overlap_observation_count": public_direct_scope["observation_count"],
            "static_discovery_overlap_artist_count": len(static_overlap),
            "public_direct_not_in_static_artist_count": len(public_direct_overlap - static_ids),
            "overlap_static_genre_count": len(static_genres),
            "overlap_static_membership_count": sum(
                len(static_by_artist[mbid]) for mbid in static_overlap
            ),
        },
        "local_metadata_example_scope": {
            "release_count_with_overlapping_credited_artist": examples.get("release", 0),
            "recording_count_with_overlapping_credited_artist": examples.get("recording", 0),
            "publication_status": "blocked_pending_separate_identity_provenance_and_policy_review",
        },
        "publication_boundaries": [
            (
                "Exact MBID equality establishes only artist identity overlap; it creates no "
                "artist-to-genre claim."
            ),
            (
                "The candidate is local-only metadata; this audit does not publish releases, "
                "recordings, names, or credits."
            ),
            (
                "Any metadata example requires a separate policy/provenance decision and must "
                "be labeled as MusicBrainz credit metadata, never as a quintessential album claim."
            ),
        ],
    }


def main() -> None:
    """Write the supplied exact-ID overlap report without modifying inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.candidate, args.public_database, args.static_discovery)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
