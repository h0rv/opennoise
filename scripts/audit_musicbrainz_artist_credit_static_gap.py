"""Explain exact-MBID static-discovery exclusions without adding memberships."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlparse
from uuid import UUID

from opennoise.deployment.static_discovery import StaticDiscoveryPayload

_REVISION: Final = "musicbrainz-artist-credit-static-gap-v1"
_MBID_TYPE: Final = "musicbrainz_artist_id"
_DIRECT_KIND: Final = "direct_source_claim"
_MUSICBRAINZ_ARTIST_URL_PATH_PARTS: Final = 3
_ATLAS_REVISION: Final = "semantic-scatter-map-v2"
_ATLAS_SOURCE: Final = "semantic-map-layout-v2"
_ATLAS_LOGICAL_OUTPUT_SHA256: Final = (
    "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"
)


class StaticGapAuditError(ValueError):
    """Raised when an input cannot support the exact-ID audit."""


@dataclass(frozen=True, slots=True)
class GapRow:
    """One candidate MBID and its first static-export gate that fails."""

    mbid: str
    category: str
    public_artist_entity_count: int
    public_direct_observation_count: int
    export_authorized_direct_observation_count: int
    exact_label_bound_direct_observation_count: int
    named_bound_direct_observation_count: int
    authorized_exact_mbid_artist_entity_count: int


@dataclass(frozen=True, slots=True)
class _StaticExportContext:
    """The non-membership authorization conditions used by the static exporter."""

    export_allowed_policy_ids: set[int]
    provenance_policy: dict[int, int]
    named_artist_ids: set[int]
    authorized_identifiers: dict[int, set[str]]
    bridgeable_genre_ids: set[int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _canonical_mbid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _musicbrainz_artist_id(url: str | None) -> str:
    if not isinstance(url, str):
        raise StaticGapAuditError("static artist has no MusicBrainz URL")
    parsed = urlparse(url)
    parts = parsed.path.rstrip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "musicbrainz.org"
        or len(parts) != _MUSICBRAINZ_ARTIST_URL_PATH_PARTS
    ):
        raise StaticGapAuditError("static artist has an invalid MusicBrainz URL")
    mbid = parts[-1]
    if not _canonical_mbid(mbid):
        raise StaticGapAuditError("static artist URL does not end in a canonical MBID")
    return mbid


def _load_static(path: Path, public_sha256: str) -> StaticDiscoveryPayload:
    try:
        payload = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    except ValueError as error:
        raise StaticGapAuditError("static discovery does not match its typed contract") from error
    if payload.availability != "ready":
        raise StaticGapAuditError("static discovery is not ready")
    if payload.source is None or payload.source.database_sha256 != public_sha256:
        raise StaticGapAuditError("static discovery is not bound to the supplied public database")
    if payload.source.observation_kind != _DIRECT_KIND:
        raise StaticGapAuditError("static discovery does not declare direct-source observations")
    return payload


def _candidate_mbids(candidate: Path) -> set[str]:
    with closing(_connect_read_only(candidate)) as connection:
        return {
            str(row["normalized_value"])
            for row in connection.execute(
                """SELECT identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   JOIN artists ON artists.id = identifier.entity_id
                   WHERE type.type_key = ?""",
                (_MBID_TYPE,),
            )
        }


def _placed_name_counts(semantic_atlas: Path) -> Counter[str]:
    """Validate the untyped renderer payload using its pinned release contract.

    The renderer atlas has no typed model. This audit instead binds its exact
    renderer revision, source revision, and declared logical layout hash.
    """
    try:
        payload = json.loads(semantic_atlas.read_bytes())
        nodes = payload["nodes"]
    except (KeyError, TypeError, ValueError) as error:
        raise StaticGapAuditError("semantic atlas has no node list") from error
    if not isinstance(nodes, list):
        raise StaticGapAuditError("semantic atlas node list is malformed")
    if payload.get("revision") != _ATLAS_REVISION:
        raise StaticGapAuditError("semantic atlas has an unexpected renderer revision")
    if payload.get("source") != _ATLAS_SOURCE:
        raise StaticGapAuditError("semantic atlas has an unexpected source revision")
    if payload.get("logical_output_sha256") != _ATLAS_LOGICAL_OUTPUT_SHA256:
        raise StaticGapAuditError("semantic atlas has an unexpected logical layout hash")
    if payload.get("placed_node_count") != len(nodes):
        raise StaticGapAuditError("semantic atlas placed-node count disagrees with nodes")
    counts: Counter[str] = Counter()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("name"), str):
            raise StaticGapAuditError("semantic atlas node has no string name")
        counts[node["name"].casefold()] += 1
    return counts


def _bridgeable_genre_ids(
    connection: sqlite3.Connection, placed_name_counts: Counter[str]
) -> set[int]:
    """Mirror the static one-map-node-to-one-catalog-genre bridge restriction."""
    catalog_candidates: dict[str, list[int]] = defaultdict(list)
    for row in connection.execute("SELECT id, name FROM genres"):
        name = str(row["name"]).casefold()
        if placed_name_counts[name] == 1:
            catalog_candidates[name].append(int(row["id"]))
    return {genre_ids[0] for genre_ids in catalog_candidates.values() if len(genre_ids) == 1}


def _static_export_context(
    connection: sqlite3.Connection, placed_name_counts: Counter[str]
) -> _StaticExportContext:
    export_allowed_policy_ids = {
        int(row["policy_id"])
        for row in connection.execute(
            """SELECT DISTINCT provenance.policy_id
               FROM provenance_records AS provenance
               JOIN active_rights_policy_permissions AS permission
                 ON permission.policy_id = provenance.policy_id
                AND permission.use_kind = 'export' AND permission.decision = 'allow'"""
        )
    }
    provenance_policy = {
        int(row["id"]): int(row["policy_id"])
        for row in connection.execute("SELECT id, policy_id FROM provenance_records")
    }
    named_artist_ids = {
        int(row["entity_id"])
        for row in connection.execute(
            """SELECT DISTINCT name.entity_id
               FROM displayable_entity_names AS name
               JOIN artists ON artists.id = name.entity_id"""
        )
    }
    authorized_identifiers: dict[int, set[str]] = defaultdict(set)
    identifier_rows = connection.execute(
        """SELECT identifier.entity_id, identifier.normalized_value
           FROM entity_identifiers AS identifier
           JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
           JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
           JOIN active_rights_policy_permissions AS export_permission
             ON export_permission.policy_id = provenance.policy_id
            AND export_permission.use_kind = 'export' AND export_permission.decision = 'allow'
           JOIN active_rights_policy_permissions AS display_permission
             ON display_permission.policy_id = provenance.policy_id
            AND display_permission.use_kind = 'display'
            AND display_permission.decision = 'allow'
           WHERE type.type_key = ? AND identifier.namespace = 'musicbrainz'""",
        (_MBID_TYPE,),
    )
    for row in identifier_rows:
        value = str(row["normalized_value"])
        if _canonical_mbid(value):
            authorized_identifiers[int(row["entity_id"])].add(value)
    return _StaticExportContext(
        export_allowed_policy_ids=export_allowed_policy_ids,
        provenance_policy=provenance_policy,
        named_artist_ids=named_artist_ids,
        authorized_identifiers=dict(authorized_identifiers),
        bridgeable_genre_ids=_bridgeable_genre_ids(connection, placed_name_counts),
    )


def _public_rows(
    public: Path, candidate_mbids: set[str], placed_name_counts: Counter[str]
) -> tuple[set[str], list[GapRow]]:
    if not candidate_mbids:
        return set(), []
    with closing(_connect_read_only(public)) as connection:
        candidate_json = json.dumps(sorted(candidate_mbids))
        identities = connection.execute(
            """SELECT identifier.normalized_value AS mbid, identifier.entity_id AS artist_id
               FROM entity_identifiers AS identifier
               JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
               JOIN artists ON artists.id = identifier.entity_id
               WHERE type.type_key = ?
                 AND identifier.normalized_value IN (SELECT value FROM json_each(?))""",
            (_MBID_TYPE, candidate_json),
        ).fetchall()
        by_mbid: dict[str, set[int]] = defaultdict(set)
        for identity in identities:
            by_mbid[str(identity["mbid"])].add(int(identity["artist_id"]))

        direct_rows = connection.execute(
            """SELECT identifier.normalized_value AS mbid, evidence.artist_id, evidence.genre_id,
                      genre.name AS genre_name, evidence.provenance_id
               FROM displayable_artist_genre_evidence AS evidence
               JOIN entity_identifiers AS identifier ON identifier.entity_id = evidence.artist_id
               JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
               JOIN genres AS genre ON genre.id = evidence.genre_id
               WHERE evidence.evidence_kind = ? AND type.type_key = ?
                 AND identifier.normalized_value IN (SELECT value FROM json_each(?))""",
            (_DIRECT_KIND, _MBID_TYPE, candidate_json),
        ).fetchall()
        direct_by_mbid: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in direct_rows:
            direct_by_mbid[str(row["mbid"])].append(row)

        export_context = _static_export_context(connection, placed_name_counts)

    public_direct_mbids = set(direct_by_mbid)
    rows: list[GapRow] = []
    for mbid in sorted(public_direct_mbids):
        direct = direct_by_mbid[mbid]
        export_direct = [
            row
            for row in direct
            if export_context.provenance_policy[int(row["provenance_id"])]
            in export_context.export_allowed_policy_ids
        ]
        bound_direct = [
            row
            for row in export_direct
            if int(row["genre_id"]) in export_context.bridgeable_genre_ids
        ]
        named_bound = [
            row for row in bound_direct if int(row["artist_id"]) in export_context.named_artist_ids
        ]
        authorized_exact = sum(
            export_context.authorized_identifiers.get(artist_id) == {mbid}
            for artist_id in by_mbid[mbid]
        )
        if not export_direct:
            category = "no_export_authorized_direct_claim"
        elif not bound_direct:
            category = "no_exact_one_to_one_placed_label_bridge"
        elif not named_bound:
            category = "no_displayable_artist_name_for_bound_claim"
        elif not authorized_exact:
            category = "no_unambiguous_export_and_display_authorized_canonical_mbid"
        else:
            category = "unexpected_static_export_equivalent"
        rows.append(
            GapRow(
                mbid=mbid,
                category=category,
                public_artist_entity_count=len(by_mbid[mbid]),
                public_direct_observation_count=len(direct),
                export_authorized_direct_observation_count=len(export_direct),
                exact_label_bound_direct_observation_count=len(bound_direct),
                named_bound_direct_observation_count=len(named_bound),
                authorized_exact_mbid_artist_entity_count=authorized_exact,
            )
        )
    return public_direct_mbids, rows


def audit(candidate: Path, public: Path, semantic_atlas: Path, static: Path) -> dict[str, object]:
    """Classify the public-direct candidate IDs absent from the supplied static asset."""
    candidate_mbids = _candidate_mbids(candidate)
    placed_name_counts = _placed_name_counts(semantic_atlas)
    public_direct_mbids, public_rows = _public_rows(public, candidate_mbids, placed_name_counts)
    public_sha256 = _sha256(public)
    static_payload = _load_static(static, public_sha256)
    static_mbids = {
        _musicbrainz_artist_id(artist.musicbrainz_url)
        for artist in static_payload.artists
        if artist.musicbrainz_url is not None
    }
    absent = public_direct_mbids - static_mbids
    gap_rows = [row for row in public_rows if row.mbid in absent]
    categories = Counter(row.category for row in gap_rows)
    if any(row.category == "unexpected_static_export_equivalent" for row in gap_rows):
        raise StaticGapAuditError("a static-eligible MBID is absent from the static asset")
    return {
        "revision": _REVISION,
        "inputs": {
            "candidate_database_sha256": _sha256(candidate),
            "public_database_sha256": public_sha256,
            "semantic_atlas_sha256": _sha256(semantic_atlas),
            "static_discovery_sha256": _sha256(static),
        },
        "scope": {
            "candidate_artist_mbid_count": len(candidate_mbids),
            "candidate_public_direct_mbid_count": len(public_direct_mbids),
            "candidate_public_direct_mbid_absent_from_static_count": len(gap_rows),
            "placed_name_count": sum(placed_name_counts.values()),
            "unique_placed_label_count": sum(count == 1 for count in placed_name_counts.values()),
        },
        "exclusion_categories": dict(sorted(categories.items())),
        "excluded_mbids": [asdict(row) for row in gap_rows],
        "boundaries": [
            "The audit joins artists only by exact MusicBrainz artist ID.",
            (
                "It classifies existing public direct claims; it neither infers nor transfers "
                "a genre membership."
            ),
            (
                "The semantic-atlas labels are used solely to reproduce the static "
                "exact-casefolded-label presentation gate."
            ),
        ],
    }


def main() -> None:
    """Write a deterministic read-only gap report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--semantic-atlas", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    report = audit(
        arguments.candidate,
        arguments.public_database,
        arguments.semantic_atlas,
        arguments.static_discovery,
    )
    arguments.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
