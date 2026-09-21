"""Read-only, hash-pinned Phase 3 v3 semantic comparison.

The contract is deliberately independent of the historical comparison report.
It compares normalized JSON tuples, not database primary keys, model output
hashes, timings, or one-hop evidence-reference strings.  See the accompanying
contract document for every tuple field and ordering rule.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_MAX_ROWS: Final = 50_000
_ProjectionKind = Literal["model", "database"]


class Phase3V3SemanticComparisonError(ValueError):
    """A pinned input or the explicit semantic-comparison contract is invalid."""


class _TupleModel(BaseModel):
    """Parse the comparison boundary once and discard irrelevant model fields."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class _Artifact(_TupleModel):
    source: str
    snapshot: str
    artifact_key: str
    content_sha256: str
    export_allowed: bool


class _Genre(_TupleModel):
    genre_id: str
    name: str


class _Component(_TupleModel):
    component_kind: str
    raw_value: float
    normalized_value: float


class _Membership(_TupleModel):
    artist_id: str
    score: float
    components: tuple[_Component, ...]


class _Profile(_TupleModel):
    genre_id: str
    profile_kind: str
    memberships: tuple[_Membership, ...]


class _Neighbor(_TupleModel):
    genre_id: str
    neighbor_genre_id: str
    profile_kind: str
    metric: str
    score: float
    shared_artist_count: int
    rank: int


class _Representative(_TupleModel):
    genre_id: str
    entity_kind: str
    entity_id: str
    name: str
    rank: int
    direct_evidence_value: float
    source_count: int


class _Coordinate(_TupleModel):
    genre_id: str
    x: float
    y: float
    component: int


class _Unplaced(_TupleModel):
    genre_id: str
    reason: str


class _Layout(_TupleModel):
    layout_key: str
    is_default: bool
    method: str
    method_version: str
    input_kind: str
    metric: str
    seed: int
    coordinates: tuple[_Coordinate, ...]
    unplaced: tuple[_Unplaced, ...]


class _ModelDocument(_TupleModel):
    input_sha256: str
    settings_sha256: str
    output_sha256: str
    artifacts: tuple[_Artifact, ...]
    genres: tuple[_Genre, ...]
    profiles: tuple[_Profile, ...]
    neighbors: tuple[_Neighbor, ...]
    representatives: tuple[_Representative, ...]
    layouts: tuple[_Layout, ...]


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    """One independently normalized semantic projection."""

    name: str
    kind: _ProjectionKind
    v3_rows: int
    sealed_rows: int
    v3_sha256: str
    sealed_sha256: str
    v3_only_rows: int
    sealed_only_rows: int

    @property
    def equal(self) -> bool:
        """Whether the normalized rows are exactly equal."""
        return self.v3_rows == self.sealed_rows and self.v3_sha256 == self.sealed_sha256


@dataclass(frozen=True, slots=True)
class Phase3V3SemanticComparison:
    """Hash-bound equality evidence for the four immutable Phase 3 inputs."""

    v3_model_path: str
    v3_model_sha256: str
    sealed_model_path: str
    sealed_model_sha256: str
    v3_database_path: str
    v3_database_sha256: str
    sealed_database_path: str
    sealed_database_sha256: str
    maximum_rows_per_projection: int
    projections: tuple[SemanticProjection, ...]

    @property
    def equal(self) -> bool:
        """Whether every specified projection agrees."""
        return all(projection.equal for projection in self.projections)

    def to_json(self) -> str:
        """Return a deterministic, human-readable comparison report."""
        return (
            json.dumps(
                {
                    **asdict(self),
                    "equal": self.equal,
                    "projections": [
                        {**asdict(item), "equal": item.equal} for item in self.projections
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


@dataclass(frozen=True, slots=True)
class Phase3V3SemanticInputs:
    """The four paths and byte pins required before a comparison can start."""

    v3_model: Path
    sealed_model: Path
    v3_database: Path
    sealed_database: Path
    expected_v3_model_sha256: str
    expected_sealed_model_sha256: str
    expected_v3_database_sha256: str
    expected_sealed_database_sha256: str


def compare_phase3_v3_semantics(
    inputs: Phase3V3SemanticInputs,
    *,
    maximum_rows_per_projection: int = _MAX_ROWS,
) -> Phase3V3SemanticComparison:
    """Compare the fully specified source-neutral semantic projections.

    All four byte pins are checked before parsing either model or opening either
    SQLite input.  SQLite files are opened through immutable, read-only URIs.
    The sealed artifacts only supply comparison values; no result is persisted.
    """
    if maximum_rows_per_projection < 1:
        raise Phase3V3SemanticComparisonError("maximum_rows_per_projection must be positive")
    v3_model_hash = _verify_file_hash(inputs.v3_model, inputs.expected_v3_model_sha256)
    sealed_model_hash = _verify_file_hash(inputs.sealed_model, inputs.expected_sealed_model_sha256)
    v3_database_hash = _verify_file_hash(inputs.v3_database, inputs.expected_v3_database_sha256)
    sealed_database_hash = _verify_file_hash(
        inputs.sealed_database, inputs.expected_sealed_database_sha256
    )
    v3_payload = _load_model(inputs.v3_model)
    sealed_payload = _load_model(inputs.sealed_model)
    model_projections = _model_projections(v3_payload, sealed_payload, maximum_rows_per_projection)
    with (
        closing(_readonly_connection(inputs.v3_database)) as v3_connection,
        closing(_readonly_connection(inputs.sealed_database)) as sealed_connection,
    ):
        database_projections = _database_projections(
            v3_connection,
            sealed_connection,
            v3_payload,
            sealed_payload,
            maximum_rows_per_projection,
        )
    return Phase3V3SemanticComparison(
        v3_model_path=str(inputs.v3_model),
        v3_model_sha256=v3_model_hash,
        sealed_model_path=str(inputs.sealed_model),
        sealed_model_sha256=sealed_model_hash,
        v3_database_path=str(inputs.v3_database),
        v3_database_sha256=v3_database_hash,
        sealed_database_path=str(inputs.sealed_database),
        sealed_database_sha256=sealed_database_hash,
        maximum_rows_per_projection=maximum_rows_per_projection,
        projections=(*model_projections, *database_projections),
    )


def _model_projections(
    v3: _ModelDocument, sealed: _ModelDocument, maximum: int
) -> tuple[SemanticProjection, ...]:
    return (
        _compare_rows(
            "source_artifact_identities",
            "model",
            _source_artifact_rows(v3, maximum),
            _source_artifact_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "genre_universe",
            "model",
            _genre_rows(v3, maximum),
            _genre_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "direct_memberships",
            "model",
            _membership_rows(v3, "direct", maximum),
            _membership_rows(sealed, "direct", maximum),
            maximum,
        ),
        _compare_rows(
            "one_hop_memberships",
            "model",
            _membership_rows(v3, "one_hop", maximum),
            _membership_rows(sealed, "one_hop", maximum),
            maximum,
        ),
        _compare_rows(
            "neighbors",
            "model",
            _neighbor_rows(v3, maximum),
            _neighbor_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "representatives",
            "model",
            _representative_rows(v3, maximum),
            _representative_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "layout_coordinates",
            "model",
            _coordinate_rows(v3, maximum),
            _coordinate_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "layouts_and_unplaced",
            "model",
            _layout_rows(v3, maximum),
            _layout_rows(sealed, maximum),
            maximum,
        ),
    )


def _database_projections(
    v3: sqlite3.Connection,
    sealed: sqlite3.Connection,
    v3_model: _ModelDocument,
    sealed_model: _ModelDocument,
    maximum: int,
) -> tuple[SemanticProjection, ...]:
    return (
        _compare_rows(
            "colisten_raw_windows",
            "database",
            _raw_window_rows(v3, maximum),
            _raw_window_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "artist_pair_supports_and_windows",
            "database",
            _artist_pair_rows(v3, maximum),
            _artist_pair_rows(sealed, maximum),
            maximum,
        ),
        _compare_rows(
            "normalized_provenance_bindings",
            "database",
            _provenance_rows(v3, v3_model, maximum),
            _provenance_rows(sealed, sealed_model, maximum),
            maximum,
        ),
    )


def _source_artifact_rows(model: _ModelDocument, maximum: int) -> list[tuple[object, ...]]:
    return _bounded_sorted(
        "source_artifact_identities",
        (
            (
                item.source,
                item.snapshot,
                item.artifact_key,
                item.content_sha256,
                item.export_allowed,
            )
            for item in model.artifacts
        ),
        maximum,
    )


def _genre_rows(model: _ModelDocument, maximum: int) -> list[tuple[object, ...]]:
    return _bounded_sorted(
        "genre_universe", ((item.genre_id, item.name) for item in model.genres), maximum
    )


def _membership_rows(
    model: _ModelDocument, profile_kind: str, maximum: int
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for profile in model.profiles:
        if profile.profile_kind != profile_kind:
            continue
        for membership in profile.memberships:
            components = tuple(
                sorted(
                    (component.component_kind, component.raw_value, component.normalized_value)
                    for component in membership.components
                )
            )
            rows.append((profile.genre_id, membership.artist_id, membership.score, components))
            _require_bound(f"{profile_kind}_memberships", rows, maximum)
    return sorted(rows)


def _neighbor_rows(model: _ModelDocument, maximum: int) -> list[tuple[object, ...]]:
    return _bounded_sorted(
        "neighbors",
        (
            (
                item.genre_id,
                item.neighbor_genre_id,
                item.profile_kind,
                item.metric,
                item.score,
                item.shared_artist_count,
                item.rank,
            )
            for item in model.neighbors
        ),
        maximum,
    )


def _representative_rows(model: _ModelDocument, maximum: int) -> list[tuple[object, ...]]:
    return _bounded_sorted(
        "representatives",
        (
            (
                item.genre_id,
                item.entity_kind,
                item.entity_id,
                item.name,
                item.rank,
                item.direct_evidence_value,
                item.source_count,
            )
            for item in model.representatives
        ),
        maximum,
    )


def _coordinate_rows(model: _ModelDocument, maximum: int) -> list[tuple[object, ...]]:
    return _bounded_sorted(
        "layout_coordinates",
        (
            (
                layout.layout_key,
                coordinate.genre_id,
                coordinate.x,
                coordinate.y,
                coordinate.component,
            )
            for layout in model.layouts
            for coordinate in layout.coordinates
        ),
        maximum,
    )


def _layout_rows(model: _ModelDocument, maximum: int) -> list[tuple[object, ...]]:
    return _bounded_sorted(
        "layouts_and_unplaced",
        (
            (
                layout.layout_key,
                layout.is_default,
                layout.method,
                layout.method_version,
                layout.input_kind,
                layout.metric,
                layout.seed,
                tuple(sorted((item.genre_id, item.reason) for item in layout.unplaced)),
            )
            for layout in model.layouts
        ),
        maximum,
    )


def _raw_window_rows(
    connection: sqlite3.Connection, maximum: int = _MAX_ROWS
) -> list[tuple[object, ...]]:
    return _query_rows(
        connection,
        maximum,
        """SELECT left_artist_source_id, right_artist_source_id, window_start, window_end,
                  distinct_user_count FROM normalizable_artist_co_listen_evidence
           ORDER BY left_artist_source_id, right_artist_source_id, window_start, window_end,
                    distinct_user_count""",
    )


def _artist_pair_rows(
    connection: sqlite3.Connection, maximum: int = _MAX_ROWS
) -> list[tuple[object, ...]]:
    return _query_rows(
        connection,
        maximum,
        """SELECT left_artist_source_id, right_artist_source_id, sum(distinct_user_count), count(*)
           FROM normalizable_artist_co_listen_evidence
           GROUP BY left_artist_source_id, right_artist_source_id
           ORDER BY left_artist_source_id, right_artist_source_id""",
    )


def _provenance_rows(
    connection: sqlite3.Connection, model: _ModelDocument, maximum: int = _MAX_ROWS
) -> list[tuple[object, ...]]:
    _require_model_run_binding(connection, model)
    return _query_rows(
        connection,
        maximum,
        """SELECT source.source_key, provenance.snapshot_ref, provenance.artifact_sha256,
                  provenance.record_fingerprint, provenance.parser_release_ref, artifact.sha256
           FROM public_model_input_provenance AS binding
           JOIN public_model_runs AS model ON model.id = binding.model_run_id
           JOIN provenance_records AS provenance ON provenance.id = binding.provenance_id
           JOIN data_sources AS source ON source.id = provenance.source_id
           JOIN source_artifacts AS artifact ON artifact.id = binding.artifact_id
           WHERE model.output_sha256 = ?
             AND model.input_sha256 = ?
             AND model.settings_sha256 = ?
           ORDER BY source.source_key, provenance.snapshot_ref, provenance.artifact_sha256,
                    provenance.record_fingerprint, provenance.parser_release_ref,
                    artifact.sha256""",
        (model.output_sha256, model.input_sha256, model.settings_sha256),
    )


def _require_model_run_binding(connection: sqlite3.Connection, model: _ModelDocument) -> None:
    """Require the database run used for provenance to bind all model hashes."""
    row = connection.execute(
        """SELECT id FROM public_model_runs
           WHERE output_sha256 = ? AND input_sha256 = ? AND settings_sha256 = ?""",
        (model.output_sha256, model.input_sha256, model.settings_sha256),
    ).fetchone()
    if row is None:
        raise Phase3V3SemanticComparisonError(
            "SQLite model run does not bind the model output, input, and settings hashes"
        )


def _compare_rows(
    name: str,
    kind: _ProjectionKind,
    v3: list[tuple[object, ...]],
    sealed: list[tuple[object, ...]],
    maximum: int,
) -> SemanticProjection:
    _require_bound(name, v3, maximum)
    _require_bound(name, sealed, maximum)
    v3_counter = Counter(v3)
    sealed_counter = Counter(sealed)
    return SemanticProjection(
        name,
        kind,
        len(v3),
        len(sealed),
        _rows_sha256(v3),
        _rows_sha256(sealed),
        sum((v3_counter - sealed_counter).values()),
        sum((sealed_counter - v3_counter).values()),
    )


def _require_bound(name: str, rows: list[tuple[object, ...]], maximum: int) -> None:
    if len(rows) > maximum:
        raise Phase3V3SemanticComparisonError(f"projection {name} exceeds bounded limit {maximum}")


def _bounded_sorted(
    name: str, values: Iterable[tuple[object, ...]], maximum: int
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for value in values:
        rows.append(value)
        _require_bound(name, rows, maximum)
    return sorted(rows)


def _query_rows(
    connection: sqlite3.Connection,
    maximum: int,
    query: str,
    parameters: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    cursor = connection.execute(query, parameters)
    rows: list[tuple[object, ...]] = []
    for _ in range(maximum + 1):
        row = cursor.fetchone()
        if row is None:
            return rows
        if len(rows) == maximum:
            raise Phase3V3SemanticComparisonError(
                f"database projection exceeds bounded limit {maximum}"
            )
        rows.append(tuple(row))
    raise AssertionError("bounded database cursor loop did not terminate")


def _rows_sha256(rows: list[tuple[object, ...]]) -> str:
    return hashlib.sha256(
        json.dumps(
            rows, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def _load_model(path: Path) -> _ModelDocument:
    try:
        return _ModelDocument.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise Phase3V3SemanticComparisonError(f"cannot parse model {path}") from error


def _verify_file_hash(path: Path, expected: str) -> str:
    actual = _sha256_file(path)
    if actual != expected:
        raise Phase3V3SemanticComparisonError(f"SHA-256 mismatch for {path}")
    return actual


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1_048_576):
                digest.update(chunk)
    except OSError as error:
        raise Phase3V3SemanticComparisonError(f"cannot read {path}") from error
    return digest.hexdigest()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()))}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection
