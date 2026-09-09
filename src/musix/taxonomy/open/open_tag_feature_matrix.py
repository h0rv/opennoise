"""Immutable sparse open-tag feature matrices backed by SQLite.

The matrix is deliberately a metadata-only, sparse relation table instead of a
dense serialized array.  It is built solely from MusicBrainz contextual tags,
can be joined by MusicBrainz artist ID, and is reusable by any downstream
model without coupling it to historical labels or a particular object store.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.ingest.musicbrainz.musicbrainz_seed_targets import (
    MusicBrainzSeedTargetArtifact,
    verify_seed_target_artifact,
)
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

_REVISION: Final = "open-tag-feature-matrix-v1"
_SETTINGS_REVISION: Final = "open-tag-feature-matrix-settings-v1"
_RECEIPT_REVISION: Final = "open-tag-feature-matrix-publication-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"
_CHUNK_SIZE: Final = 1_048_576

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class OpenTagFeatureMatrixError(ValueError):
    """Report a malformed, changed, or over-bounded open feature matrix."""


class OpenTagFeatureMatrixSettings(FrozenModel):
    """Bounds and weighting semantics for a portable sparse matrix."""

    revision: Literal["open-tag-feature-matrix-settings-v1"] = _SETTINGS_REVISION
    max_feature_rows: int = Field(default=2_000_000, gt=0)
    max_artist_count: int = Field(default=1_000_000, gt=0)
    max_tag_count: int = Field(default=500_000, gt=0)
    tag_count_default: int = Field(default=1, ge=1, le=1_000_000)


class OpenTagFeatureMatrixCounters(FrozenModel):
    """Full feature extraction accounting, including non-model paths."""

    contextual_rows_seen: int = Field(ge=0)
    feature_rows_written: int = Field(ge=0)
    duplicate_feature_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    tag_count: int = Field(ge=0)
    historical_inputs_read: Literal[False] = False
    direct_target_features_used: Literal[False] = False


class OpenTagFeatureMatrixArtifact(FrozenModel):
    """Hash-bound manifest for a separate immutable sparse SQLite matrix."""

    revision: Literal["open-tag-feature-matrix-v1"] = _REVISION
    source_seed_target_output_sha256: str = Field(pattern=_SHA256)
    source_seed_archive_sha256: str = Field(pattern=_SHA256)
    settings: OpenTagFeatureMatrixSettings
    settings_sha256: str = Field(pattern=_SHA256)
    matrix_sha256: str = Field(pattern=_SHA256)
    matrix_byte_size: int = Field(ge=1)
    counters: OpenTagFeatureMatrixCounters
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _bound(self) -> OpenTagFeatureMatrixArtifact:
        if self.settings_sha256 != feature_matrix_settings_sha256(self.settings):
            raise ValueError("open feature matrix settings hash does not match settings")
        if self.counters.feature_rows_written > self.settings.max_feature_rows:
            raise ValueError("open feature matrix exceeds feature row bound")
        if self.counters.artist_count > self.settings.max_artist_count:
            raise ValueError("open feature matrix exceeds artist bound")
        if self.counters.tag_count > self.settings.max_tag_count:
            raise ValueError("open feature matrix exceeds tag bound")
        return self


class OpenTagFeatureMatrixPublicationReceipt(FrozenModel):
    """Immutable receipt binding manifest and matrix bytes together."""

    revision: Literal["open-tag-feature-matrix-publication-v1"] = _RECEIPT_REVISION
    manifest: ObjectWrite
    matrix: ObjectWrite
    manifest_sha256: str = Field(pattern=_SHA256)
    matrix_sha256: str = Field(pattern=_SHA256)
    logical_output_sha256: str = Field(pattern=_SHA256)
    source_seed_target_output_sha256: str = Field(pattern=_SHA256)
    content_policy: Literal["metadata_only_no_audio"] = "metadata_only_no_audio"


@dataclass(frozen=True, slots=True)
class OpenTagFeature:
    """One sparse nonzero, with only trusted typed scalar fields."""

    artist_id: str
    tag_identity: str
    tag_count: int


class OpenTagFeatureMatrixReader:
    """Validated read-only sparse matrix adapter independent of storage backend."""

    def __init__(
        self,
        artifact: OpenTagFeatureMatrixArtifact,
        matrix_path: Path,
        *,
        snapshot_owned: bool = False,
    ) -> None:
        """Retain one already verified manifest and immutable SQLite matrix path."""
        self.artifact = artifact
        self.matrix_path = matrix_path
        self._snapshot_owned = snapshot_owned

    def close(self) -> None:
        """Remove a private matrix snapshot once its consumer has finished."""
        if self._snapshot_owned:
            self.matrix_path.unlink(missing_ok=True)

    def iter_features_for_artists(self, artist_ids: Iterable[str]) -> Iterator[OpenTagFeature]:
        """Yield sparse rows for an iterable of trusted MusicBrainz identifiers."""
        with tempfile.TemporaryDirectory(prefix="musix-feature-filter-") as directory:
            index_path = Path(directory) / "artists.sqlite"
            with closing(sqlite3.connect(index_path.as_uri(), uri=True)) as filter_connection:
                filter_connection.execute(
                    "CREATE TABLE requested_artist_ids (artist_id TEXT PRIMARY KEY) WITHOUT ROWID"
                )
                filter_connection.executemany(
                    "INSERT OR IGNORE INTO requested_artist_ids VALUES (?)",
                    ((artist_id,) for artist_id in artist_ids),
                )
                filter_connection.execute(
                    "ATTACH DATABASE ? AS features",
                    (_readonly_matrix_uri(self.matrix_path),),
                )
                rows = filter_connection.execute(
                    """
                    SELECT feature.artist_id, feature.tag_identity, feature.tag_count
                      FROM features.artist_tag_features AS feature
                      JOIN requested_artist_ids AS requested
                        ON requested.artist_id = feature.artist_id
                     ORDER BY feature.artist_id, feature.tag_identity
                    """
                )
                for artist_id, tag_identity, tag_count in rows:
                    yield OpenTagFeature(
                        artist_id=str(artist_id),
                        tag_identity=str(tag_identity),
                        tag_count=int(tag_count),
                    )

    def iter_all_features(self) -> Iterator[OpenTagFeature]:
        """Yield the complete source-only sparse matrix in canonical order."""
        with closing(
            sqlite3.connect(_readonly_matrix_uri(self.matrix_path), uri=True)
        ) as connection:
            rows = connection.execute(
                """
                SELECT artist_id, tag_identity, tag_count
                  FROM artist_tag_features
                 ORDER BY artist_id, tag_identity
                """
            )
            for artist_id, tag_identity, tag_count in rows:
                yield OpenTagFeature(
                    artist_id=str(artist_id),
                    tag_identity=str(tag_identity),
                    tag_count=int(tag_count),
                )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while block := stream.read(_CHUNK_SIZE):
            digest.update(block)
            byte_size += len(block)
    return digest.hexdigest(), byte_size


def _readonly_matrix_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro&immutable=1"


def _require_matrix_sha256(actual: str, expected: str, message: str) -> None:
    if actual != expected:
        raise OpenTagFeatureMatrixError(message)


def _require_matrix_receipt_custody(
    artifact: OpenTagFeatureMatrixArtifact, receipt: OpenTagFeatureMatrixPublicationReceipt
) -> None:
    if (
        artifact.output_sha256 != receipt.logical_output_sha256
        or artifact.source_seed_target_output_sha256 != receipt.source_seed_target_output_sha256
    ):
        raise OpenTagFeatureMatrixError("feature matrix content does not match receipt custody")


def _copy_snapshot(source: Path, expected_sha256: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="musix-verified-feature-matrix-", suffix=".sqlite"
    )
    destination = Path(temporary_name)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
            while block := input_stream.read(_CHUNK_SIZE):
                digest.update(block)
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        _require_matrix_sha256(
            digest.hexdigest(),
            expected_sha256,
            "feature matrix changed while its receipt snapshot was copied",
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def feature_matrix_settings_sha256(settings: OpenTagFeatureMatrixSettings) -> str:
    """Hash the full explicit feature extraction contract."""
    return hashlib.sha256(_canonical(settings.model_dump(mode="json"))).hexdigest()


def feature_matrix_artifact_sha256(artifact: OpenTagFeatureMatrixArtifact) -> str:
    """Hash logical manifest fields excluding their self-referential output hash."""
    return hashlib.sha256(
        _canonical(artifact.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _initialize_matrix(
    connection: sqlite3.Connection, artifact: OpenTagFeatureMatrixArtifact
) -> None:
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA page_size = 4096")
    connection.execute("VACUUM")
    connection.execute(
        """
        CREATE TABLE matrix_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        """
        CREATE TABLE artist_tag_features (
            artist_id TEXT NOT NULL,
            tag_identity TEXT NOT NULL,
            tag_count INTEGER NOT NULL CHECK(tag_count >= 1),
            PRIMARY KEY (artist_id, tag_identity)
        ) WITHOUT ROWID
        """
    )
    connection.executemany(
        "INSERT INTO matrix_metadata VALUES (?, ?)",
        (
            ("revision", artifact.revision),
            ("source_seed_target_output_sha256", artifact.source_seed_target_output_sha256),
            ("source_seed_archive_sha256", artifact.source_seed_archive_sha256),
            ("settings_sha256", artifact.settings_sha256),
        ),
    )


def _write_matrix(
    source: MusicBrainzSeedTargetArtifact,
    matrix_path: Path,
    settings: OpenTagFeatureMatrixSettings,
) -> OpenTagFeatureMatrixCounters:
    """Write a compact deterministic SQLite sparse matrix via atomic replacement."""
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{matrix_path.name}.", dir=matrix_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    provisional = OpenTagFeatureMatrixArtifact(
        source_seed_target_output_sha256=source.output_sha256,
        source_seed_archive_sha256=source.archive_sha256,
        settings=settings,
        settings_sha256=feature_matrix_settings_sha256(settings),
        matrix_sha256="0" * 64,
        matrix_byte_size=1,
        counters=OpenTagFeatureMatrixCounters(
            contextual_rows_seen=0,
            feature_rows_written=0,
            duplicate_feature_count=0,
            artist_count=0,
            tag_count=0,
        ),
        output_sha256="0" * 64,
    )
    counters = dict.fromkeys(
        (
            "contextual_rows_seen",
            "feature_rows_written",
            "duplicate_feature_count",
            "artist_count",
            "tag_count",
        ),
        0,
    )
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            _initialize_matrix(connection, provisional)
            for row in source.contextual_tags:
                counters["contextual_rows_seen"] += 1
                value = row.tag_count if row.tag_count is not None else settings.tag_count_default
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO artist_tag_features VALUES (?, ?, ?)",
                    (row.artist_id, row.tag_identity, value),
                ).rowcount
                if inserted:
                    counters["feature_rows_written"] += 1
                    if counters["feature_rows_written"] > settings.max_feature_rows:
                        raise OpenTagFeatureMatrixError(
                            "open feature matrix exceeds feature row bound"
                        )
                else:
                    counters["duplicate_feature_count"] += 1
            counters["artist_count"] = int(
                connection.execute(
                    "SELECT count(DISTINCT artist_id) FROM artist_tag_features"
                ).fetchone()[0]
            )
            counters["tag_count"] = int(
                connection.execute(
                    "SELECT count(DISTINCT tag_identity) FROM artist_tag_features"
                ).fetchone()[0]
            )
            if counters["artist_count"] > settings.max_artist_count:
                raise OpenTagFeatureMatrixError("open feature matrix exceeds artist bound")
            if counters["tag_count"] > settings.max_tag_count:
                raise OpenTagFeatureMatrixError("open feature matrix exceeds tag bound")
            connection.commit()
            connection.execute("VACUUM")
        temporary.replace(matrix_path)
    finally:
        temporary.unlink(missing_ok=True)
    return OpenTagFeatureMatrixCounters.model_validate(counters)


def build_open_tag_feature_matrix(
    source: MusicBrainzSeedTargetArtifact,
    matrix_path: Path,
    settings: OpenTagFeatureMatrixSettings | None = None,
) -> OpenTagFeatureMatrixArtifact:
    """Persist a source-only sparse tag matrix without reading historical inputs."""
    verify_seed_target_artifact(source)
    resolved = settings or OpenTagFeatureMatrixSettings()
    counters = _write_matrix(source, matrix_path, resolved)
    matrix_sha256, matrix_byte_size = _sha256_path(matrix_path)
    provisional = OpenTagFeatureMatrixArtifact(
        source_seed_target_output_sha256=source.output_sha256,
        source_seed_archive_sha256=source.archive_sha256,
        settings=resolved,
        settings_sha256=feature_matrix_settings_sha256(resolved),
        matrix_sha256=matrix_sha256,
        matrix_byte_size=matrix_byte_size,
        counters=counters,
        output_sha256="0" * 64,
    )
    artifact = provisional.model_copy(
        update={"output_sha256": feature_matrix_artifact_sha256(provisional)}
    )
    verify_open_tag_feature_matrix(artifact, matrix_path)
    return artifact


def verify_open_tag_feature_matrix(
    artifact: OpenTagFeatureMatrixArtifact, matrix_path: Path
) -> None:
    """Verify manifest, matrix bytes, schema, metadata, and sparse row accounting."""
    if artifact.output_sha256 != feature_matrix_artifact_sha256(artifact):
        raise OpenTagFeatureMatrixError("open feature matrix output hash does not replay")
    if artifact.settings_sha256 != feature_matrix_settings_sha256(artifact.settings):
        raise OpenTagFeatureMatrixError("open feature matrix settings hash does not replay")
    matrix_sha256, matrix_byte_size = _sha256_path(matrix_path)
    if (matrix_sha256, matrix_byte_size) != (artifact.matrix_sha256, artifact.matrix_byte_size):
        raise OpenTagFeatureMatrixError("open feature matrix bytes do not match manifest")
    try:
        with closing(sqlite3.connect(_readonly_matrix_uri(matrix_path), uri=True)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            tables = {
                str(name)
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                )
            }
            metadata = dict(connection.execute("SELECT key, value FROM matrix_metadata"))
            row = connection.execute(
                "SELECT count(*), count(DISTINCT artist_id), count(DISTINCT tag_identity) "
                "FROM artist_tag_features"
            ).fetchone()
    except sqlite3.Error as error:
        raise OpenTagFeatureMatrixError("open feature matrix schema is unavailable") from error
    if integrity != ("ok",) or tables != {"artist_tag_features", "matrix_metadata"}:
        raise OpenTagFeatureMatrixError("open feature matrix integrity or schema check failed")
    if metadata != {
        "revision": artifact.revision,
        "source_seed_target_output_sha256": artifact.source_seed_target_output_sha256,
        "source_seed_archive_sha256": artifact.source_seed_archive_sha256,
        "settings_sha256": artifact.settings_sha256,
    }:
        raise OpenTagFeatureMatrixError("open feature matrix metadata does not match manifest")
    if row is None or tuple(int(value) for value in row) != (
        artifact.counters.feature_rows_written,
        artifact.counters.artist_count,
        artifact.counters.tag_count,
    ):
        raise OpenTagFeatureMatrixError("open feature matrix counters do not replay")


def write_open_tag_feature_matrix_artifact(
    artifact: OpenTagFeatureMatrixArtifact, path: Path
) -> str:
    """Atomically write the compact manifest after validating its logical hash."""
    if artifact.output_sha256 != feature_matrix_artifact_sha256(artifact):
        raise OpenTagFeatureMatrixError("open feature matrix output hash does not replay")
    payload = _canonical(artifact.model_dump(mode="json")) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def load_open_tag_feature_matrix(
    artifact_path: Path, matrix_path: Path
) -> OpenTagFeatureMatrixReader:
    """Parse a small strict manifest and return a verified SQLite adapter."""
    with artifact_path.open("rb") as stream:
        artifact = OpenTagFeatureMatrixArtifact.model_validate_json(stream.read())
    verify_open_tag_feature_matrix(artifact, matrix_path)
    return OpenTagFeatureMatrixReader(artifact, matrix_path)


def load_receipted_open_tag_feature_matrix(
    artifact_path: Path,
    matrix_path: Path,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> OpenTagFeatureMatrixReader:
    """Load a matrix only when a declared immutable receipt binds both files."""
    receipt_sha256, _receipt_size = _sha256_path(receipt_path)
    if receipt_sha256 != expected_receipt_sha256:
        raise OpenTagFeatureMatrixError("feature matrix receipt does not match declared trust root")
    with receipt_path.open("rb") as stream:
        receipt = OpenTagFeatureMatrixPublicationReceipt.model_validate_json(stream.read())
    artifact_sha256, _artifact_size = _sha256_path(artifact_path)
    matrix_sha256, _matrix_size = _sha256_path(matrix_path)
    if artifact_sha256 != receipt.manifest_sha256 or matrix_sha256 != receipt.matrix_sha256:
        raise OpenTagFeatureMatrixError("feature matrix files do not match publication receipt")
    snapshot = _copy_snapshot(matrix_path, matrix_sha256)
    try:
        reader = load_open_tag_feature_matrix(artifact_path, snapshot)
        _require_matrix_sha256(
            _sha256_path(matrix_path)[0],
            matrix_sha256,
            "feature matrix changed while it was being verified",
        )
        _require_matrix_receipt_custody(reader.artifact, receipt)
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    return OpenTagFeatureMatrixReader(reader.artifact, snapshot, snapshot_owned=True)


def publish_open_tag_feature_matrix(
    artifact: OpenTagFeatureMatrixArtifact,
    *,
    artifact_path: Path,
    matrix_path: Path,
    store: ObjectStore,
) -> OpenTagFeatureMatrixPublicationReceipt:
    """Push both sealed feature files through a source-agnostic object store."""
    verify_open_tag_feature_matrix(artifact, matrix_path)
    manifest_sha256 = write_open_tag_feature_matrix_artifact(artifact, artifact_path)
    manifest = store.push(
        artifact_path,
        ObjectKey(value=f"open-tag-feature-matrix/manifest/sha256/{manifest_sha256}.json"),
    )
    matrix = store.push(
        matrix_path,
        ObjectKey(value=f"open-tag-feature-matrix/matrix/sha256/{artifact.matrix_sha256}.sqlite"),
    )
    if manifest.sha256 != manifest_sha256 or matrix.sha256 != artifact.matrix_sha256:
        raise OpenTagFeatureMatrixError("object store changed open feature matrix bytes")
    return OpenTagFeatureMatrixPublicationReceipt(
        manifest=manifest,
        matrix=matrix,
        manifest_sha256=manifest_sha256,
        matrix_sha256=artifact.matrix_sha256,
        logical_output_sha256=artifact.output_sha256,
        source_seed_target_output_sha256=artifact.source_seed_target_output_sha256,
    )
