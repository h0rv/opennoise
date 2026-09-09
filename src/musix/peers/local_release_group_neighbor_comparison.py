"""Compare local direct and release-group support neighborhoods without blending them."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Final

from musix.common import sha256_file
from musix.musicbrainz_release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)

_REVISION: Final = "local-release-group-neighbor-comparison-v1"
_MAX_NEIGHBORS: Final = 25
_SHA256_LENGTH: Final = 64

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


class LocalReleaseGroupNeighborComparisonError(ValueError):
    """Report an incomplete or mismatched local research input."""


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise LocalReleaseGroupNeighborComparisonError(f"missing SQLite input: {path}")
    connection = sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _verify_evidence(database: Path, artifact_path: Path) -> ReleaseGroupEvidenceArtifact:
    try:
        artifact = ReleaseGroupEvidenceArtifact.model_validate_json(artifact_path.read_bytes())
    except (OSError, ValueError) as error:
        raise LocalReleaseGroupNeighborComparisonError("invalid evidence artifact") from error
    verify_release_group_evidence(artifact)
    if sha256_file(database) != (
        artifact.evidence_database_sha256,
        artifact.evidence_database_bytes,
    ):
        raise LocalReleaseGroupNeighborComparisonError("evidence database does not match artifact")
    return artifact


def _membership_rows(table: str) -> str:
    if table == "direct_anchor":
        return """SELECT genre_id, artist_id, 1 AS support_count
                     FROM direct_anchor GROUP BY genre_id, artist_id
                    ORDER BY genre_id, artist_id"""
    if table == "release_group_support":
        return """SELECT genre_id, artist_id, count(DISTINCT release_group_id) AS support_count
                     FROM release_group_support GROUP BY genre_id, artist_id
                    ORDER BY genre_id, artist_id"""
    raise AssertionError(table)


def _memberships(
    connection: sqlite3.Connection, table: str, query_ids: frozenset[str]
) -> tuple[dict[str, int], dict[str, set[str]], dict[tuple[str, str], int]]:
    counts: dict[str, int] = defaultdict(int)
    query_artists: dict[str, set[str]] = {query_id: set() for query_id in query_ids}
    support_counts: dict[tuple[str, str], int] = {}
    for genre_id, artist_id, support_count in connection.execute(_membership_rows(table)):
        genre = str(genre_id)
        artist = str(artist_id)
        counts[genre] += 1
        if genre in query_artists:
            query_artists[genre].add(artist)
            support_counts[(genre, artist)] = int(support_count)
    return dict(counts), query_artists, support_counts


def _shared(
    connection: sqlite3.Connection,
    table: str,
    query_artists: dict[str, set[str]],
    support_counts: dict[tuple[str, str], int],
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    by_artist: dict[str, set[str]] = defaultdict(set)
    for query_id, artists in query_artists.items():
        for artist in artists:
            by_artist[artist].add(query_id)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    shared_support: dict[tuple[str, str], int] = defaultdict(int)
    query = _membership_rows(table).replace(
        "ORDER BY genre_id, artist_id", "ORDER BY artist_id, genre_id"
    )
    for genre_id, artist_id, support_count in connection.execute(query):
        artist = str(artist_id)
        for query_id in by_artist.get(artist, ()):
            candidate = str(genre_id)
            if candidate == query_id:
                continue
            key = (query_id, candidate)
            shared[key] += 1
            shared_support[key] += min(support_counts[(query_id, artist)], int(support_count))
    return dict(shared), dict(shared_support)


def _neighbors(
    query_id: str,
    counts: dict[str, int],
    shared: dict[tuple[str, str], int],
    shared_support: dict[tuple[str, str], int],
    *,
    limit: int,
) -> list[dict[str, object]]:
    query_count = counts.get(query_id, 0)
    rows: list[tuple[float, str, int, int]] = []
    for (source, candidate), shared_artist_count in shared.items():
        if source != query_id:
            continue
        denominator = query_count + counts[candidate] - shared_artist_count
        if denominator <= 0:
            continue
        rows.append(
            (
                shared_artist_count / denominator,
                candidate,
                shared_artist_count,
                shared_support.get((source, candidate), 0),
            )
        )
    return [
        {
            "seed_id": candidate,
            "score": round(score, 12),
            "shared_artist_count": shared_artist_count,
            "shared_artist_release_group_minimum_sum": shared_group_count,
        }
        for score, candidate, shared_artist_count, shared_group_count in sorted(
            rows, key=lambda row: (-row[0], row[1])
        )[:limit]
    ]


def _frozen_neighbors(
    connection: sqlite3.Connection, query_id: str, *, limit: int
) -> list[dict[str, object]]:
    rows = connection.execute(
        """SELECT candidate, direct_score, shared_direct_artist_count FROM (
               SELECT target_genre_id AS candidate, direct_score, shared_direct_artist_count
                 FROM peer_edge WHERE source_genre_id = ?
               UNION ALL
               SELECT source_genre_id AS candidate, direct_score, shared_direct_artist_count
                 FROM peer_edge WHERE target_genre_id = ?
           ) ORDER BY direct_score DESC, candidate LIMIT ?""",
        (query_id, query_id, limit),
    ).fetchall()
    return [
        {
            "seed_id": str(seed_id),
            "direct_score": float(score),
            "shared_direct_artist_count": int(shared_count),
        }
        for seed_id, score, shared_count in rows
    ]


def _frozen_metadata(connection: sqlite3.Connection) -> str:
    values = {
        str(key): str(value) for key, value in connection.execute("SELECT key, value FROM metadata")
    }
    if values.get("non_production_candidate") != "true":
        raise LocalReleaseGroupNeighborComparisonError(
            "frozen peer index is not marked non-production"
        )
    if values.get("all_inputs_export_allowed") != "false":
        raise LocalReleaseGroupNeighborComparisonError(
            "frozen peer index export policy is incompatible"
        )
    artifact_sha = values.get("artifact_output_sha256")
    if artifact_sha is None or len(artifact_sha) != _SHA256_LENGTH:
        raise LocalReleaseGroupNeighborComparisonError("frozen peer index lacks artifact hash")
    return artifact_sha


def compare_neighbors(
    *,
    evidence_database: Path,
    evidence_artifact: Path,
    frozen_peer_index: Path,
    query_seed_ids: Iterable[str],
    limit: int = 10,
) -> dict[str, object]:
    """Return a bounded, local-only direct and support neighborhood comparison."""
    selected = tuple(dict.fromkeys(query_seed_ids))
    if not selected or limit < 1 or limit > _MAX_NEIGHBORS:
        raise LocalReleaseGroupNeighborComparisonError(
            f"query seeds and a limit from 1 to {_MAX_NEIGHBORS} are required"
        )
    artifact = _verify_evidence(evidence_database, evidence_artifact)
    query_ids = frozenset(selected)
    with closing(_read_only(evidence_database)) as connection:
        direct_counts, direct_artists, direct_support_counts = _memberships(
            connection, "direct_anchor", query_ids
        )
        direct_shared, _ = _shared(
            connection, "direct_anchor", direct_artists, direct_support_counts
        )
        support_counts, support_artists, support_group_counts = _memberships(
            connection, "release_group_support", query_ids
        )
        support_shared, support_shared_groups = _shared(
            connection, "release_group_support", support_artists, support_group_counts
        )
    with closing(_read_only(frozen_peer_index)) as peer_connection:
        frozen_artifact_sha = _frozen_metadata(peer_connection)
        frozen = {
            query_id: _frozen_neighbors(peer_connection, query_id, limit=limit)
            for query_id in selected
        }
    support_only = sorted(set(support_counts) - set(direct_counts))
    return {
        "revision": _REVISION,
        "scope": "local_research_only",
        "export_allowed": False,
        "serving_allowed": False,
        "method": {
            "direct_binary": "distinct artist membership Jaccard from direct_anchor",
            "support_binary": "distinct artist membership Jaccard from release_group_support",
            "support_deduplication": "distinct release_group_id per seed and artist across facets",
            "support_neighbor_diagnostic": (
                "sum across shared artists of the minimum distinct release-group count per endpoint"
            ),
            "interpretation": "support is separate evidence, not an artist-direct claim",
        },
        "evidence_artifact_sha256": artifact.output_sha256,
        "evidence_database_sha256": artifact.evidence_database_sha256,
        "frozen_peer_index_sha256": sha256_file(frozen_peer_index)[0],
        "frozen_peer_artifact_output_sha256": frozen_artifact_sha,
        "support_seed_count": len(support_counts),
        "support_only_seed_count": len(support_only),
        "support_only_seed_ids": support_only,
        "neighborhoods": [
            {
                "seed_id": query_id,
                "direct_artist_count": direct_counts.get(query_id, 0),
                "support_artist_count": support_counts.get(query_id, 0),
                "direct_binary_neighbors": _neighbors(
                    query_id, direct_counts, direct_shared, {}, limit=limit
                ),
                "support_binary_neighbors": _neighbors(
                    query_id, support_counts, support_shared, support_shared_groups, limit=limit
                ),
                "frozen_direct_weighted_jaccard_neighbors": frozen[query_id],
            }
            for query_id in selected
        ],
    }
