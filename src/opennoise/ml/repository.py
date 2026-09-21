"""Load bounded, policy-safe public graph evidence from SQLite catalogs."""

import sqlite3
from collections.abc import Callable, Iterable
from typing import Literal
from urllib.parse import quote

from pydantic import Field

from opennoise.ml.artist_pair_refs import artist_pair_source_artifact_ref_v3
from opennoise.models import FrozenModel
from opennoise.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreHierarchyEdge,
    GenreIdentity,
    MembershipFacet,
    MetadataCandidate,
    PublicArtifact,
    PublicModelInput,
    PublicSource,
)

_MAX_ARTIST_PAIR_EVIDENCE_REFS = 366


class PublicInputLoadSettings(FrozenModel):
    """Bound every database result before the model allocates its graph."""

    max_direct_memberships: int = Field(default=100_000, gt=0, le=1_000_000)
    max_artist_pairs: int = Field(default=250_000, gt=0, le=5_000_000)
    max_metadata_candidates: int = Field(default=100_000, gt=0, le=1_000_000)
    max_hierarchy_edges: int = Field(default=100_000, gt=0, le=100_000)
    minimum_pair_support: int = Field(default=2, gt=0)
    minimum_pair_windows: int = Field(default=1, gt=0)
    artist_pair_evidence_ref_version: Literal[
        "attempt_ids_v1", "source_artifacts_v2", "source_artifacts_v3"
    ] = "attempt_ids_v1"


class PublicInputLoadError(RuntimeError):
    """Report an incomplete identity or an exceeded query bound."""


def _public_source(source_key: str) -> PublicSource:
    normalized = source_key.casefold()
    if "listenbrainz" in normalized:
        return "listenbrainz"
    if "musicbrainz" in normalized:
        return "musicbrainz"
    if "wikidata" in normalized:
        return "wikidata"
    raise PublicInputLoadError(f"unsupported model source: {source_key}")


def _bounded_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
    limit: int,
    label: str,
) -> tuple[sqlite3.Row, ...]:
    rows: list[sqlite3.Row] = []
    for raw_row in connection.execute(query, (*parameters, limit + 1)):
        if not isinstance(raw_row, sqlite3.Row):
            raise PublicInputLoadError("SQLite row factory must return sqlite3.Row")
        rows.append(raw_row)
    if len(rows) > limit:
        raise PublicInputLoadError(f"{label} exceed declared limit {limit}")
    return tuple(rows)


def _direct_memberships(
    connection: sqlite3.Connection, settings: PublicInputLoadSettings
) -> tuple[DirectMembershipEvidence, ...]:
    rows = _bounded_rows(
        connection,
        """
        SELECT evidence.id, evidence.evidence_value, evidence.method_key,
               evidence.source_record_id,
               (SELECT 'musicbrainz:artist:' || identifier.normalized_value
                FROM entity_identifiers AS identifier
                WHERE identifier.entity_id = evidence.artist_id
                  AND identifier.namespace = 'musicbrainz'
                ORDER BY identifier.id LIMIT 1) AS artist_ref,
               COALESCE(
                 (SELECT 'wikidata:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'wikidata'
                  ORDER BY identifier.id LIMIT 1),
                 (SELECT 'musicbrainz:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'musicbrainz'
                  ORDER BY identifier.id LIMIT 1)
               ) AS genre_ref
        FROM normalizable_artist_genre_evidence AS evidence
        JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
        JOIN active_rights_policy_permissions AS embed_permission
          ON embed_permission.policy_id = evidence.policy_id
         AND embed_permission.use_kind = 'embed'
         AND embed_permission.decision = 'allow'
        WHERE evidence.evidence_kind = 'direct_source_claim'
          AND evidence.method_key IN (
            'direct_musicbrainz_artist_genre', 'musicbrainz_artist_genre', 'wikidata_p136'
          )
          AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                CAST(evidence.artist_id AS TEXT), CAST(evidence.genre_id AS TEXT)
              ))
              OR (suppression.target_kind = 'provenance'
                  AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
              OR (suppression.target_kind = 'source' AND suppression.target_ref = CAST((
                    SELECT source_id FROM provenance_records
                    WHERE id = evidence.provenance_id
                  ) AS TEXT))
            )
          )
        ORDER BY artist_ref, genre_ref, evidence.method_key, evidence.id
        LIMIT ?
        """,
        (),
        settings.max_direct_memberships,
        "direct memberships",
    )
    missing = [int(row[0]) for row in rows if row[4] is None or row[5] is None]
    if missing:
        raise PublicInputLoadError(
            f"direct memberships lack public stable identities: {missing[:10]}"
        )
    result: list[DirectMembershipEvidence] = []
    for row in rows:
        method = str(row[2])
        facet: MembershipFacet = "wikidata_p136" if method == "wikidata_p136" else "musicbrainz_tag"
        result.append(
            DirectMembershipEvidence(
                artist_id=str(row[4]),
                genre_id=str(row[5]),
                facet=facet,
                value=float(row[1]),
                evidence_ref=f"catalog:artist-genre:{int(row[0])}:{row[3]!s}",
            )
        )
    return tuple(result)


def _artist_pairs(
    connection: sqlite3.Connection, settings: PublicInputLoadSettings
) -> tuple[ArtistPairEvidence, ...]:
    """Load pairs with the requested provenance-reference contract."""
    if settings.artist_pair_evidence_ref_version == "source_artifacts_v2":
        return _artist_pairs_source_artifacts(connection, settings, _source_artifact_ref)
    if settings.artist_pair_evidence_ref_version == "source_artifacts_v3":
        return _artist_pairs_source_artifacts(
            connection, settings, artist_pair_source_artifact_ref_v3
        )
    return _artist_pairs_attempt_ids_v1(connection, settings)


def _artist_pairs_attempt_ids_v1(
    connection: sqlite3.Connection, settings: PublicInputLoadSettings
) -> tuple[ArtistPairEvidence, ...]:
    """Preserve the sealed attempt-ID reference contract exactly."""
    rows = _bounded_rows(
        connection,
        """
        SELECT evidence.left_artist_source_id, evidence.right_artist_source_id,
               sum(evidence.distinct_user_count), count(*),
               min(evidence.ingest_attempt_id), max(evidence.ingest_attempt_id)
        FROM normalizable_artist_co_listen_evidence AS evidence
        JOIN artist_co_listen_runs AS run
          ON run.ingest_attempt_id = evidence.ingest_attempt_id
        JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
        JOIN active_rights_policy_permissions AS embed_permission
          ON embed_permission.policy_id = artifact.policy_id
         AND embed_permission.use_kind = 'embed'
         AND embed_permission.decision = 'allow'
        JOIN normalization_exports AS export
          ON export.staged_record_id = evidence.staged_record_id
        JOIN provenance_records AS provenance ON provenance.id = export.provenance_id
        WHERE NOT EXISTS (
          SELECT 1 FROM active_suppressions AS suppression
          WHERE suppression.use_kind IN ('all', 'embed') AND (
            (suppression.target_kind = 'provenance'
             AND suppression.target_ref = CAST(provenance.id AS TEXT))
            OR (suppression.target_kind = 'source'
                AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
            OR (suppression.target_kind = 'entity' AND suppression.target_ref IN (
              SELECT CAST(identifier.entity_id AS TEXT)
              FROM entity_identifiers AS identifier
              WHERE identifier.namespace = 'musicbrainz'
                AND ('musicbrainz:artist:' || identifier.normalized_value) IN (
                  evidence.left_artist_source_id, evidence.right_artist_source_id
                )
            ))
          )
        )
        GROUP BY evidence.left_artist_source_id, evidence.right_artist_source_id
        HAVING sum(evidence.distinct_user_count) >= ? AND count(*) >= ?
        ORDER BY sum(evidence.distinct_user_count) DESC,
                 evidence.left_artist_source_id, evidence.right_artist_source_id
        LIMIT ?
        """,
        (settings.minimum_pair_support, settings.minimum_pair_windows),
        settings.max_artist_pairs,
        "artist pairs",
    )
    return tuple(
        ArtistPairEvidence(
            left_artist_id=str(row[0]),
            right_artist_id=str(row[1]),
            listener_day_support=int(row[2]),
            supporting_windows=int(row[3]),
            evidence_refs=(f"listenbrainz:attempts:{int(row[4])}-{int(row[5])}",),
        )
        for row in rows
    )


def _source_artifact_ref(source_key: str, snapshot_ref: str, artifact_sha256: str) -> str:
    """Return an unambiguous, source-backed ListenBrainz evidence identity."""
    return (
        "listenbrainz:v2:source_key="
        f"{quote(source_key, safe='')}&snapshot_ref={quote(snapshot_ref, safe='')}"
        f"&artifact_sha256={artifact_sha256}"
    )


def _artist_pairs_source_artifacts(
    connection: sqlite3.Connection,
    settings: PublicInputLoadSettings,
    reference_builder: Callable[[str, str, str], str],
) -> tuple[ArtistPairEvidence, ...]:
    """Aggregate unchanged pair evidence with stable source-artifact references.

    ``pair_stats`` first applies the legacy aggregation and bound.  The outer
    query then streams each selected pair's distinct backing artifacts in a
    deterministic order, avoiding one query per pair.
    """
    cursor = connection.execute(
        """
        WITH eligible AS (
          SELECT evidence.left_artist_source_id AS left_artist_id,
                 evidence.right_artist_source_id AS right_artist_id,
                 evidence.distinct_user_count,
                 source.source_key, snapshot.snapshot_ref, artifact.sha256
          FROM normalizable_artist_co_listen_evidence AS evidence
          JOIN artist_co_listen_runs AS run
            ON run.ingest_attempt_id = evidence.ingest_attempt_id
          JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
          JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
          JOIN data_sources AS source ON source.id = snapshot.source_id
          JOIN active_rights_policy_permissions AS embed_permission
            ON embed_permission.policy_id = artifact.policy_id
           AND embed_permission.use_kind = 'embed'
           AND embed_permission.decision = 'allow'
          JOIN normalization_exports AS export
            ON export.staged_record_id = evidence.staged_record_id
          JOIN provenance_records AS provenance ON provenance.id = export.provenance_id
          WHERE NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'provenance'
               AND suppression.target_ref = CAST(provenance.id AS TEXT))
              OR (suppression.target_kind = 'source'
                  AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
              OR (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                SELECT CAST(identifier.entity_id AS TEXT)
                FROM entity_identifiers AS identifier
                WHERE identifier.namespace = 'musicbrainz'
                  AND ('musicbrainz:artist:' || identifier.normalized_value) IN (
                    evidence.left_artist_source_id, evidence.right_artist_source_id
                  )
              ))
            )
          )
        ), pair_stats AS (
          SELECT left_artist_id, right_artist_id, sum(distinct_user_count) AS support,
                 count(*) AS windows
          FROM eligible
          GROUP BY left_artist_id, right_artist_id
          HAVING sum(distinct_user_count) >= ? AND count(*) >= ?
          ORDER BY sum(distinct_user_count) DESC, left_artist_id, right_artist_id
          LIMIT ?
        ), pair_artifacts AS (
          SELECT DISTINCT eligible.left_artist_id, eligible.right_artist_id,
                 eligible.source_key, eligible.snapshot_ref, eligible.sha256
          FROM eligible
          JOIN pair_stats
            ON pair_stats.left_artist_id = eligible.left_artist_id
           AND pair_stats.right_artist_id = eligible.right_artist_id
        )
        SELECT pair_stats.left_artist_id, pair_stats.right_artist_id,
               pair_stats.support, pair_stats.windows,
               pair_artifacts.source_key, pair_artifacts.snapshot_ref, pair_artifacts.sha256
        FROM pair_stats
        JOIN pair_artifacts
          ON pair_artifacts.left_artist_id = pair_stats.left_artist_id
         AND pair_artifacts.right_artist_id = pair_stats.right_artist_id
        ORDER BY pair_stats.support DESC, pair_stats.left_artist_id, pair_stats.right_artist_id,
                 pair_artifacts.source_key, pair_artifacts.snapshot_ref, pair_artifacts.sha256
        """,
        (
            settings.minimum_pair_support,
            settings.minimum_pair_windows,
            settings.max_artist_pairs + 1,
        ),
    )
    result: list[ArtistPairEvidence] = []
    current_key: tuple[str, str] | None = None
    current_support = 0
    current_windows = 0
    refs: list[str] = []

    def append_current() -> None:
        if current_key is None:
            return
        if len(refs) > _MAX_ARTIST_PAIR_EVIDENCE_REFS:
            raise PublicInputLoadError(
                "artist pair evidence references exceed declared limit "
                f"{_MAX_ARTIST_PAIR_EVIDENCE_REFS}"
            )
        result.append(
            ArtistPairEvidence(
                left_artist_id=current_key[0],
                right_artist_id=current_key[1],
                listener_day_support=current_support,
                supporting_windows=current_windows,
                evidence_refs=tuple(refs),
            )
        )

    for raw_row in cursor:
        if not isinstance(raw_row, sqlite3.Row):
            raise PublicInputLoadError("SQLite row factory must return sqlite3.Row")
        key = (str(raw_row[0]), str(raw_row[1]))
        if current_key != key:
            append_current()
            current_key = key
            current_support = int(raw_row[2])
            current_windows = int(raw_row[3])
            refs = []
        if len(refs) >= _MAX_ARTIST_PAIR_EVIDENCE_REFS:
            raise PublicInputLoadError(
                "artist pair evidence references exceed declared limit "
                f"{_MAX_ARTIST_PAIR_EVIDENCE_REFS}"
            )
        refs.append(reference_builder(str(raw_row[4]), str(raw_row[5]), str(raw_row[6])))
    append_current()
    if len(result) > settings.max_artist_pairs:
        raise PublicInputLoadError(
            f"artist pairs exceed declared limit {settings.max_artist_pairs}"
        )
    return tuple(result)


def _hierarchy_edges(
    connection: sqlite3.Connection, settings: PublicInputLoadSettings
) -> tuple[GenreHierarchyEdge, ...]:
    rows = _bounded_rows(
        connection,
        """
        SELECT hierarchy.relation_id,
               'wikidata:genre:' || child_identifier.normalized_value,
               'wikidata:genre:' || parent_identifier.normalized_value
        FROM genre_hierarchy AS hierarchy
        JOIN modelable_music_genres AS qualified_child
          ON qualified_child.genre_id = hierarchy.child_genre_id
        JOIN modelable_music_genres AS qualified_parent
          ON qualified_parent.genre_id = hierarchy.parent_genre_id
        JOIN provenance_records AS provenance
          ON provenance.id = hierarchy.provenance_id
        JOIN active_rights_policy_permissions AS permission
          ON permission.policy_id = provenance.policy_id
         AND permission.use_kind = 'embed'
         AND permission.decision = 'allow'
        JOIN entity_identifiers AS child_identifier
          ON child_identifier.entity_id = hierarchy.child_genre_id
         AND child_identifier.namespace = 'wikidata'
        JOIN entity_identifiers AS parent_identifier
          ON parent_identifier.entity_id = hierarchy.parent_genre_id
         AND parent_identifier.namespace = 'wikidata'
        WHERE NOT EXISTS (
          SELECT 1 FROM active_suppressions AS suppression
          WHERE suppression.use_kind IN ('all', 'embed') AND (
            (suppression.target_kind = 'entity' AND suppression.target_ref IN (
              CAST(hierarchy.child_genre_id AS TEXT),
              CAST(hierarchy.parent_genre_id AS TEXT)
            ))
            OR (suppression.target_kind = 'provenance'
                AND suppression.target_ref = CAST(provenance.id AS TEXT))
            OR (suppression.target_kind = 'source'
                AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
          )
        )
        ORDER BY 2, 3, hierarchy.relation_id
        LIMIT ?
        """,
        (),
        settings.max_hierarchy_edges,
        "genre hierarchy edges",
    )
    result: dict[tuple[str, str], GenreHierarchyEdge] = {}
    for row in rows:
        key = (str(row[1]), str(row[2]))
        result.setdefault(
            key,
            GenreHierarchyEdge(
                child_genre_id=key[0],
                parent_genre_id=key[1],
                evidence_ref=f"catalog:genre-hierarchy:{int(row[0])}",
            ),
        )
    return tuple(result[key] for key in sorted(result))


def _genres(
    connection: sqlite3.Connection, settings: PublicInputLoadSettings
) -> tuple[GenreIdentity, ...]:
    rows = _bounded_rows(
        connection,
        """
        WITH eligible_genres AS (
          SELECT evidence.genre_id,
                 'catalog:artist-genre:' || min(evidence.id) AS evidence_ref
          FROM normalizable_artist_genre_evidence AS evidence
          JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
          JOIN active_rights_policy_permissions AS embed_permission
            ON embed_permission.policy_id = evidence.policy_id
           AND embed_permission.use_kind = 'embed'
           AND embed_permission.decision = 'allow'
          WHERE evidence.evidence_kind = 'direct_source_claim'
            AND evidence.method_key IN (
              'direct_musicbrainz_artist_genre',
              'musicbrainz_artist_genre',
              'wikidata_p136'
            )
            AND NOT EXISTS (
              SELECT 1 FROM active_suppressions AS suppression
              WHERE suppression.use_kind IN ('all', 'embed') AND (
                (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                  CAST(evidence.artist_id AS TEXT), CAST(evidence.genre_id AS TEXT)
                ))
                OR (suppression.target_kind = 'provenance'
                    AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
                OR (suppression.target_kind = 'source' AND suppression.target_ref = CAST((
                      SELECT source_id FROM provenance_records
                      WHERE id = evidence.provenance_id
                    ) AS TEXT))
              )
            )
          GROUP BY evidence.genre_id
          UNION
          SELECT evidence.genre_id,
                 'catalog:album-genre:' || min(evidence.id) AS evidence_ref
          FROM normalizable_album_genre_memberships AS evidence
          JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
          JOIN active_rights_policy_permissions AS embed_permission
            ON embed_permission.policy_id = evidence.policy_id
           AND embed_permission.use_kind = 'embed'
           AND embed_permission.decision = 'allow'
          WHERE evidence.evidence_kind IN (
            'musicbrainz_release_group_genre', 'wikidata_p136'
          )
            AND NOT EXISTS (
              SELECT 1 FROM active_suppressions AS suppression
              WHERE suppression.use_kind IN ('all', 'embed') AND (
                (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                  CAST(evidence.release_group_id AS TEXT), CAST(evidence.genre_id AS TEXT)
                ))
                OR (suppression.target_kind = 'provenance'
                    AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
                OR (suppression.target_kind = 'source' AND suppression.target_ref = CAST((
                      SELECT source_id FROM provenance_records
                      WHERE id = evidence.provenance_id
                    ) AS TEXT))
              )
            )
          GROUP BY evidence.genre_id
          UNION
          SELECT evidence.genre_id,
                 'catalog:recording-genre:' || min(evidence.id) AS evidence_ref
          FROM normalizable_recording_genre_memberships AS evidence
          JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
          JOIN active_rights_policy_permissions AS embed_permission
            ON embed_permission.policy_id = evidence.policy_id
           AND embed_permission.use_kind = 'embed'
           AND embed_permission.decision = 'allow'
          WHERE evidence.evidence_kind IN (
            'musicbrainz_recording_genre', 'wikidata_p136'
          )
            AND NOT EXISTS (
              SELECT 1 FROM active_suppressions AS suppression
              WHERE suppression.use_kind IN ('all', 'embed') AND (
                (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                  CAST(evidence.recording_id AS TEXT), CAST(evidence.genre_id AS TEXT)
                ))
                OR (suppression.target_kind = 'provenance'
                    AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
                OR (suppression.target_kind = 'source' AND suppression.target_ref = CAST((
                      SELECT source_id FROM provenance_records
                      WHERE id = evidence.provenance_id
                    ) AS TEXT))
              )
            )
          GROUP BY evidence.genre_id
          UNION
          SELECT endpoint.genre_id,
                 'catalog:genre-hierarchy:' || min(endpoint.relation_id) AS evidence_ref
          FROM (
            SELECT hierarchy.child_genre_id AS genre_id,
                   hierarchy.relation_id, hierarchy.provenance_id
            FROM genre_hierarchy AS hierarchy
            UNION ALL
            SELECT hierarchy.parent_genre_id AS genre_id,
                   hierarchy.relation_id, hierarchy.provenance_id
            FROM genre_hierarchy AS hierarchy
          ) AS endpoint
          JOIN modelable_music_genres AS qualified ON qualified.genre_id = endpoint.genre_id
          JOIN provenance_records AS provenance ON provenance.id = endpoint.provenance_id
          JOIN active_rights_policy_permissions AS embed_permission
            ON embed_permission.policy_id = provenance.policy_id
           AND embed_permission.use_kind = 'embed'
           AND embed_permission.decision = 'allow'
          WHERE NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'entity'
               AND suppression.target_ref = CAST(endpoint.genre_id AS TEXT))
              OR (suppression.target_kind = 'provenance'
                  AND suppression.target_ref = CAST(provenance.id AS TEXT))
              OR (suppression.target_kind = 'source'
                  AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
            )
          )
          GROUP BY endpoint.genre_id
        )
        SELECT eligible.genre_id,
               COALESCE(
                 (SELECT 'wikidata:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = eligible.genre_id
                    AND identifier.namespace = 'wikidata'
                  ORDER BY identifier.id LIMIT 1),
                 (SELECT 'musicbrainz:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = eligible.genre_id
                    AND identifier.namespace = 'musicbrainz'
                  ORDER BY identifier.id LIMIT 1)
               ) AS genre_ref,
               COALESCE(
                 (SELECT name FROM genres WHERE id = eligible.genre_id),
                 (SELECT name FROM entity_names
                  WHERE entity_id = eligible.genre_id
                  ORDER BY (substr(name, 1, 1) = 'Q' AND length(name) > 1
                            AND substr(name, 2) NOT GLOB '*[^0-9]*'),
                           is_preferred DESC, id LIMIT 1)
               ) AS name,
               min(eligible.evidence_ref)
        FROM eligible_genres AS eligible
        GROUP BY eligible.genre_id
        ORDER BY genre_ref
        LIMIT ?
        """,
        (),
        settings.max_direct_memberships,
        "genre identities",
    )
    result: list[GenreIdentity] = []
    for row in rows:
        if row[1] is None or row[2] is None:
            raise PublicInputLoadError(f"genre {int(row[0])} lacks a public identity or name")
        result.append(
            GenreIdentity(
                genre_id=str(row[1]),
                name=str(row[2]),
                evidence_refs=(str(row[3]),),
            )
        )
    return tuple(result)


def _metadata_candidates(
    connection: sqlite3.Connection, settings: PublicInputLoadSettings
) -> tuple[MetadataCandidate, ...]:
    artist_rows = _bounded_rows(
        connection,
        """
        SELECT evidence.artist_id, evidence.genre_id, max(evidence.evidence_value),
               count(DISTINCT evidence.source_key),
               (SELECT name FROM entity_names
                WHERE entity_id = evidence.artist_id
                ORDER BY (substr(name, 1, 1) = 'Q' AND length(name) > 1
                          AND substr(name, 2) NOT GLOB '*[^0-9]*'),
                         is_preferred DESC, id LIMIT 1) AS name,
               (SELECT 'musicbrainz:artist:' || identifier.normalized_value
                FROM entity_identifiers AS identifier
                WHERE identifier.entity_id = evidence.artist_id
                  AND identifier.namespace = 'musicbrainz'
                ORDER BY identifier.id LIMIT 1) AS entity_ref,
               COALESCE(
                 (SELECT 'wikidata:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'wikidata'
                  ORDER BY identifier.id LIMIT 1),
                 (SELECT 'musicbrainz:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'musicbrainz'
                  ORDER BY identifier.id LIMIT 1)
               ) AS genre_ref,
               min(evidence.id)
        FROM normalizable_artist_genre_evidence AS evidence
        JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
        JOIN active_rights_policy_permissions AS embed_permission
          ON embed_permission.policy_id = evidence.policy_id
         AND embed_permission.use_kind = 'embed'
         AND embed_permission.decision = 'allow'
        WHERE evidence.evidence_kind = 'direct_source_claim'
          AND evidence.method_key IN (
            'direct_musicbrainz_artist_genre', 'musicbrainz_artist_genre', 'wikidata_p136'
          )
          AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                CAST(evidence.artist_id AS TEXT), CAST(evidence.genre_id AS TEXT)
              ))
              OR (suppression.target_kind = 'provenance'
                  AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
              OR (suppression.target_kind = 'source' AND suppression.target_ref = CAST((
                    SELECT source_id FROM provenance_records
                    WHERE id = evidence.provenance_id
                  ) AS TEXT))
            )
          )
        GROUP BY evidence.artist_id, evidence.genre_id
        ORDER BY genre_ref, max(evidence.evidence_value) DESC, entity_ref
        LIMIT ?
        """,
        (),
        settings.max_metadata_candidates,
        "artist metadata candidates",
    )
    album_rows = _bounded_rows(
        connection,
        """
        SELECT evidence.release_group_id, evidence.genre_id,
               max(COALESCE(evidence.source_count, 1)),
               count(DISTINCT evidence.source_family),
               (SELECT name FROM entity_names
                WHERE entity_id = evidence.release_group_id
                ORDER BY (substr(name, 1, 1) = 'Q' AND length(name) > 1
                          AND substr(name, 2) NOT GLOB '*[^0-9]*'),
                         is_preferred DESC, id LIMIT 1) AS name,
               COALESCE(
                 (SELECT 'musicbrainz:release-group:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.release_group_id
                    AND identifier.namespace = 'musicbrainz'
                  ORDER BY identifier.id LIMIT 1),
                 (SELECT 'wikidata:release-group:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.release_group_id
                    AND identifier.namespace = 'wikidata'
                  ORDER BY identifier.id LIMIT 1)
               ) AS entity_ref,
               COALESCE(
                 (SELECT 'wikidata:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'wikidata'
                  ORDER BY identifier.id LIMIT 1),
                 (SELECT 'musicbrainz:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'musicbrainz'
                  ORDER BY identifier.id LIMIT 1)
               ) AS genre_ref,
               min(evidence.id)
        FROM normalizable_album_genre_memberships AS evidence
        JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
        JOIN active_rights_policy_permissions AS embed_permission
          ON embed_permission.policy_id = evidence.policy_id
         AND embed_permission.use_kind = 'embed'
         AND embed_permission.decision = 'allow'
        WHERE evidence.evidence_kind IN (
            'musicbrainz_release_group_genre', 'wikidata_p136'
        )
          AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'entity' AND suppression.target_ref IN (
                CAST(evidence.release_group_id AS TEXT), CAST(evidence.genre_id AS TEXT)
              ))
              OR (suppression.target_kind = 'provenance'
                  AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
              OR (suppression.target_kind = 'source' AND suppression.target_ref = CAST((
                    SELECT source_id FROM provenance_records
                    WHERE id = evidence.provenance_id
                  ) AS TEXT))
            )
          )
        GROUP BY evidence.release_group_id, evidence.genre_id
        ORDER BY genre_ref, max(COALESCE(evidence.source_count, 1)) DESC, entity_ref
        LIMIT ?
        """,
        (),
        settings.max_metadata_candidates,
        "album metadata candidates",
    )
    has_recording_genres = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') "
        "AND name = 'normalizable_recording_genre_memberships'"
    ).fetchone()
    recording_rows = (
        ()
        if has_recording_genres is None
        else _bounded_rows(
            connection,
            """
        SELECT evidence.recording_id, evidence.genre_id,
               max(COALESCE(evidence.source_count, 1)), 1,
               (SELECT name FROM entity_names
                WHERE entity_id = evidence.recording_id
                ORDER BY (substr(name, 1, 1) = 'Q' AND length(name) > 1
                          AND substr(name, 2) NOT GLOB '*[^0-9]*'),
                         is_preferred DESC, id LIMIT 1) AS name,
               (SELECT 'musicbrainz:recording:' || identifier.normalized_value
                FROM entity_identifiers AS identifier
                WHERE identifier.entity_id = evidence.recording_id
                  AND identifier.namespace = 'musicbrainz'
                ORDER BY identifier.id LIMIT 1) AS entity_ref,
               COALESCE(
                 (SELECT 'wikidata:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'wikidata'
                  ORDER BY identifier.id LIMIT 1),
                 (SELECT 'musicbrainz:genre:' || identifier.normalized_value
                  FROM entity_identifiers AS identifier
                  WHERE identifier.entity_id = evidence.genre_id
                    AND identifier.namespace = 'musicbrainz'
                  ORDER BY identifier.id LIMIT 1)
               ) AS genre_ref,
               min(evidence.id)
        FROM normalizable_recording_genre_memberships AS evidence
        JOIN modelable_music_genres AS qualified ON qualified.genre_id = evidence.genre_id
        JOIN active_rights_policy_permissions AS embed_permission
          ON embed_permission.policy_id = evidence.policy_id
         AND embed_permission.use_kind = 'embed'
         AND embed_permission.decision = 'allow'
        WHERE NOT EXISTS (
          SELECT 1 FROM active_suppressions AS suppression
          WHERE suppression.use_kind IN ('all', 'embed') AND (
            (suppression.target_kind = 'entity' AND suppression.target_ref IN (
              CAST(evidence.recording_id AS TEXT), CAST(evidence.genre_id AS TEXT)
            ))
            OR (suppression.target_kind = 'provenance'
                AND suppression.target_ref = CAST(evidence.provenance_id AS TEXT))
            OR (suppression.target_kind = 'source'
                AND suppression.target_ref = CAST((
                  SELECT source_id FROM provenance_records
                  WHERE id = evidence.provenance_id
                ) AS TEXT))
          )
        )
        GROUP BY evidence.recording_id, evidence.genre_id
        ORDER BY genre_ref, max(COALESCE(evidence.source_count, 1)) DESC, entity_ref
        LIMIT ?
        """,
            (),
            settings.max_metadata_candidates,
            "recording metadata candidates",
        )
    )
    rows = (*artist_rows, *album_rows, *recording_rows)
    if len(rows) > settings.max_metadata_candidates:
        raise PublicInputLoadError(
            f"combined metadata candidates exceed declared limit {settings.max_metadata_candidates}"
        )
    return _candidate_rows(rows)


def _candidate_rows(rows: Iterable[sqlite3.Row]) -> tuple[MetadataCandidate, ...]:
    result: list[MetadataCandidate] = []
    for index, row in enumerate(rows):
        if row[4] is None or row[5] is None or row[6] is None:
            raise PublicInputLoadError(f"metadata candidate lacks public identity at row {index}")
        name = str(row[4])
        if name.startswith("Q") and name[1:].isdigit():
            continue
        entity_ref = str(row[5])
        if ":release-group:" in entity_ref:
            entity_kind = "release_group"
        elif ":recording:" in entity_ref:
            entity_kind = "recording"
        else:
            entity_kind = "artist"
        result.append(
            MetadataCandidate(
                entity_kind=entity_kind,
                entity_id=entity_ref,
                genre_id=str(row[6]),
                name=name,
                direct_evidence_value=float(row[2]),
                source_count=int(row[3]),
                evidence_refs=(f"catalog:metadata:{int(row[7])}",),
            )
        )
    return tuple(result)


def _artifacts(connection: sqlite3.Connection) -> tuple[PublicArtifact, ...]:
    rows = connection.execute(
        """
        SELECT DISTINCT source.source_key, provenance.snapshot_ref,
                        provenance.artifact_sha256,
                        EXISTS (
                          SELECT 1 FROM active_rights_policy_permissions AS export_permission
                          WHERE export_permission.policy_id = provenance.policy_id
                            AND export_permission.use_kind = 'export'
                            AND export_permission.decision = 'allow'
                        ) AS export_allowed
        FROM provenance_records AS provenance
        JOIN data_sources AS source ON source.id = provenance.source_id
        JOIN active_rights_policy_permissions AS embed_permission
          ON embed_permission.policy_id = provenance.policy_id
         AND embed_permission.use_kind = 'embed'
         AND embed_permission.decision = 'allow'
        WHERE provenance.artifact_sha256 IS NOT NULL
          AND (
            lower(source.source_key) LIKE '%listenbrainz%'
            OR lower(source.source_key) LIKE '%musicbrainz%'
            OR lower(source.source_key) LIKE '%wikidata%'
          )
          AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'provenance'
               AND suppression.target_ref = CAST(provenance.id AS TEXT))
              OR (suppression.target_kind = 'source'
                  AND suppression.target_ref = CAST(provenance.source_id AS TEXT))
            )
          )
        ORDER BY source.source_key, provenance.snapshot_ref, provenance.artifact_sha256
        """
    )
    return tuple(
        PublicArtifact(
            source=_public_source(str(row[0])),
            snapshot=str(row[1]),
            artifact_key=f"{row[0]!s}:{row[2]!s}",
            content_sha256=str(row[2]),
            export_allowed=bool(row[3]),
        )
        for row in rows
    )


class PublicModelRepository:
    """Load graph inputs without coupling model algorithms to catalog SQL."""

    def __init__(
        self,
        catalog: sqlite3.Connection,
        listenbrainz: sqlite3.Connection | None = None,
    ) -> None:
        """Keep both read-only connection lifetimes with the caller."""
        catalog.row_factory = sqlite3.Row
        self._catalog = catalog
        if listenbrainz is not None:
            listenbrainz.row_factory = sqlite3.Row
        self._listenbrainz = listenbrainz

    def load(self, settings: PublicInputLoadSettings) -> PublicModelInput:
        """Load only policy-safe public evidence under explicit row limits."""
        if self._listenbrainz is None:
            raise PublicInputLoadError("artist pair loading requires a ListenBrainz database")
        artifact_values = (*_artifacts(self._catalog), *_artifacts(self._listenbrainz))
        artifacts = tuple(
            sorted(
                set(artifact_values),
                key=lambda item: (item.source, item.snapshot, item.artifact_key),
            )
        )
        return PublicModelInput(
            artifacts=artifacts,
            genres=_genres(self._catalog, settings),
            direct_memberships=_direct_memberships(self._catalog, settings),
            artist_pairs=_artist_pairs(self._listenbrainz, settings),
            metadata_candidates=_metadata_candidates(self._catalog, settings),
            hierarchy=_hierarchy_edges(self._catalog, settings),
        )

    def load_catalog_only(self, settings: PublicInputLoadSettings) -> PublicModelInput:
        """Load policy-safe catalog evidence before a temporal graph is selected."""
        return PublicModelInput(
            artifacts=_artifacts(self._catalog),
            genres=_genres(self._catalog, settings),
            direct_memberships=_direct_memberships(self._catalog, settings),
            metadata_candidates=_metadata_candidates(self._catalog, settings),
            hierarchy=_hierarchy_edges(self._catalog, settings),
        )
