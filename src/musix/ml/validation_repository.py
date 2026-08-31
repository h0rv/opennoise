"""Load bounded temporal and hierarchy evidence for graph validation."""

import sqlite3

from pydantic import Field

from musix.ml.repository import PublicInputLoadError
from musix.models import FrozenModel
from musix.models.modeling import GenreHierarchyEdge


class ValidationLoadSettings(FrozenModel):
    """Bound temporal and hierarchy validation inputs."""

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

    def __init__(self, catalog: sqlite3.Connection) -> None:
        """Keep the read-only catalog connection lifetime with the caller."""
        catalog.row_factory = sqlite3.Row
        self._catalog = catalog

    def hierarchy_edges(self, settings: ValidationLoadSettings) -> tuple[GenreHierarchyEdge, ...]:
        """Load direct public hierarchy claims as a separate facet."""
        return _hierarchy_edges(self._catalog, settings)
