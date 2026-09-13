"""Bounded, row-free extraction of open MusicBrainz release-group labels.

This module stores only distinct genre/tag strings and source-kind counts.  It
never retains releases, artists, aliases, or target names.  The optional
sidecar can therefore broaden the open vocabulary without importing any
Every-Noise-derived relationship.
"""

from __future__ import annotations

import json
import resource
import tarfile
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_durable_bytes
from opennoise.ml.label_alignment.normalize import normalized_label
from opennoise.models import FrozenModel
from opennoise.pipeline.source_cache import SourceCacheReceipt, receipt_sha256

if TYPE_CHECKING:
    from collections.abc import Iterator

_ARCHIVE_MEMBER: Final = "mbdump/release-group"
_SHA: Final = r"^[0-9a-f]{64}$"
_SOURCE_ID: Final = "musicbrainz_json_release_group_research_20260905"

type SourceKind = Literal[
    "musicbrainz_release_group_genre_name", "musicbrainz_release_group_tag_name"
]


class ReleaseGroupVocabularyError(ValueError):
    """The source archive or its bounded vocabulary sidecar is invalid."""


class ReleaseGroupVocabularySettings(FrozenModel):
    """Fixed laptop bounds for one streaming vocabulary checkpoint."""

    revision: Literal["release-group-label-vocabulary-settings-v1"] = (
        "release-group-label-vocabulary-settings-v1"
    )
    maximum_archive_bytes: int = Field(default=1_300_000_000, gt=0)
    maximum_member_bytes: int = Field(default=20 * 1024**3, gt=0)
    maximum_records: int = Field(default=50_000, ge=1, le=20_000_000)
    maximum_record_bytes: int = Field(default=2 * 1024**2, ge=1024, le=16 * 1024**2)


class ReleaseGroupVocabularyLabel(FrozenModel):
    """One label with bounded top-level genre/tag observation counts."""

    normalized: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    genre_observation_count: int = Field(ge=0)
    tag_observation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _has_observation(self) -> ReleaseGroupVocabularyLabel:
        if self.genre_observation_count + self.tag_observation_count == 0:
            raise ValueError("a vocabulary label requires at least one observation")
        return self

    @property
    def kinds(self) -> tuple[SourceKind, ...]:
        """Return source kinds with a nonzero bounded observation count."""
        result: list[SourceKind] = []
        if self.genre_observation_count:
            result.append("musicbrainz_release_group_genre_name")
        if self.tag_observation_count:
            result.append("musicbrainz_release_group_tag_name")
        return tuple(result)


class ReleaseGroupVocabularyArtifact(FrozenModel):
    """Small source-bound vocabulary sidecar with no retained release rows."""

    revision: Literal["release-group-label-vocabulary-v1"] = "release-group-label-vocabulary-v1"
    source_archive_sha256: str = Field(pattern=_SHA)
    source_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=_SHA)
    source_cache_receipt_bytes: int = Field(gt=0)
    source_cache_receipt_logical_sha256: str = Field(pattern=_SHA)
    source_member_name: Literal["mbdump/release-group"] = _ARCHIVE_MEMBER
    source_member_bytes: int = Field(gt=0)
    settings: ReleaseGroupVocabularySettings
    records_seen: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    oversized_records: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    completed_source_member: bool
    labels: tuple[ReleaseGroupVocabularyLabel, ...]
    vocabulary_sha256: str = Field(pattern=_SHA)
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _consistent(self) -> ReleaseGroupVocabularyArtifact:
        classified = self.records_parsed + self.oversized_records + self.malformed_records
        if classified != self.records_seen:
            raise ValueError("every seen row must be parsed, oversized, or malformed")
        if self.records_seen > self.settings.maximum_records:
            raise ValueError("records seen exceed the fixed maximum")
        if not self.completed_source_member and self.records_seen != self.settings.maximum_records:
            raise ValueError("a partial scan must stop exactly at the fixed record maximum")
        return self


class ReleaseGroupVocabularyReceipt(FrozenModel):
    """Content-addressed custody receipt for a vocabulary sidecar."""

    revision: Literal["release-group-label-vocabulary-receipt-v1"] = (
        "release-group-label-vocabulary-receipt-v1"
    )
    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)
    object_key: str = Field(min_length=1)


class ReleaseGroupVocabularyRunReport(FrozenModel):
    """Non-logical operational measurement for one bounded scan."""

    logical_output_sha256: str = Field(pattern=_SHA)
    elapsed_seconds: float = Field(ge=0.0)
    peak_rss_kib: int = Field(ge=0)


def release_group_vocabulary_artifact_sha256(artifact: ReleaseGroupVocabularyArtifact) -> str:
    """Return the logical sidecar digest without its self-reference."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_release_group_vocabulary(artifact: ReleaseGroupVocabularyArtifact) -> None:
    """Fail closed if a vocabulary sidecar cannot replay its digest."""
    if release_group_vocabulary_artifact_sha256(artifact) != artifact.output_sha256:
        raise ReleaseGroupVocabularyError("release-group vocabulary output hash does not replay")
    expected_vocabulary = _vocabulary_sha(artifact.labels)
    if expected_vocabulary != artifact.vocabulary_sha256:
        raise ReleaseGroupVocabularyError("release-group vocabulary label digest does not replay")


def build_release_group_vocabulary(  # noqa: C901 - bounded stream checks stay together.
    archive: Path,
    source_cache_receipt: Path,
    settings: ReleaseGroupVocabularySettings | None = None,
) -> ReleaseGroupVocabularyArtifact:
    """Scan one bounded prefix, retaining distinct genre/tag labels only."""
    resolved_settings = settings or ReleaseGroupVocabularySettings()
    source_receipt, receipt_sha, receipt_size, expected_archive = _load_source_admission(
        source_cache_receipt
    )
    if archive.resolve() != expected_archive.resolve():
        raise ReleaseGroupVocabularyError(
            "source archive is not the declared OpenNoise-custodied object"
        )
    source_entry = next(entry for entry in source_receipt.entries if entry.source_id == _SOURCE_ID)
    source_sha, source_size = sha256_file(archive)
    if (source_sha, source_size) != (source_entry.sha256, source_entry.expected_bytes):
        raise ReleaseGroupVocabularyError(
            "source archive does not match the admitted source cache entry"
        )
    if source_size > resolved_settings.maximum_archive_bytes:
        raise ReleaseGroupVocabularyError("source archive exceeds the configured laptop bound")

    labels: dict[str, dict[SourceKind, int]] = defaultdict(dict)
    records_seen = records_parsed = oversized_records = malformed_records = 0
    member_size = 0
    completed = True
    try:
        with closing(tarfile.open(archive, mode="r|xz")) as stream:
            member = next(
                (
                    entry
                    for entry in stream
                    if entry.isfile() and _safe_member(entry.name) == PurePosixPath(_ARCHIVE_MEMBER)
                ),
                None,
            )
            if member is None:
                raise ReleaseGroupVocabularyError("release-group archive member is absent")
            member_size = member.size
            if member_size > resolved_settings.maximum_member_bytes:
                raise ReleaseGroupVocabularyError(
                    "release-group archive member exceeds configured bound"
                )
            extracted = stream.extractfile(member)
            if extracted is None:
                raise ReleaseGroupVocabularyError("release-group archive member cannot be read")
            for line in _bounded_lines(extracted, resolved_settings.maximum_record_bytes):
                if records_seen == resolved_settings.maximum_records:
                    completed = False
                    break
                records_seen += 1
                if line is None:
                    oversized_records += 1
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    malformed_records += 1
                    continue
                if not isinstance(raw, dict):
                    malformed_records += 1
                    continue
                records_parsed += 1
                _collect_labels(raw, labels)
    except (OSError, tarfile.TarError) as error:
        raise ReleaseGroupVocabularyError(
            "cannot stream the declared release-group archive"
        ) from error

    entries = tuple(
        ReleaseGroupVocabularyLabel(
            normalized=normalized,
            label=min(values, key=lambda value: (len(value), value)),
            genre_observation_count=kinds.get("musicbrainz_release_group_genre_name", 0),
            tag_observation_count=kinds.get("musicbrainz_release_group_tag_name", 0),
        )
        for normalized, (values, kinds) in _merge_by_normalized(labels).items()
    )
    vocabulary_sha = _vocabulary_sha(entries)
    base = ReleaseGroupVocabularyArtifact(
        source_archive_sha256=source_sha,
        source_archive_bytes=source_size,
        source_cache_receipt_sha256=receipt_sha,
        source_cache_receipt_bytes=receipt_size,
        source_cache_receipt_logical_sha256=receipt_sha256(source_receipt),
        source_member_bytes=member_size,
        settings=resolved_settings,
        records_seen=records_seen,
        records_parsed=records_parsed,
        oversized_records=oversized_records,
        malformed_records=malformed_records,
        completed_source_member=completed,
        labels=entries,
        vocabulary_sha256=vocabulary_sha,
        output_sha256="0" * 64,
    )
    artifact = base.model_copy(
        update={"output_sha256": release_group_vocabulary_artifact_sha256(base)}
    )
    verify_release_group_vocabulary(artifact)
    return artifact


def write_release_group_vocabulary(
    artifact: ReleaseGroupVocabularyArtifact, output_root: Path
) -> tuple[ReleaseGroupVocabularyReceipt, Path, Path]:
    """Publish a sidecar and receipt under a durable content-addressed root."""
    verify_release_group_vocabulary(artifact)
    directory = output_root / "sha256"
    directory.mkdir(parents=True, exist_ok=True)
    artifact_path = directory / f"{artifact.output_sha256}.json"
    payload = canonical_json(artifact.model_dump(mode="json")) + b"\n"
    write_durable_bytes(artifact_path, payload)
    receipt = ReleaseGroupVocabularyReceipt(
        artifact_sha256=sha256_hex(payload),
        artifact_byte_count=len(payload),
        logical_output_sha256=artifact.output_sha256,
        object_key=f"release-group-label-vocabulary/v1/sha256/{artifact.output_sha256}.json",
    )
    receipt_path = directory / f"{artifact.output_sha256}.receipt.json"
    write_durable_bytes(receipt_path, canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return receipt, artifact_path, receipt_path


def build_release_group_vocabulary_with_report(
    archive: Path,
    source_cache_receipt: Path,
    settings: ReleaseGroupVocabularySettings | None = None,
) -> tuple[ReleaseGroupVocabularyArtifact, ReleaseGroupVocabularyRunReport]:
    """Build with timing and peak RSS kept outside the logical sidecar."""
    started = time.monotonic()
    artifact = build_release_group_vocabulary(archive, source_cache_receipt, settings)
    return artifact, ReleaseGroupVocabularyRunReport(
        logical_output_sha256=artifact.output_sha256,
        elapsed_seconds=round(time.monotonic() - started, 3),
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )


def _bounded_lines(stream: object, maximum: int) -> Iterator[bytes | None]:
    readline = getattr(stream, "readline", None)
    if not callable(readline):
        raise ReleaseGroupVocabularyError("archive member is not line-readable")
    while line := readline(maximum + 1):
        if not isinstance(line, bytes):
            raise ReleaseGroupVocabularyError("archive member yielded a non-byte row")
        if len(line) > maximum:
            while line and not line.endswith(b"\n"):
                line = readline(64 * 1024)
            yield None
            continue
        stripped = line.rstrip(b"\r\n")
        if stripped:
            yield stripped


def _safe_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    return None if path.is_absolute() or ".." in path.parts else path


def _collect_labels(raw: dict[str, object], labels: dict[str, dict[SourceKind, int]]) -> None:
    """Read only documented top-level release-group labels, never nested artists."""
    for name, kind in (
        ("genres", "musicbrainz_release_group_genre_name"),
        ("tags", "musicbrainz_release_group_tag_name"),
    ):
        values = raw.get(name)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            label = value.get("name")
            if not isinstance(label, str) or not label.strip():
                continue
            normalized = normalized_label(label)
            if normalized:
                counts = labels.setdefault(f"{normalized}\0{label.strip()}", {})
                counts[kind] = counts.get(kind, 0) + 1


def _merge_by_normalized(
    labels: dict[str, dict[SourceKind, int]],
) -> dict[str, tuple[set[str], dict[SourceKind, int]]]:
    merged: dict[str, tuple[set[str], dict[SourceKind, int]]] = {}
    for key, counts in labels.items():
        normalized, label = key.split("\0", maxsplit=1)
        labels_for_normalized, kinds_for_normalized = merged.setdefault(normalized, (set(), {}))
        labels_for_normalized.add(label)
        for kind, count in counts.items():
            kinds_for_normalized[kind] = kinds_for_normalized.get(kind, 0) + count
    return dict(sorted(merged.items()))


def _load_source_admission(
    path: Path,
) -> tuple[SourceCacheReceipt, str, int, Path]:
    try:
        payload = path.read_bytes()
        receipt = SourceCacheReceipt.model_validate_json(payload)
    except (OSError, ValueError) as error:
        raise ReleaseGroupVocabularyError("source-cache admission receipt is invalid") from error
    matches = tuple(entry for entry in receipt.entries if entry.source_id == _SOURCE_ID)
    if len(matches) != 1:
        raise ReleaseGroupVocabularyError(
            "source-cache receipt lacks the declared release-group source"
        )
    expected = (
        path.parent / "musicbrainz-release-group-source-objects" / matches[0].object_key.value
    )
    return receipt, sha256_hex(payload), len(payload), expected


def _vocabulary_sha(labels: tuple[ReleaseGroupVocabularyLabel, ...]) -> str:
    return sha256_hex(canonical_json([label.model_dump(mode="json") for label in labels]))
