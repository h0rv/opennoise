"""One-pass, bounded MusicBrainz artist-to-seed evidence extraction.

This module deliberately does not load artists into the catalog database.  It
reads the compressed artist dump once, keeps only positive claims that match a
name-only seed vocabulary, and emits a hash-bound JSON artifact suitable for
later modelling and review.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol, overload, override
from uuid import UUID

import ijson
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, TypeAdapter, model_validator

from musix.taxonomy.seeds.universe import SeedInput, normalize_label

type Facet = Literal["genre", "tag"]
type MatchKind = Literal["exact", "normalized", "reviewed_alias"]
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object])


class MusicBrainzSeedTargetExtractorError(ValueError):
    """Raised when archive-level safety or schema checks fail."""


class SeedTargetExtractorSettings(BaseModel):
    """Explicit parse and memory bounds included in the output fingerprint."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    revision: Literal["musicbrainz-seed-targets-v1"] = "musicbrainz-seed-targets-v1"
    max_archive_bytes: int = Field(default=8 * 1024**3, gt=0)
    max_member_bytes: int = Field(default=64 * 1024**3, gt=0)
    max_record_bytes: int = Field(default=64 * 1024**2, gt=0)
    max_records: int = Field(default=10_000_000, gt=0)
    max_decompression_ratio: int = Field(default=128, gt=0)
    max_genres_per_artist: int = Field(default=128, gt=0)
    max_tags_per_artist: int = Field(default=512, gt=0)
    max_evidence_rows: int = Field(default=2_000_000, gt=0)
    max_contextual_tag_rows: int = Field(default=2_000_000, gt=0)


class ReviewedSeedAlias(BaseModel):
    """One human-approved spelling alias for an immutable stable seed ID."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_item_id: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    approval_ref: str = Field(
        pattern=r"^reviewed:[a-z0-9][a-z0-9._:-]{0,290}$",
        max_length=300,
    )
    facets: tuple[Facet, ...] = ("tag",)

    @model_validator(mode="after")
    def require_unique_facets(self) -> ReviewedSeedAlias:
        """Keep the reviewed source facet scope explicit and deterministic."""
        if not self.facets or len(self.facets) != len(set(self.facets)):
            raise ValueError("reviewed aliases require unique allowed facets")
        return self


class SeedTargetEvidence(BaseModel):
    """One direct positive artist claim matched to one supplied seed."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    seed_source_item_id: str = Field(min_length=1)
    seed_source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    seed_normalized_name: str = Field(min_length=1)
    facet: Facet
    target_namespace: Literal["musicbrainz_genre_id", "musicbrainz_tag_name"]
    target_identity: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_record_id: str = Field(min_length=1)
    source_record_ordinal: int = Field(gt=0)
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_byte_length: int = Field(ge=1)
    evidence_ref: str = Field(min_length=1)
    positive_weight: float = Field(gt=0)
    match_kind: MatchKind


class ContextualArtistTag(BaseModel):
    """A non-target co-occurring tag retained only for a matched artist."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_record_id: str = Field(min_length=1)
    source_record_ordinal: int = Field(gt=0)
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_byte_length: int = Field(ge=1)
    tag_name: str = Field(min_length=1)
    tag_identity: str = Field(min_length=1)
    tag_count: int | None = Field(default=None, ge=0)
    matched_seed_source_item_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)


class _StreamingRows[T: BaseModel](Sequence[T]):
    """Re-iterable, bounded-memory view over one JSON array.

    The public artifact still exposes ``evidence`` and ``contextual_tags`` as
    sequences of the same Pydantic row types.  Only the loader's backing
    storage changes: each pass opens the source and validates one row before
    yielding it, so consumers that aggregate rows do not retain the complete
    million-row corpus.
    """

    __slots__ = ("_count", "_model", "_path", "_prefix")

    def __init__(self, path: Path, prefix: str, model: type[T], count: int) -> None:
        self._path = path
        self._prefix = prefix
        self._model = model
        self._count = count

    @override
    def __len__(self) -> int:
        return self._count

    def _iter_rows(self) -> Iterator[T]:
        count = 0
        with self._path.open("rb") as stream:
            for row in ijson.items(stream, f"{self._prefix}.item", use_float=True):
                count += 1
                # JSON arrays become Python lists under ijson, while strict
                # tuple fields (for example matched seed IDs) are accepted
                # by Pydantic's JSON validator.  Re-encode only this row.
                yield self._model.model_validate_json(_canonical(row))
        if count != self._count:
            raise ValueError(
                f"streamed {self._prefix} row count {count} does not match expected {self._count}"
            )

    @override
    def __iter__(self) -> Iterator[T]:
        return self._iter_rows()

    @overload
    def __getitem__(self, index: int, /) -> T: ...

    @overload
    def __getitem__(self, index: slice[int | None], /) -> Sequence[T]: ...

    @override
    def __getitem__(self, index: int | slice[int | None], /) -> T | Sequence[T]:
        if isinstance(index, slice):
            return tuple(self._iter_rows())[index]
        resolved = index if index >= 0 else self._count + index
        if resolved < 0 or resolved >= self._count:
            raise IndexError(index)
        for row_index, row in enumerate(self._iter_rows()):
            if row_index == resolved:
                return row
        raise IndexError(index)


class SeedTargetCoverage(BaseModel):
    """Coverage rollup for every input seed, including zero-match seeds."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    seed_source_item_id: str = Field(min_length=1)
    seed_source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    evidence_count: int = Field(ge=0)
    distinct_artist_count: int = Field(ge=0)
    distinct_target_identity_count: int = Field(ge=0)
    genre_evidence_count: int = Field(ge=0)
    tag_evidence_count: int = Field(ge=0)


class SeedTargetExtractorCounters(BaseModel):
    """Explicit accounting for all bounded and malformed input paths."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    archive_member_count: int = Field(ge=0)
    member_over_limit_count: int = Field(ge=0)
    malformed_member_path_count: int = Field(ge=0)
    records_seen: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    records_with_matches: int = Field(ge=0)
    records_skipped_over_limit: int = Field(ge=0)
    record_over_limit_count: int = Field(ge=0)
    malformed_json_count: int = Field(ge=0)
    malformed_shape_count: int = Field(ge=0)
    malformed_claim_count: int = Field(ge=0)
    claim_over_limit_count: int = Field(ge=0)
    duplicate_claim_count: int = Field(ge=0)
    evidence_over_limit_count: int = Field(ge=0)
    contextual_over_limit_count: int = Field(ge=0)
    positive_evidence_count: int = Field(ge=0)
    contextual_tag_count: int = Field(ge=0)


class MusicBrainzSeedTargetArtifact(BaseModel):
    """Reproducible seed-target evidence and contextual feature artifact."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    artifact_revision: Literal["musicbrainz-seed-target-artifact-v1"] = (
        "musicbrainz-seed-target-artifact-v1"
    )
    seed_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_source_id: str = Field(min_length=1)
    seed_source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_count: int = Field(gt=0)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: SeedTargetExtractorSettings
    settings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    counters: SeedTargetExtractorCounters
    coverage: tuple[SeedTargetCoverage, ...] = Field(min_length=1)
    evidence: Sequence[SeedTargetEvidence] = ()
    contextual_tags: Sequence[ContextualArtistTag] = ()
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    _source_path: Path | None = PrivateAttr(default=None)

    def streaming_source_path(self) -> Path | None:
        """Return the backing path when this artifact was stream-loaded."""
        return self._source_path

    def bind_streaming_source_path(self, path: Path) -> None:
        """Bind the verified source path used for replay hashing."""
        self._source_path = path

    @model_validator(mode="after")
    def validate_shape(self) -> MusicBrainzSeedTargetArtifact:
        """Keep the denormalized coverage length and settings fingerprint aligned."""
        if self.seed_count != len(self.coverage):
            raise ValueError("seed_count must equal coverage length")
        if self.settings_sha256 != settings_sha256(self.settings):
            raise ValueError("settings_sha256 does not match settings")
        return self


@dataclass(frozen=True, slots=True)
class _RawLine:
    ordinal: int
    payload: bytes | None
    byte_length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _Claim:
    facet: Facet
    identity: str
    name: str
    count: int | None


@dataclass(frozen=True, slots=True)
class _SeedMatch:
    """One canonical or reviewed-alias resolution for a source claim."""

    index: int
    match_kind: MatchKind
    approval_ref: str | None = None
    allowed_facets: tuple[Facet, ...] = ()
    mapping_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class _ParsedArtist:
    artist_id: UUID
    genres: tuple[_Claim, ...]
    tags: tuple[_Claim, ...]


@dataclass(slots=True)
class _CoverageAccumulator:
    evidence_count: int = 0
    genre_count: int = 0
    tag_count: int = 0
    artists: set[str] = field(default_factory=set)
    identities: set[str] = field(default_factory=set)


class _HashingReader(io.RawIOBase):
    """Minimal buffered-reader interface required by tarfile stream mode."""

    def __init__(self, stream: _ReadableStream) -> None:
        super().__init__()
        self._stream = stream
        self.digest = hashlib.sha256()

    @override
    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        if not isinstance(data, bytes):
            raise TypeError("archive stream returned non-bytes")
        self.digest.update(data)
        return data

    @override
    def readable(self) -> bool:
        return True

    @override
    def seekable(self) -> bool:
        return False


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def settings_sha256(settings: SeedTargetExtractorSettings) -> str:
    """Return the canonical hash of extraction bounds and revision."""
    return _sha256_bytes(_canonical(settings.model_dump(mode="json")))


@dataclass(slots=True)
class _CanonicalHashFrame:
    kind: Literal["map", "array"]
    first: bool = True
    expecting_value: bool = False


def _streaming_artifact_hash(path: Path) -> str:  # noqa: C901, PLR0912, PLR0915
    """Hash canonical artifact JSON while omitting its self-referential field.

    The artifact writer emits compact, sorted-key JSON.  Replaying the JSON
    parser into a compact encoder preserves that logical hash without ever
    constructing the evidence or contextual-tag arrays.  ``output_sha256`` is
    skipped as a root object member, exactly as :func:`artifact_sha256` does
    for an in-memory model.
    """
    digest = hashlib.sha256()
    frames: list[_CanonicalHashFrame] = []
    root_value_seen = False
    root_closed = False
    skip_value = False
    skip_depth = 0

    def before_value() -> None:
        nonlocal root_value_seen
        if not frames:
            if root_value_seen:
                raise ValueError("artifact JSON contains multiple root values")
            root_value_seen = True
            return
        frame = frames[-1]
        if frame.kind == "array":
            if not frame.first:
                digest.update(b",")
            frame.first = False
            return
        if not frame.expecting_value:
            raise ValueError("artifact JSON map value is missing its key")
        frame.expecting_value = False

    with path.open("rb") as stream:
        for event, value in ijson.basic_parse(stream, use_float=True):
            if skip_depth:
                if event in {"start_map", "start_array"}:
                    skip_depth += 1
                elif event in {"end_map", "end_array"}:
                    skip_depth -= 1
                continue
            if skip_value:
                skip_value = False
                if event in {"start_map", "start_array"}:
                    skip_depth = 1
                continue
            if event == "map_key":
                if not frames or frames[-1].kind != "map" or not isinstance(value, str):
                    raise ValueError("artifact JSON has a map key outside an object")
                frame = frames[-1]
                if len(frames) == 1 and value == "output_sha256":
                    skip_value = True
                    continue
                if not frame.first:
                    digest.update(b",")
                frame.first = False
                digest.update(_canonical(value))
                digest.update(b":")
                frame.expecting_value = True
                continue
            if event == "start_map":
                before_value()
                digest.update(b"{")
                frames.append(_CanonicalHashFrame("map"))
                continue
            if event == "start_array":
                before_value()
                digest.update(b"[")
                frames.append(_CanonicalHashFrame("array"))
                continue
            if event in {"string", "number", "boolean", "null"}:
                before_value()
                digest.update(_canonical(value))
                continue
            if event == "end_map":
                if not frames or frames[-1].kind != "map" or frames[-1].expecting_value:
                    raise ValueError("artifact JSON object is incomplete")
                frames.pop()
                digest.update(b"}")
                if not frames:
                    root_closed = True
                continue
            if event == "end_array":
                if not frames or frames[-1].kind != "array":
                    raise ValueError("artifact JSON array is incomplete")
                frames.pop()
                digest.update(b"]")
                continue
            raise ValueError(f"unsupported artifact JSON event: {event}")
    if frames or not root_closed or not root_value_seen:
        raise ValueError("artifact JSON root is incomplete")
    return digest.hexdigest()


def artifact_sha256(artifact: MusicBrainzSeedTargetArtifact) -> str:
    """Return the canonical output hash excluding the self-referential field."""
    source_path = artifact.streaming_source_path()
    if (
        source_path is not None
        and isinstance(artifact.evidence, _StreamingRows)
        and isinstance(artifact.contextual_tags, _StreamingRows)
    ):
        return _streaming_artifact_hash(source_path)
    return _sha256_bytes(_canonical(artifact.model_dump(mode="json", exclude={"output_sha256"})))


@dataclass(slots=True)
class _ParsedSeedTargetSections:
    values: dict[str, object]
    coverage: tuple[SeedTargetCoverage, ...]
    evidence_count: int
    contextual_count: int


_ARTIFACT_FIELDS = frozenset(MusicBrainzSeedTargetArtifact.model_fields)
_ARRAY_FIELDS = frozenset({"coverage", "evidence", "contextual_tags"})
_SMALL_OBJECT_FIELDS = frozenset({"settings", "counters"})


def _parse_seed_target_artifact(  # noqa: C901, PLR0912, PLR0915
    path: Path,
) -> tuple[MusicBrainzSeedTargetArtifact, int, int]:
    """Parse all bounded sections without materializing either large row array."""
    root_keys: set[str] = set()
    values: dict[str, object] = {}
    coverage_rows: list[SeedTargetCoverage] = []
    small_objects: dict[str, dict[str, object]] = {}
    small_object_keys: dict[str, set[str]] = {}
    active_small: str | None = None
    active_small_key: str | None = None
    active_coverage: dict[str, object] | None = None
    active_coverage_keys: set[str] = set()
    arrays_open: set[str] = set()
    arrays_closed: set[str] = set()
    evidence_count = 0
    contextual_count = 0

    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream, use_float=True):
            if prefix == "" and event == "map_key":
                if not isinstance(value, str):
                    raise ValueError("seed-target root key is not a string")
                if value in root_keys:
                    raise ValueError(f"duplicate seed-target root key: {value}")
                root_keys.add(value)
                active_small = None
                active_small_key = None
                continue

            if prefix == "settings" and event == "start_map":
                active_small = "settings"
                small_objects[active_small] = {}
                small_object_keys[active_small] = set()
                continue
            if prefix == "counters" and event == "start_map":
                active_small = "counters"
                small_objects[active_small] = {}
                small_object_keys[active_small] = set()
                continue
            if active_small is not None:
                if prefix == active_small and event == "map_key":
                    if not isinstance(value, str):
                        raise ValueError(f"{active_small} key is not a string")
                    if value in small_object_keys[active_small]:
                        raise ValueError(f"duplicate {active_small} key: {value}")
                    small_object_keys[active_small].add(value)
                    active_small_key = value
                    small_objects[active_small][value] = None
                    continue
                if (
                    active_small_key is not None
                    and prefix == f"{active_small}.{active_small_key}"
                    and event in {"string", "number", "boolean", "null"}
                ):
                    small_objects[active_small][active_small_key] = value
                    continue
                if prefix == active_small and event == "end_map":
                    active_small = None
                    active_small_key = None
                    continue

            if prefix == "coverage" and event == "start_array":
                arrays_open.add("coverage")
                continue
            if prefix == "coverage" and event == "end_array":
                if active_coverage is not None:
                    raise ValueError("coverage array ended inside a row")
                arrays_open.discard("coverage")
                arrays_closed.add("coverage")
                continue
            if prefix == "coverage.item" and event == "start_map":
                if active_coverage is not None:
                    raise ValueError("coverage row contains a nested object")
                active_coverage = {}
                active_coverage_keys = set()
                continue
            if prefix == "coverage.item" and event == "end_map":
                if active_coverage is None:
                    raise ValueError("coverage row is not an object")
                coverage_rows.append(SeedTargetCoverage.model_validate(active_coverage))
                active_coverage = None
                active_coverage_keys = set()
                continue
            if active_coverage is not None:
                if prefix == "coverage.item" and event == "map_key":
                    if not isinstance(value, str):
                        raise ValueError("coverage row key is not a string")
                    if value in active_coverage_keys:
                        raise ValueError(f"duplicate coverage row key: {value}")
                    active_coverage_keys.add(value)
                    active_coverage[value] = None
                    continue
                if (
                    prefix.startswith("coverage.item.")
                    and prefix.removeprefix("coverage.item.") in active_coverage_keys
                    and event in {"string", "number", "boolean", "null"}
                ):
                    active_coverage[prefix.removeprefix("coverage.item.")] = value
                    continue

            if prefix == "evidence" and event == "start_array":
                arrays_open.add("evidence")
                continue
            if prefix == "evidence" and event == "end_array":
                arrays_open.discard("evidence")
                arrays_closed.add("evidence")
                continue
            if prefix == "contextual_tags" and event == "start_array":
                arrays_open.add("contextual_tags")
                continue
            if prefix == "contextual_tags" and event == "end_array":
                arrays_open.discard("contextual_tags")
                arrays_closed.add("contextual_tags")
                continue
            if prefix == "evidence.item" and event in {
                "start_map",
                "start_array",
                "string",
                "number",
                "boolean",
                "null",
            }:
                evidence_count += 1
                continue
            if prefix == "contextual_tags.item" and event in {
                "start_map",
                "start_array",
                "string",
                "number",
                "boolean",
                "null",
            }:
                contextual_count += 1
                continue
            if (
                prefix in root_keys
                and event in {"string", "number", "boolean", "null"}
                and prefix not in _ARRAY_FIELDS
                and prefix not in _SMALL_OBJECT_FIELDS
            ):
                values[prefix] = value

    if root_keys != _ARTIFACT_FIELDS:
        missing = sorted(_ARTIFACT_FIELDS - root_keys)
        extra = sorted(root_keys - _ARTIFACT_FIELDS)
        raise ValueError(f"seed-target root fields mismatch (missing={missing}, extra={extra})")
    if arrays_open or arrays_closed != _ARRAY_FIELDS:
        raise ValueError("seed-target row arrays are missing or malformed")
    if active_small is not None or active_coverage is not None:
        raise ValueError("seed-target bounded object is incomplete")
    values["settings"] = SeedTargetExtractorSettings.model_validate(
        small_objects.get("settings", {})
    )
    values["counters"] = SeedTargetExtractorCounters.model_validate(
        small_objects.get("counters", {})
    )
    values["coverage"] = tuple(coverage_rows)
    values["evidence"] = ()
    values["contextual_tags"] = ()
    artifact = MusicBrainzSeedTargetArtifact.model_validate(values)
    return artifact, evidence_count, contextual_count


def _verify_sorted_evidence(rows: Sequence[SeedTargetEvidence], *, require_sorted: bool) -> None:
    previous: tuple[str, Facet, str, str] | None = None
    seen: set[tuple[str, Facet, str, str]] | None = set() if not require_sorted else None
    for row in rows:
        key = (row.seed_source_item_id, row.facet, row.target_identity, row.artist_id)
        if seen is not None and key in seen:
            raise ValueError("duplicate seed-target evidence row")
        if seen is not None:
            seen.add(key)
        if previous is not None:
            if key == previous:
                raise ValueError("duplicate seed-target evidence row")
            if require_sorted and key < previous:
                raise ValueError("seed-target evidence rows are not canonically sorted")
        previous = key


def _verify_sorted_contextual_tags(
    rows: Sequence[ContextualArtistTag], *, require_sorted: bool
) -> None:
    previous: tuple[str, str] | None = None
    seen: set[tuple[str, str]] | None = set() if not require_sorted else None
    for row in rows:
        key = (row.artist_id, row.tag_identity)
        if seen is not None and key in seen:
            raise ValueError("duplicate contextual tag row")
        if seen is not None:
            seen.add(key)
        if previous is not None:
            if key == previous:
                raise ValueError("duplicate contextual tag row")
            if require_sorted and key < previous:
                raise ValueError("contextual tag rows are not canonically sorted")
        previous = key


def verify_seed_target_artifact(artifact: MusicBrainzSeedTargetArtifact) -> None:
    """Verify settings, structure, and output hashes after load or transfer."""
    if artifact.settings_sha256 != settings_sha256(artifact.settings):
        raise ValueError("seed-target settings hash mismatch")
    if artifact.output_sha256 != artifact_sha256(artifact):
        raise ValueError("seed-target output hash mismatch")
    _verify_sorted_evidence(
        artifact.evidence, require_sorted=isinstance(artifact.evidence, _StreamingRows)
    )
    _verify_sorted_contextual_tags(
        artifact.contextual_tags,
        require_sorted=isinstance(artifact.contextual_tags, _StreamingRows),
    )


def write_seed_target_artifact(path: Path, artifact: MusicBrainzSeedTargetArtifact) -> None:
    """Write canonical compact JSON after verifying its integrity."""
    verify_seed_target_artifact(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(artifact.model_dump(mode="json")) + b"\n")


def load_seed_target_artifact(path: Path) -> MusicBrainzSeedTargetArtifact:
    """Load scalar fields eagerly and keep large row arrays on disk."""
    artifact, evidence_count, contextual_count = _parse_seed_target_artifact(path)
    loaded = MusicBrainzSeedTargetArtifact.model_construct(
        artifact_revision=artifact.artifact_revision,
        seed_input_sha256=artifact.seed_input_sha256,
        seed_source_id=artifact.seed_source_id,
        seed_source_content_sha256=artifact.seed_source_content_sha256,
        seed_count=artifact.seed_count,
        archive_sha256=artifact.archive_sha256,
        settings=artifact.settings,
        settings_sha256=artifact.settings_sha256,
        counters=artifact.counters,
        coverage=artifact.coverage,
        evidence=_StreamingRows(path, "evidence", SeedTargetEvidence, evidence_count),
        contextual_tags=_StreamingRows(
            path, "contextual_tags", ContextualArtistTag, contextual_count
        ),
        output_sha256=artifact.output_sha256,
    )
    loaded.bind_streaming_source_path(path)
    artifact = loaded
    verify_seed_target_artifact(artifact)
    return artifact


def _normalize_tag(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    words = re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", without_marks))
    return re.sub(r"\s+", " ", words).strip()


def _tag_identity(value: str) -> str:
    normalized = _normalize_tag(value)
    return "tag:" + re.sub(r"[^\w]+", "-", normalized).strip("-")


def _safe_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


class _ReadableStream(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...

    def readline(self, size: int = -1, /) -> bytes: ...


def _raw_lines(stream: _ReadableStream, max_record_bytes: int) -> Iterator[_RawLine]:
    ordinal = 0
    while True:
        first = stream.readline(max_record_bytes + 2)
        if not isinstance(first, bytes) or not first:
            return
        chunks = [first]
        while not chunks[-1].endswith(b"\n"):
            continuation = stream.readline(64 * 1024)
            if not isinstance(continuation, bytes) or not continuation:
                break
            chunks.append(continuation)
        payload = b"".join(chunks).rstrip(b"\r\n")
        if not payload.strip():
            continue
        ordinal += 1
        digest = _sha256_bytes(payload)
        yield _RawLine(
            ordinal=ordinal,
            payload=payload if len(payload) <= max_record_bytes else None,
            byte_length=len(payload),
            sha256=digest,
        )


def _int_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _parse_artist(  # noqa: C901, PLR0915
    payload: bytes, settings: SeedTargetExtractorSettings
) -> tuple[_ParsedArtist | None, str]:
    try:
        raw = _JSON_OBJECT_ADAPTER.validate_json(payload)
    except ValueError:
        return None, "json"
    raw_id = raw.get("id")
    if not isinstance(raw_id, str):
        return None, "shape"
    try:
        artist_id = UUID(raw_id)
    except ValueError:
        return None, "shape"

    def claims(  # noqa: C901, PLR0912
        value: object, facet: Facet, limit: int
    ) -> tuple[tuple[_Claim, ...], int, int, int]:
        if value is None:
            return (), 0, 0, 0
        if not isinstance(value, list):
            return (), 1, 0, 0
        if len(value) > limit:
            return (), 0, 0, 1
        parsed: list[_Claim] = []
        seen: set[str] = set()
        malformed = 0
        duplicate = 0
        for item in value:
            if not isinstance(item, dict):
                malformed += 1
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                malformed += 1
                continue
            count = _int_count(item.get("count"))
            if "count" in item and item.get("count") is not None and count is None:
                malformed += 1
                continue
            if facet == "tag" and (count is None or count <= 0):
                continue
            if facet == "genre":
                raw_genre_id = item.get("id")
                if not isinstance(raw_genre_id, str):
                    malformed += 1
                    continue
                try:
                    identity = str(UUID(raw_genre_id))
                except ValueError:
                    malformed += 1
                    continue
            else:
                identity = _tag_identity(name)
                if identity == "tag:":
                    malformed += 1
                    continue
            if identity in seen:
                duplicate += 1
                continue
            seen.add(identity)
            parsed.append(_Claim(facet, identity, name.strip(), count))
        return tuple(parsed), malformed, duplicate, 0

    genres, genre_errors, genre_duplicates, genre_over_limit = claims(
        raw.get("genres"), "genre", settings.max_genres_per_artist
    )
    tags, tag_errors, tag_duplicates, tag_over_limit = claims(
        raw.get("tags"), "tag", settings.max_tags_per_artist
    )
    if genre_errors or tag_errors:
        # The record identity remains useful; malformed claims are counted by caller.
        pass
    parsed = _ParsedArtist(artist_id, genres, tags)
    return parsed, (
        f"claims:{genre_errors + tag_errors}:{genre_duplicates + tag_duplicates}:"
        f"{genre_over_limit + tag_over_limit}"
    )


def _matches(
    claim: _Claim,
    exact: dict[str, tuple[int, ...]],
    normalized: dict[str, tuple[int, ...]],
    reviewed_aliases: dict[str, _SeedMatch],
) -> tuple[_SeedMatch, ...]:
    exact_indices = exact.get(claim.name, ())
    if exact_indices:
        return tuple(_SeedMatch(index, "exact") for index in exact_indices)
    normalized_indices = normalized.get(normalize_label(claim.name), ())
    if normalized_indices:
        return tuple(_SeedMatch(index, "normalized") for index in normalized_indices)
    reviewed = reviewed_aliases.get(normalize_label(claim.name))
    if reviewed is None or claim.facet not in reviewed.allowed_facets:
        return ()
    return (reviewed,)


def _reviewed_alias_lookup(
    seed_input: SeedInput, aliases: tuple[ReviewedSeedAlias, ...]
) -> dict[str, _SeedMatch]:
    """Validate a small reviewed overlay without modifying the source vocabulary."""
    indices_by_id = {seed.source_item_id: index for index, seed in enumerate(seed_input.names)}
    canonical_ids_by_normalized_name: dict[str, set[str]] = {}
    for seed in seed_input.names:
        canonical_ids_by_normalized_name.setdefault(normalize_label(seed.name), set()).add(
            seed.source_item_id
        )
    alias_rows = tuple(
        sorted(
            aliases,
            key=lambda item: (item.source_item_id, normalize_label(item.alias), item.approval_ref),
        )
    )
    mapping_sha256 = _sha256_bytes(
        _canonical([item.model_dump(mode="json") for item in alias_rows])
    )
    resolved: dict[str, _SeedMatch] = {}
    for alias in aliases:
        index = indices_by_id.get(alias.source_item_id)
        if index is None:
            raise MusicBrainzSeedTargetExtractorError(
                "reviewed alias references an unknown stable seed ID"
            )
        normalized_alias = normalize_label(alias.alias)
        if not normalized_alias:
            raise MusicBrainzSeedTargetExtractorError("reviewed alias normalizes to an empty label")
        canonical_ids = canonical_ids_by_normalized_name.get(normalized_alias, set())
        if canonical_ids:
            raise MusicBrainzSeedTargetExtractorError(
                "reviewed alias conflicts with a canonical seed spelling"
            )
        if normalized_alias in resolved:
            raise MusicBrainzSeedTargetExtractorError(
                "reviewed aliases must have unique normalized spellings"
            )
        resolved[normalized_alias] = _SeedMatch(
            index=index,
            match_kind="reviewed_alias",
            approval_ref=alias.approval_ref,
            allowed_facets=alias.facets,
            mapping_sha256=mapping_sha256,
        )
    return resolved


def extract_musicbrainz_seed_targets(  # noqa: C901, PLR0912, PLR0915
    archive_path: Path,
    seed_input: SeedInput,
    settings: SeedTargetExtractorSettings | None = None,
    *,
    reviewed_aliases: tuple[ReviewedSeedAlias, ...] = (),
) -> MusicBrainzSeedTargetArtifact:
    """Scan one artist archive once and return positive target evidence."""
    settings = settings or SeedTargetExtractorSettings()
    reviewed_aliases_by_name = _reviewed_alias_lookup(seed_input, reviewed_aliases)
    archive_size = archive_path.stat().st_size
    if archive_size > settings.max_archive_bytes:
        raise MusicBrainzSeedTargetExtractorError("archive exceeds max_archive_bytes")
    exact_lists: dict[str, list[int]] = {}
    normalized_lists: dict[str, list[int]] = {}
    accumulators = [_CoverageAccumulator() for _ in seed_input.names]
    for index, seed in enumerate(seed_input.names):
        exact_lists.setdefault(seed.name, []).append(index)
        normalized_lists.setdefault(normalize_label(seed.name), []).append(index)
    exact = {name: tuple(indices) for name, indices in exact_lists.items()}
    normalized = {name: tuple(indices) for name, indices in normalized_lists.items()}
    evidence: list[SeedTargetEvidence] = []
    contextual: dict[tuple[str, str], ContextualArtistTag] = {}
    counters = dict.fromkeys(SeedTargetExtractorCounters.model_fields, 0)
    found_artist = False
    schema_number: str | None = None
    with archive_path.open("rb") as original:
        hashing = _HashingReader(original)
        with tarfile.open(fileobj=hashing, mode="r|xz") as archive:
            for member in archive:
                counters["archive_member_count"] += 1
                member_path = _safe_member(member.name)
                if member_path is None:
                    counters["malformed_member_path_count"] += 1
                    continue
                if member.size > settings.max_member_bytes:
                    counters["member_over_limit_count"] += 1
                    continue
                if member.size > archive_size * settings.max_decompression_ratio:
                    counters["member_over_limit_count"] += 1
                    continue
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                try:
                    if member_path == PurePosixPath("JSON_DUMPS_SCHEMA_NUMBER"):
                        schema_bytes = stream.read(32)
                        if not isinstance(schema_bytes, bytes):
                            raise MusicBrainzSeedTargetExtractorError(
                                "schema member returned non-bytes"
                            )
                        schema_number = str(schema_bytes.decode("ascii", errors="replace")).strip()
                    elif member_path == PurePosixPath("mbdump/artist"):
                        if found_artist:
                            raise MusicBrainzSeedTargetExtractorError(
                                "archive repeats mbdump/artist"
                            )
                        found_artist = True
                        for raw_line in _raw_lines(stream, settings.max_record_bytes):
                            counters["records_seen"] += 1
                            if raw_line.byte_length > settings.max_record_bytes:
                                counters["record_over_limit_count"] += 1
                                continue
                            if raw_line.ordinal > settings.max_records:
                                counters["records_skipped_over_limit"] += 1
                                continue
                            parsed, status = _parse_artist(raw_line.payload or b"", settings)
                            if parsed is None:
                                counters[f"malformed_{status}_count"] += 1
                                continue
                            counters["records_parsed"] += 1
                            if status.startswith("claims:"):
                                _, malformed, duplicates, over_limit = status.split(":")
                                counters["malformed_claim_count"] += int(malformed)
                                counters["duplicate_claim_count"] += int(duplicates)
                                counters["claim_over_limit_count"] += int(over_limit)
                            artist_id = str(parsed.artist_id)
                            source_record_id = f"musicbrainz:artist:{artist_id}"
                            matched_seed_indices: set[int] = set()
                            matched_target_identities: set[str] = set()
                            target_tag_identities: set[str] = set()
                            evidence_before_record = len(evidence)
                            for claim in parsed.tags:
                                matches = _matches(
                                    claim, exact, normalized, reviewed_aliases_by_name
                                )
                                if matches:
                                    target_tag_identities.add(claim.identity)
                            for claim in (*parsed.genres, *parsed.tags):
                                matches = _matches(
                                    claim, exact, normalized, reviewed_aliases_by_name
                                )
                                if not matches:
                                    continue
                                matched_seed_indices.update(match.index for match in matches)
                                matched_target_identities.add(claim.identity)
                                for match in matches:
                                    index = match.index
                                    seed = seed_input.names[index]
                                    target_namespace = (
                                        "musicbrainz_genre_id"
                                        if claim.facet == "genre"
                                        else "musicbrainz_tag_name"
                                    )
                                    if len(evidence) >= settings.max_evidence_rows:
                                        counters["evidence_over_limit_count"] += 1
                                        raise MusicBrainzSeedTargetExtractorError(
                                            "max_evidence_rows exceeded"
                                        )
                                    evidence_ref = (
                                        f"musicbrainz:seed-target:{raw_line.sha256}:"
                                        f"{claim.facet}:{claim.identity}"
                                    )
                                    if match.approval_ref is not None:
                                        if match.mapping_sha256 is None:
                                            raise MusicBrainzSeedTargetExtractorError(
                                                "reviewed alias is missing its mapping digest"
                                            )
                                        evidence_ref += (
                                            f":reviewed-alias:{match.approval_ref}:"
                                            f"{match.mapping_sha256}"
                                        )
                                    row = SeedTargetEvidence(
                                        seed_source_item_id=seed.source_item_id,
                                        seed_source_external_id=seed.source_external_id,
                                        seed_name=seed.name,
                                        seed_normalized_name=normalize_label(seed.name),
                                        facet=claim.facet,
                                        target_namespace=target_namespace,
                                        target_identity=claim.identity,
                                        target_name=claim.name,
                                        artist_id=artist_id,
                                        source_record_id=source_record_id,
                                        source_record_ordinal=raw_line.ordinal,
                                        source_record_sha256=raw_line.sha256,
                                        source_record_byte_length=raw_line.byte_length,
                                        evidence_ref=evidence_ref,
                                        positive_weight=float(
                                            claim.count if claim.count and claim.count > 0 else 1
                                        ),
                                        match_kind=match.match_kind,
                                    )
                                    evidence.append(row)
                                    accumulator = accumulators[index]
                                    accumulator.evidence_count += 1
                                    accumulator.artists.add(artist_id)
                                    accumulator.identities.add(claim.identity)
                                    if claim.facet == "genre":
                                        accumulator.genre_count += 1
                                    else:
                                        accumulator.tag_count += 1
                            if matched_seed_indices:
                                counters["records_with_matches"] += 1
                                counters["positive_evidence_count"] += (
                                    len(evidence) - evidence_before_record
                                )
                                for claim in parsed.tags:
                                    if claim.identity in target_tag_identities:
                                        continue
                                    key = (artist_id, claim.identity)
                                    if key in contextual:
                                        continue
                                    if len(contextual) >= settings.max_contextual_tag_rows:
                                        counters["contextual_over_limit_count"] += 1
                                        raise MusicBrainzSeedTargetExtractorError(
                                            "max_contextual_tag_rows exceeded"
                                        )
                                    context_ref = (
                                        f"musicbrainz:artist-context-tag:{raw_line.sha256}:"
                                        f"{claim.identity}"
                                    )
                                    contextual[key] = ContextualArtistTag(
                                        artist_id=artist_id,
                                        source_record_id=source_record_id,
                                        source_record_ordinal=raw_line.ordinal,
                                        source_record_sha256=raw_line.sha256,
                                        source_record_byte_length=raw_line.byte_length,
                                        tag_name=claim.name,
                                        tag_identity=claim.identity,
                                        tag_count=claim.count,
                                        matched_seed_source_item_ids=tuple(
                                            seed_input.names[index].source_item_id
                                            for index in sorted(matched_seed_indices)
                                        ),
                                        evidence_ref=context_ref,
                                    )
                finally:
                    stream.close()

    if not found_artist:
        raise MusicBrainzSeedTargetExtractorError("archive has no mbdump/artist member")
    if schema_number != "1":
        raise MusicBrainzSeedTargetExtractorError(
            f"unsupported JSON dump schema: {schema_number!r}"
        )
    coverage = tuple(
        SeedTargetCoverage(
            seed_source_item_id=seed.source_item_id,
            seed_source_external_id=seed.source_external_id,
            seed_name=seed.name,
            normalized_name=normalize_label(seed.name),
            evidence_count=acc.evidence_count,
            distinct_artist_count=len(acc.artists),
            distinct_target_identity_count=len(acc.identities),
            genre_evidence_count=acc.genre_count,
            tag_evidence_count=acc.tag_count,
        )
        for seed, acc in zip(seed_input.names, accumulators, strict=True)
    )
    counters["contextual_tag_count"] = len(contextual)
    counter_model = SeedTargetExtractorCounters(**counters)
    evidence.sort(
        key=lambda row: (row.seed_source_item_id, row.facet, row.target_identity, row.artist_id)
    )
    context_rows = tuple(
        sorted(contextual.values(), key=lambda row: (row.artist_id, row.tag_identity))
    )
    provisional = MusicBrainzSeedTargetArtifact(
        seed_input_sha256=seed_input.artifact_sha256,
        seed_source_id=seed_input.source_id,
        seed_source_content_sha256=seed_input.source_content_sha256,
        seed_count=len(seed_input.names),
        archive_sha256=hashing.digest.hexdigest(),
        settings=settings,
        settings_sha256=settings_sha256(settings),
        counters=counter_model,
        coverage=coverage,
        evidence=tuple(evidence),
        contextual_tags=context_rows,
        output_sha256="0" * 64,
    )
    return provisional.model_copy(update={"output_sha256": artifact_sha256(provisional)})
