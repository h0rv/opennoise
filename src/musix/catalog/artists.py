"""Direct-SQL repository for common artist projections."""

import hashlib
import sqlite3

from musix.models.catalog import ArtistProjection, CatalogProjection, ProjectionResult


def _hash_parts(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _one_id(connection: sqlite3.Connection, query: str, values: tuple[object, ...]) -> int:
    row = connection.execute(query, values).fetchone()
    if row is None:
        raise RuntimeError("catalog object could not be read back")
    return int(row[0])


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id


class ArtistProjector:
    """Persist source-supported artist core fields, names, and identifiers."""

    @property
    def key(self) -> str:
        """Return the accepted projection discriminant."""
        return "artist"

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Persist artist claims idempotently without source lifecycle writes."""
        if not isinstance(projection, ArtistProjection):
            raise TypeError("ArtistProjector requires ArtistProjection")
        source_identifier = projection.identifiers[0]
        connection.execute(
            "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES (?, ?)",
            (source_identifier.type_key, source_identifier.type_key.replace("_", " ").title()),
        )
        identifier_type_id = _one_id(
            connection,
            "SELECT id FROM identifier_types WHERE type_key = ?",
            (source_identifier.type_key,),
        )
        row = connection.execute(
            """SELECT entity_id FROM entity_identifiers
               WHERE identifier_type_id = ? AND namespace = ? AND normalized_value = ?
               ORDER BY id LIMIT 1""",
            (identifier_type_id, source_identifier.namespace, source_identifier.value.strip()),
        ).fetchone()
        duplicate = row is not None
        if row is None:
            cursor = connection.execute(
                "INSERT INTO catalog_entities (entity_kind) VALUES ('artist')"
            )
            entity_id = _lastrowid(cursor)
            connection.execute(
                """INSERT INTO artists
                   (id, artist_kind, disambiguation, begin_year, end_year)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    entity_id,
                    projection.artist_kind,
                    projection.disambiguation,
                    projection.begin_year,
                    projection.end_year,
                ),
            )
        else:
            entity_id = int(row[0])
        connection.execute(
            """INSERT OR IGNORE INTO entity_provenance
               (entity_id, provenance_id, field_set_json, is_primary)
               VALUES (?, ?, '["name","aliases","identifiers","artist_core"]', 0)""",
            (entity_id, provenance_id),
        )
        for identifier in projection.identifiers:
            connection.execute(
                "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES (?, ?)",
                (identifier.type_key, identifier.type_key.replace("_", " ").title()),
            )
            type_id = _one_id(
                connection,
                "SELECT id FROM identifier_types WHERE type_key = ?",
                (identifier.type_key,),
            )
            connection.execute(
                """INSERT OR IGNORE INTO entity_identifiers
                   (entity_id, identifier_type_id, namespace, value, normalized_value,
                    provenance_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entity_id,
                    type_id,
                    identifier.namespace,
                    identifier.value,
                    identifier.value.strip(),
                    provenance_id,
                ),
            )
        for claim in projection.names:
            fingerprint = _hash_parts(str(entity_id), claim.kind, claim.language_tag, claim.value)
            connection.execute(
                """INSERT OR IGNORE INTO entity_names
                   (entity_id, name_kind, name, language_tag, is_preferred, provenance_id,
                    fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entity_id,
                    claim.kind,
                    claim.value,
                    claim.language_tag,
                    int(claim.kind == "primary"),
                    provenance_id,
                    fingerprint,
                ),
            )
        search_text = " ".join(claim.value for claim in projection.names)
        connection.execute(
            """INSERT OR IGNORE INTO search_documents
               (entity_id, language_tag, field_kind, search_text, input_fingerprint,
                provenance_id, policy_id)
               VALUES (?, 'und', 'name', ?, ?, ?, ?)""",
            (
                entity_id,
                search_text,
                _hash_parts(str(entity_id), search_text),
                provenance_id,
                policy_id,
            ),
        )
        return ProjectionResult(
            projection_kind=self.key,
            target_id=entity_id,
            duplicate=duplicate,
        )
