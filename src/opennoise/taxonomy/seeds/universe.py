"""Build a deterministic, name-only bridge from Every Noise H2 to catalogs.

The bridge intentionally treats H2 as a vocabulary.  Coordinates, colours,
representative tracks, H3 memberships, and historical neighbours are not read
as inputs to resolution.  Catalog evidence is direct positive artist/genre
evidence only; no artist edges are inferred from names or compositional
candidates.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from opennoise.common import sha256_file, sha256_hex, sha256_json

if TYPE_CHECKING:
    from collections.abc import Iterable

WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
NON_ALNUM: Final[re.Pattern[str]] = re.compile(r"[^\w]+", re.UNICODE)
SeedClassification = Literal[
    "direct_exact", "alias_exact", "compositional_candidate", "ambiguous", "unresolved"
]


class SeedName(BaseModel):
    """The only H2 fields allowed into the bridge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class SeedInput(BaseModel):
    """A name-only projection of a retained H2 artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    names: tuple[SeedName, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_names_and_ids(self) -> SeedInput:
        """Reject duplicate source identities at the H2 boundary."""
        if len({item.source_item_id for item in self.names}) != len(self.names):
            raise ValueError("H2 source item IDs must be unique")
        if len({item.name for item in self.names}) != len(self.names):
            raise ValueError("H2 seed names must be unique")
        return self


class CatalogInput(BaseModel):
    """Fingerprint and source scope for one approved catalog database."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_keys: tuple[str, ...] = ()


class CatalogCandidate(BaseModel):
    """One exact identity candidate, retained when a name is ambiguous."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    matched_names: tuple[str, ...] = ()
    source_keys: tuple[str, ...] = ()


class CompositionalCandidate(BaseModel):
    """A review-only token-head candidate; never a canonical membership."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_id: str = Field(min_length=1)
    head_name: str = Field(min_length=1)
    components: tuple[str, ...] = Field(min_length=2)
    reason: Literal["exact_token_head"] = "exact_token_head"


class EvidenceRef(BaseModel):
    """A direct catalog evidence row, with stable source references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1)
    artist_id: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    evidence_value: float = Field(ge=0)


class SeedResolution(BaseModel):
    """Resolution for every H2 seed, including unresolved and review states."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    classification: SeedClassification
    candidates: tuple[CatalogCandidate, ...] = ()
    compositional_candidates: tuple[CompositionalCandidate, ...] = ()
    direct_evidence_count: int = Field(default=0, ge=0)
    distinct_artist_count: int = Field(default=0, ge=0)
    evidence_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def enforce_canonical_membership_boundary(self) -> SeedResolution:
        """Keep review candidates and unresolved states evidence-free."""
        if self.classification == "compositional_candidate" and (
            self.direct_evidence_count or self.evidence_refs
        ):
            raise ValueError("compositional candidates cannot carry direct membership evidence")
        if self.classification in {"unresolved", "ambiguous"} and self.direct_evidence_count:
            raise ValueError("unresolved or ambiguous seeds cannot carry canonical evidence")
        return self


class GenreSeedUniverseArtifact(BaseModel):
    """Complete reproducible bridge artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_revision: Literal["genre-seed-universe-v1"] = "genre-seed-universe-v1"
    seed_input: SeedInput
    catalog_inputs: tuple[CatalogInput, ...] = Field(min_length=1)
    resolutions: tuple[SeedResolution, ...] = Field(min_length=1)
    seed_count: int = Field(ge=1)
    direct_exact_count: int = Field(ge=0)
    alias_exact_count: int = Field(ge=0)
    compositional_candidate_count: int = Field(ge=0)
    ambiguous_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    canonical_membership_count: int = Field(ge=0)
    direct_evidence_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def normalize_label(value: str) -> str:
    """Normalize only spelling presentation, not semantic tokens or fuzzy similarity."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    words = NON_ALNUM.sub(" ", unicodedata.normalize("NFKC", without_marks))
    return WHITESPACE.sub(" ", words).strip()


def _json_object(path: Path) -> dict[str, object]:
    return TypeAdapter(dict[str, object]).validate_json(path.read_bytes())


def load_seed_input(path: Path) -> SeedInput:
    """Read H2 names and provenance while deliberately dropping every other field.

    The parser reads only ``artifact.source_id``, ``artifact.content_sha256``
    and each genre's IDs and name.  Extra historical fields are ignored by
    design, so changing them cannot affect this bridge.
    """
    document = _json_object(path)
    artifact_value = document.get("artifact")
    artifact = artifact_value if isinstance(artifact_value, dict) else document
    source_id = artifact.get("source_id")
    source_hash = artifact.get("content_sha256")
    genres_value = document.get("genres")
    if not isinstance(source_id, str) or not isinstance(source_hash, str):
        raise TypeError("H2 artifact must declare artifact.source_id and artifact.content_sha256")
    if not isinstance(genres_value, list):
        raise TypeError("H2 artifact must declare a genres list")
    names: list[SeedName] = []
    for ordinal, value in enumerate(genres_value, 1):
        if not isinstance(value, dict):
            raise TypeError(f"H2 genre {ordinal} must be an object")
        source_item_id = value.get("source_item_id")
        source_external_id = value.get("external_id")
        name = value.get("name")
        if not all(
            isinstance(item, str) and item for item in (source_item_id, source_external_id, name)
        ):
            raise TypeError(f"H2 genre {ordinal} lacks name-only identity fields")
        names.append(
            SeedName(
                source_item_id=source_item_id,
                source_external_id=source_external_id,
                name=name,
            )
        )
    name_projection = {
        "source_id": source_id,
        "source_content_sha256": source_hash,
        "names": [item.model_dump(mode="json") for item in names],
    }
    return SeedInput(
        source_id=source_id,
        source_content_sha256=source_hash,
        artifact_sha256=sha256_json(name_projection),
        names=tuple(names),
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _identity_value(connection: sqlite3.Connection, row_id: int, kind: str) -> str:
    tables = _tables(connection)
    if {"entity_identifiers", "identifier_types"} <= tables:
        row = connection.execute(
            """SELECT identifier.normalized_value FROM entity_identifiers AS identifier
               JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
               WHERE identifier.entity_id = ? AND type.type_key = ?
               ORDER BY identifier.normalized_value LIMIT 1""",
            (row_id, kind),
        ).fetchone()
        if row is not None and row[0]:
            return str(row[0])
    return str(row_id)


def _catalog_rows(connection: sqlite3.Connection) -> list[tuple[str, str, str, bool, str]]:
    """Return identity, display name, matched label, alias flag, source key."""
    tables = _tables(connection)
    if "genres" not in tables:
        raise ValueError("catalog database must contain a genres table")
    rows: list[tuple[str, str, str, bool, str]] = []
    genre_columns = _table_columns(connection, "genres")
    if "entity_kind" in genre_columns:
        genres = connection.execute(
            "SELECT id, name FROM genres WHERE entity_kind = 'genre' ORDER BY id"
        ).fetchall()
    else:
        genres = connection.execute("SELECT id, name FROM genres ORDER BY id").fetchall()
    for row_id, canonical in genres:
        identity = _identity_value(connection, int(row_id), "musicbrainz_genre_id")
        source_keys: set[str] = set()
        rows.append((identity, str(canonical), str(canonical), False, ""))
        if "entity_names" in tables:
            labels = connection.execute(
                """SELECT name, name_kind FROM entity_names
                   WHERE entity_id = ? ORDER BY name, name_kind""",
                (row_id,),
            ).fetchall()
            for label, name_kind in labels:
                rows.append((identity, str(canonical), str(label), str(name_kind) == "alias", ""))
        if (
            "entity_provenance" in tables
            and "provenance_records" in tables
            and "data_sources" in tables
        ):
            source_rows = connection.execute(
                """SELECT DISTINCT source.source_key FROM entity_provenance AS link
                   JOIN provenance_records AS provenance ON provenance.id = link.provenance_id
                   JOIN data_sources AS source ON source.id = provenance.source_id
                   WHERE link.entity_id = ? ORDER BY source.source_key""",
                (row_id,),
            ).fetchall()
            source_keys.update(str(item[0]) for item in source_rows)
        # Attach provenance scope to canonical and aliases in a second pass below.
        if source_keys:
            rows[-1] = (*rows[-1][:-1], ",".join(sorted(source_keys)))
    return rows


def _evidence_rows(connection: sqlite3.Connection) -> dict[str, tuple[EvidenceRef, ...]]:
    """Read only direct positive evidence and index it by catalog identity."""
    tables = _tables(connection)
    if "artist_genre_evidence" not in tables:
        return {}
    columns = _table_columns(connection, "artist_genre_evidence")
    required = {"id", "genre_id", "artist_id", "evidence_value", "source_key"}
    if not required <= columns:
        return {}
    if "source_record_id" in columns and "evidence_kind" in columns:
        rows = connection.execute(
            """SELECT id, genre_id, artist_id, source_record_id, source_key, evidence_value
                FROM artist_genre_evidence
                WHERE evidence_value > 0 AND evidence_kind = 'direct_source_claim'
                ORDER BY genre_id, artist_id, id"""
        ).fetchall()
    elif "source_record_id" in columns:
        rows = connection.execute(
            """SELECT id, genre_id, artist_id, source_record_id, source_key, evidence_value
                FROM artist_genre_evidence
                WHERE evidence_value > 0 ORDER BY genre_id, artist_id, id"""
        ).fetchall()
    elif "evidence_kind" in columns:
        rows = connection.execute(
            """SELECT id, genre_id, artist_id, CAST(id AS TEXT), source_key, evidence_value
                FROM artist_genre_evidence
                WHERE evidence_value > 0 AND evidence_kind = 'direct_source_claim'
                ORDER BY genre_id, artist_id, id"""
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT id, genre_id, artist_id, CAST(id AS TEXT), source_key, evidence_value
                FROM artist_genre_evidence
                WHERE evidence_value > 0 ORDER BY genre_id, artist_id, id"""
        ).fetchall()
    values: dict[str, list[EvidenceRef]] = defaultdict(list)
    for evidence_id, genre_id, artist_id, source_record_id, source_key, weight in rows:
        identity = _identity_value(connection, int(genre_id), "musicbrainz_genre_id")
        artist_identity = _identity_value(connection, int(artist_id), "source_id")
        values[identity].append(
            EvidenceRef(
                evidence_id=str(evidence_id),
                artist_id=artist_identity,
                source_key=str(source_key),
                source_record_id=str(source_record_id),
                evidence_value=float(weight),
            )
        )
    return {key: tuple(value) for key, value in values.items()}


def _source_keys(connection: sqlite3.Connection) -> tuple[str, ...]:
    tables = _tables(connection)
    if "data_sources" in tables:
        columns = _table_columns(connection, "data_sources")
        if "source_key" in columns:
            rows = connection.execute(
                "SELECT source_key FROM data_sources ORDER BY source_key"
            ).fetchall()
            return tuple(str(row[0]) for row in rows)
    return ()


def build_genre_seed_universe(  # noqa: C901
    seed_artifact: Path, catalog_databases: Iterable[Path]
) -> GenreSeedUniverseArtifact:
    """Build the name bridge from one H2 artifact and one or more catalog DBs."""
    seed = load_seed_input(seed_artifact)
    databases = tuple(sorted({Path(path) for path in catalog_databases}, key=str))
    if not databases:
        raise ValueError("at least one catalog database is required")
    labels: dict[str, dict[str, CatalogCandidate]] = defaultdict(dict)
    evidence: dict[str, list[EvidenceRef]] = defaultdict(list)
    catalog_inputs: list[CatalogInput] = []
    for database_path in databases:
        if not database_path.is_file():
            raise FileNotFoundError(database_path)
        with sqlite3.connect(database_path) as connection:
            rows = _catalog_rows(connection)
            evidence_rows = _evidence_rows(connection)
            for identity, canonical, label, _is_alias, source_scope in rows:
                keys = tuple(item for item in source_scope.split(",") if item)
                candidate = CatalogCandidate(
                    catalog_id=identity,
                    canonical_name=canonical,
                    matched_names=(label,),
                    source_keys=keys,
                )
                labels[normalize_label(label)][identity] = candidate
            for identity, refs in evidence_rows.items():
                evidence[identity].extend(refs)
            catalog_inputs.append(
                CatalogInput(
                    path=str(database_path),
                    database_sha256=sha256_file(database_path)[0],
                    source_keys=_source_keys(connection),
                )
            )
    resolutions: list[SeedResolution] = []
    for item in seed.names:
        normalized = normalize_label(item.name)
        matches = tuple(
            sorted(labels.get(normalized, {}).values(), key=lambda candidate: candidate.catalog_id)
        )
        if len(matches) == 1:
            candidate = matches[0]
            refs = tuple(
                sorted(
                    evidence.get(candidate.catalog_id, ()),
                    key=lambda ref: (ref.source_key, ref.artist_id, ref.evidence_id),
                )
            )
            is_alias = normalized != normalize_label(candidate.canonical_name)
            classification: SeedClassification = "alias_exact" if is_alias else "direct_exact"
            resolutions.append(
                SeedResolution(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalized,
                    classification=classification,
                    candidates=(candidate,),
                    direct_evidence_count=len(refs),
                    distinct_artist_count=len({ref.artist_id for ref in refs}),
                    evidence_refs=refs,
                )
            )
            continue
        if len(matches) > 1:
            resolutions.append(
                SeedResolution(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalized,
                    classification="ambiguous",
                    candidates=matches,
                )
            )
            continue
        tokens = tuple(normalized.split())
        compositional: list[CompositionalCandidate] = []
        for offset in range(1, len(tokens)):
            head = " ".join(tokens[offset:])
            head_matches = tuple(
                sorted(labels.get(head, {}).values(), key=lambda candidate: candidate.catalog_id)
            )
            if len(head_matches) == 1:
                compositional.append(
                    CompositionalCandidate(
                        catalog_id=head_matches[0].catalog_id,
                        head_name=head_matches[0].canonical_name,
                        components=(" ".join(tokens[:offset]), head_matches[0].canonical_name),
                    )
                )
        classification = "compositional_candidate" if compositional else "unresolved"
        resolutions.append(
            SeedResolution(
                source_item_id=item.source_item_id,
                source_external_id=item.source_external_id,
                seed_name=item.name,
                normalized_name=normalized,
                classification=classification,
                compositional_candidates=tuple(compositional),
            )
        )
    counts = {
        name: sum(item.classification == name for item in resolutions)
        for name in (
            "direct_exact",
            "alias_exact",
            "compositional_candidate",
            "ambiguous",
            "unresolved",
        )
    }
    preliminary = GenreSeedUniverseArtifact(
        seed_input=seed,
        catalog_inputs=tuple(catalog_inputs),
        resolutions=tuple(resolutions),
        seed_count=len(resolutions),
        direct_exact_count=counts["direct_exact"],
        alias_exact_count=counts["alias_exact"],
        compositional_candidate_count=counts["compositional_candidate"],
        ambiguous_count=counts["ambiguous"],
        unresolved_count=counts["unresolved"],
        canonical_membership_count=counts["direct_exact"] + counts["alias_exact"],
        direct_evidence_count=sum(item.direct_evidence_count for item in resolutions),
        output_sha256="0" * 64,
    )
    output_hash = sha256_json(preliminary.model_dump(mode="json", exclude={"output_sha256"}))
    return preliminary.model_copy(update={"output_sha256": output_hash})


def write_genre_seed_universe(artifact: GenreSeedUniverseArtifact, path: Path) -> str:
    """Write deterministic JSON and return the bytes hash."""
    payload = artifact.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return sha256_hex(payload.encode())
