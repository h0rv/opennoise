"""Defensive local-only adapters for pinned Every Noise snapshots."""

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unicodedata
import urllib.request
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Literal, override

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator

ITEM_ID_PATTERN = re.compile(r"^item[1-9][0-9]*$")
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
StyleName = Literal["x", "y", "color", "font_size"]
STYLE_PATTERNS: dict[StyleName, re.Pattern[str]] = {
    "x": re.compile(r"(?:^|;)\s*left\s*:\s*([0-9]+)px\s*(?:;|$)", re.IGNORECASE),
    "y": re.compile(r"(?:^|;)\s*top\s*:\s*([0-9]+)px\s*(?:;|$)", re.IGNORECASE),
    "color": re.compile(r"(?:^|;)\s*color\s*:\s*(#[0-9a-fA-F]{6})\s*(?:;|$)", re.IGNORECASE),
    "font_size": re.compile(r"(?:^|;)\s*font-size\s*:\s*([0-9]+)%\s*(?:;|$)", re.IGNORECASE),
}

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ColorHex = Annotated[str, StringConstraints(pattern=r"^#[0-9a-f]{6}$")]


class SourceVerificationError(ValueError):
    """Report bytes that do not match their immutable source specification."""


class SourceSpec(BaseModel):
    """Immutable retrieval and parsing contract for one pinned source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: NonEmptyText
    namespace: NonEmptyText
    snapshot: NonEmptyText
    url: AnyHttpUrl
    expected_bytes: Annotated[int, Field(gt=0)]
    sha256: Sha256
    expected_records: Annotated[int, Field(gt=0)]
    adapter: Literal["enao_html_map_v1", "enao_watch_csv_v1"]
    local_only: Literal[True] = True
    rights_classification: Literal["user_authorized_local"] = "user_authorized_local"


QUINT_SOURCE = SourceSpec(
    source_id="enao_quint_legacy_map_2025",
    namespace="enao-legacy",
    snapshot="git:e80265defc743b307586ac0a7a5c72d2dacdf409",
    url=(
        "https://raw.githubusercontent.com/quint-t/Every-Noise-at-Once/"
        "e80265defc743b307586ac0a7a5c72d2dacdf409/index.html"
    ),
    expected_bytes=3_789_046,
    sha256="1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180",
    expected_records=6_291,
    adapter="enao_html_map_v1",
)

WATCH_SOURCE = SourceSpec(
    source_id="enao_watch_coordinates_2021",
    namespace="enao-watch",
    snapshot="git:4d3febe3762a555ac197524eea97a0f2825652de",
    url=(
        "https://raw.githubusercontent.com/AyrtonB/EveryNoise-Watch/"
        "4d3febe3762a555ac197524eea97a0f2825652de/data/genre_attrs.csv"
    ),
    expected_bytes=178_804,
    sha256="21d9e576fd3f0ae0ec2db46f72d20043f3aafd1ec84d8c14da35e58ecc5ca367",
    expected_records=5_453,
    adapter="enao_watch_csv_v1",
)


class IdentifierRecord(BaseModel):
    """One identifier accepted by the catalog JSONL boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["source_id"] = "source_id"
    namespace: NonEmptyText
    value: NonEmptyText


class GenreRecord(BaseModel):
    """Policy-safe genre fields projected to the catalog importer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["genre"] = "genre"
    external_id: NonEmptyText
    name: NonEmptyText
    slug: NonEmptyText
    aliases: tuple[str, ...] = ()
    identifiers: tuple[IdentifierRecord, ...]

    @field_validator("name")
    @classmethod
    def name_is_single_line(cls, value: str) -> str:
        """Keep source markup and control characters out of catalog names."""
        if any(character in value for character in "\r\n\x00"):
            raise ValueError("genre name must be a single non-null line")
        return value


class LayoutPointRecord(BaseModel):
    """A source observation in the historical display coordinate system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: NonEmptyText
    x_px: Annotated[int, Field(ge=0, le=1_500)]
    y_px: Annotated[int, Field(ge=0, le=22_648)]
    color_hex: ColorHex
    font_size_percent: Annotated[int, Field(ge=100, le=200)] | None
    coordinate_kind: Literal["legacy_display_coordinate"] = "legacy_display_coordinate"
    source_id: NonEmptyText
    source_sha256: Sha256


class AdaptedGenre(BaseModel):
    """One catalog record paired with its separate layout observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog: GenreRecord
    layout: LayoutPointRecord


class QuarantineRecord(BaseModel):
    """Safe diagnostics for a source row that was not accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: NonEmptyText
    record_number: Annotated[int, Field(gt=0)]
    source_record_id: str | None = None
    reason: NonEmptyText


class AdaptationResult(BaseModel):
    """Deterministic accepted and quarantined outputs from one adapter run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: SourceSpec
    records: tuple[AdaptedGenre, ...]
    quarantine: tuple[QuarantineRecord, ...]

    @property
    def accepted_count(self) -> int:
        """Return the number of accepted unique records."""
        return len(self.records)

    @property
    def quarantined_count(self) -> int:
        """Return the number of rejected records."""
        return len(self.quarantine)

    def catalog_jsonl(self) -> bytes:
        """Serialize catalog records deterministically for the unified importer."""
        return _jsonl(record.catalog for record in self.records)

    def layout_jsonl(self) -> bytes:
        """Serialize layout observations separately from catalog facts."""
        return _jsonl(record.layout for record in self.records)

    def quarantine_jsonl(self) -> bytes:
        """Serialize diagnostics without retaining rejected source payloads."""
        return _jsonl(self.quarantine)


class _HtmlCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_number: int
    attributes: dict[str, str]
    direct_text: str


class _GenreMapParser(HTMLParser):
    """Capture only the direct safe fields from genre div elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[_HtmlCandidate] = []
        self._attributes: dict[str, str] | None = None
        self._text_parts: list[str] = []
        self._nested_depth = 0
        self._record_number = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Begin a genre candidate or track nesting within one."""
        if self._attributes is not None:
            self._nested_depth += 1
            return
        attributes = {name: value for name, value in attrs if value is not None}
        classes = frozenset(attributes.get("class", "").split())
        if tag == "div" and {"genre", "scanme"}.issubset(classes):
            self._record_number += 1
            self._attributes = attributes
            self._text_parts = []
            self._nested_depth = 0

    @override
    def handle_data(self, data: str) -> None:
        """Keep direct genre-name text while excluding nested navigation content."""
        if self._attributes is not None and self._nested_depth == 0:
            self._text_parts.append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        """Finish a genre div once its root closing tag is reached."""
        if self._attributes is None:
            return
        if self._nested_depth > 0:
            self._nested_depth -= 1
            return
        if tag == "div":
            self.candidates.append(
                _HtmlCandidate(
                    record_number=self._record_number,
                    attributes=self._attributes,
                    direct_text="".join(self._text_parts).strip(),
                )
            )
            self._attributes = None
            self._text_parts = []


def _slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold()
    pieces: list[str] = []
    separating = False
    for character in normalized:
        if character.isalnum():
            pieces.append(character)
            separating = False
        elif pieces and not separating:
            pieces.append("-")
            separating = True
    return "".join(pieces).strip("-")


def _verify_bytes(raw: bytes, source: SourceSpec) -> None:
    if len(raw) != source.expected_bytes:
        raise SourceVerificationError(
            f"{source.source_id} has {len(raw)} bytes; expected {source.expected_bytes}"
        )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source.sha256:
        raise SourceVerificationError(
            f"{source.source_id} has SHA256 {digest}; expected {source.sha256}"
        )


def _style_value(style: str, name: StyleName) -> str:
    match = STYLE_PATTERNS[name].search(style)
    if match is None:
        raise ValueError(f"style is missing required field: {name}")
    return match.expand(r"\1")


def _parse_style(style: str) -> tuple[int, int, str, int]:
    return (
        int(_style_value(style, "x")),
        int(_style_value(style, "y")),
        _style_value(style, "color").lower(),
        int(_style_value(style, "font_size")),
    )


def _adapt_html_candidate(candidate: _HtmlCandidate, source: SourceSpec) -> AdaptedGenre:
    item_id = candidate.attributes.get("id", "")
    if ITEM_ID_PATTERN.fullmatch(item_id) is None:
        raise ValueError("id must match item followed by a positive integer")
    name = candidate.direct_text.strip()
    slug = _slug(name)
    x_px, y_px, color_hex, font_size_percent = _parse_style(candidate.attributes.get("style", ""))
    external_id = f"{source.namespace}:{item_id}"
    return AdaptedGenre(
        catalog=GenreRecord(
            external_id=external_id,
            name=name,
            slug=slug,
            identifiers=(IdentifierRecord(namespace=source.namespace, value=item_id),),
        ),
        layout=LayoutPointRecord(
            external_id=external_id,
            x_px=x_px,
            y_px=y_px,
            color_hex=color_hex,
            font_size_percent=font_size_percent,
            source_id=source.source_id,
            source_sha256=source.sha256,
        ),
    )


def _append_unique(
    record: AdaptedGenre,
    *,
    accepted: list[AdaptedGenre],
    fingerprints: dict[str, str],
) -> None:
    fingerprint = hashlib.sha256(
        record.model_dump_json(exclude_none=False).encode("utf-8")
    ).hexdigest()
    prior = fingerprints.get(record.catalog.external_id)
    if prior is not None:
        if prior == fingerprint:
            raise ValueError("duplicate source ID")
        raise ValueError("source ID has conflicting content")
    fingerprints[record.catalog.external_id] = fingerprint
    accepted.append(record)


def adapt_quint_html(raw: bytes, source: SourceSpec = QUINT_SOURCE) -> AdaptationResult:
    """Verify and adapt the pinned 6,291-point HTML snapshot."""
    _verify_bytes(raw, source)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceVerificationError("Every Noise HTML is not valid UTF-8") from error
    parser = _GenreMapParser()
    parser.feed(text)
    parser.close()
    if len(parser.candidates) != source.expected_records:
        raise SourceVerificationError(
            f"{source.source_id} exposed {len(parser.candidates)} genre elements; "
            f"expected {source.expected_records}"
        )
    accepted: list[AdaptedGenre] = []
    quarantined: list[QuarantineRecord] = []
    fingerprints: dict[str, str] = {}
    for candidate in parser.candidates:
        source_record_id = candidate.attributes.get("id")
        try:
            record = _adapt_html_candidate(candidate, source)
            _append_unique(record, accepted=accepted, fingerprints=fingerprints)
        except (ValueError, TypeError) as error:
            quarantined.append(
                QuarantineRecord(
                    source_id=source.source_id,
                    record_number=candidate.record_number,
                    source_record_id=source_record_id,
                    reason=str(error),
                )
            )
    return AdaptationResult(
        source=source,
        records=tuple(accepted),
        quarantine=tuple(quarantined),
    )


def _adapt_watch_row(row: dict[str, str | None], source: SourceSpec) -> AdaptedGenre:
    if frozenset(row) != {"genre", "x", "y", "hex_colour"}:
        raise ValueError("CSV fields changed from genre,x,y,hex_colour")
    name = (row["genre"] or "").strip()
    slug = _slug(name)
    color = (row["hex_colour"] or "").lower()
    if COLOR_PATTERN.fullmatch(color) is None:
        raise ValueError("hex_colour must be a six-digit hexadecimal color")
    external_id = f"{source.namespace}:{slug}"
    return AdaptedGenre(
        catalog=GenreRecord(
            external_id=external_id,
            name=name,
            slug=slug,
            identifiers=(IdentifierRecord(namespace=source.namespace, value=name),),
        ),
        layout=LayoutPointRecord(
            external_id=external_id,
            x_px=int(row["x"] or ""),
            y_px=int(row["y"] or ""),
            color_hex=color,
            font_size_percent=None,
            source_id=source.source_id,
            source_sha256=source.sha256,
        ),
    )


def adapt_watch_csv(raw: bytes, source: SourceSpec = WATCH_SOURCE) -> AdaptationResult:
    """Verify and adapt the licensed EveryNoise-Watch coordinate CSV."""
    _verify_bytes(raw, source)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceVerificationError("EveryNoise-Watch CSV is not valid UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != ["genre", "x", "y", "hex_colour"]:
        raise SourceVerificationError("EveryNoise-Watch CSV header changed")
    accepted: list[AdaptedGenre] = []
    quarantined: list[QuarantineRecord] = []
    fingerprints: dict[str, str] = {}
    row_count = 0
    for record_number, row in enumerate(reader, start=2):
        row_count += 1
        name = row.get("genre")
        try:
            record = _adapt_watch_row(row, source)
            _append_unique(record, accepted=accepted, fingerprints=fingerprints)
        except (ValueError, TypeError) as error:
            quarantined.append(
                QuarantineRecord(
                    source_id=source.source_id,
                    record_number=record_number,
                    source_record_id=name,
                    reason=str(error),
                )
            )
    if row_count != source.expected_records:
        raise SourceVerificationError(
            f"{source.source_id} exposed {row_count} CSV records; "
            f"expected {source.expected_records}"
        )
    return AdaptationResult(
        source=source,
        records=tuple(accepted),
        quarantine=tuple(quarantined),
    )


def adapt_source(raw: bytes, source: SourceSpec) -> AdaptationResult:
    """Dispatch a verified artifact to its explicitly selected adapter."""
    if source.adapter == "enao_html_map_v1":
        return adapt_quint_html(raw, source)
    return adapt_watch_csv(raw, source)


def store_verified_bytes(raw: bytes, source: SourceSpec, vault_root: Path) -> Path:
    """Store verified bytes under their digest without overwriting an object."""
    _verify_bytes(raw, source)
    vault_root.mkdir(parents=True, exist_ok=True)
    destination = vault_root / source.sha256
    if destination.exists():
        existing = destination.read_bytes()
        _verify_bytes(existing, source)
        return destination
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{source.sha256}.", dir=vault_root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _download_verified_source(source: SourceSpec, vault_root: Path) -> Path:
    vault_root.mkdir(parents=True, exist_ok=True)
    destination = vault_root / source.sha256
    if destination.exists():
        _verify_bytes(destination.read_bytes(), source)
        return destination
    if shutil.disk_usage(vault_root).free < source.expected_bytes * 2:
        raise SourceVerificationError("free disk must be at least twice the expected source size")
    request = urllib.request.Request(  # noqa: S310 - source is a validated pinned HTTPS URL.
        str(source.url),
        headers={"User-Agent": "musix-data-bootstrap/0.1 (local research)"},
    )
    with urllib.request.urlopen(request, timeout=30.0) as response:  # noqa: S310
        raw = response.read(source.expected_bytes + 1)
    return store_verified_bytes(raw, source, vault_root)


async def fetch_verified_source(source: SourceSpec, vault_root: Path) -> Path:
    """Fetch, verify, and atomically vault one pinned source off the event loop."""
    return await asyncio.to_thread(_download_verified_source, source, vault_root)


def _jsonl(records: Iterable[BaseModel]) -> bytes:
    lines = [
        json.dumps(
            record.model_dump(mode="json", exclude_none=False),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for record in records
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode()
