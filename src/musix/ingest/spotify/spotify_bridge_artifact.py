"""Streaming reader and verifier for the sealed MusicBrainz--Spotify bridge.

The bridge can contain hundreds of thousands of rows.  This module treats its
JSON as an immutable stream: small custody fields are parsed eagerly, while
rows and conflict records remain re-iterable, strict Pydantic sequences backed
by the original file.  The loader never calls ``read_bytes`` on the artifact.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, overload, override

import ijson
from pydantic import Field

from musix.common import canonical_json, sha256_file
from musix.ingest.spotify.musicbrainz_spotify_bridge import (
    MusicBrainzSpotifyBridgeArtifact,
    SpotifyBridgeConflict,
    SpotifyBridgeCounters,
    SpotifyBridgePublicationReceipt,
    SpotifyBridgeRow,
    SpotifyBridgeSettings,
    settings_sha256,
)
from musix.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Iterator

_SHA256: Final = r"^[0-9a-f]{64}$"
_ROOT_FIELDS: Final = frozenset(MusicBrainzSpotifyBridgeArtifact.model_fields)
_MIN_CONFLICT_MBIDS: Final = 2


class SpotifyBridgeArtifactError(ValueError):
    """Report an invalid, changed, or internally inconsistent bridge artifact."""


class SpotifyBridgeArtifactHeader(FrozenModel):
    """Small bridge fields that can be trusted after a streaming parse."""

    revision: Literal["musicbrainz-spotify-bridge-v1"] = "musicbrainz-spotify-bridge-v1"
    source_archive_sha256: str = Field(pattern=_SHA256)
    source_archive_byte_size: int = Field(ge=1)
    historical_database_sha256: str = Field(pattern=_SHA256)
    historical_artist_count: int = Field(ge=0)
    settings: SpotifyBridgeSettings
    settings_sha256: str = Field(pattern=_SHA256)
    counters: SpotifyBridgeCounters
    output_sha256: str = Field(pattern=_SHA256)


class _StreamingRows[T: FrozenModel](Sequence[T]):
    """Strict, re-iterable JSON array view that holds no row list in memory."""

    __slots__ = ("_count", "_model", "_path", "_prefix")

    def __init__(self, path: Path, prefix: str, model: type[T], count: int) -> None:
        self._path = path
        self._prefix = prefix
        self._model = model
        self._count = count

    @override
    def __len__(self) -> int:
        return self._count

    def _iter(self) -> Iterator[T]:
        count = 0
        with self._path.open("rb") as stream:
            for raw in ijson.items(stream, f"{self._prefix}.item", use_float=True):
                count += 1
                yield self._model.model_validate_json(canonical_json(raw))
        if count != self._count:
            raise SpotifyBridgeArtifactError(
                f"streamed {self._prefix} count {count} does not match parsed count {self._count}"
            )

    @override
    def __iter__(self) -> Iterator[T]:
        return self._iter()

    @overload
    def __getitem__(self, index: int, /) -> T: ...

    @overload
    def __getitem__(self, index: slice[int | None], /) -> Sequence[T]: ...

    @override
    def __getitem__(self, index: int | slice[int | None], /) -> T | Sequence[T]:
        if isinstance(index, slice):
            raise TypeError("streaming bridge rows do not support slicing")
        resolved = index if index >= 0 else self._count + index
        if not 0 <= resolved < self._count:
            raise IndexError(index)
        for position, row in enumerate(self._iter()):
            if position == resolved:
                return row
        raise IndexError(index)


@dataclass(frozen=True, slots=True)
class LoadedSpotifyBridgeArtifact:
    """A verified header and lazily parsed bridge rows/conflicts."""

    path: Path
    header: SpotifyBridgeArtifactHeader
    rows: Sequence[SpotifyBridgeRow]
    conflicts: Sequence[SpotifyBridgeConflict]
    snapshot_owned: bool = False

    def close(self) -> None:
        """Remove the private verified snapshot when this artifact owns it."""
        if self.snapshot_owned:
            self.path.unlink(missing_ok=True)


@dataclass(slots=True)
class _HashFrame:
    kind: str
    first: bool = True
    expecting_value: bool = False


def _logical_sha256(path: Path) -> str:  # noqa: C901, PLR0912, PLR0915
    """Replay canonical JSON hash while omitting only ``output_sha256``."""
    digest = hashlib.sha256()
    frames: list[_HashFrame] = []
    root_seen = False
    root_closed = False
    skip_value = False
    skip_depth = 0

    def before_value() -> None:
        nonlocal root_seen
        if not frames:
            if root_seen:
                raise SpotifyBridgeArtifactError("bridge artifact contains multiple root values")
            root_seen = True
            return
        frame = frames[-1]
        if frame.kind == "array":
            if not frame.first:
                digest.update(b",")
            frame.first = False
            return
        if not frame.expecting_value:
            raise SpotifyBridgeArtifactError("bridge artifact map value is missing its key")
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
                    raise SpotifyBridgeArtifactError("bridge artifact map key is malformed")
                frame = frames[-1]
                if len(frames) == 1 and value == "output_sha256":
                    skip_value = True
                    continue
                if not frame.first:
                    digest.update(b",")
                frame.first = False
                digest.update(canonical_json(value))
                digest.update(b":")
                frame.expecting_value = True
                continue
            if event == "start_map":
                before_value()
                digest.update(b"{")
                frames.append(_HashFrame("map"))
                continue
            if event == "start_array":
                before_value()
                digest.update(b"[")
                frames.append(_HashFrame("array"))
                continue
            if event in {"string", "number", "boolean", "null"}:
                before_value()
                digest.update(canonical_json(value))
                continue
            if event == "end_map":
                if not frames or frames[-1].kind != "map" or frames[-1].expecting_value:
                    raise SpotifyBridgeArtifactError("bridge artifact object is incomplete")
                frames.pop()
                digest.update(b"}")
                if not frames:
                    root_closed = True
                continue
            if event == "end_array":
                if not frames or frames[-1].kind != "array":
                    raise SpotifyBridgeArtifactError("bridge artifact array is incomplete")
                frames.pop()
                digest.update(b"]")
                continue
            raise SpotifyBridgeArtifactError(f"unsupported bridge JSON event: {event}")
    if frames or not root_seen or not root_closed:
        raise SpotifyBridgeArtifactError("bridge artifact root is incomplete")
    return digest.hexdigest()


def _require_expected_sha256(actual: str, expected: str) -> None:
    if actual != expected:
        raise SpotifyBridgeArtifactError("bridge changed while its receipt snapshot was copied")


def _require_unchanged_bridge(path: Path, expected_sha256: str) -> None:
    if sha256_file(path)[0] != expected_sha256:
        raise SpotifyBridgeArtifactError("bridge changed while it was being verified")


def _require_receipt_custody(
    header: SpotifyBridgeArtifactHeader, receipt: SpotifyBridgePublicationReceipt
) -> None:
    if (
        header.output_sha256 != receipt.logical_output_sha256
        or header.source_archive_sha256 != receipt.source_archive_sha256
        or header.historical_database_sha256 != receipt.historical_database_sha256
    ):
        raise SpotifyBridgeArtifactError(
            "bridge content does not match publication receipt custody"
        )


def _snapshot_file(source: Path, expected_sha256: str, *, prefix: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix=prefix, suffix=".json")
    destination = Path(temporary_name)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
            while block := input_stream.read(1_048_576):
                digest.update(block)
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        _require_expected_sha256(digest.hexdigest(), expected_sha256)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    else:
        return destination


def _read_one(path: Path, prefix: str) -> object:
    with path.open("rb") as stream:
        values = ijson.items(stream, prefix, use_float=True)
        try:
            value = next(values)
        except StopIteration as error:
            raise SpotifyBridgeArtifactError(f"bridge artifact lacks {prefix}") from error
        if next(values, None) is not None:
            raise SpotifyBridgeArtifactError(f"bridge artifact repeats {prefix}")
        return value


def _root_fields_and_counts(path: Path) -> tuple[frozenset[str], int, int]:
    fields: set[str] = set()
    row_count = 0
    conflict_count = 0
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream, use_float=True):
            if prefix == "" and event == "map_key":
                if not isinstance(value, str) or value in fields:
                    raise SpotifyBridgeArtifactError("bridge artifact root keys are malformed")
                fields.add(value)
            elif prefix == "rows.item" and event == "start_map":
                row_count += 1
            elif prefix == "conflicts.item" and event == "start_map":
                conflict_count += 1
    return frozenset(fields), row_count, conflict_count


def load_musicbrainz_spotify_bridge(path: Path) -> LoadedSpotifyBridgeArtifact:
    """Load a bridge header, bind lazy rows, and verify logical custody."""
    if not path.is_file():
        raise SpotifyBridgeArtifactError("bridge artifact must be a regular file")
    fields, row_count, conflict_count = _root_fields_and_counts(path)
    if fields != _ROOT_FIELDS:
        raise SpotifyBridgeArtifactError(
            f"bridge root fields mismatch (missing={sorted(_ROOT_FIELDS - fields)}, "
            f"extra={sorted(fields - _ROOT_FIELDS)})"
        )
    values = {
        name: _read_one(path, name)
        for name in _ROOT_FIELDS - {"rows", "conflicts", "settings", "counters"}
    }
    values["settings"] = SpotifyBridgeSettings.model_validate(_read_one(path, "settings"))
    values["counters"] = SpotifyBridgeCounters.model_validate(_read_one(path, "counters"))
    header = SpotifyBridgeArtifactHeader.model_validate(values)
    loaded = LoadedSpotifyBridgeArtifact(
        path=path,
        header=header,
        rows=_StreamingRows(path, "rows", SpotifyBridgeRow, row_count),
        conflicts=_StreamingRows(path, "conflicts", SpotifyBridgeConflict, conflict_count),
    )
    verify_loaded_musicbrainz_spotify_bridge(loaded)
    return loaded


def load_receipted_musicbrainz_spotify_bridge(
    path: Path, receipt_path: Path, expected_receipt_sha256: str
) -> LoadedSpotifyBridgeArtifact:
    """Load only a bridge whose immutable publication receipt binds its bytes."""
    if sha256_file(receipt_path)[0] != expected_receipt_sha256:
        raise SpotifyBridgeArtifactError("bridge receipt bytes do not match declared trust root")
    with receipt_path.open("rb") as stream:
        receipt = SpotifyBridgePublicationReceipt.model_validate_json(stream.read())
    before = sha256_file(path)[0]
    if before != receipt.artifact_sha256 or before != receipt.artifact.sha256:
        raise SpotifyBridgeArtifactError("bridge bytes do not match publication receipt")
    snapshot = _snapshot_file(path, before, prefix="musix-verified-bridge-")
    try:
        artifact = load_musicbrainz_spotify_bridge(snapshot)
        _require_unchanged_bridge(path, before)
        _require_receipt_custody(artifact.header, receipt)
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    return LoadedSpotifyBridgeArtifact(
        path=snapshot,
        header=artifact.header,
        rows=artifact.rows,
        conflicts=artifact.conflicts,
        snapshot_owned=True,
    )


def _verify_header(artifact: LoadedSpotifyBridgeArtifact) -> None:
    header = artifact.header
    if header.settings_sha256 != settings_sha256(header.settings):
        raise SpotifyBridgeArtifactError("bridge settings hash does not replay")
    if _logical_sha256(artifact.path) != header.output_sha256:
        raise SpotifyBridgeArtifactError("bridge output hash does not replay")
    if len(artifact.rows) != header.counters.distinct_claim_count:
        raise SpotifyBridgeArtifactError("bridge row count does not match counters")
    if len(artifact.conflicts) != header.counters.spotify_conflict_count:
        raise SpotifyBridgeArtifactError("bridge conflict count does not match counters")


def _verify_rows_and_conflicts(  # noqa: C901, PLR0912
    artifact: LoadedSpotifyBridgeArtifact,
) -> tuple[int, int]:
    """Use disk-backed conflict membership so bridge verification stays bounded."""
    with tempfile.TemporaryDirectory(prefix="musix-bridge-verify-") as directory:
        database = Path(directory) / "conflicts.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "CREATE TABLE declared_conflicts (spotify_artist_id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            connection.execute(
                """
                CREATE TABLE declared_conflict_mbids (
                    spotify_artist_id TEXT NOT NULL,
                    musicbrainz_artist_id TEXT NOT NULL,
                    PRIMARY KEY (spotify_artist_id, musicbrainz_artist_id)
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                """
                CREATE TABLE declared_conflict_evidence (
                    spotify_artist_id TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    PRIMARY KEY (spotify_artist_id, evidence_ref)
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                """
                CREATE TABLE claims (
                    spotify_artist_id TEXT NOT NULL,
                    musicbrainz_artist_id TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    PRIMARY KEY (spotify_artist_id, musicbrainz_artist_id)
                ) WITHOUT ROWID
                """
            )
            for conflict in artifact.conflicts:
                if conflict.kind != "spotify_id_multiple_musicbrainz_artists":
                    raise SpotifyBridgeArtifactError("unsupported bridge conflict kind")
                if conflict.spotify_artist_ids != (conflict.identity,):
                    raise SpotifyBridgeArtifactError(
                        "bridge conflict must declare exactly its own Spotify identity"
                    )
                if (
                    len(conflict.musicbrainz_artist_ids) < _MIN_CONFLICT_MBIDS
                    or tuple(sorted(set(conflict.musicbrainz_artist_ids)))
                    != conflict.musicbrainz_artist_ids
                    or len(set(conflict.evidence_refs)) != len(conflict.evidence_refs)
                ):
                    raise SpotifyBridgeArtifactError("bridge conflict declaration is not canonical")
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO declared_conflicts VALUES (?)", (conflict.identity,)
                ).rowcount
                if inserted != 1:
                    raise SpotifyBridgeArtifactError(
                        "bridge declares the same conflict more than once"
                    )
                connection.executemany(
                    "INSERT INTO declared_conflict_mbids VALUES (?, ?)",
                    ((conflict.identity, mbid) for mbid in conflict.musicbrainz_artist_ids),
                )
                connection.executemany(
                    "INSERT INTO declared_conflict_evidence VALUES (?, ?)",
                    ((conflict.identity, evidence) for evidence in conflict.evidence_refs),
                )
            previous: tuple[str, str] | None = None
            for row in artifact.rows:
                key = (row.musicbrainz_artist_id, row.spotify_artist_id)
                if previous is not None and key <= previous:
                    raise SpotifyBridgeArtifactError(
                        "bridge rows are not uniquely canonically sorted"
                    )
                previous = key
                if row.relation_url != f"https://open.spotify.com/artist/{row.spotify_artist_id}":
                    raise SpotifyBridgeArtifactError(
                        "bridge relation URL does not bind its declared Spotify identity"
                    )
                connection.execute(
                    "INSERT INTO claims VALUES (?, ?, ?, ?)",
                    (
                        row.spotify_artist_id,
                        row.musicbrainz_artist_id,
                        row.evidence_ref,
                        row.disposition,
                    ),
                )
            accepted = conflicts = 0
            groups = connection.execute(
                """
                SELECT spotify_artist_id, count(*), min(disposition), max(disposition)
                  FROM claims
                 GROUP BY spotify_artist_id
                 ORDER BY spotify_artist_id
                """
            )
            for spotify_id, claim_count, low_disposition, high_disposition in groups:
                declared = connection.execute(
                    "SELECT 1 FROM declared_conflicts WHERE spotify_artist_id = ?",
                    (spotify_id,),
                ).fetchone()
                if int(claim_count) == 1:
                    if declared is not None or low_disposition != "accepted":
                        raise SpotifyBridgeArtifactError(
                            "single bridge identity must be accepted with no conflict declaration"
                        )
                    accepted += 1
                    continue
                if (
                    declared is None
                    or low_disposition != "conflict"
                    or high_disposition != "conflict"
                ):
                    raise SpotifyBridgeArtifactError(
                        "ambiguous bridge identity must have an exact all-conflict declaration"
                    )
                actual_mbids = tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT musicbrainz_artist_id FROM claims
                         WHERE spotify_artist_id = ?
                         ORDER BY musicbrainz_artist_id
                        """,
                        (spotify_id,),
                    )
                )
                declared_mbids = tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT musicbrainz_artist_id FROM declared_conflict_mbids
                         WHERE spotify_artist_id = ?
                         ORDER BY musicbrainz_artist_id
                        """,
                        (spotify_id,),
                    )
                )
                actual_evidence = tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT evidence_ref FROM claims
                         WHERE spotify_artist_id = ?
                         ORDER BY evidence_ref
                        """,
                        (spotify_id,),
                    )
                )
                declared_evidence = tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT evidence_ref FROM declared_conflict_evidence
                         WHERE spotify_artist_id = ?
                         ORDER BY evidence_ref
                        """,
                        (spotify_id,),
                    )
                )
                if actual_mbids != declared_mbids or actual_evidence != declared_evidence:
                    raise SpotifyBridgeArtifactError(
                        "bridge conflict declaration does not match rows"
                    )
                conflicts += int(claim_count)
            orphan = connection.execute(
                """
                SELECT 1 FROM declared_conflicts AS conflict
                 WHERE NOT EXISTS (
                     SELECT 1 FROM claims
                      WHERE claims.spotify_artist_id = conflict.spotify_artist_id
                 )
                """
            ).fetchone()
            if orphan is not None:
                raise SpotifyBridgeArtifactError("bridge declares a conflict without claim rows")
    return accepted, conflicts


def verify_loaded_musicbrainz_spotify_bridge(artifact: LoadedSpotifyBridgeArtifact) -> None:
    """Verify streaming hash, strict rows, sorting, and conflict dispositions."""
    _verify_header(artifact)
    accepted, conflicts = _verify_rows_and_conflicts(artifact)
    header = artifact.header
    if accepted != header.counters.accepted_bridge_count:
        raise SpotifyBridgeArtifactError("bridge accepted count does not match counters")
    if conflicts != header.counters.conflict_claim_count:
        raise SpotifyBridgeArtifactError("bridge conflict count does not match counters")


def iter_accepted_spotify_to_musicbrainz(
    artifact: LoadedSpotifyBridgeArtifact,
) -> Iterator[tuple[str, str]]:
    """Yield unambiguous ``(Spotify ID, MusicBrainz ID)`` identity pairs only."""
    for row in artifact.rows:
        if row.disposition == "accepted":
            yield row.spotify_artist_id, row.musicbrainz_artist_id
