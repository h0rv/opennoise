"""Resolve typed exact artist identifiers without choosing among ambiguous entities.

This resolver is read-only. New source-qualified identifiers and provenance remain
owned by the calling projector; existing split entities are never merged here.
"""

import re
import sqlite3
from uuid import UUID

from opennoise.models.catalog import IdentifierClaim

_MBID_TYPE = "musicbrainz_artist_id"
_QID_TYPES = ("wikidata_qid", "wikidata_artist_qid")


class ArtistIdentityError(ValueError):
    """Reject ambiguous, malformed or contradictory exact artist identities."""


def _mbid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except ValueError as error:
        raise ArtistIdentityError(
            "Artist MusicBrainz identifier is not a canonical UUID"
        ) from error
    if value != canonical:
        raise ArtistIdentityError("Artist MusicBrainz identifier is not a canonical UUID")
    return value


def _qid(value: str) -> str:
    if not re.fullmatch(r"Q[1-9][0-9]*", value):
        raise ArtistIdentityError("Artist Wikidata identifier is not a canonical QID")
    return value


def _matches(connection: sqlite3.Connection, *, namespace: str, value: str, mbid: bool) -> set[int]:
    # A QID is globally source-local, so a genre/recording QID binding also matters:
    # it is a kind conflict, never permission to create another artist for that QID.
    query = """SELECT DISTINCT entity.entity_id
               FROM entity_identifiers AS entity
               JOIN identifier_types AS type ON type.id = entity.identifier_type_id
               WHERE entity.namespace = ? AND entity.normalized_value = ?"""
    if mbid:
        query += " AND type.type_key IN ('musicbrainz_artist_id', 'source_id')"
    else:
        query += " AND (type.type_key = 'wikidata_qid' OR type.type_key GLOB 'wikidata_*_qid')"
    return {int(r[0]) for r in connection.execute(query, (namespace, value))}


def _values(
    identifiers: tuple[IdentifierClaim, ...],
    subject_qid: str | None = None,
) -> tuple[set[str], set[str]]:
    mbids: set[str] = set()
    qids: set[str] = {_qid(subject_qid)} if subject_qid is not None else set()
    for claim in identifiers:
        if claim.type_key == _MBID_TYPE or (
            claim.type_key == "source_id" and claim.namespace == "musicbrainz"
        ):
            if claim.namespace != "musicbrainz":
                raise ArtistIdentityError("Artist MusicBrainz identifier has wrong namespace")
            mbids.add(_mbid(claim.value))
        elif claim.type_key in _QID_TYPES:
            if claim.namespace != "wikidata":
                raise ArtistIdentityError("Artist Wikidata identifier has wrong namespace")
            qids.add(_qid(claim.value))
        elif (claim.type_key.startswith("wikidata_") and claim.type_key.endswith("_qid")) or (
            claim.type_key.startswith("musicbrainz_") and claim.type_key.endswith("_id")
        ):
            raise ArtistIdentityError("Artist projection contains a foreign entity-kind identifier")
    return mbids, qids


def _consistent(mbids: set[str], qids: set[str]) -> None:
    if len(mbids) > 1 or len(qids) > 1:
        raise ArtistIdentityError("Artist identity has conflicting exact identifiers")


def _existing(connection: sqlite3.Connection, entity_id: int) -> tuple[set[str], set[str]]:
    kind = connection.execute(
        """SELECT e.entity_kind, a.id FROM catalog_entities e
           LEFT JOIN artists a ON a.id=e.id WHERE e.id=?""",
        (entity_id,),
    ).fetchone()
    if kind is None or kind[0] != "artist" or kind[1] is None:
        raise ArtistIdentityError("Exact artist identifier resolves to wrong entity kind")
    rows = connection.execute(
        """SELECT type.type_key, identifier.namespace, identifier.normalized_value
           FROM entity_identifiers identifier
           JOIN identifier_types type ON type.id=identifier.identifier_type_id
           WHERE identifier.entity_id=? AND
             (type.type_key GLOB 'musicbrainz_*_id' OR type.type_key='wikidata_qid'
              OR type.type_key GLOB 'wikidata_*_qid'
              OR (type.type_key='source_id' AND identifier.namespace='musicbrainz'))""",
        (entity_id,),
    )
    claims = []
    for type_key, namespace, value in rows:
        if type_key not in (_MBID_TYPE, "source_id", *_QID_TYPES):
            raise ArtistIdentityError("Existing artist has conflicting typed Wikidata identity")
        claims.append(IdentifierClaim(type_key=type_key, namespace=namespace, value=value))
    return _values(tuple(claims))


def resolve_artist(
    connection: sqlite3.Connection,
    identifiers: tuple[IdentifierClaim, ...],
    *,
    subject_qid: str | None = None,
) -> int | None:
    """Return one consistent artist or absence; fail before any projector mutation.

    Repeated observations on the same entity are permitted. Two entities for one
    identifier or contradictory source identities require external reconciliation.
    """
    mbids, qids = _values(identifiers, subject_qid)
    _consistent(mbids, qids)
    if not mbids and not qids:
        raise ArtistIdentityError("Artist projection has no supported typed exact identifier")
    candidates: set[int] = set()
    for value in mbids:
        candidates |= _matches(connection, namespace="musicbrainz", value=value, mbid=True)
    for value in qids:
        candidates |= _matches(connection, namespace="wikidata", value=value, mbid=False)
    if len(candidates) > 1:
        raise ArtistIdentityError(
            "Exact artist identifiers resolve ambiguously; reconciliation required"
        )
    if not candidates:
        return None
    entity_id = next(iter(candidates))
    existing_mbids, existing_qids = _existing(connection, entity_id)
    _consistent(mbids | existing_mbids, qids | existing_qids)
    return entity_id
