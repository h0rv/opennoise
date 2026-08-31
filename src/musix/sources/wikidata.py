"""Stream a bounded Wikidata SPARQL snapshot into common catalog claims."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import ijson
from pydantic import AliasChoices, ConfigDict, Field

from musix.models import FrozenModel
from musix.models.catalog import (
    EntityProjection,
    ExternalIdentity,
    IdentifierClaim,
    NameClaim,
    RelationClaim,
    StatementReference,
    ValueClaim,
)
from musix.models.pipeline import (
    ParsedSourceRecord,
    RejectedSourceRecord,
    SourceLimits,
    SourceRecord,
)
from musix.models.sources import DownloadSource
from musix.policy import require_metadata_file
from musix.types import EntityKind, StatementRank

WIKIDATA_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
WIKIDATA_STATEMENT_PREFIX = "http://www.wikidata.org/entity/statement/"
WIKIDATA_REFERENCE_PREFIX = "http://www.wikidata.org/reference/"
WIKIBASE_PREFERRED_RANK = "http://wikiba.se/ontology#PreferredRank"
QID_PATTERN = r"^Q[1-9][0-9]*$"
SCRIPT_RANGES = (
    (0x3040, 0x30FF, "Jpan"),
    (0x4E00, 0x9FFF, "Hani"),
    (0xAC00, 0xD7AF, "Hang"),
    (0x0600, 0x06FF, "Arab"),
    (0x0900, 0x097F, "Deva"),
)


class WikidataSliceError(ValueError):
    """Report an invalid or unsafe Wikidata slice artifact."""


class WikidataCapabilities(FrozenModel):
    """Declare exactly what the bounded adapter emits."""

    entity_kinds: tuple[EntityKind, ...] = (
        "genre",
        "artist",
        "release_group",
        "recording",
        "work",
    )
    identifiers: bool = True
    multilingual_names: bool = True
    ranked_statements: bool = True
    statement_references: bool = True
    checkpoint_key: Literal["wikidata_qid"] = "wikidata_qid"


class WikidataSliceLimits(FrozenModel):
    """Bound artifact and parser resource consumption."""

    max_artifact_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    max_rows: int = Field(default=20_000, gt=0)
    max_entities: int = Field(default=256, gt=0)
    max_names_per_entity: int = Field(default=256, gt=0)
    max_claims_per_entity: int = Field(default=2048, gt=0)


class SparqlBinding(FrozenModel):
    """Parse one SPARQL JSON binding at the source boundary."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore", populate_by_name=True)

    binding_type: Literal["uri", "literal", "typed-literal", "bnode"] = Field(
        validation_alias=AliasChoices("type", "binding_type")
    )
    value: str = Field(min_length=1)
    language: str | None = Field(default=None, alias="xml:lang")
    datatype: str | None = None


class WikidataSliceRow(FrozenModel):
    """Parse one row from the checked-in bounded query."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore", populate_by_name=True)

    entity: SparqlBinding
    entity_kind: SparqlBinding = Field(alias="entityKind")
    label: SparqlBinding | None = None
    alias: SparqlBinding | None = None
    musicbrainz_id: SparqlBinding | None = Field(default=None, alias="musicbrainzId")
    genre: SparqlBinding | None = None
    statement: SparqlBinding | None = None
    rank: SparqlBinding | None = None
    reference: SparqlBinding | None = None
    reference_url: SparqlBinding | None = Field(default=None, alias="referenceUrl")
    parent: SparqlBinding | None = None
    inception: SparqlBinding | None = None
    publication_date: SparqlBinding | None = Field(default=None, alias="publicationDate")


def _parse_row(raw_row: object) -> WikidataSliceRow:
    try:
        return WikidataSliceRow.model_validate(raw_row)
    except ValueError as error:
        raise WikidataSliceError("invalid SPARQL result row") from error


def _qid(binding: SparqlBinding) -> str:
    value = binding.value.removeprefix(WIKIDATA_ENTITY_PREFIX)
    if binding.binding_type != "uri" or not value.startswith("Q") or not value[1:].isdigit():
        raise WikidataSliceError("expected a Wikidata item URI")
    return value


def _source_identity(binding: SparqlBinding, prefix: str, namespace: str) -> ExternalIdentity:
    if binding.binding_type != "uri" or not binding.value.startswith(prefix):
        raise WikidataSliceError(f"expected a {namespace} URI")
    value = binding.value.removeprefix(prefix)
    if not value:
        raise WikidataSliceError(f"empty {namespace} identity")
    return ExternalIdentity(namespace=namespace, value=value)


def _script_code(value: str, language_tag: str) -> str:
    if language_tag == "ja":
        return "Jpan"
    if language_tag.startswith("zh"):
        return "Hani"
    if language_tag == "ko":
        return "Kore"
    for character in value:
        codepoint = ord(character)
        for lower, upper, script in SCRIPT_RANGES:
            if lower <= codepoint <= upper:
                return script
    return "Latn"


def _entity_kind(binding: SparqlBinding) -> EntityKind:
    value = binding.value
    if value not in {"genre", "artist", "release_group", "recording", "work"}:
        raise WikidataSliceError(f"unsupported entity kind: {value}")
    return value


def _rank(binding: SparqlBinding | None) -> StatementRank:
    return (
        "preferred"
        if binding is not None and binding.value == WIKIBASE_PREFERRED_RANK
        else "normal"
    )


def _statement_reference(row: WikidataSliceRow) -> tuple[StatementReference, ...]:
    if row.reference is None:
        return ()
    identity = _source_identity(
        row.reference,
        WIKIDATA_REFERENCE_PREFIX,
        "wikidata_reference",
    )
    url = row.reference_url.value if row.reference_url is not None else None
    if url is not None and urlparse(url).scheme not in {"http", "https"}:
        raise WikidataSliceError("reference URL must use HTTP or HTTPS")
    return (StatementReference(identity=identity, url=url),)


def _unique[T](items: list[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def _names(rows: list[WikidataSliceRow], qid: str) -> tuple[NameClaim, ...]:
    names = [
        NameClaim(
            value=binding.value,
            language_tag=binding.language or "und",
            script_code=_script_code(binding.value, binding.language or "und"),
            kind=name_kind,
        )
        for row in rows
        for name_kind, binding in (("primary", row.label), ("alias", row.alias))
        if binding is not None
    ]
    return _unique(names) or (
        NameClaim(value=qid, language_tag="und", script_code="Latn", kind="primary"),
    )


def _identifiers(
    rows: list[WikidataSliceRow], qid: str, kind: EntityKind
) -> tuple[IdentifierClaim, ...]:
    identifiers = [IdentifierClaim(type_key="wikidata_qid", namespace="wikidata", value=qid)]
    identifiers.extend(
        IdentifierClaim(
            type_key=f"musicbrainz_{kind}_id",
            namespace="musicbrainz",
            value=row.musicbrainz_id.value,
        )
        for row in rows
        if row.musicbrainz_id is not None
    )
    return _unique(identifiers)


def _value_claims(rows: list[WikidataSliceRow]) -> tuple[ValueClaim, ...]:
    return _unique(
        [
            ValueClaim(property_key=property_key, value_kind="time", value=binding.value)
            for row in rows
            for property_key, binding in (
                ("inception", row.inception),
                ("publication_date", row.publication_date),
            )
            if binding is not None
        ]
    )


def _relation_claims(rows: list[WikidataSliceRow]) -> tuple[RelationClaim, ...]:
    claims: list[RelationClaim] = []
    for row in rows:
        statement_id = (
            _source_identity(row.statement, WIKIDATA_STATEMENT_PREFIX, "wikidata_statement")
            if row.statement is not None
            else None
        )
        references = _statement_reference(row)
        for property_key, binding in (("subclass_of", row.parent), ("genre", row.genre)):
            if binding is not None:
                claims.append(
                    RelationClaim(
                        property_key=property_key,
                        target=ExternalIdentity(namespace="wikidata", value=_qid(binding)),
                        target_kind="genre",
                        statement_id=statement_id if property_key == "genre" else None,
                        rank=_rank(row.rank) if property_key == "genre" else "normal",
                        references=references if property_key == "genre" else (),
                    )
                )
    return _unique(claims)


def _project_rows(rows: list[WikidataSliceRow], limits: WikidataSliceLimits) -> EntityProjection:
    first = rows[0]
    qid = _qid(first.entity)
    kind = _entity_kind(first.entity_kind)
    for row in rows:
        if _qid(row.entity) != qid or _entity_kind(row.entity_kind) != kind:
            raise WikidataSliceError("SPARQL entity group changed identity or kind")
    names = _names(rows, qid)
    claims = (*_value_claims(rows), *_relation_claims(rows))
    if len(names) > limits.max_names_per_entity:
        raise WikidataSliceError("entity exceeds max_names_per_entity")
    if len(claims) > limits.max_claims_per_entity:
        raise WikidataSliceError("entity exceeds max_claims_per_entity")
    return EntityProjection(
        entity_kind=kind,
        source_identity=ExternalIdentity(namespace="wikidata", value=qid),
        names=names,
        identifiers=_identifiers(rows, qid, kind),
        claims=claims,
    )


class WikidataSourceAdapter:
    """Parse one verified SPARQL JSON artifact without lifecycle side effects."""

    key = "wikidata_music_sparql_slice_v1"
    version = "1"
    capabilities = WikidataCapabilities()

    def supports(self, source: DownloadSource) -> bool:
        """Accept only uncompressed SPARQL JSON declared for this adapter."""
        return (
            source.adapter == self.key
            and source.compression == "none"
            and "json" in source.expected_content_type.casefold()
        )

    @staticmethod
    def _record(projection: EntityProjection, ordinal: int, limits: SourceLimits) -> SourceRecord:
        canonical = projection.model_dump_json().encode()
        digest = hashlib.sha256(canonical).hexdigest()
        if len(canonical) > limits.max_record_bytes:
            return RejectedSourceRecord(
                ordinal=ordinal,
                exact_sha256=digest,
                byte_length=len(canonical),
                reason="projected entity exceeds max_record_bytes",
            )
        return ParsedSourceRecord(
            ordinal=ordinal,
            exact_sha256=digest,
            byte_length=len(canonical),
            projection=projection,
        )

    def _group_record(
        self,
        rows: list[WikidataSliceRow],
        ordinal: int,
        limits: SourceLimits,
        adapter_limits: WikidataSliceLimits,
    ) -> SourceRecord:
        try:
            projection = _project_rows(rows, adapter_limits)
        except WikidataSliceError as error:
            canonical = json.dumps(
                [item.model_dump(mode="json") for item in rows],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            return RejectedSourceRecord(
                ordinal=ordinal,
                exact_sha256=hashlib.sha256(canonical).hexdigest(),
                byte_length=len(canonical),
                reason=str(error),
            )
        return self._record(projection, ordinal, limits)

    def iter_records(
        self,
        path: Path,
        limits: SourceLimits,
        *,
        start_after: int,
    ) -> Iterator[SourceRecord]:
        """Yield bounded projections after a committed ordinal checkpoint."""
        require_metadata_file(path)
        if path.stat().st_size > limits.max_archive_bytes:
            raise WikidataSliceError("artifact exceeds max_artifact_bytes")
        adapter_limits = WikidataSliceLimits(
            max_artifact_bytes=limits.max_archive_bytes,
            max_rows=limits.max_records,
            max_entities=limits.max_records,
        )
        current_identity: tuple[str, EntityKind] | None = None
        current_rows: list[WikidataSliceRow] = []
        row_count = 0
        ordinal = -1
        with path.open("rb") as stream:
            for raw_row in ijson.items(stream, "results.bindings.item", use_float=True):
                row_count += 1
                if row_count > adapter_limits.max_rows:
                    raise WikidataSliceError("artifact exceeds max_rows")
                row = _parse_row(raw_row)
                identity = (_qid(row.entity), _entity_kind(row.entity_kind))
                if current_identity is not None and identity != current_identity:
                    ordinal += 1
                    if ordinal + 1 > adapter_limits.max_entities:
                        raise WikidataSliceError("artifact exceeds max_entities")
                    if ordinal > start_after:
                        yield self._group_record(
                            current_rows,
                            ordinal,
                            limits,
                            adapter_limits,
                        )
                    current_rows = []
                current_identity = identity
                current_rows.append(row)
        if current_identity is not None:
            ordinal += 1
            if ordinal + 1 > adapter_limits.max_entities:
                raise WikidataSliceError("artifact exceeds max_entities")
            if ordinal > start_after:
                yield self._group_record(current_rows, ordinal, limits, adapter_limits)
