"""Direct-SQL persistence for generic evidence-rich entity projections."""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from musix.models.catalog import (
    CatalogProjection,
    EntityProjection,
    ProjectionResult,
    RelationClaim,
)
from musix.types import EntityKind


def _hash_parts(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id


def _one_id(connection: sqlite3.Connection, query: str, values: tuple[object, ...]) -> int:
    row = connection.execute(query, values).fetchone()
    if row is None:
        raise RuntimeError("catalog object could not be read back")
    return int(row[0])


def _identifier_type(connection: sqlite3.Connection, type_key: str) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES (?, ?)",
        (type_key, type_key.replace("_", " ").title()),
    )
    return _one_id(
        connection,
        "SELECT id FROM identifier_types WHERE type_key = ?",
        (type_key,),
    )


def _qid_entity(connection: sqlite3.Connection, qid: str, entity_kind: EntityKind) -> int | None:
    identifier_type_id = _identifier_type(connection, f"wikidata_{entity_kind}_qid")
    row = connection.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type_id = ? AND namespace = 'wikidata' AND normalized_value = ?
           ORDER BY id LIMIT 1""",
        (identifier_type_id, qid),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _genre_slug(qid: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", qid.casefold()).strip("-")
    return f"wikidata-{normalized}"


def _insert_subtype(
    connection: sqlite3.Connection,
    entity_id: int,
    entity_kind: EntityKind,
    name: str,
    qid: str,
) -> None:
    match entity_kind:
        case "genre":
            connection.execute(
                "INSERT INTO genres (id, slug, name) VALUES (?, ?, ?)",
                (entity_id, _genre_slug(qid), name),
            )
        case "artist":
            connection.execute("INSERT INTO artists (id) VALUES (?)", (entity_id,))
        case "release_group":
            connection.execute("INSERT INTO release_groups (id) VALUES (?)", (entity_id,))
        case "recording":
            connection.execute("INSERT INTO recordings (id) VALUES (?)", (entity_id,))
        case "work":
            connection.execute("INSERT INTO works (id) VALUES (?)", (entity_id,))


def _ensure_entity(
    connection: sqlite3.Connection,
    *,
    qid: str,
    entity_kind: EntityKind,
    name: str,
    provenance_id: int,
) -> tuple[int, bool]:
    existing = _qid_entity(connection, qid, entity_kind)
    if existing is not None:
        row = connection.execute(
            "SELECT entity_kind FROM catalog_entities WHERE id = ?", (existing,)
        ).fetchone()
        if row is None or str(row[0]) != entity_kind:
            raise ValueError(f"Wikidata {qid} has conflicting projected entity kinds")
        return existing, True
    entity_id = _lastrowid(
        connection.execute("INSERT INTO catalog_entities (entity_kind) VALUES (?)", (entity_kind,))
    )
    _insert_subtype(connection, entity_id, entity_kind, name, qid)
    identifier_type_id = _identifier_type(connection, f"wikidata_{entity_kind}_qid")
    connection.execute(
        """INSERT INTO entity_identifiers
           (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
           VALUES (?, ?, 'wikidata', ?, ?, ?)""",
        (entity_id, identifier_type_id, qid, qid, provenance_id),
    )
    return entity_id, False


def _preferred_name(projection: EntityProjection) -> str:
    english = next(
        (
            claim.value
            for claim in projection.names
            if claim.kind == "primary" and claim.language_tag == "en"
        ),
        None,
    )
    return english or next(claim.value for claim in projection.names if claim.kind == "primary")


def _persist_names(
    connection: sqlite3.Connection,
    projection: EntityProjection,
    entity_id: int,
    provenance_id: int,
) -> None:
    for claim in projection.names:
        fingerprint = _hash_parts(str(entity_id), claim.kind, claim.language_tag, claim.value)
        connection.execute(
            """INSERT OR IGNORE INTO entity_names
               (entity_id, name_kind, name, language_tag, script_code, is_preferred,
                provenance_id, fingerprint)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_id,
                claim.kind,
                claim.value,
                claim.language_tag,
                claim.script_code,
                int(claim.kind == "primary"),
                provenance_id,
                fingerprint,
            ),
        )


def _persist_identifiers(
    connection: sqlite3.Connection,
    projection: EntityProjection,
    entity_id: int,
    provenance_id: int,
) -> None:
    for identifier in projection.identifiers:
        type_id = _identifier_type(connection, identifier.type_key)
        connection.execute(
            """INSERT OR IGNORE INTO entity_identifiers
               (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
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


def _persist_claims(
    connection: sqlite3.Connection,
    projection: EntityProjection,
    entity_id: int,
    provenance_id: int,
    policy_id: int,
) -> None:
    for claim in projection.claims:
        canonical = json.dumps(
            claim.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        claim_hash = hashlib.sha256(canonical.encode()).hexdigest()
        connection.execute(
            """INSERT OR IGNORE INTO entity_claims
               (entity_id, claim_type, claim_key, normalized_value_json, asserted_at,
                provenance_id, policy_id, claim_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_id,
                f"wikidata_{claim.claim_kind}",
                claim.property_key,
                canonical,
                _now(),
                provenance_id,
                policy_id,
                claim_hash,
            ),
        )


def _ensure_target_genre(
    connection: sqlite3.Connection,
    claim: RelationClaim,
    provenance_id: int,
) -> int:
    target_id, _duplicate = _ensure_entity(
        connection,
        qid=claim.target.value,
        entity_kind="genre",
        name=claim.target.value,
        provenance_id=provenance_id,
    )
    return target_id


def _persist_relations(
    connection: sqlite3.Connection,
    projection: EntityProjection,
    entity_id: int,
    provenance_id: int,
    policy_id: int,
) -> None:
    for claim in projection.claims:
        if not isinstance(claim, RelationClaim) or claim.target.namespace != "wikidata":
            continue
        genre_id = _ensure_target_genre(connection, claim, provenance_id)
        if projection.entity_kind == "genre" and claim.property_key == "subclass_of":
            relation_type_id = _one_id(
                connection,
                "SELECT id FROM relation_types WHERE relation_key = 'genre_subgenre_of'",
                (),
            )
            connection.execute(
                """INSERT OR IGNORE INTO entity_relations
                   (relation_type_id, subject_entity_id, object_entity_id,
                    relation_instance_key, properties_json, provenance_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    relation_type_id,
                    entity_id,
                    genre_id,
                    claim.statement_id.value if claim.statement_id is not None else "",
                    claim.model_dump_json(),
                    provenance_id,
                ),
            )
        if claim.property_key == "genre":
            _persist_genre_evidence(
                connection,
                _GenreEvidenceContext(
                    projection=projection,
                    entity_id=entity_id,
                    genre_id=genre_id,
                    claim=claim,
                    provenance_id=provenance_id,
                    policy_id=policy_id,
                ),
            )


@dataclass(frozen=True, slots=True)
class _GenreEvidenceContext:
    projection: EntityProjection
    entity_id: int
    genre_id: int
    claim: RelationClaim
    provenance_id: int
    policy_id: int


def _persist_genre_evidence(
    connection: sqlite3.Connection,
    context: _GenreEvidenceContext,
) -> None:
    projection = context.projection
    claim = context.claim
    source_record_id = (
        claim.statement_id.value
        if claim.statement_id is not None
        else _hash_parts(projection.external_id, claim.model_dump_json())
    )
    fingerprint = _hash_parts(
        projection.external_id,
        str(context.entity_id),
        str(context.genre_id),
        claim.model_dump_json(),
    )
    if projection.entity_kind == "artist":
        source_key_row = connection.execute(
            """SELECT source.source_key
               FROM provenance_records AS provenance
               JOIN data_sources AS source ON source.id = provenance.source_id
               WHERE provenance.id = ?""",
            (context.provenance_id,),
        ).fetchone()
        if source_key_row is None:
            raise RuntimeError("Wikidata provenance source could not be read back")
        connection.execute(
            """INSERT OR IGNORE INTO artist_genre_evidence
               (artist_id, genre_id, evidence_kind, evidence_value, source_key,
                source_record_id, method_key, method_version, parameter_manifest_json,
                observed_at, provenance_id, policy_id, record_fingerprint)
               VALUES (?, ?, 'direct_source_claim', 1.0, ?, ?,
                       'wikidata_p136', '1', '{}', ?, ?, ?, ?)""",
            (
                context.entity_id,
                context.genre_id,
                str(source_key_row[0]),
                source_record_id,
                _now(),
                context.provenance_id,
                context.policy_id,
                fingerprint,
            ),
        )
    elif projection.entity_kind == "release_group":
        connection.execute(
            """INSERT OR IGNORE INTO album_genre_membership_observations
               (release_group_id, genre_id, evidence_kind, evidence_level, source_family,
                source_record_id, source_genre_name, method_key, method_version,
                observed_at, provenance_id, policy_id, record_fingerprint)
               VALUES (?, ?, 'wikidata_p136', 'release_group', 'wikidata', ?, ?,
                       'direct_wikidata_p136', '1', ?, ?, ?, ?)""",
            (
                context.entity_id,
                context.genre_id,
                source_record_id,
                claim.target.value,
                _now(),
                context.provenance_id,
                context.policy_id,
                fingerprint,
            ),
        )


class EntityProjector:
    """Persist evidence-rich entities and direct genre claims idempotently."""

    @property
    def key(self) -> str:
        """Return the accepted projection discriminant."""
        return "entity"

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Persist one generic projection without owning lifecycle state."""
        if not isinstance(projection, EntityProjection):
            raise TypeError("entity projector requires EntityProjection")
        qid = projection.source_identity.value
        entity_id, duplicate = _ensure_entity(
            connection,
            qid=qid,
            entity_kind=projection.entity_kind,
            name=_preferred_name(projection),
            provenance_id=provenance_id,
        )
        connection.execute(
            """INSERT OR IGNORE INTO entity_provenance
               (entity_id, provenance_id, field_set_json, is_primary)
               VALUES (?, ?, '["names","identifiers","claims"]', 0)""",
            (entity_id, provenance_id),
        )
        _persist_identifiers(connection, projection, entity_id, provenance_id)
        _persist_names(connection, projection, entity_id, provenance_id)
        _persist_claims(connection, projection, entity_id, provenance_id, policy_id)
        _persist_relations(connection, projection, entity_id, provenance_id, policy_id)
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
