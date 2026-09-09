"""Custody the qualified public release and its reproducibility evidence."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.ml.public_model_gate import PublicModelGateReport
from musix.models import FrozenModel
from musix.pipeline.public_release import PublicReleaseResult
from musix.pipeline.release_manifest import verify_manifest_against_database
from musix.serving.artist_membership_evaluation import ArtistMembershipEvaluationReport
from musix.serving.metadata.representatives import MetadataRepresentativeArtifact
from musix.storage import LocalObjectStore, ObjectKey, ObjectStore

if TYPE_CHECKING:
    from collections.abc import Iterator

from musix.types import Sha256  # noqa: TC001

_CHUNK_BYTES: Final = 1024 * 1024
_RELEASE_SCHEMA_VERSION: Final = 10
_EXPECTED_CACHE_BYTES: Final = 153_231_360
_EXPECTED_INPUT_ARTIFACTS: Final = 62
_EXPECTED_REPRESENTATIVE_ITEMS: Final = 3_344
_EXPECTED_PROFILE_MEMBERSHIPS: Final = 26_525
_EXPECTED_NEIGHBOR_ROWS: Final = 34_348
_EXPECTED_DATABASE_COUNTS: Final[dict[str, int]] = {
    "data_sources": 62,
    "source_snapshots": 62,
    "source_artifacts": 62,
    "ingest_attempts": 62,
    "staged_records": 37_011,
    "parser_releases": 2,
}
_EVIDENCE_FILES: Final[tuple[tuple[str, str], ...]] = (
    ("public-model", "public-model.json"),
    ("production-map", "production-map-v1.json"),
    ("production-map-acceptance", "production-map-v1.acceptance.json"),
    ("production-map-seed-report", "production-map-v1.seed-report.json"),
    ("production-map-browser", "production-map-v1.browser.json"),
    ("production-map-report", "production-map-v1.report.json"),
    ("release-receipt", "receipt.json"),
)
_OBJECTIVE_EVIDENCE_FILES: Final[tuple[tuple[str, str], ...]] = (
    ("public-model-gate", "public-model-gate-v1.json"),
    ("metadata-representatives", "metadata-representatives-v1.json"),
)
_OPTIONAL_ARTIST_MEMBERSHIP_EVIDENCE_FILES: Final[tuple[tuple[str, str], ...]] = (
    ("artist-membership-evaluation", "artist-membership-evaluation-v1.json"),
    ("artist-membership-judgments", "artist-membership-judgments-v1.json"),
)

_ALLOWED_ADDITIONAL_EVIDENCE_FILES: Final[dict[str, str]] = {
    "musicbrainz-core-metadata-hydration": "musicbrainz-release-tracks.json",
    "musicbrainz-core-metadata-hydration-report": "musicbrainz-release-tracks.report.json",
    "representative-catalog-candidates": "representative-candidates-v1.json",
    "representative-catalog-candidates-report": "representative-candidates-v1.report.json",
    "open-construction-graph": "open-construction-graph-v1.json",
    "open-construction-graph-gate": "open-construction-graph-v1.gate.json",
    "open-construction-graph-receipt": "open-construction-graph-v1.receipt.json",
    "phase4-api-source-qa": "phase4-api-source-qa.json",
    "phase4-integration-report": "phase4-integration-report.json",
}


class PublicReleaseCustodyError(ValueError):
    """Report a release boundary that cannot be sealed for rebuild."""


class CustodyObject(FrozenModel):
    """One immutable object written to the custody store."""

    key: ObjectKey
    sha256: Sha256
    byte_size: int = Field(ge=0)


class SourceCustody(CustodyObject):
    """One manifest-bound raw source retained through a streamed copy."""

    source_key: str = Field(min_length=1, max_length=300)
    recorded_vault_key: Sha256
    storage_mode: Literal["copy", "reference"]


class MissingSource(FrozenModel):
    """One manifest-bound source that was absent from the inspected local vault."""

    source_key: str = Field(min_length=1, max_length=300)
    artifact_sha256: Sha256
    expected_path: str = Field(min_length=1, max_length=2_000)
    byte_size: int = Field(ge=0)


class DatabaseCounts(FrozenModel):
    """Counts checked in the immutable qualified cache."""

    data_sources: int = Field(ge=0)
    source_snapshots: int = Field(ge=0)
    source_artifacts: int = Field(ge=0)
    ingest_attempts: int = Field(ge=0)
    staged_records: int = Field(ge=0)
    parser_releases: int = Field(ge=0)


class EvidenceBinding(CustodyObject):
    """One release or browser evidence file bound by its content hash."""

    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=2_000)


class PublicReleaseCustodyReceipt(FrozenModel):
    """Atomic receipt for a cache-backed, source-aware public release custody run."""

    revision: Literal["public-release-custody-v1"] = "public-release-custody-v1"
    release_id: str = Field(min_length=1, max_length=300)
    cache: CustodyObject
    cache_declared_byte_size: int = Field(gt=0)
    cache_integrity: Literal["ok"] = "ok"
    database_counts: DatabaseCounts
    expected_database_counts: DatabaseCounts
    source_objects_expected: int = Field(gt=0)
    source_objects_custodied: int = Field(ge=0)
    source_objects: tuple[SourceCustody, ...] = Field(max_length=64)
    source_objects_missing: tuple[MissingSource, ...] = Field(max_length=64)
    source_completeness: Literal["complete", "cache_only"]
    source_vault: str = Field(min_length=1, max_length=2_000)
    source_storage_mode: Literal["copy", "reference"]
    evidence: tuple[EvidenceBinding, ...] = Field(min_length=1, max_length=24)
    objective_gate_state: Literal["present", "absent"]
    objective_gate_evidence: tuple[EvidenceBinding, ...] = Field(max_length=4)
    public_model_gate_sha256: Sha256 | None = None
    metadata_representatives_sha256: Sha256 | None = None
    artist_membership_evaluation_sha256: Sha256 | None = None
    artist_membership_judgments_sha256: Sha256 | None = None
    model_logical_sha256: Sha256
    model_file_sha256: Sha256
    production_map_sha256: Sha256
    browser_evidence_sha256: Sha256
    representative_items: int = Field(ge=0)
    profile_memberships: int = Field(ge=0)
    neighbor_rows: int = Field(ge=0)
    rebuild_command: tuple[str, ...] = Field(min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=200)
    code_revision: str = Field(min_length=1, max_length=200)
    created_at: str = Field(min_length=1, max_length=100)


class PublicReleaseCustodySettings(FrozenModel):
    """Paths for one offline public-release custody operation."""

    release_directory: Path
    cache_database: Path
    source_vault: Path
    evidence_directory: Path
    output_directory: Path
    objective_gates_directory: Path | None = None
    additional_evidence_files: tuple[tuple[str, str], ...] = ()
    source_mode: Literal["copy", "reference"] = "copy"
    expected_cache_sha256: Sha256
    expected_cache_byte_size: int = Field(gt=0)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _atomic_write(path: Path, payload: bytes) -> None:
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


def _code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _load_release_receipt(path: Path) -> PublicReleaseResult:
    try:
        return PublicReleaseResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PublicReleaseCustodyError("release receipt is missing or malformed") from error


def _source_rows(database: Path) -> Iterator[tuple[str, str, int, str]]:
    absolute = database.resolve(strict=True)
    with closing(
        sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        rows = connection.execute(
            """SELECT source.source_key, artifact.sha256, artifact.byte_size, artifact.vault_key
               FROM source_artifacts AS artifact
               JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
               JOIN data_sources AS source ON source.id = snapshot.source_id
               ORDER BY source.source_key"""
        )
        yield from (
            (str(source), str(sha256), int(size), str(vault_key))
            for source, sha256, size, vault_key in rows
        )


def _database_counts(database: Path) -> DatabaseCounts:
    absolute = database.resolve(strict=True)
    queries = (
        ("data_sources", "SELECT count(*) FROM data_sources"),
        ("source_snapshots", "SELECT count(*) FROM source_snapshots"),
        ("source_artifacts", "SELECT count(*) FROM source_artifacts"),
        ("ingest_attempts", "SELECT count(*) FROM ingest_attempts"),
        ("staged_records", "SELECT count(*) FROM staged_records"),
        ("parser_releases", "SELECT count(*) FROM parser_releases"),
    )
    with closing(
        sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        values = {name: int(connection.execute(query).fetchone()[0]) for name, query in queries}
    return DatabaseCounts.model_validate(values)


def _verify_cache(settings: PublicReleaseCustodySettings) -> tuple[str, int, DatabaseCounts]:
    cache_sha256, cache_size = _hash_file(settings.cache_database)
    if (cache_sha256, cache_size) != (
        settings.expected_cache_sha256,
        settings.expected_cache_byte_size,
    ):
        raise PublicReleaseCustodyError(
            "qualified cache hash or byte size is not the declared boundary"
        )
    try:
        with closing(
            sqlite3.connect(
                f"file:{settings.cache_database.resolve(strict=True).as_posix()}?mode=ro&immutable=1",
                uri=True,
            )
        ) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            schema = connection.execute("PRAGMA user_version").fetchone()
    except (OSError, sqlite3.Error) as error:
        raise PublicReleaseCustodyError("qualified cache cannot be opened read-only") from error
    if integrity is None or integrity[0] != "ok":
        raise PublicReleaseCustodyError("qualified cache integrity check failed")
    if schema is None or int(schema[0]) != _RELEASE_SCHEMA_VERSION:
        raise PublicReleaseCustodyError("qualified cache schema does not match the release")
    try:
        manifest = verify_manifest_against_database(
            settings.release_directory, settings.cache_database
        )
    except ValueError as error:
        raise PublicReleaseCustodyError(
            "qualified cache does not match the release manifest"
        ) from error
    if int(manifest["input_artifacts"]) != _EXPECTED_INPUT_ARTIFACTS:
        raise PublicReleaseCustodyError("qualified cache does not contain 62 source artifacts")
    counts = _database_counts(settings.cache_database)
    expected = DatabaseCounts.model_validate(_EXPECTED_DATABASE_COUNTS)
    if counts != expected:
        raise PublicReleaseCustodyError(
            f"qualified cache table counts differ: observed={counts.model_dump()}"
        )
    return cache_sha256, cache_size, counts


def _object(key: ObjectKey, sha256: str, byte_size: int) -> CustodyObject:
    return CustodyObject(key=key, sha256=sha256, byte_size=byte_size)


def _push_verified(
    store: ObjectStore, path: Path, key: ObjectKey, expected_sha256: str, expected_size: int
) -> CustodyObject:
    result = store.push(path, key)
    if (result.sha256, result.byte_size) != (expected_sha256, expected_size):
        raise PublicReleaseCustodyError(f"object store changed verified bytes for {path}")
    return _object(key, result.sha256, result.byte_size)


def _evidence_bindings(
    store: ObjectStore,
    evidence_directory: Path,
    release_receipt: PublicReleaseResult,
    files: tuple[tuple[str, str], ...],
) -> tuple[EvidenceBinding, ...]:
    names = tuple(name for name, _ in files)
    filenames = tuple(filename for _, filename in files)
    if len(set(names)) != len(names) or len(set(filenames)) != len(filenames):
        raise PublicReleaseCustodyError("release evidence names and filenames must be unique")
    bindings: list[EvidenceBinding] = []
    for name, filename in files:
        path = evidence_directory / filename
        if not path.is_file():
            raise PublicReleaseCustodyError(f"release evidence is missing: {path}")
        sha256, byte_size = _hash_file(path)
        if name == "public-model" and sha256 != release_receipt.model_file_sha256:
            raise PublicReleaseCustodyError(
                "public model evidence does not match its release receipt"
            )
        key = ObjectKey(value=f"evidence/{name}/{sha256}.json")
        stored = _push_verified(store, path, key, sha256, byte_size)
        bindings.append(EvidenceBinding(**stored.model_dump(), name=name, path=str(path.resolve())))
    return tuple(bindings)


def _validate_additional_evidence(files: tuple[tuple[str, str], ...]) -> None:
    """Accept only named public-release evidence with a fixed in-directory filename."""
    if len(set(files)) != len(files):
        raise PublicReleaseCustodyError("additional release evidence entries must be unique")
    for name, filename in files:
        if _ALLOWED_ADDITIONAL_EVIDENCE_FILES.get(name) != filename:
            raise PublicReleaseCustodyError(
                f"additional release evidence is not an allowlisted semantic artifact: {name}"
            )
        if Path(filename).name != filename:
            raise PublicReleaseCustodyError(
                "additional release evidence must stay in its directory"
            )


def _objective_evidence_files(
    settings: PublicReleaseCustodySettings,
) -> tuple[tuple[str, str], ...]:
    """Require base gates together and artist calibration report/source as an optional pair."""
    directory = settings.objective_gates_directory
    if directory is None:
        return ()
    paths = tuple(directory / filename for _, filename in _OBJECTIVE_EVIDENCE_FILES)
    present = tuple(path.is_file() for path in paths)
    artist_paths = tuple(
        directory / filename for _, filename in _OPTIONAL_ARTIST_MEMBERSHIP_EVIDENCE_FILES
    )
    artist_present = tuple(path.is_file() for path in artist_paths)
    if any(present) and not all(present):
        missing = ", ".join(
            str(path) for path, exists in zip(paths, present, strict=True) if not exists
        )
        raise PublicReleaseCustodyError(f"objective release evidence is incomplete: {missing}")
    if any(artist_present) and not all(artist_present):
        missing = ", ".join(
            str(path)
            for path, exists in zip(artist_paths, artist_present, strict=True)
            if not exists
        )
        raise PublicReleaseCustodyError(
            f"artist membership evaluation evidence is incomplete: {missing}"
        )
    if any(artist_present) and not all(present):
        raise PublicReleaseCustodyError(
            "artist membership evaluation requires the base objective release evidence"
        )
    if not all(present):
        return ()
    return (
        (*_OBJECTIVE_EVIDENCE_FILES, *_OPTIONAL_ARTIST_MEMBERSHIP_EVIDENCE_FILES)
        if all(artist_present)
        else _OBJECTIVE_EVIDENCE_FILES
    )


def _verify_objective_evidence(  # noqa: C901, PLR0912
    paths: tuple[tuple[str, Path], ...], release_receipt: PublicReleaseResult
) -> None:
    """Parse objective reports and bind them to the same public model release."""
    for name, path in paths:
        try:
            if name == "public-model-gate":
                report = PublicModelGateReport.model_validate_json(path.read_text(encoding="utf-8"))
                if not report.passed:
                    raise PublicReleaseCustodyError("public model objective gate did not pass")
                if (
                    report.artifact_file_sha256 != release_receipt.model_file_sha256
                    or report.artifact_output_sha256 != release_receipt.model_logical_sha256
                ):
                    raise PublicReleaseCustodyError(
                        "public model objective gate targets another model"
                    )
            elif name == "metadata-representatives":
                artifact = MetadataRepresentativeArtifact.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                if artifact.run.output_sha256 != release_receipt.model_logical_sha256:
                    raise PublicReleaseCustodyError(
                        "metadata representatives objective gate targets another model"
                    )
            elif name == "artist-membership-evaluation":
                report = ArtistMembershipEvaluationReport.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                if not report.passed or not report.stability.exact_replay:
                    raise PublicReleaseCustodyError(
                        "artist membership evaluation gate did not pass"
                    )
                if (
                    report.model_file_sha256 != release_receipt.model_file_sha256
                    or report.model_output_sha256 != release_receipt.model_logical_sha256
                ):
                    raise PublicReleaseCustodyError(
                        "artist membership evaluation targets another model"
                    )
            elif name == "artist-membership-judgments":
                judgment_sha256 = _hash_file(path)[0]
                evaluation_path = path.parent / "artist-membership-evaluation-v1.json"
                report = ArtistMembershipEvaluationReport.model_validate_json(
                    evaluation_path.read_text(encoding="utf-8")
                )
                if judgment_sha256 != report.judgment_file_sha256:
                    raise PublicReleaseCustodyError(
                        "artist membership evaluation does not bind its judgment bytes"
                    )
        except (OSError, ValueError) as error:
            if isinstance(error, PublicReleaseCustodyError):
                raise
            raise PublicReleaseCustodyError(f"invalid {name} objective evidence") from error


def custody_public_release(
    settings: PublicReleaseCustodySettings,
    *,
    store: ObjectStore | None = None,
    rebuild_command: tuple[str, ...] | None = None,
    code_revision: str | None = None,
) -> PublicReleaseCustodyReceipt:
    """Verify and custody the cache, manifest sources, and release evidence atomically."""
    _validate_additional_evidence(settings.additional_evidence_files)
    cache_sha256, cache_size, counts = _verify_cache(settings)
    receipt_path = settings.evidence_directory / "receipt.json"
    release_receipt = _load_release_receipt(receipt_path)
    if release_receipt.cache_sha256 != cache_sha256:
        raise PublicReleaseCustodyError(
            "release receipt cache hash differs from the qualified cache"
        )
    if (
        release_receipt.input_artifacts,
        release_receipt.representative_items,
        release_receipt.profile_memberships,
        release_receipt.neighbor_rows,
    ) != (
        _EXPECTED_INPUT_ARTIFACTS,
        _EXPECTED_REPRESENTATIVE_ITEMS,
        _EXPECTED_PROFILE_MEMBERSHIPS,
        _EXPECTED_NEIGHBOR_ROWS,
    ):
        raise PublicReleaseCustodyError("release receipt counts do not match the qualified release")
    object_store = store or LocalObjectStore(settings.output_directory / "objects")
    cache_key = ObjectKey(value=f"cache/sha256/{cache_sha256}.sqlite")
    cache_object = _push_verified(
        object_store, settings.cache_database, cache_key, cache_sha256, cache_size
    )

    source_objects: list[SourceCustody] = []
    missing_sources: list[MissingSource] = []
    for source_key, artifact_sha256, byte_size, recorded_vault_key in _source_rows(
        settings.cache_database
    ):
        expected_path = settings.source_vault / "raw" / "sha256" / artifact_sha256
        if not expected_path.is_file():
            missing_sources.append(
                MissingSource(
                    source_key=source_key,
                    artifact_sha256=artifact_sha256,
                    expected_path=str(expected_path.resolve()),
                    byte_size=byte_size,
                )
            )
            continue
        if recorded_vault_key != artifact_sha256:
            raise PublicReleaseCustodyError(
                f"source vault key is not content-addressed: {source_key}"
            )
        key = ObjectKey(value=f"raw/sha256/{artifact_sha256}")
        if settings.source_mode == "reference":
            source_sha256, source_size = _hash_file(expected_path)
            if (source_sha256, source_size) != (artifact_sha256, byte_size):
                raise PublicReleaseCustodyError(
                    f"source vault bytes do not match the manifest: {source_key}"
                )
            stored = _object(key, source_sha256, source_size)
        else:
            stored = _push_verified(object_store, expected_path, key, artifact_sha256, byte_size)
        source_objects.append(
            SourceCustody(
                **stored.model_dump(),
                source_key=source_key,
                recorded_vault_key=recorded_vault_key,
                storage_mode=settings.source_mode,
            )
        )

    evidence = _evidence_bindings(
        object_store,
        settings.evidence_directory,
        release_receipt,
        (*_EVIDENCE_FILES, *settings.additional_evidence_files),
    )
    objective_directory = settings.objective_gates_directory
    objective_files = _objective_evidence_files(settings)
    objective_paths = tuple(
        (name, objective_directory / filename)
        for name, filename in objective_files
        if objective_directory is not None
    )
    if objective_directory is not None and objective_paths:
        _verify_objective_evidence(objective_paths, release_receipt)
        objective_evidence = _evidence_bindings(
            object_store,
            objective_directory,
            release_receipt,
            objective_files,
        )
    else:
        objective_evidence = ()
    all_evidence = (*evidence, *objective_evidence)
    evidence_by_name = {item.name: item for item in all_evidence}
    source_complete = not missing_sources
    receipt = PublicReleaseCustodyReceipt(
        release_id=release_receipt.release_id,
        cache=cache_object,
        cache_declared_byte_size=settings.expected_cache_byte_size,
        database_counts=counts,
        expected_database_counts=DatabaseCounts.model_validate(_EXPECTED_DATABASE_COUNTS),
        source_objects_expected=_EXPECTED_INPUT_ARTIFACTS,
        source_objects_custodied=len(source_objects),
        source_objects=tuple(source_objects),
        source_objects_missing=tuple(missing_sources),
        source_completeness="complete" if source_complete else "cache_only",
        source_vault=str(settings.source_vault.resolve()),
        source_storage_mode=settings.source_mode,
        evidence=all_evidence,
        objective_gate_state="present" if objective_evidence else "absent",
        objective_gate_evidence=objective_evidence,
        public_model_gate_sha256=(
            evidence_by_name["public-model-gate"].sha256 if objective_evidence else None
        ),
        metadata_representatives_sha256=(
            evidence_by_name["metadata-representatives"].sha256 if objective_evidence else None
        ),
        artist_membership_evaluation_sha256=(
            evidence_by_name["artist-membership-evaluation"].sha256
            if "artist-membership-evaluation" in evidence_by_name
            else None
        ),
        artist_membership_judgments_sha256=(
            evidence_by_name["artist-membership-judgments"].sha256
            if "artist-membership-judgments" in evidence_by_name
            else None
        ),
        model_logical_sha256=release_receipt.model_logical_sha256,
        model_file_sha256=evidence_by_name["public-model"].sha256,
        production_map_sha256=evidence_by_name["production-map"].sha256,
        browser_evidence_sha256=evidence_by_name["production-map-browser"].sha256,
        representative_items=release_receipt.representative_items,
        profile_memberships=release_receipt.profile_memberships,
        neighbor_rows=release_receipt.neighbor_rows,
        rebuild_command=rebuild_command or tuple(sys.argv),
        python_version=sys.version,
        code_revision=code_revision or _code_revision(),
        created_at=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )
    output_path = settings.output_directory / "public-release-custody-receipt.json"
    _atomic_write(output_path, (receipt.model_dump_json(indent=2) + "\n").encode("utf-8"))
    return receipt
