"""Stream Wikidata genre JSON, SPARQL JSON, and truthy RDF into typed claims."""

import bz2
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

import httpx
import ijson
from pydantic import BaseModel, ConfigDict, Field

WIKIDATA_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
WIKIDATA_DIRECT_PREFIX = "http://www.wikidata.org/prop/direct/"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
SKOS_ALT_LABEL = "http://www.w3.org/2004/02/skos/core#altLabel"
MUSIC_GENRE_QID = "Q188451"
QID_PATTERN = re.compile(r"Q[1-9][0-9]*\Z")

type RdfPredicate = Literal[
    "instance_of",
    "subgenre_of",
    "origin",
    "label",
    "alias",
    "musicbrainz_genre_id",
    "every_noise_id",
]


class WikidataAdapterError(ValueError):
    """Report an invalid Wikidata record or bounded input."""


class BinaryReader(Protocol):
    """Describe the binary operation needed by the streaming parser."""

    def read(self, size: int = -1) -> bytes:
        """Read binary data from the source."""
        ...


class AdapterLimits(BaseModel):
    """Bound compressed bytes, expanded bytes, records, and response bytes."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    max_archive_bytes: int = Field(default=128 * 1024 * 1024 * 1024, gt=0)
    max_decompressed_bytes: int = Field(default=2 * 1024 * 1024 * 1024 * 1024, gt=0)
    max_records: int = Field(default=200_000_000, gt=0)
    max_response_bytes: int = Field(default=64 * 1024 * 1024, gt=0)


class WikidataTerm(BaseModel):
    """Parse one Wikidata label or alias."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    language: str = Field(min_length=1)
    value: str = Field(min_length=1)


class WikibaseEntityId(BaseModel):
    """Parse an entity ID value from a claim data value."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    entity_type: str = Field(alias="entity-type", min_length=1)
    id: str = Field(pattern=r"^Q[1-9][0-9]*$")


class WikidataTime(BaseModel):
    """Parse the supported part of a Wikidata time value."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    time: str = Field(min_length=1)
    precision: int


type DataValueContent = str | int | float | WikibaseEntityId | WikidataTime
type ActiveClaimRank = Literal["preferred", "normal"]


class WikidataDataValue(BaseModel):
    """Parse a supported Wikidata claim data value."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    value: DataValueContent
    type: str = Field(min_length=1)


class WikidataSnak(BaseModel):
    """Parse the main snak of a Wikidata statement."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    property: str = Field(min_length=2)
    snaktype: str = Field(min_length=1)
    datavalue: WikidataDataValue | None = None


class WikidataReference(BaseModel):
    """Parse the source snaks attached to one Wikidata statement."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    hash: str | None = None
    snaks: dict[str, tuple[WikidataSnak, ...]] = Field(default_factory=dict)


class WikidataClaim(BaseModel):
    """Parse one ranked Wikidata statement."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    id: str | None = None
    mainsnak: WikidataSnak
    rank: Literal["preferred", "normal", "deprecated"]
    qualifiers: dict[str, tuple[WikidataSnak, ...]] = Field(default_factory=dict)
    references: tuple[WikidataReference, ...] = ()


class WikidataEntity(BaseModel):
    """Parse the genre fields from one Wikidata entity dump object."""

    model_config = ConfigDict(frozen=True, strict=False, extra="ignore")

    id: str = Field(pattern=r"^Q[1-9][0-9]*$")
    type: Literal["item"]
    labels: dict[str, WikidataTerm] = Field(default_factory=dict)
    aliases: dict[str, tuple[WikidataTerm, ...]] = Field(default_factory=dict)
    claims: dict[str, tuple[WikidataClaim, ...]] = Field(default_factory=dict)


class Identifier(BaseModel):
    """Represent one typed Wikidata crosswalk identifier."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["source_id", "musicbrainz_genre_id", "every_noise_id"]
    namespace: Literal["wikidata", "musicbrainz", "every_noise"]
    value: str = Field(min_length=1)


class GenreRecord(BaseModel):
    """Represent one normalized genre for the catalog importer."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["genre"] = "genre"
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    identifiers: tuple[Identifier, ...] = ()


class GenreRelationship(BaseModel):
    """Represent one direct Wikidata subgenre statement."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["genre_subgenre_of"] = "genre_subgenre_of"
    subject_external_id: str = Field(min_length=1)
    object_external_id: str = Field(min_length=1)


class AdaptedGenre(BaseModel):
    """Keep one genre and its bounded hierarchy claims together while streaming."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    genre: GenreRecord
    relationships: tuple[GenreRelationship, ...]
    origins: tuple[str, ...] = ()
    inception: tuple[str, ...] = ()


class AlbumGenreEvidenceRecord(BaseModel):
    """Represent one direct Wikidata P136 claim on an album or edition."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["album_genre_evidence"] = "album_genre_evidence"
    source_family: Literal["wikidata"] = "wikidata"
    wikidata_item_id: str = Field(pattern=r"^Q[1-9][0-9]*$")
    evidence_level: Literal["release_group", "release"]
    musicbrainz_target_id: UUID
    genre_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    claim_id: str | None = None
    claim_rank: Literal["preferred", "normal"]
    qualifier_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    publication_dates: tuple[str, ...] = ()
    source_record_id: str = Field(min_length=1)


class SparqlBinding(BaseModel):
    """Parse one variable binding from a SPARQL JSON response."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    type: Literal["uri", "literal", "typed-literal", "bnode"]
    value: str
    language: str | None = Field(default=None, alias="xml:lang")
    datatype: str | None = None


class GenreSparqlRow(BaseModel):
    """Parse one row emitted by the genre bootstrap SPARQL query."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    genre: SparqlBinding
    genre_label: SparqlBinding | None = Field(default=None, alias="genreLabel")
    genre_alt_label: SparqlBinding | None = Field(default=None, alias="genreAltLabel")
    parent: SparqlBinding | None = None
    origin: SparqlBinding | None = None
    inception: SparqlBinding | None = None
    musicbrainz_genre_id: SparqlBinding | None = Field(
        default=None,
        alias="musicbrainzGenreId",
    )
    every_noise_id: SparqlBinding | None = Field(default=None, alias="everyNoiseId")


class WikidataRdfStatement(BaseModel):
    """Represent one relevant statement from the truthy N-Triples dump."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    subject_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    predicate: RdfPredicate
    object_qid: str | None = Field(default=None, pattern=r"^Q[1-9][0-9]*$")
    literal: str | None = None
    language: str | None = None


class _BoundedReader:
    def __init__(self, stream: BinaryReader, maximum: int) -> None:
        self._stream = stream
        self._maximum = maximum
        self._consumed = 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self._consumed += len(data)
        if self._consumed > self._maximum:
            raise WikidataAdapterError("Wikidata input exceeds max_decompressed_bytes")
        return data


def _qid_from_uri(uri: str) -> str | None:
    if not uri.startswith(WIKIDATA_ENTITY_PREFIX):
        return None
    qid = uri.removeprefix(WIKIDATA_ENTITY_PREFIX)
    return qid if QID_PATTERN.fullmatch(qid) else None


def _entity_claim_values(entity: WikidataEntity, property_id: str) -> Iterator[DataValueContent]:
    for claim in entity.claims.get(property_id, ()):
        if claim.rank == "deprecated" or claim.mainsnak.snaktype != "value":
            continue
        if claim.mainsnak.datavalue is not None:
            yield claim.mainsnak.datavalue.value


def _entity_ids(entity: WikidataEntity, property_id: str) -> tuple[str, ...]:
    values: list[str] = []
    for value in _entity_claim_values(entity, property_id):
        if isinstance(value, WikibaseEntityId) and value.id not in values:
            values.append(value.id)
    return tuple(values)


def _string_values(entity: WikidataEntity, property_id: str) -> tuple[str, ...]:
    values: list[str] = []
    for value in _entity_claim_values(entity, property_id):
        if isinstance(value, str) and value not in values:
            values.append(value)
    return tuple(values)


def _time_values(entity: WikidataEntity, property_id: str) -> tuple[str, ...]:
    values: list[str] = []
    for value in _entity_claim_values(entity, property_id):
        if isinstance(value, WikidataTime) and value.time not in values:
            values.append(value.time)
    return tuple(values)


def _choose_name(entity: WikidataEntity) -> str | None:
    if english := entity.labels.get("en"):
        return english.value
    if not entity.labels:
        return None
    return entity.labels[min(entity.labels)].value


def _deduplicated_aliases(entity: WikidataEntity, name: str) -> tuple[str, ...]:
    seen = {name.casefold()}
    aliases: list[str] = []
    terms = [*entity.labels.values()]
    for language in sorted(entity.aliases):
        terms.extend(entity.aliases[language])
    for term in terms:
        value = term.value.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            aliases.append(value)
    return tuple(aliases)


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-")
    return slug or fallback.casefold()


def adapt_entity(entity: WikidataEntity) -> AdaptedGenre | None:
    """Convert one genre candidate into local genre and hierarchy records."""
    instance_ids = _entity_ids(entity, "P31")
    musicbrainz_ids = _string_values(entity, "P8052")
    every_noise_ids = _string_values(entity, "P9881")
    if MUSIC_GENRE_QID not in instance_ids and not musicbrainz_ids and not every_noise_ids:
        return None
    name = _choose_name(entity)
    if name is None:
        return None

    external_id = f"wikidata:genre:{entity.id}"
    identifiers = [Identifier(type="source_id", namespace="wikidata", value=entity.id)]
    identifiers.extend(
        Identifier(type="musicbrainz_genre_id", namespace="musicbrainz", value=value)
        for value in musicbrainz_ids
    )
    identifiers.extend(
        Identifier(type="every_noise_id", namespace="every_noise", value=value)
        for value in every_noise_ids
    )
    relationships = tuple(
        GenreRelationship(
            subject_external_id=external_id,
            object_external_id=f"wikidata:genre:{parent_id}",
        )
        for parent_id in _entity_ids(entity, "P279")
    )
    return AdaptedGenre(
        genre=GenreRecord(
            external_id=external_id,
            name=name,
            slug=_slug(name, entity.id),
            aliases=_deduplicated_aliases(entity, name),
            identifiers=tuple(identifiers),
        ),
        relationships=relationships,
        origins=_entity_ids(entity, "P495"),
        inception=_time_values(entity, "P571"),
    )


def _valid_string_claims(
    entity: WikidataEntity,
    property_id: str,
) -> Iterator[tuple[str, WikidataClaim, ActiveClaimRank]]:
    for claim in entity.claims.get(property_id, ()):
        if claim.rank == "deprecated" or claim.mainsnak.snaktype != "value":
            continue
        data_value = claim.mainsnak.datavalue
        if data_value is not None and isinstance(data_value.value, str):
            yield data_value.value, claim, claim.rank


def _valid_entity_claims(
    entity: WikidataEntity,
    property_id: str,
) -> Iterator[tuple[str, WikidataClaim, ActiveClaimRank]]:
    for claim in entity.claims.get(property_id, ()):
        if claim.rank == "deprecated" or claim.mainsnak.snaktype != "value":
            continue
        data_value = claim.mainsnak.datavalue
        if data_value is not None and isinstance(data_value.value, WikibaseEntityId):
            yield data_value.value.id, claim, claim.rank


def adapt_album_genre_evidence(entity: WikidataEntity) -> tuple[AlbumGenreEvidenceRecord, ...]:
    """Join direct album P136 claims to typed MusicBrainz target IDs."""
    genres = tuple(_valid_entity_claims(entity, "P136"))
    if not genres:
        return ()
    publication_dates = _time_values(entity, "P577")
    targets: list[tuple[Literal["release_group", "release"], UUID]] = []
    for evidence_level, property_id in (("release_group", "P436"), ("release", "P5813")):
        for raw_target_id, _claim, _rank in _valid_string_claims(entity, property_id):
            try:
                target_id = UUID(raw_target_id)
            except ValueError:
                continue
            targets.append((evidence_level, target_id))
    evidence: list[AlbumGenreEvidenceRecord] = []
    for evidence_level, target_id in targets:
        for position, (genre_qid, claim, claim_rank) in enumerate(genres):
            claim_ref = claim.id or f"{entity.id}:P136:{position}:{genre_qid}"
            evidence.append(
                AlbumGenreEvidenceRecord(
                    wikidata_item_id=entity.id,
                    evidence_level=evidence_level,
                    musicbrainz_target_id=target_id,
                    genre_qid=genre_qid,
                    claim_id=claim.id,
                    claim_rank=claim_rank,
                    qualifier_count=sum(len(values) for values in claim.qualifiers.values()),
                    reference_count=len(claim.references),
                    publication_dates=publication_dates,
                    source_record_id=f"wikidata:{claim_ref}:{evidence_level}:{target_id}",
                )
            )
    return tuple(evidence)


def _check_archive_size(path: Path, limits: AdapterLimits) -> None:
    if path.stat().st_size > limits.max_archive_bytes:
        raise WikidataAdapterError("Wikidata archive exceeds max_archive_bytes")


def _iter_wikidata_entities(path: Path, limits: AdapterLimits) -> Iterator[WikidataEntity]:
    _check_archive_size(path, limits)
    count = 0
    with bz2.open(path, "rb") as compressed:
        stream = _BoundedReader(compressed, limits.max_decompressed_bytes)
        for raw_entity in ijson.items(stream, "item", use_float=True):
            count += 1
            if count > limits.max_records:
                raise WikidataAdapterError("Wikidata dump exceeds max_records")
            try:
                entity = WikidataEntity.model_validate(raw_entity)
            except ValueError as error:
                raise WikidataAdapterError("invalid Wikidata entity record") from error
            yield entity


def iter_entity_dump(path: Path, limits: AdapterLimits) -> Iterator[AdaptedGenre]:
    """Stream relevant genre entities from an official `all.json.bz2` dump."""
    for entity in _iter_wikidata_entities(path, limits):
        if adapted := adapt_entity(entity):
            yield adapted


def iter_album_genre_evidence_dump(
    path: Path,
    limits: AdapterLimits,
) -> Iterator[AlbumGenreEvidenceRecord]:
    """Stream direct album P136 claims from an official entity dump."""
    for entity in _iter_wikidata_entities(path, limits):
        yield from adapt_album_genre_evidence(entity)


def _binding_qid(binding: SparqlBinding) -> str | None:
    return _qid_from_uri(binding.value) if binding.type == "uri" else None


def _row_value(binding: SparqlBinding | None) -> str | None:
    if binding is None or not binding.value.strip():
        return None
    return binding.value.strip()


def _adapt_sparql_group(qid: str, rows: list[GenreSparqlRow]) -> AdaptedGenre:
    name = next(
        (value for row in rows if (value := _row_value(row.genre_label)) is not None),
        qid,
    )
    alias_values: list[str] = []
    parent_ids: list[str] = []
    origin_ids: list[str] = []
    inception: list[str] = []
    musicbrainz_ids: list[str] = []
    every_noise_ids: list[str] = []
    for row in rows:
        if raw_aliases := _row_value(row.genre_alt_label):
            alias_values.extend(part.strip() for part in raw_aliases.split(",") if part.strip())
        if row.parent is not None and (parent_id := _binding_qid(row.parent)) is not None:
            parent_ids.append(parent_id)
        if row.origin is not None and (origin_id := _binding_qid(row.origin)) is not None:
            origin_ids.append(origin_id)
        if value := _row_value(row.inception):
            inception.append(value)
        if value := _row_value(row.musicbrainz_genre_id):
            musicbrainz_ids.append(value)
        if value := _row_value(row.every_noise_id):
            every_noise_ids.append(value)

    identifiers = [Identifier(type="source_id", namespace="wikidata", value=qid)]
    identifiers.extend(
        Identifier(type="musicbrainz_genre_id", namespace="musicbrainz", value=value)
        for value in dict.fromkeys(musicbrainz_ids)
    )
    identifiers.extend(
        Identifier(type="every_noise_id", namespace="every_noise", value=value)
        for value in dict.fromkeys(every_noise_ids)
    )
    external_id = f"wikidata:genre:{qid}"
    relationships = tuple(
        GenreRelationship(
            subject_external_id=external_id,
            object_external_id=f"wikidata:genre:{parent_id}",
        )
        for parent_id in dict.fromkeys(parent_ids)
    )
    aliases = tuple(
        value for value in dict.fromkeys(alias_values) if value.casefold() != name.casefold()
    )
    return AdaptedGenre(
        genre=GenreRecord(
            external_id=external_id,
            name=name,
            slug=_slug(name, qid),
            aliases=aliases,
            identifiers=tuple(identifiers),
        ),
        relationships=relationships,
        origins=tuple(dict.fromkeys(origin_ids)),
        inception=tuple(dict.fromkeys(inception)),
    )


def iter_sparql_response(path: Path, limits: AdapterLimits) -> Iterator[AdaptedGenre]:
    """Stream ordered genre groups from a saved SPARQL JSON response."""
    if path.stat().st_size > limits.max_response_bytes:
        raise WikidataAdapterError("Wikidata SPARQL response exceeds max_response_bytes")
    current_qid: str | None = None
    current_rows: list[GenreSparqlRow] = []
    count = 0
    with path.open("rb") as stream:
        for raw_row in ijson.items(stream, "results.bindings.item", use_float=True):
            count += 1
            if count > limits.max_records:
                raise WikidataAdapterError("Wikidata SPARQL response exceeds max_records")
            try:
                row = GenreSparqlRow.model_validate(raw_row)
            except ValueError as error:
                raise WikidataAdapterError("invalid Wikidata SPARQL row") from error
            qid = _binding_qid(row.genre)
            if qid is None:
                raise WikidataAdapterError("SPARQL genre binding is not a Wikidata item URI")
            if current_qid is not None and qid != current_qid:
                yield _adapt_sparql_group(current_qid, current_rows)
                current_rows = []
            current_qid = qid
            current_rows.append(row)
    if current_qid is not None:
        yield _adapt_sparql_group(current_qid, current_rows)


_URI_TRIPLE = re.compile(r"^<([^>]+)> <([^>]+)> <([^>]+)> \.\s*$")
_LITERAL_TRIPLE = re.compile(
    r'^<([^>]+)> <([^>]+)> "((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+)|\^\^<[^>]+>)? \.\s*$'
)


def _predicate(uri: str) -> RdfPredicate | None:
    mapping: dict[str, RdfPredicate] = {
        f"{WIKIDATA_DIRECT_PREFIX}P31": "instance_of",
        f"{WIKIDATA_DIRECT_PREFIX}P279": "subgenre_of",
        f"{WIKIDATA_DIRECT_PREFIX}P495": "origin",
        f"{WIKIDATA_DIRECT_PREFIX}P8052": "musicbrainz_genre_id",
        f"{WIKIDATA_DIRECT_PREFIX}P9881": "every_noise_id",
        RDFS_LABEL: "label",
        SKOS_ALT_LABEL: "alias",
    }
    return mapping.get(uri)


def parse_truthy_line(line: str) -> WikidataRdfStatement | None:
    """Parse one relevant N-Triples line without accepting a partial match."""
    if uri_match := _URI_TRIPLE.fullmatch(line):
        subject_uri, predicate_uri, object_uri = uri_match.groups()
        subject_qid = _qid_from_uri(subject_uri)
        object_qid = _qid_from_uri(object_uri)
        predicate = _predicate(predicate_uri)
        if (
            subject_qid is None
            or object_qid is None
            or predicate
            not in {
                "instance_of",
                "subgenre_of",
                "origin",
            }
        ):
            return None
        return WikidataRdfStatement(
            subject_qid=subject_qid,
            predicate=predicate,
            object_qid=object_qid,
        )
    if literal_match := _LITERAL_TRIPLE.fullmatch(line):
        subject_uri, predicate_uri, escaped_literal, language = literal_match.groups()
        subject_qid = _qid_from_uri(subject_uri)
        predicate = _predicate(predicate_uri)
        if subject_qid is None or predicate not in {
            "label",
            "alias",
            "musicbrainz_genre_id",
            "every_noise_id",
        }:
            return None
        literal_value = json.loads(f'"{escaped_literal}"')
        if not isinstance(literal_value, str):
            raise WikidataAdapterError("N-Triples literal did not decode to text")
        return WikidataRdfStatement(
            subject_qid=subject_qid,
            predicate=predicate,
            literal=literal_value,
            language=language,
        )
    return None


def iter_truthy_dump(path: Path, limits: AdapterLimits) -> Iterator[WikidataRdfStatement]:
    """Stream relevant claims from an official truthy N-Triples BZ2 dump."""
    _check_archive_size(path, limits)
    consumed = 0
    count = 0
    with bz2.open(path, "rt", encoding="utf-8", newline="") as stream:
        for line in stream:
            consumed += len(line.encode("utf-8"))
            if consumed > limits.max_decompressed_bytes:
                raise WikidataAdapterError("Wikidata input exceeds max_decompressed_bytes")
            count += 1
            if count > limits.max_records:
                raise WikidataAdapterError("Wikidata dump exceeds max_records")
            if statement := parse_truthy_line(line):
                yield statement


def _write_line(stream: BinaryIO, model: BaseModel) -> None:
    stream.write(model.model_dump_json().encode("utf-8"))
    stream.write(b"\n")


def write_genre_outputs(
    records: Iterator[AdaptedGenre],
    entities_destination: Path,
    relationships_destination: Path,
) -> tuple[int, int]:
    """Atomically write importer genre JSONL and relationship JSONL."""
    entities_destination.parent.mkdir(parents=True, exist_ok=True)
    relationships_destination.parent.mkdir(parents=True, exist_ok=True)
    entities_temporary = entities_destination.with_name(f".{entities_destination.name}.tmp")
    relationships_temporary = relationships_destination.with_name(
        f".{relationships_destination.name}.tmp"
    )
    entity_count = 0
    relationship_count = 0
    try:
        with (
            entities_temporary.open("xb") as entities_stream,
            relationships_temporary.open("xb") as relationships_stream,
        ):
            for adapted in records:
                _write_line(entities_stream, adapted.genre)
                entity_count += 1
                for relationship in adapted.relationships:
                    _write_line(relationships_stream, relationship)
                    relationship_count += 1
        entities_temporary.replace(entities_destination)
        relationships_temporary.replace(relationships_destination)
    finally:
        entities_temporary.unlink(missing_ok=True)
        relationships_temporary.unlink(missing_ok=True)
    return entity_count, relationship_count


async def fetch_sparql_snapshot(
    client: httpx.AsyncClient,
    *,
    query: str,
    destination: Path,
    user_agent: str,
    max_response_bytes: int,
) -> int:
    """Fetch one bounded SPARQL JSON snapshot and replace its destination atomically."""
    if not query.strip():
        raise ValueError("Wikidata query must not be empty")
    if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
        raise ValueError("Wikidata user_agent must include an app version and contact")
    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    total = 0
    try:
        async with client.stream(
            "POST",
            "https://query.wikidata.org/sparql",
            data={"query": query},
            headers={
                "User-Agent": user_agent,
                "Accept": "application/sparql-results+json",
            },
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                raise WikidataAdapterError(
                    f"Wikidata SPARQL returned unexpected content type: {content_type!r}"
                )
            with temporary.open("xb") as stream:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_response_bytes:
                        raise WikidataAdapterError(
                            "Wikidata SPARQL response exceeds max_response_bytes"
                        )
                    stream.write(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return total
