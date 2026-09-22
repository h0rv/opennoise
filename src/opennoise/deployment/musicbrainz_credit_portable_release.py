"""Custody a small, offline-replayable MusicBrainz artist-credit source slice.

The normal MusicBrainz cache is deliberately ignored: it is useful working
state, but cannot be an input to a production release.  This module turns the
already filtered CC0 core-metadata projection into one content-addressed
portable object.  It retains neither raw HTTP bodies nor any audio, artwork,
tags, or genre fields.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from opennoise.deployment.musicbrainz_credit_static_export import sha256_file
from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import (
    ARTIST_CREDIT_V2_SHA256,
    CORE_HYDRATION_SHA256,
    ArtistCreditCatalogReport,
    materialize_artist_credit_candidate,
)
from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    ArtistCreditRefreshCandidateArtifact,
    _parse_cached_release,
    _projection_sha256,
)
from opennoise.ingest.musicbrainz.release_hydration import (
    CachedResponse,
    MusicBrainzHydrationError,
    MusicBrainzReleaseHydrationArtifact,
)
from opennoise.models import FrozenModel
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite

_SOURCE_REVISION = "musicbrainz-credit-portable-source-v1"
_RECEIPT_REVISION = "musicbrainz-credit-portable-release-v1"
_OBJECT_PREFIX = "musicbrainz-credit-catalog/sha256"
_REQUEST = "GET /ws/2/release/{release_mbid}?inc=release-groups+recordings+artist-credits"
_CONTENT_POLICY: Literal["core_metadata_only_no_audio_preview_artwork_or_genres"] = (
    "core_metadata_only_no_audio_preview_artwork_or_genres"
)


class MusicBrainzCreditPortableReleaseError(RuntimeError):
    """Report an invalid or incomplete portable credit release boundary."""


class PortableCreditProjection(FrozenModel):
    """One exact safe source projection, preserved as its original JSON bytes."""

    endpoint: str = Field(pattern=r"^release/[0-9a-f-]{36}$")
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cached_response_json: str = Field(min_length=1)

    @model_validator(mode="after")
    def exact_safe_projection(self) -> PortableCreditProjection:
        """Bind the receipt fields to one parseable, exact-MBID cache response."""
        try:
            cached = CachedResponse.model_validate_json(self.cached_response_json)
            release = _parse_cached_release(cached)
        except ValueError as error:
            raise ValueError(
                "portable projection is not a valid cached MusicBrainz response"
            ) from error
        if cached.projection_sha256 is None:
            raise ValueError("portable projection lacks v2 projection SHA-256")
        if (
            cached.endpoint,
            cached.projection_sha256,
            cached.response_sha256,
        ) != (self.endpoint, self.projection_sha256, self.response_sha256):
            raise ValueError("portable projection receipt differs from cached response")
        if cached.endpoint != f"release/{release.id}":
            raise ValueError("portable projection endpoint does not match release MBID")
        if (
            _projection_sha256(endpoint=cached.endpoint, payload=cached.payload)
            != cached.projection_sha256
        ):
            raise ValueError("portable projection SHA-256 does not replay")
        return self


class PortableMusicBrainzCreditSource(FrozenModel):
    """All metadata-only inputs required to recreate the isolated credit catalog."""

    revision: Literal["musicbrainz-credit-portable-source-v1"] = _SOURCE_REVISION
    content_policy: Literal["core_metadata_only_no_audio_preview_artwork_or_genres"]
    required_upstream_request: Literal[
        "GET /ws/2/release/{release_mbid}?inc=release-groups+recordings+artist-credits"
    ] = _REQUEST
    no_name_inference: Literal[True] = True
    hydration_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hydration_artifact_json: str = Field(min_length=1)
    credit_artifact_json: str = Field(min_length=1)
    candidate_report_json: str = Field(min_length=1)
    projections: tuple[PortableCreditProjection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def closed_offline_replay(self) -> PortableMusicBrainzCreditSource:  # noqa: C901
        """Require a complete, ordered exact-MBID source partition before custody."""
        if self.hydration_artifact_sha256 != _sha256_text(self.hydration_artifact_json):
            raise ValueError("portable source hydration artifact SHA-256 does not replay")
        if self.credit_artifact_sha256 != _sha256_text(self.credit_artifact_json):
            raise ValueError("portable source credit artifact SHA-256 does not replay")
        if self.candidate_report_sha256 != _sha256_text(self.candidate_report_json):
            raise ValueError("portable source candidate report SHA-256 does not replay")
        try:
            hydration = MusicBrainzReleaseHydrationArtifact.model_validate_json(
                self.hydration_artifact_json
            )
            credit = ArtistCreditRefreshCandidateArtifact.model_validate_json(
                self.credit_artifact_json
            )
            report = ArtistCreditCatalogReport.model_validate_json(self.candidate_report_json)
        except ValueError as error:
            raise ValueError("portable source contains an invalid typed artifact") from error
        if (
            self.hydration_artifact_sha256 != CORE_HYDRATION_SHA256
            or self.credit_artifact_sha256 != ARTIST_CREDIT_V2_SHA256
        ):
            raise ValueError("portable source is not the approved artist-credit input revision")
        if (
            credit.source_hydration_sha256 != self.hydration_artifact_sha256
            or report.source_hydration_sha256 != self.hydration_artifact_sha256
            or report.source_credit_sha256 != self.credit_artifact_sha256
            or report.database_sha256 != self.candidate_database_sha256
            or report.content_policy != self.content_policy
        ):
            raise ValueError("portable source artifact provenance does not form one chain")
        endpoints = tuple(projection.endpoint for projection in self.projections)
        if endpoints != tuple(sorted(endpoints)) or len(set(endpoints)) != len(endpoints):
            raise ValueError("portable source projections must be sorted and unique by endpoint")
        release_ids = {f"release/{release.release_id}" for release in hydration.releases}
        if set(endpoints) != release_ids:
            raise ValueError("portable source projections do not exactly cover hydration releases")
        if tuple(credit.requested_release_ids) != tuple(
            sorted((UUID(endpoint.removeprefix("release/")) for endpoint in endpoints), key=str)
        ):
            raise ValueError("portable source credit artifact has a different release selection")
        if credit.abstentions or credit.failures:
            raise ValueError("portable source credit artifact is incomplete")
        return self


class MusicBrainzCreditCatalogCustodyScope(FrozenModel):
    """Tracked machine-checked scope declaration; it is not deployment approval."""

    revision: Literal["musicbrainz-credit-catalog-custody-scope-v1"] = (
        "musicbrainz-credit-catalog-custody-scope-v1"
    )
    decision: Literal["custody_only"]
    approved_policy_key: Literal["musicbrainz-core-metadata-hydration"]
    approved_use: Literal["musicbrainz_credit_metadata_artist_detail"]
    source_credit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_policy: Literal["core_metadata_only_no_audio_preview_artwork_or_genres"]
    no_name_inference: Literal[True] = True
    no_membership_or_discovery_claims: Literal[True] = True


class PortableMusicBrainzCreditReleaseReceipt(FrozenModel):
    """Content-addressed receipt for a complete offline-replayable source object."""

    revision: Literal["musicbrainz-credit-portable-release-v1"] = _RECEIPT_REVISION
    source: ObjectWrite
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_projection_count: int = Field(gt=0)
    hydration_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    custody_scope: MusicBrainzCreditCatalogCustodyScope
    catalog: ObjectWrite
    catalog_report: ObjectWrite

    @model_validator(mode="after")
    def source_object_is_content_addressed(self) -> PortableMusicBrainzCreditReleaseReceipt:
        """Make the receipt name exactly the immutable source object it approves."""
        expected_key = f"{_OBJECT_PREFIX}/{self.source_sha256}.json"
        if (
            self.source.key.value != expected_key
            or self.source.sha256 != self.source_sha256
            or self.custody_scope.source_credit_sha256 != self.credit_artifact_sha256
        ):
            raise ValueError("portable credit receipt does not bind its source object and scope")
        if (
            self.catalog.key.value
            != f"{_OBJECT_PREFIX}/catalog/{self.candidate_database_sha256}.sqlite"
            or self.catalog.sha256 != self.candidate_database_sha256
            or self.catalog_report.sha256 != self.candidate_report_sha256
            or self.catalog_report.key.value
            != f"{_OBJECT_PREFIX}/catalog-report/{self.candidate_report_sha256}.json"
        ):
            raise ValueError("portable credit receipt does not bind its catalog artifacts")
        return self


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(model: FrozenModel) -> bytes:
    return (model.model_dump_json() + "\n").encode("utf-8")


def build_portable_musicbrainz_credit_source(
    *,
    hydration_artifact: Path,
    credit_artifact: Path,
    cache_directory: Path,
    candidate_database: Path,
    candidate_report: Path,
) -> PortableMusicBrainzCreditSource:
    """Parse the retained local candidate once and return a portable typed source object."""
    hydration_json = hydration_artifact.read_text(encoding="utf-8")
    credit_json = credit_artifact.read_text(encoding="utf-8")
    report_json = candidate_report.read_text(encoding="utf-8")
    projections: list[PortableCreditProjection] = []
    for path in sorted(cache_directory.glob("*.json")):
        try:
            cached = CachedResponse.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise MusicBrainzCreditPortableReleaseError(
                f"portable source cache contains a non-success projection: {path.name}"
            ) from error
        if cached.projection_sha256 is None:
            raise MusicBrainzCreditPortableReleaseError("portable source cache has a v1 projection")
        projections.append(
            PortableCreditProjection(
                endpoint=cached.endpoint,
                projection_sha256=cached.projection_sha256,
                response_sha256=cached.response_sha256,
                cached_response_json=path.read_text(encoding="utf-8"),
            )
        )
    try:
        report = ArtistCreditCatalogReport.model_validate_json(report_json)
    except ValueError as error:
        raise MusicBrainzCreditPortableReleaseError("candidate report is not typed JSON") from error
    candidate_sha256 = sha256_file(candidate_database)
    if report.database_sha256 != candidate_sha256:
        raise MusicBrainzCreditPortableReleaseError(
            "candidate report does not bind candidate database"
        )
    if report.content_policy != _CONTENT_POLICY:
        raise MusicBrainzCreditPortableReleaseError("candidate report has an unsafe content policy")
    return PortableMusicBrainzCreditSource(
        content_policy=_CONTENT_POLICY,
        hydration_artifact_sha256=_sha256_text(hydration_json),
        credit_artifact_sha256=_sha256_text(credit_json),
        candidate_database_sha256=candidate_sha256,
        candidate_report_sha256=_sha256_text(report_json),
        hydration_artifact_json=hydration_json,
        credit_artifact_json=credit_json,
        candidate_report_json=report_json,
        projections=tuple(sorted(projections, key=lambda projection: projection.endpoint)),
    )


def publish_portable_musicbrainz_credit_source(  # noqa: PLR0913 - explicit custody boundary inputs.
    source: PortableMusicBrainzCreditSource,
    *,
    store: ObjectStore,
    custody_scope: MusicBrainzCreditCatalogCustodyScope,
    candidate_database: Path,
    candidate_report: Path,
    receipt_output: Path,
) -> PortableMusicBrainzCreditReleaseReceipt:
    """Publish verified objects; a failure may leave only unreferenced immutable objects.

    ``ObjectStore`` has no multi-object transaction. Every input is therefore
    rehashed before its first write, and the receipt is the sole published
    reference written last. A failed object write can leave a content-addressed,
    unreachable object, but never a receipt that names a partial release.
    """
    if (
        custody_scope.source_credit_sha256 != source.credit_artifact_sha256
        or custody_scope.content_policy != source.content_policy
    ):
        raise MusicBrainzCreditPortableReleaseError("custody scope does not bind portable source")
    if (
        sha256_file(candidate_database),
        sha256_file(candidate_report),
    ) != (
        source.candidate_database_sha256,
        source.candidate_report_sha256,
    ):
        raise MusicBrainzCreditPortableReleaseError(
            "catalog inputs do not match the portable source before publication"
        )
    source_bytes = _canonical_json(source)
    source_sha256 = _sha256_bytes(source_bytes)
    with tempfile.TemporaryDirectory(prefix="musicbrainz-credit-source-") as directory:
        staged = Path(directory) / "source.json"
        staged.write_bytes(source_bytes)
        write = store.push(staged, ObjectKey(value=f"{_OBJECT_PREFIX}/{source_sha256}.json"))
    catalog = store.push(
        candidate_database,
        ObjectKey(value=f"{_OBJECT_PREFIX}/catalog/{source.candidate_database_sha256}.sqlite"),
    )
    catalog_report = store.push(
        candidate_report,
        ObjectKey(value=f"{_OBJECT_PREFIX}/catalog-report/{source.candidate_report_sha256}.json"),
    )
    receipt = PortableMusicBrainzCreditReleaseReceipt(
        source=write,
        source_sha256=source_sha256,
        source_projection_count=len(source.projections),
        hydration_artifact_sha256=source.hydration_artifact_sha256,
        credit_artifact_sha256=source.credit_artifact_sha256,
        candidate_database_sha256=source.candidate_database_sha256,
        candidate_report_sha256=source.candidate_report_sha256,
        custody_scope=custody_scope,
        catalog=catalog,
        catalog_report=catalog_report,
    )
    _write_no_replace(_canonical_json(receipt), receipt_output)
    return receipt


def materialize_portable_musicbrainz_credit_catalog(
    receipt: PortableMusicBrainzCreditReleaseReceipt,
    *,
    store: ObjectStore,
    candidate_database: Path,
    candidate_report: Path,
) -> ArtistCreditCatalogReport:
    """Restore and reproduce the custodied catalog without reading ignored cache state."""
    metadata = store.inspect(receipt.source.key)
    if (metadata.sha256, metadata.byte_size) != (receipt.source_sha256, receipt.source.byte_size):
        raise MusicBrainzCreditPortableReleaseError("portable source object differs from receipt")
    with tempfile.TemporaryDirectory(prefix="musicbrainz-credit-restore-") as directory:
        root = Path(directory)
        pulled = store.pull(receipt.source.key, root / "source.json")
        if (pulled.sha256, pulled.byte_size) != (receipt.source_sha256, receipt.source.byte_size):
            raise MusicBrainzCreditPortableReleaseError("portable source pull differs from receipt")
        try:
            source = PortableMusicBrainzCreditSource.model_validate_json(
                (root / "source.json").read_bytes()
            )
        except ValueError as error:
            raise MusicBrainzCreditPortableReleaseError(
                "portable source object is not valid"
            ) from error
        _require_receipt_source_match(receipt, source)
        hydration = root / "hydration.json"
        credit = root / "credit.json"
        cache = root / "cache"
        cache.mkdir()
        hydration.write_text(source.hydration_artifact_json, encoding="utf-8")
        credit.write_text(source.credit_artifact_json, encoding="utf-8")
        for projection in source.projections:
            cache.joinpath(f"{_sha256_text(projection.endpoint)}.json").write_text(
                projection.cached_response_json, encoding="utf-8"
            )
        try:
            report = materialize_artist_credit_candidate(
                hydration_artifact_path=hydration,
                credit_artifact_path=credit,
                cache_directory=cache,
                candidate_database_path=candidate_database,
                report_path=candidate_report,
                expected_hydration_sha256=source.hydration_artifact_sha256,
                expected_credit_sha256=source.credit_artifact_sha256,
            )
        except MusicBrainzHydrationError as error:
            raise MusicBrainzCreditPortableReleaseError(
                "portable source cannot reproduce catalog"
            ) from error
    if (
        report.release_relations,
        report.recording_relations,
        report.ordered_credit_members,
        report.artists,
        report.verified_cache_projections,
        report.foreign_key_violations,
    ) != (87, 1_031, 1_344, 352, receipt.source_projection_count, 0):
        raise MusicBrainzCreditPortableReleaseError(
            "portable source replay differs from the receipt-bound catalog coverage"
        )
    return report


def restore_portable_musicbrainz_credit_catalog(
    receipt: PortableMusicBrainzCreditReleaseReceipt,
    *,
    store: ObjectStore,
    candidate_database: Path,
    candidate_report: Path,
) -> ArtistCreditCatalogReport:
    """Restore the byte-pinned catalog artifact without reading ignored working state."""
    if any(path.exists() or path.is_symlink() for path in (candidate_database, candidate_report)):
        raise MusicBrainzCreditPortableReleaseError(
            "portable catalog restore targets already exist"
        )
    _verify_object(store, receipt.catalog)
    _verify_object(store, receipt.catalog_report)
    database = store.pull(receipt.catalog.key, candidate_database)
    report_file = store.pull(receipt.catalog_report.key, candidate_report)
    if (
        database.sha256,
        database.byte_size,
        report_file.sha256,
        report_file.byte_size,
    ) != (
        receipt.catalog.sha256,
        receipt.catalog.byte_size,
        receipt.catalog_report.sha256,
        receipt.catalog_report.byte_size,
    ):
        raise MusicBrainzCreditPortableReleaseError("portable catalog restore differs from receipt")
    try:
        report = ArtistCreditCatalogReport.model_validate_json(candidate_report.read_bytes())
    except ValueError as error:
        raise MusicBrainzCreditPortableReleaseError(
            "portable catalog report is not valid"
        ) from error
    if report.database_sha256 != sha256_file(candidate_database):
        raise MusicBrainzCreditPortableReleaseError(
            "portable catalog report does not bind restored bytes"
        )
    return report


def _require_receipt_source_match(
    receipt: PortableMusicBrainzCreditReleaseReceipt, source: PortableMusicBrainzCreditSource
) -> None:
    if (
        receipt.source_projection_count,
        receipt.hydration_artifact_sha256,
        receipt.credit_artifact_sha256,
        receipt.candidate_database_sha256,
        receipt.candidate_report_sha256,
    ) != (
        len(source.projections),
        source.hydration_artifact_sha256,
        source.credit_artifact_sha256,
        source.candidate_database_sha256,
        source.candidate_report_sha256,
    ):
        raise MusicBrainzCreditPortableReleaseError("portable receipt and source are inconsistent")


def _verify_object(store: ObjectStore, expected: ObjectWrite) -> None:
    metadata = store.inspect(expected.key)
    if (metadata.sha256, metadata.byte_size) != (expected.sha256, expected.byte_size):
        raise MusicBrainzCreditPortableReleaseError("portable object differs from receipt")


def _write_no_replace(payload: bytes, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise MusicBrainzCreditPortableReleaseError("portable receipt output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".staging", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise MusicBrainzCreditPortableReleaseError(
                "portable receipt output already exists"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)
