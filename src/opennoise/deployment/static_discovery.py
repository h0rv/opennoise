"""Build the static artist-discovery payload from display-authorized direct claims."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.common import sha256_file
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_REVISION = "static-direct-discovery-v1"
_RELATED_LIMIT = 8


class StaticDiscoveryExportError(ValueError):
    """The selected catalog snapshot cannot safely populate static discovery."""


class StaticDiscoveryEvidencePayload(FrozenModel):
    """One immutable direct source observation visible in static discovery."""

    evidence_id: int
    source_key: str
    source_record_id: str
    method_key: str
    method_version: str
    provenance_id: int


class StaticDiscoveryMembershipPayload(FrozenModel):
    """One catalog membership bridged to an exact map label for presentation."""

    node_id: str
    catalog_genre_id: int
    catalog_genre_name: str
    binding: Literal["exact_casefolded_label"]
    evidence: tuple[StaticDiscoveryEvidencePayload, ...]


class StaticDiscoveryArtistOverlapPayload(FrozenModel):
    """A transparent artist relation derived from shared direct observations."""

    artist_id: str
    shared_genre_ids: tuple[str, ...]
    shared_genre_count: int
    score: float
    method: Literal["shared_direct_catalog_genre"]


class StaticDiscoveryArtistPayload(FrozenModel):
    """One source-observed artist and its bounded discovery links."""

    artist_id: str
    name: str
    memberships: tuple[StaticDiscoveryMembershipPayload, ...]
    shared_genre_artists: tuple[StaticDiscoveryArtistOverlapPayload, ...]


class StaticDiscoveryGenrePayload(FrozenModel):
    """One map genre with direct source-observed artists only."""

    node_id: str
    catalog_genre_id: int
    catalog_genre_name: str
    binding: Literal["exact_casefolded_label"]
    artist_ids: tuple[str, ...]


class StaticDiscoverySourceCount(FrozenModel):
    """One export-authorized source partition represented in the payload."""

    source_key: str
    observation_count: int


class StaticDiscoverySourcePayload(FrozenModel):
    """Byte-bound public catalog input and its source partition counts."""

    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_byte_count: int
    observation_kind: Literal["direct_source_claim"]
    sources: tuple[StaticDiscoverySourceCount, ...]


class StaticDiscoveryCoveragePayload(FrozenModel):
    """Truthful coverage accounting for the current static discovery snapshot."""

    placed_map_node_count: int
    exact_label_bound_catalog_genre_count: int
    genres_with_direct_artists: int
    artists_with_direct_map_genres: int
    direct_catalog_observation_count: int
    bound_direct_observation_count: int
    artist_relation_method: Literal["shared_direct_catalog_genre"]
    unserved_colisten_reason: Literal["active_display_policy_denies_colisten"]


class StaticDiscoveryPayload(FrozenModel):
    """The complete static discovery JSON contract."""

    revision: Literal["static-direct-discovery-v1"]
    availability: Literal["ready", "unavailable"]
    reason: str | None = None
    source: StaticDiscoverySourcePayload | None = None
    coverage: StaticDiscoveryCoveragePayload | None = None
    genres: tuple[StaticDiscoveryGenrePayload, ...] = ()
    artists: tuple[StaticDiscoveryArtistPayload, ...] = ()


@dataclass(frozen=True, slots=True)
class StaticDiscoveryNode:
    """One placed public map node eligible for a catalog identity bridge."""

    node_id: str
    name: str


@dataclass(frozen=True, slots=True)
class _CatalogGenre:
    """One catalog genre bound to a single exact map label."""

    catalog_id: int
    name: str
    node_id: str


@dataclass(frozen=True, slots=True)
class _DirectEvidence:
    """One direct, policy-filtered source observation retained for publication."""

    evidence_id: int
    artist_id: int
    artist_name: str
    catalog_genre_id: int
    source_key: str
    source_record_id: str
    method_key: str
    method_version: str
    provenance_id: int


@dataclass(frozen=True, slots=True)
class _ArtistMembership:
    """A direct artist observation projected through one exact label bridge."""

    artist_id: int
    artist_name: str
    catalog_genre: _CatalogGenre
    evidence: tuple[_DirectEvidence, ...]


def unavailable_static_discovery_payload() -> StaticDiscoveryPayload:
    """Return an explicit empty state when an export has no catalog snapshot."""
    return StaticDiscoveryPayload(
        revision=_REVISION,
        availability="unavailable",
        reason="no_display_authorized_catalog_snapshot",
    )


def build_static_discovery_payload(
    database: Path,
    nodes: tuple[StaticDiscoveryNode, ...],
) -> StaticDiscoveryPayload:
    """Export direct artist evidence and explained artist overlap into static JSON.

    A catalog genre is bridgeable only when its casefolded display label names one
    placed map node exactly once. The bridge is a presentation join, while every
    artist membership remains a direct source observation from the catalog view.
    """
    if not database.is_file():
        raise StaticDiscoveryExportError(f"catalog snapshot is unavailable: {database}")
    nodes_by_name = _unique_nodes_by_name(nodes)
    try:
        with closing(_connect_read_only(database)) as connection:
            catalog_genres = _catalog_genres(connection, nodes_by_name)
            evidence, total_direct_count = _direct_evidence(connection, catalog_genres)
    except sqlite3.Error as error:
        raise StaticDiscoveryExportError("catalog snapshot lacks direct discovery data") from error
    memberships = _memberships(evidence, catalog_genres)
    return _payload(
        database=database,
        nodes=nodes,
        catalog_genres=catalog_genres,
        memberships=memberships,
        total_direct_count=total_direct_count,
    )


def _connect_read_only(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _unique_nodes_by_name(
    nodes: tuple[StaticDiscoveryNode, ...],
) -> dict[str, StaticDiscoveryNode]:
    candidates: dict[str, list[StaticDiscoveryNode]] = defaultdict(list)
    for node in nodes:
        candidates[node.name.casefold()].append(node)
    return {name: values[0] for name, values in candidates.items() if len(values) == 1}


def _catalog_genres(
    connection: sqlite3.Connection,
    nodes_by_name: dict[str, StaticDiscoveryNode],
) -> dict[int, _CatalogGenre]:
    rows = connection.execute("SELECT id, name FROM genres ORDER BY id").fetchall()
    candidates = [
        _CatalogGenre(catalog_id=int(row["id"]), name=str(row["name"]), node_id=node.node_id)
        for row in rows
        if (node := nodes_by_name.get(str(row["name"]).casefold())) is not None
    ]
    by_node: dict[str, list[_CatalogGenre]] = defaultdict(list)
    for candidate in candidates:
        by_node[candidate.node_id].append(candidate)
    return {
        candidate.catalog_id: candidate
        for candidates_for_node in by_node.values()
        if len(candidates_for_node) == 1
        for candidate in candidates_for_node
    }


def _direct_evidence(
    connection: sqlite3.Connection,
    catalog_genres: dict[int, _CatalogGenre],
) -> tuple[tuple[_DirectEvidence, ...], int]:
    total_direct_count = int(
        connection.execute(
            """SELECT count(*) FROM displayable_artist_genre_evidence AS evidence
               JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
               JOIN active_rights_policy_permissions AS export_permission
                 ON export_permission.policy_id = provenance.policy_id
                AND export_permission.use_kind = 'export'
                AND export_permission.decision = 'allow'
               JOIN active_rights_policy_permissions AS display_permission
                 ON display_permission.policy_id = provenance.policy_id
                AND display_permission.use_kind = 'display'
                AND display_permission.decision = 'allow'
               WHERE evidence.evidence_kind = 'direct_source_claim'"""
        ).fetchone()[0]
    )
    if not catalog_genres:
        return (), total_direct_count
    genre_marks = ",".join("?" for _ in catalog_genres)
    rows = connection.execute(
        f"""WITH preferred_artist_names AS (
                SELECT entity_id, name FROM (
                    SELECT name.entity_id, name.name,
                           row_number() OVER (
                               PARTITION BY name.entity_id
                               ORDER BY name.is_preferred DESC, name.id
                           ) AS row_number
                    FROM displayable_entity_names AS name
                    JOIN artists AS artist ON artist.id = name.entity_id
                ) WHERE row_number = 1
            )
            SELECT evidence.id, evidence.artist_id, artist_name.name, evidence.genre_id,
                   evidence.source_key, evidence.source_record_id, evidence.method_key,
                   evidence.method_version, evidence.provenance_id
            FROM displayable_artist_genre_evidence AS evidence
            JOIN preferred_artist_names AS artist_name ON artist_name.entity_id = evidence.artist_id
            JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
            JOIN active_rights_policy_permissions AS export_permission
              ON export_permission.policy_id = provenance.policy_id
             AND export_permission.use_kind = 'export'
             AND export_permission.decision = 'allow'
            JOIN active_rights_policy_permissions AS display_permission
              ON display_permission.policy_id = provenance.policy_id
             AND display_permission.use_kind = 'display'
             AND display_permission.decision = 'allow'
            WHERE evidence.evidence_kind = 'direct_source_claim'
              AND evidence.genre_id IN ({genre_marks})
            ORDER BY evidence.artist_id, evidence.genre_id, evidence.id""",  # noqa: S608 - integer placeholders only.
        tuple(catalog_genres),
    ).fetchall()
    return (
        tuple(
            _DirectEvidence(
                evidence_id=int(row["id"]),
                artist_id=int(row["artist_id"]),
                artist_name=str(row["name"]),
                catalog_genre_id=int(row["genre_id"]),
                source_key=str(row["source_key"]),
                source_record_id=str(row["source_record_id"]),
                method_key=str(row["method_key"]),
                method_version=str(row["method_version"]),
                provenance_id=int(row["provenance_id"]),
            )
            for row in rows
        ),
        total_direct_count,
    )


def _memberships(
    evidence: tuple[_DirectEvidence, ...],
    catalog_genres: dict[int, _CatalogGenre],
) -> tuple[_ArtistMembership, ...]:
    grouped: dict[tuple[int, int], list[_DirectEvidence]] = defaultdict(list)
    for item in evidence:
        grouped[(item.artist_id, item.catalog_genre_id)].append(item)
    return tuple(
        _ArtistMembership(
            artist_id=artist_id,
            artist_name=items[0].artist_name,
            catalog_genre=catalog_genres[catalog_genre_id],
            evidence=tuple(items),
        )
        for (artist_id, catalog_genre_id), items in sorted(grouped.items())
    )


def _payload(
    *,
    database: Path,
    nodes: tuple[StaticDiscoveryNode, ...],
    catalog_genres: dict[int, _CatalogGenre],
    memberships: tuple[_ArtistMembership, ...],
    total_direct_count: int,
) -> StaticDiscoveryPayload:
    by_artist: dict[int, list[_ArtistMembership]] = defaultdict(list)
    by_node: dict[str, list[_ArtistMembership]] = defaultdict(list)
    for membership in memberships:
        by_artist[membership.artist_id].append(membership)
        by_node[membership.catalog_genre.node_id].append(membership)
    related = _related_artists(by_artist)
    source_counts = Counter(
        observation.source_key for membership in memberships for observation in membership.evidence
    )
    file_sha256, file_byte_count = sha256_file(database)
    return StaticDiscoveryPayload(
        revision=_REVISION,
        availability="ready",
        source=StaticDiscoverySourcePayload(
            database_sha256=file_sha256,
            database_byte_count=file_byte_count,
            observation_kind="direct_source_claim",
            sources=tuple(
                StaticDiscoverySourceCount(source_key=source_key, observation_count=count)
                for source_key, count in sorted(source_counts.items())
            ),
        ),
        coverage=StaticDiscoveryCoveragePayload(
            placed_map_node_count=len(nodes),
            exact_label_bound_catalog_genre_count=len(catalog_genres),
            genres_with_direct_artists=len(by_node),
            artists_with_direct_map_genres=len(by_artist),
            direct_catalog_observation_count=total_direct_count,
            bound_direct_observation_count=sum(
                len(membership.evidence) for membership in memberships
            ),
            artist_relation_method="shared_direct_catalog_genre",
            unserved_colisten_reason="active_display_policy_denies_colisten",
        ),
        genres=tuple(
            StaticDiscoveryGenrePayload(
                node_id=node_id,
                catalog_genre_id=members[0].catalog_genre.catalog_id,
                catalog_genre_name=members[0].catalog_genre.name,
                binding="exact_casefolded_label",
                artist_ids=tuple(
                    _artist_key(membership.artist_id) for membership in _sorted_memberships(members)
                ),
            )
            for node_id, members in sorted(by_node.items())
        ),
        artists=tuple(
            StaticDiscoveryArtistPayload(
                artist_id=_artist_key(artist_id),
                name=_artist_name(artist_memberships),
                memberships=tuple(
                    _membership_payload(membership)
                    for membership in _sorted_memberships(artist_memberships)
                ),
                shared_genre_artists=related.get(artist_id, ()),
            )
            for artist_id, artist_memberships in sorted(
                by_artist.items(), key=lambda item: (_artist_name(item[1]).casefold(), item[0])
            )
        ),
    )


def _artist_key(artist_id: int) -> str:
    return f"artist:{artist_id}"


def _artist_name(memberships: Iterable[_ArtistMembership]) -> str:
    return next(iter(memberships)).artist_name


def _sorted_memberships(
    memberships: Iterable[_ArtistMembership],
) -> list[_ArtistMembership]:
    return sorted(
        memberships,
        key=lambda item: (
            item.catalog_genre.name.casefold(),
            item.catalog_genre.node_id,
            item.catalog_genre.catalog_id,
        ),
    )


def _membership_payload(membership: _ArtistMembership) -> StaticDiscoveryMembershipPayload:
    return StaticDiscoveryMembershipPayload(
        node_id=membership.catalog_genre.node_id,
        catalog_genre_id=membership.catalog_genre.catalog_id,
        catalog_genre_name=membership.catalog_genre.name,
        binding="exact_casefolded_label",
        evidence=tuple(
            StaticDiscoveryEvidencePayload(
                evidence_id=item.evidence_id,
                source_key=item.source_key,
                source_record_id=item.source_record_id,
                method_key=item.method_key,
                method_version=item.method_version,
                provenance_id=item.provenance_id,
            )
            for item in membership.evidence
        ),
    )


def _related_artists(
    by_artist: dict[int, list[_ArtistMembership]],
) -> dict[int, tuple[StaticDiscoveryArtistOverlapPayload, ...]]:
    artists_by_genre: dict[str, set[int]] = defaultdict(set)
    genres_by_artist: dict[int, set[str]] = {}
    for artist_id, memberships in by_artist.items():
        genre_ids = {membership.catalog_genre.node_id for membership in memberships}
        genres_by_artist[artist_id] = genre_ids
        for genre_id in genre_ids:
            artists_by_genre[genre_id].add(artist_id)
    shared: dict[int, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for genre_id, artist_ids in artists_by_genre.items():
        ordered = sorted(artist_ids)
        for index, artist_id in enumerate(ordered):
            for other_id in ordered[index + 1 :]:
                shared[artist_id][other_id].add(genre_id)
                shared[other_id][artist_id].add(genre_id)
    result: dict[int, tuple[StaticDiscoveryArtistOverlapPayload, ...]] = {}
    for artist_id, peers in shared.items():
        ranked = sorted(
            peers.items(),
            key=lambda item: (
                -len(item[1]),
                -_jaccard(genres_by_artist[artist_id], genres_by_artist[item[0]]),
                _artist_name(by_artist[item[0]]).casefold(),
                item[0],
            ),
        )[:_RELATED_LIMIT]
        result[artist_id] = tuple(
            StaticDiscoveryArtistOverlapPayload(
                artist_id=_artist_key(other_id),
                shared_genre_ids=tuple(sorted(shared_genres)),
                shared_genre_count=len(shared_genres),
                score=_jaccard(genres_by_artist[artist_id], genres_by_artist[other_id]),
                method="shared_direct_catalog_genre",
            )
            for other_id, shared_genres in ranked
        )
    return result


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right)


def static_discovery_json(payload: StaticDiscoveryPayload) -> bytes:
    """Serialize the validated public contract without exposing an untyped intermediary."""
    serialized = str(payload.model_dump_json(exclude_none=True))
    return (serialized + "\n").encode()
