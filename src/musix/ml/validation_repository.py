"""Load bounded temporal and hierarchy evidence for graph validation."""

import sqlite3

from pydantic import Field

from musix.ml.repository import PublicInputLoadError
from musix.models import FrozenModel
from musix.models.modeling import ArtistPairEvidence, PublicArtifact
from musix.models.validation import GenreHierarchyEdge, TemporalPairSnapshot

_MINIMUM_TEMPORAL_SNAPSHOTS = 3


class ValidationLoadSettings(FrozenModel):
    """Bound temporal and hierarchy validation inputs."""

    minimum_pair_support: int = Field(default=2, gt=0)
    maximum_pairs_per_snapshot: int = Field(default=250_000, gt=0, le=1_000_000)
    maximum_snapshots: int = Field(default=14, ge=3, le=14)
    maximum_hierarchy_edges: int = Field(default=100_000, gt=0)


def _rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
    *,
    maximum: int,
    label: str,
) -> tuple[sqlite3.Row, ...]:
    values: list[sqlite3.Row] = []
    for row in connection.execute(query, (*parameters, maximum + 1)):
        if not isinstance(row, sqlite3.Row):
            raise PublicInputLoadError("SQLite row factory must return sqlite3.Row")
        values.append(row)
    if len(values) > maximum:
        raise PublicInputLoadError(f"{label} exceed declared limit {maximum}")
    return tuple(values)


def _snapshot_runs(
    connection: sqlite3.Connection,
    settings: ValidationLoadSettings,
) -> tuple[sqlite3.Row, ...]:
    return _rows(
        connection,
        """
        SELECT snapshot.snapshot_ref, artifact.sha256, source.source_key,
               run.ingest_attempt_id, run.minimum_listened_at, run.maximum_listened_at,
               run.listens_seen, run.listens_with_artist_mbid, run.distinct_artists,
               run.user_windows,
               EXISTS (
                 SELECT 1 FROM active_rights_policy_permissions AS permission
                 WHERE permission.policy_id = artifact.policy_id
                   AND permission.use_kind = 'export'
                   AND permission.decision = 'allow'
               ) AS export_allowed
        FROM artist_co_listen_runs AS run
        JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
        JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
        JOIN data_sources AS source ON source.id = snapshot.source_id
        JOIN active_rights_policy_permissions AS permission
          ON permission.policy_id = artifact.policy_id
         AND permission.use_kind = 'embed'
         AND permission.decision = 'allow'
        WHERE run.minimum_listened_at IS NOT NULL
          AND run.maximum_listened_at IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM active_suppressions AS suppression
            WHERE suppression.use_kind IN ('all', 'embed') AND (
              (suppression.target_kind = 'source'
               AND suppression.target_ref = CAST(source.id AS TEXT))
              OR (suppression.target_kind = 'snapshot'
                  AND suppression.target_ref = CAST(snapshot.id AS TEXT))
              OR (suppression.target_kind = 'artifact'
                  AND suppression.target_ref = CAST(artifact.id AS TEXT))
            )
          )
        ORDER BY run.minimum_listened_at, snapshot.snapshot_ref
        LIMIT ?
        """,
        (),
        maximum=settings.maximum_snapshots,
        label="ListenBrainz snapshots",
    )


def _snapshot_pairs(
    connection: sqlite3.Connection,
    attempt_id: int,
    settings: ValidationLoadSettings,
) -> tuple[ArtistPairEvidence, ...]:
    rows = _rows(
        connection,
        """
        SELECT left_artist_source_id, right_artist_source_id,
               sum(distinct_user_count) AS support, count(*) AS windows,
               min(id), max(id)
        FROM normalizable_artist_co_listen_evidence
        WHERE ingest_attempt_id = ?
        GROUP BY left_artist_source_id, right_artist_source_id
        HAVING sum(distinct_user_count) >= ?
        ORDER BY support DESC, left_artist_source_id, right_artist_source_id
        LIMIT ?
        """,
        (attempt_id, settings.minimum_pair_support),
        maximum=settings.maximum_pairs_per_snapshot,
        label=f"pairs for attempt {attempt_id}",
    )
    return tuple(
        ArtistPairEvidence(
            left_artist_id=str(row[0]),
            right_artist_id=str(row[1]),
            listener_day_support=int(row[2]),
            supporting_windows=int(row[3]),
            evidence_refs=(f"listenbrainz:pair-rows:{int(row[4])}-{int(row[5])}",),
        )
        for row in rows
    )


def _hierarchy_edges(
    connection: sqlite3.Connection,
    settings: ValidationLoadSettings,
) -> tuple[GenreHierarchyEdge, ...]:
    rows = _rows(
        connection,
        """
        SELECT hierarchy.relation_id,
               'wikidata:genre:' || child_identifier.normalized_value,
               'wikidata:genre:' || parent_identifier.normalized_value
        FROM genre_hierarchy AS hierarchy
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
        maximum=settings.maximum_hierarchy_edges,
        label="genre hierarchy edges",
    )
    deduplicated: dict[tuple[str, str], GenreHierarchyEdge] = {}
    for row in rows:
        key = (str(row[1]), str(row[2]))
        deduplicated.setdefault(
            key,
            GenreHierarchyEdge(
                child_genre_id=key[0],
                parent_genre_id=key[1],
                evidence_ref=f"catalog:genre-hierarchy:{int(row[0])}",
            ),
        )
    return tuple(deduplicated[key] for key in sorted(deduplicated))


class GraphValidationRepository:
    """Load source-separated validation evidence without model SQL coupling."""

    def __init__(self, catalog: sqlite3.Connection, listenbrainz: sqlite3.Connection) -> None:
        """Keep both read-only connection lifetimes with the caller."""
        catalog.row_factory = sqlite3.Row
        listenbrainz.row_factory = sqlite3.Row
        self._catalog = catalog
        self._listenbrainz = listenbrainz

    def temporal_snapshots(
        self, settings: ValidationLoadSettings
    ) -> tuple[TemporalPairSnapshot, ...]:
        """Load complete privacy-safe runs in chronological order."""
        result = [
            TemporalPairSnapshot(
                artifact=PublicArtifact(
                    source="listenbrainz",
                    snapshot=str(row[0]),
                    artifact_key=f"{row[2]!s}:{row[1]!s}",
                    content_sha256=str(row[1]),
                    export_allowed=bool(row[10]),
                ),
                minimum_listened_at=int(row[4]),
                maximum_listened_at=int(row[5]),
                listens_seen=int(row[6]),
                listens_with_artist_mbid=int(row[7]),
                distinct_artists=int(row[8]),
                user_windows=int(row[9]),
                pairs=_snapshot_pairs(self._listenbrainz, int(row[3]), settings),
            )
            for row in _snapshot_runs(self._listenbrainz, settings)
        ]
        if len(result) < _MINIMUM_TEMPORAL_SNAPSHOTS:
            raise PublicInputLoadError("temporal validation requires at least three snapshots")
        return tuple(result)

    def hierarchy_edges(self, settings: ValidationLoadSettings) -> tuple[GenreHierarchyEdge, ...]:
        """Load direct public hierarchy claims as a separate facet."""
        return _hierarchy_edges(self._catalog, settings)
