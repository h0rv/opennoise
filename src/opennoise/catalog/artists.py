"""Direct-SQL repository for common artist projections."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import NamedTuple

from opennoise.models.catalog import (
    ArtistProjection,
    CatalogProjection,
    GenreMembershipClaim,
    ProjectionResult,
)

GENRE_PARAMETER_MANIFEST = {
    "association": "official_genre",
    "count_semantics": "positive_aggregate",
    "maximum_genres_per_artist": 128,
}
TAG_PARAMETER_MANIFEST = {
    "association": "artist_tag",
    "count_semantics": "positive_aggregate",
    "maximum_tags_per_artist": 512,
}


class _EvidenceFacet(NamedTuple):
    claims: tuple[GenreMembershipClaim, ...]
    method_key: str
    parameter_manifest: str
    source_record_facet: str


class _ClaimPersistence(NamedTuple):
    connection: sqlite3.Connection
    projection: ArtistProjection
    artist_id: int
    provenance_id: int
    policy_id: int


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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _genre_slug(source_id: str, *, namespace: str = "musicbrainz") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", source_id.casefold()).strip("-")
    if namespace == "musicbrainz_tag":
        # Tags can contain scripts that the legacy ASCII slugger erases. Keep
        # a readable prefix, then disambiguate with the complete source key.
        digest = _hash_parts(namespace, source_id)[:12]
        return f"musicbrainz-tag-{normalized or 'tag'}-{digest}"
    return f"musicbrainz-{normalized}"


def _ensure_genre(
    connection: sqlite3.Connection,
    claim: GenreMembershipClaim,
    provenance_id: int,
) -> int:
    identifier_type_key = (
        "musicbrainz_tag_name"
        if claim.source_identity.namespace == "musicbrainz_tag"
        else "musicbrainz_genre_id"
    )
    identifier_type_id = _identifier_type(connection, identifier_type_key)
    row = connection.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type_id = ? AND namespace = ? AND normalized_value = ?
           ORDER BY id LIMIT 1""",
        (identifier_type_id, claim.source_identity.namespace, claim.source_identity.value),
    ).fetchone()
    if row is None:
        cursor = connection.execute("INSERT INTO catalog_entities (entity_kind) VALUES ('genre')")
        genre_id = _lastrowid(cursor)
        connection.execute(
            "INSERT INTO genres (id, slug, name) VALUES (?, ?, ?)",
            (
                genre_id,
                _genre_slug(
                    claim.source_identity.value,
                    namespace=claim.source_identity.namespace,
                ),
                claim.name,
            ),
        )
    else:
        genre_id = int(row[0])
        kind = connection.execute(
            "SELECT entity_kind FROM catalog_entities WHERE id = ?", (genre_id,)
        ).fetchone()
        if kind is None or str(kind[0]) != "genre":
            raise ValueError("MusicBrainz genre identifier resolves to a non-genre entity")
    connection.execute(
        """INSERT OR IGNORE INTO entity_identifiers
           (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            genre_id,
            identifier_type_id,
            claim.source_identity.namespace,
            claim.source_identity.value,
            claim.source_identity.value,
            provenance_id,
        ),
    )
    connection.execute(
        """INSERT OR IGNORE INTO entity_provenance
           (entity_id, provenance_id, field_set_json, is_primary)
           VALUES (?, ?, ?, 0)""",
        (
            genre_id,
            provenance_id,
            json.dumps(["name", identifier_type_key], separators=(",", ":")),
        ),
    )
    fingerprint = _hash_parts(str(genre_id), "primary", "und", claim.name)
    connection.execute(
        """INSERT OR IGNORE INTO entity_names
           (entity_id, name_kind, name, language_tag, is_preferred, provenance_id, fingerprint)
           VALUES (?, 'primary', ?, 'und', 1, ?, ?)""",
        (genre_id, claim.name, provenance_id, fingerprint),
    )
    return genre_id


def _source_key(connection: sqlite3.Connection, provenance_id: int) -> str:
    row = connection.execute(
        """SELECT source.source_key
           FROM provenance_records AS provenance
           JOIN data_sources AS source ON source.id = provenance.source_id
           WHERE provenance.id = ?""",
        (provenance_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("artist provenance source could not be read back")
    return str(row[0])


def _persist_genre_claims(
    connection: sqlite3.Connection,
    projection: ArtistProjection,
    artist_id: int,
    provenance_id: int,
    policy_id: int,
) -> None:
    _persist_claims(
        _ClaimPersistence(connection, projection, artist_id, provenance_id, policy_id),
        _EvidenceFacet(
            claims=projection.genre_claims,
            method_key="musicbrainz_artist_genre",
            parameter_manifest=json.dumps(
                GENRE_PARAMETER_MANIFEST, sort_keys=True, separators=(",", ":")
            ),
            source_record_facet="genre",
        ),
    )


def _persist_claims(
    context: _ClaimPersistence,
    facet: _EvidenceFacet,
) -> None:
    """Persist one immutable direct evidence facet in the shared evidence table."""
    connection = context.connection
    projection = context.projection
    artist_id = context.artist_id
    provenance_id = context.provenance_id
    policy_id = context.policy_id
    source_key = _source_key(connection, provenance_id)
    observed_at = _now()
    for claim in facet.claims:
        genre_id = _ensure_genre(connection, claim, provenance_id)
        source_record_id = (
            f"musicbrainz:artist:{projection.external_id}:{facet.source_record_facet}:"
            f"{claim.source_identity.value}"
        )
        fingerprint = _hash_parts(
            source_key,
            source_record_id,
            str(claim.support_count),
            str(provenance_id),
        )
        connection.execute(
            """INSERT OR IGNORE INTO artist_genre_evidence
               (artist_id, genre_id, evidence_kind, evidence_value, source_key,
                source_record_id, method_key, method_version, parameter_manifest_json,
                observed_at, provenance_id, policy_id, record_fingerprint)
               VALUES (?, ?, 'direct_source_claim', ?, ?, ?,
                       ?, '1', ?, ?, ?, ?, ?)""",
            (
                artist_id,
                genre_id,
                float(claim.support_count),
                source_key,
                source_record_id,
                facet.method_key,
                facet.parameter_manifest,
                observed_at,
                provenance_id,
                policy_id,
                fingerprint,
            ),
        )


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
            raise TypeError("artist projector received the wrong projection")
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
        _persist_genre_claims(
            connection,
            projection,
            entity_id,
            provenance_id,
            policy_id,
        )
        _persist_claims(
            _ClaimPersistence(connection, projection, entity_id, provenance_id, policy_id),
            _EvidenceFacet(
                claims=projection.tag_claims,
                method_key="musicbrainz_artist_tag",
                parameter_manifest=json.dumps(
                    TAG_PARAMETER_MANIFEST, sort_keys=True, separators=(",", ":")
                ),
                source_record_facet="tag",
            ),
        )
        return ProjectionResult(
            projection_kind=self.key,
            target_id=entity_id,
            duplicate=duplicate,
        )
