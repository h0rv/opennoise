"""Persist MusicBrainz release-group and recording metadata with exact identities."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime

from opennoise.models.catalog import (
    ArtistCreditMemberClaim,
    CatalogProjection,
    GenreMembershipClaim,
    IdentifierClaim,
    NameClaim,
    ProjectionResult,
    RecordingProjection,
    ReleaseGroupProjection,
)


def _hash_parts(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _last_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return cursor.lastrowid


def _identifier_type(connection: sqlite3.Connection, type_key: str) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES (?, ?)",
        (type_key, type_key.replace("_", " ").title()),
    )
    row = connection.execute(
        "SELECT id FROM identifier_types WHERE type_key = ?", (type_key,)
    ).fetchone()
    if row is None:
        raise RuntimeError("identifier type could not be read back")
    return int(row[0])


def _entity_by_identifier(
    connection: sqlite3.Connection, identifier: IdentifierClaim
) -> int | None:
    type_id = _identifier_type(connection, identifier.type_key)
    row = connection.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type_id = ? AND namespace = ? AND normalized_value = ?
           ORDER BY id LIMIT 1""",
        (type_id, identifier.namespace, identifier.value.strip()),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _persist_identifiers(
    connection: sqlite3.Connection,
    entity_id: int,
    identifiers: tuple[IdentifierClaim, ...],
    provenance_id: int,
) -> None:
    for identifier in identifiers:
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


def _persist_names(
    connection: sqlite3.Connection,
    entity_id: int,
    names: tuple[NameClaim, ...],
    provenance_id: int,
    policy_id: int,
) -> None:
    for claim in names:
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
    search_text = " ".join(claim.value for claim in names)
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


def _ensure_artist(
    connection: sqlite3.Connection,
    member: ArtistCreditMemberClaim,
    provenance_id: int,
    policy_id: int,
) -> int:
    identifier = IdentifierClaim(
        type_key="musicbrainz_artist_id",
        namespace=member.artist_identity.namespace,
        value=member.artist_identity.value,
    )
    entity_id = _entity_by_identifier(connection, identifier)
    if entity_id is None:
        entity_id = _last_id(
            connection.execute("INSERT INTO catalog_entities (entity_kind) VALUES ('artist')")
        )
        connection.execute("INSERT INTO artists (id) VALUES (?)", (entity_id,))
    _persist_identifiers(connection, entity_id, (identifier,), provenance_id)
    _persist_names(
        connection,
        entity_id,
        (NameClaim(kind="primary", value=member.artist_name),),
        provenance_id,
        policy_id,
    )
    return entity_id


def _persist_credit(
    connection: sqlite3.Connection,
    entity_id: int,
    members: tuple[ArtistCreditMemberClaim, ...],
    provenance_id: int,
    policy_id: int,
) -> None:
    canonical = json.dumps(
        [member.model_dump(mode="json") for member in members],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    credit_key = _hash_parts("musicbrainz", canonical)
    connection.execute(
        "INSERT OR IGNORE INTO artist_credits (credit_key, provenance_id) VALUES (?, ?)",
        (credit_key, provenance_id),
    )
    row = connection.execute(
        "SELECT id FROM artist_credits WHERE credit_key = ?", (credit_key,)
    ).fetchone()
    if row is None:
        raise RuntimeError("artist credit could not be read back")
    credit_id = int(row[0])
    for position, member in enumerate(members):
        artist_id = _ensure_artist(connection, member, provenance_id, policy_id)
        connection.execute(
            """INSERT OR IGNORE INTO artist_credit_members
               (artist_credit_id, position, artist_id, credited_name, join_phrase)
               VALUES (?, ?, ?, ?, ?)""",
            (credit_id, position, artist_id, member.credited_name, member.join_phrase),
        )
    connection.execute(
        """INSERT OR IGNORE INTO entity_artist_credits
           (entity_id, credit_kind, artist_credit_id, provenance_id)
           VALUES (?, 'primary', ?, ?)""",
        (entity_id, credit_id, provenance_id),
    )


def _genre_slug(source_id: str) -> str:
    return "musicbrainz-" + re.sub(r"[^a-z0-9]+", "-", source_id.casefold()).strip("-")


def _ensure_genre(
    connection: sqlite3.Connection, claim: GenreMembershipClaim, provenance_id: int
) -> int:
    identifier = IdentifierClaim(
        type_key="musicbrainz_genre_id",
        namespace=claim.source_identity.namespace,
        value=claim.source_identity.value,
    )
    genre_id = _entity_by_identifier(connection, identifier)
    if genre_id is None:
        genre_id = _last_id(
            connection.execute("INSERT INTO catalog_entities (entity_kind) VALUES ('genre')")
        )
        connection.execute(
            "INSERT INTO genres (id, slug, name) VALUES (?, ?, ?)",
            (genre_id, _genre_slug(identifier.value), claim.name),
        )
    _persist_identifiers(connection, genre_id, (identifier,), provenance_id)
    return genre_id


def _persist_date_claim(
    connection: sqlite3.Connection,
    entity_id: int,
    value: str | None,
    provenance_id: int,
    policy_id: int,
) -> None:
    if value is None:
        return
    normalized = json.dumps({"value": value}, separators=(",", ":"), sort_keys=True)
    connection.execute(
        """INSERT OR IGNORE INTO entity_claims
           (entity_id, claim_type, claim_key, normalized_value_json, asserted_at,
            provenance_id, policy_id, claim_hash)
           VALUES (?, 'musicbrainz_value', 'first_release_date', ?, ?, ?, ?, ?)""",
        (
            entity_id,
            normalized,
            _now(),
            provenance_id,
            policy_id,
            _hash_parts(str(entity_id), "first_release_date", normalized),
        ),
    )


class ReleaseGroupProjector:
    """Persist album-level identity, direct genres, and ordered credits."""

    @property
    def key(self) -> str:
        """Return the accepted projection discriminant."""
        return "release_group"

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Persist one release group without owning pipeline lifecycle state."""
        if not isinstance(projection, ReleaseGroupProjection):
            raise TypeError("release-group projector received the wrong projection")
        entity_id = _entity_by_identifier(connection, projection.identifiers[0])
        duplicate = entity_id is not None
        if entity_id is None:
            entity_id = _last_id(
                connection.execute(
                    "INSERT INTO catalog_entities (entity_kind) VALUES ('release_group')"
                )
            )
            connection.execute(
                """INSERT INTO release_groups (id, group_kind, secondary_kinds_json)
                   VALUES (?, ?, ?)""",
                (
                    entity_id,
                    projection.primary_type,
                    json.dumps(projection.secondary_types, separators=(",", ":")),
                ),
            )
        connection.execute(
            """INSERT OR IGNORE INTO entity_provenance
               (entity_id, provenance_id, field_set_json, is_primary)
               VALUES (?, ?, '["names","identifiers","artist_credit","release_group_core"]', 0)""",
            (entity_id, provenance_id),
        )
        _persist_identifiers(connection, entity_id, projection.identifiers, provenance_id)
        _persist_names(connection, entity_id, projection.names, provenance_id, policy_id)
        _persist_credit(connection, entity_id, projection.artist_credit, provenance_id, policy_id)
        _persist_date_claim(
            connection, entity_id, projection.first_release_date, provenance_id, policy_id
        )
        for claim in projection.genre_claims:
            genre_id = _ensure_genre(connection, claim, provenance_id)
            source_record_id = (
                f"musicbrainz:release-group:{projection.external_id}:genre:"
                f"{claim.source_identity.value}"
            )
            fingerprint = _hash_parts(
                source_record_id, str(claim.support_count), str(provenance_id)
            )
            connection.execute(
                """INSERT OR IGNORE INTO album_genre_membership_observations
                   (release_group_id, genre_id, evidence_kind, evidence_level, source_family,
                    source_record_id, source_genre_name, source_count, method_key,
                    method_version, observed_at, provenance_id, policy_id, record_fingerprint)
                   VALUES (?, ?, 'musicbrainz_release_group_genre', 'release_group',
                           'musicbrainz', ?, ?, ?, 'direct_musicbrainz_genre', '1',
                           ?, ?, ?, ?)""",
                (
                    entity_id,
                    genre_id,
                    source_record_id,
                    claim.name,
                    claim.support_count,
                    _now(),
                    provenance_id,
                    policy_id,
                    fingerprint,
                ),
            )
        return ProjectionResult(projection_kind=self.key, target_id=entity_id, duplicate=duplicate)


class RecordingProjector:
    """Persist recording identity, direct genres, and ordered credits."""

    @property
    def key(self) -> str:
        """Return the accepted projection discriminant."""
        return "recording"

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Persist one recording without media or acoustic fields."""
        if not isinstance(projection, RecordingProjection):
            raise TypeError("recording projector received the wrong projection")
        entity_id = _entity_by_identifier(connection, projection.identifiers[0])
        duplicate = entity_id is not None
        if entity_id is None:
            entity_id = _last_id(
                connection.execute(
                    "INSERT INTO catalog_entities (entity_kind) VALUES ('recording')"
                )
            )
            connection.execute(
                "INSERT INTO recordings (id, disambiguation) VALUES (?, ?)",
                (entity_id, projection.disambiguation),
            )
        connection.execute(
            """INSERT OR IGNORE INTO entity_provenance
               (entity_id, provenance_id, field_set_json, is_primary)
               VALUES (?, ?, '["names","identifiers","artist_credit","recording_core"]', 0)""",
            (entity_id, provenance_id),
        )
        _persist_identifiers(connection, entity_id, projection.identifiers, provenance_id)
        _persist_names(connection, entity_id, projection.names, provenance_id, policy_id)
        _persist_credit(connection, entity_id, projection.artist_credit, provenance_id, policy_id)
        _persist_date_claim(
            connection, entity_id, projection.first_release_date, provenance_id, policy_id
        )
        for claim in projection.genre_claims:
            genre_id = _ensure_genre(connection, claim, provenance_id)
            source_record_id = (
                f"musicbrainz:recording:{projection.external_id}:genre:"
                f"{claim.source_identity.value}"
            )
            fingerprint = _hash_parts(
                source_record_id, str(claim.support_count), str(provenance_id)
            )
            connection.execute(
                """INSERT OR IGNORE INTO recording_genre_membership_observations
                   (recording_id, genre_id, evidence_kind, source_family, source_record_id,
                    source_genre_name, source_count, method_key, method_version, observed_at,
                    provenance_id, policy_id, record_fingerprint)
                   VALUES (?, ?, 'musicbrainz_recording_genre', 'musicbrainz', ?, ?, ?,
                           'direct_musicbrainz_genre', '1', ?, ?, ?, ?)""",
                (
                    entity_id,
                    genre_id,
                    source_record_id,
                    claim.name,
                    claim.support_count,
                    _now(),
                    provenance_id,
                    policy_id,
                    fingerprint,
                ),
            )
        return ProjectionResult(projection_kind=self.key, target_id=entity_id, duplicate=duplicate)
