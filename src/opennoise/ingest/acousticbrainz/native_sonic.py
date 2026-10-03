"""Replay native per-recording sonic metadata with separate core-credit custody."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opennoise.ingest.acousticbrainz.projection import (
    NUMERIC_PATHS,
    AcousticIdentityError,
    json_document,
    project_low_level,
    verify_embedded_recording,
)
from opennoise.pipeline.foundation import _safe_path
from opennoise.serving.metadata.recording_facts import project_recording_fact, recording_source_url

if TYPE_CHECKING:
    from pathlib import Path

REVISION: Final = "native-cc0-recording-sonic-v1"
MAX_RECORDINGS: Final = 100
MAX_SONIC_BYTES: Final = 5_000_000
MAX_CORE_BYTES: Final = 1_000_000
MAX_CORE_REQUESTS: Final = 60
LICENSE_AUDIT: Final[dict[str, object]] = {
    "source": "https://acousticbrainz.org/",
    "source_body_sha256": "dad99100be34964459ec9c936efdeacb779a403a73a1c744e27c113e7618a472",
    "source_body_bytes": 8728,
    "source_observed_at": "2026-09-30T23:19:42.421597+00:00",
    "quote": (
        "All of the data contained in AcousticBrainz is licensed under the "
        "CC0 license (public domain)."
    ),
    "data_license": "CC0-1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "review": (
        "independent_gap_review, 2026-10-03; "
        "native AB dataset reusable separately from old wrappers"
    ),
    "scope": "AcousticBrainz data only; not audio, MusicBrainz supplementary data or homepage HTML",
    "core_credit_license_url": "https://musicbrainz.org/doc/About/Data_License",
    "old_research_wrappers_promoted": False,
}
UUID_PATTERN: Final = r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
SHA_PATTERN: Final = r"^[0-9a-f]{64}$"


class Boundary(BaseModel):
    """Strict source-custody declarations reject silent scope additions."""

    model_config = ConfigDict(strict=True, extra="forbid")


class FileBinding(Boundary):
    """Strict exact file bytes, including finite integer lengths."""

    sha256: str = Field(pattern=SHA_PATTERN)
    size_bytes: int = Field(ge=0)


class SelectedRecording(Boundary):
    """Benchmark association describes selection only, never an artist credit."""

    cohort_artist_mbid: str = Field(pattern=UUID_PATTERN)
    recording_mbid: str = Field(pattern=UUID_PATTERN)


class NativeSonicCapture(SelectedRecording):
    """Retained native AB endpoint body with explicit unknown capture dates."""

    url: str
    status_code: int | None = Field(ge=100, le=599)
    source_observed_at: str | None
    observation_time_status: Literal["retained", "not_retained"]
    payload_complete: bool | None
    raw_path: str
    sha256: str = Field(pattern=SHA_PATTERN)
    size_bytes: int = Field(ge=0, le=MAX_SONIC_BYTES)


class NativeCreditCapture(SelectedRecording):
    """Core-only exact recording lookup, separately verified from uploader tags."""

    origin: Literal["reused-native", "fresh-lookup"]
    origin_receipt_sha256: str | None = Field(pattern=SHA_PATTERN)
    request_made: bool
    url: str
    source_observed_at: str | None
    status_code: int | None = Field(ge=100, le=599)
    outcome: Literal[
        "accepted_core", "http_status", "network_error", "byte_budget", "unapproved_payload"
    ]
    response_bytes: int = Field(ge=0, le=MAX_CORE_BYTES)
    response_complete: bool
    raw_path: str | None
    sha256: str | None = Field(pattern=SHA_PATTERN)


class NativeSonicManifest(Boundary):
    """Frozen bounded recording roster and two independent source roles."""

    revision: Literal["native-cc0-recording-sonic-v1"]
    imported_at: str
    selection_method: str
    source_receipt_sha256: str = Field(pattern=SHA_PATTERN)
    source_declaration_sha256: str = Field(pattern=SHA_PATTERN)
    original_wrapper_product_promotion_allowed: Literal[False]
    original_wrapper_scope: Literal["authorized_local_research"]
    selected_recordings: list[SelectedRecording] = Field(min_length=1, max_length=MAX_RECORDINGS)
    sonic_captures: list[NativeSonicCapture] = Field(max_length=MAX_RECORDINGS)
    credit_request_roster: list[SelectedRecording] = Field(max_length=MAX_RECORDINGS)
    credit_captures: list[NativeCreditCapture] = Field(max_length=MAX_RECORDINGS)


def sonic_source_url(recording: str) -> str:
    """Use only the exact native low-level endpoint, without audio or genre queries."""
    if str(UUID(recording)) != recording:
        raise ValueError("sonic endpoint requires a canonical recording UUID")
    return f"https://acousticbrainz.org/api/v1/{recording}/low-level"


def _date(value: str | None) -> None:
    if value is not None and datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("retained source date must include a timezone")


def _raw(root: Path, name: str, digest: str, size: int) -> bytes:
    path = _safe_path(root, name)
    if not path.is_file() or path.stat().st_size != size:
        raise ValueError(f"native source file or byte length mismatch: {name}")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError(f"native source hash mismatch: {name}")
    return body


def _sonic_record(root: Path, capture: NativeSonicCapture) -> dict[str, Any]:
    recording = capture.recording_mbid
    if (
        capture.url != sonic_source_url(recording)
        or capture.raw_path != f"raw/sonic/{recording}.json"
    ):
        raise ValueError("sonic source URL/path is not the exact native recording endpoint")
    _date(capture.source_observed_at)
    if (capture.source_observed_at is None) != (capture.observation_time_status == "not_retained"):
        raise ValueError("source observation date and missingness declaration disagree")
    body = _raw(root, capture.raw_path, capture.sha256, capture.size_bytes)
    result: dict[str, Any] = {
        "recording_mbid": recording,
        "cohort_artist_mbid": capture.cohort_artist_mbid,
        "cohort_artist_role": "selection association only; never uploader credit proof",
        "source_url": capture.url,
        "source_sha256": capture.sha256,
        "source_observed_at": capture.source_observed_at,
        "observation_time_status": capture.observation_time_status,
        "source_transport_completeness": capture.payload_complete,
        "source_license": "CC0-1.0",
        "state": "source_request_failed",
        "identity_state": "not_checked",
        "descriptors": [],
        "descriptor_missing_paths": [],
    }
    if capture.status_code != HTTPStatus.OK:
        result["state"] = (
            "missing_http_404"
            if capture.status_code == HTTPStatus.NOT_FOUND
            else "source_http_error"
        )
        return result
    if capture.payload_complete is False:
        result["state"] = "incomplete_source_response"
        return result
    try:
        document = json_document(body)
        identity = verify_embedded_recording(document, UUID(recording))
        result["identity_state"] = identity
        if identity != "matched":
            result["state"] = "identity_unverified"
            return result
        descriptors = [row.model_dump(mode="json") for row in project_low_level(document)]
    except AcousticIdentityError:
        result["identity_state"] = "mismatched"
        result["state"] = "identity_mismatch"
    except (TypeError, ValueError):
        result["state"] = "invalid_scalar_schema"
    else:
        result["descriptors"] = descriptors
        result["descriptor_missing_paths"] = [
            row["path"] for row in descriptors if row["value"] is None
        ]
        result["state"] = (
            "available"
            if any(row["value"] is not None for row in descriptors)
            else "no_scalar_evidence"
        )
    return result


def _credit_record(root: Path, capture: NativeCreditCapture) -> dict[str, Any]:
    if capture.url != recording_source_url(capture.recording_mbid):
        raise ValueError("credit lookup must use an exact core-only recording URL")
    _date(capture.source_observed_at)
    if capture.origin == "reused-native" and (
        capture.request_made or not capture.origin_receipt_sha256
    ):
        raise ValueError("reused core custody must bind its receipt without a fresh request")
    if capture.origin == "fresh-lookup" and capture.origin_receipt_sha256 is not None:
        raise ValueError("fresh core capture cannot claim an older receipt")
    result: dict[str, Any] = {
        "state": capture.outcome,
        "source_url": capture.url,
        "source_observed_at": capture.source_observed_at,
        "source_role": "independent native MusicBrainz exact recording credit",
        "source_license": "CC0-1.0",
        "fact": None,
    }
    if capture.outcome != "accepted_core":
        if capture.raw_path is not None or capture.sha256 is not None:
            raise ValueError("unapproved core response cannot enter the public raw pack")
        return result
    if (
        capture.status_code != HTTPStatus.OK
        or not capture.response_complete
        or capture.source_observed_at is None
        or capture.raw_path != f"raw/credits/{capture.recording_mbid}.json"
        or capture.sha256 is None
    ):
        raise ValueError("accepted native core custody is incomplete")
    body = _raw(root, capture.raw_path, capture.sha256, capture.response_bytes)
    json_document(body)  # Duplicate keys and nonfinite values cannot bypass the core parser.
    fact = project_recording_fact(body, capture.recording_mbid, capture.cohort_artist_mbid)
    result["fact"] = fact
    return result


def project_native_sonic(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Replay every selected recording and preserve separate sonic and credit missingness."""
    parsed = NativeSonicManifest.model_validate(manifest)
    _date(parsed.imported_at)
    roster = [(row.cohort_artist_mbid, row.recording_mbid) for row in parsed.selected_recordings]
    if len(roster) != len(set(roster)) or len({row[1] for row in roster}) != len(roster):
        raise ValueError("native sonic roster contains repeated recording identities")
    if [(r.cohort_artist_mbid, r.recording_mbid) for r in parsed.sonic_captures] != roster:
        raise ValueError("sonic captures must account for the exact complete frozen roster")
    if sum(row.size_bytes for row in parsed.sonic_captures) > MAX_SONIC_BYTES:
        raise ValueError("native sonic source-byte budget exceeded")
    credit_roster = [
        (row.cohort_artist_mbid, row.recording_mbid) for row in parsed.credit_request_roster
    ]
    if credit_roster != [
        (r.cohort_artist_mbid, r.recording_mbid)
        for r in parsed.sonic_captures
        if r.status_code == HTTPStatus.OK
    ]:
        raise ValueError("core lookups must cover precisely the frozen HTTP-200 recording roster")
    if [(r.cohort_artist_mbid, r.recording_mbid) for r in parsed.credit_captures] != credit_roster:
        raise ValueError("core captures must account for the complete credit lookup roster")
    if (
        sum(row.request_made for row in parsed.credit_captures) > MAX_CORE_REQUESTS
        or sum(row.response_bytes for row in parsed.credit_captures) > MAX_CORE_BYTES
    ):
        raise ValueError("core request or byte budget exceeded")
    credit_facts = {row.recording_mbid: _credit_record(root, row) for row in parsed.credit_captures}
    records = [_sonic_record(root, row) for row in parsed.sonic_captures]
    for record in records:
        record["exact_credit"] = credit_facts.get(
            record["recording_mbid"], {"state": "not_requested_missing_sonic_source", "fact": None}
        )
        record["artist_join_allowed"] = (
            record["state"] == "available" and record["exact_credit"]["fact"] is not None
        )
    return {
        "revision": REVISION,
        "scope": "bounded native per-recording sonic metadata and separate exact core credits",
        "license": "CC0-1.0 native AcousticBrainz data and MusicBrainz core credit facts",
        "imported_at": parsed.imported_at,
        "numeric_paths": list(NUMERIC_PATHS),
        "selection_method": parsed.selection_method,
        "records": records,
        "selected_recordings": len(roster),
        "sonic_source_bytes": sum(row.size_bytes for row in parsed.sonic_captures),
        "state_counts": dict(Counter(row["state"] for row in records)),
        "retained_source_date_count": sum(
            row.source_observed_at is not None for row in parsed.sonic_captures
        ),
        "missing_source_date_count": sum(
            row.source_observed_at is None for row in parsed.sonic_captures
        ),
        "exact_credit_count": sum(row["fact"] is not None for row in credit_facts.values()),
        "missing_credit_count": sum(row["fact"] is None for row in credit_facts.values()),
        "fresh_core_requests": sum(row.request_made for row in parsed.credit_captures),
        "reused_core_captures": sum(
            row.origin == "reused-native" for row in parsed.credit_captures
        ),
        "core_response_bytes": sum(row.response_bytes for row in parsed.credit_captures),
        "descriptive_tags_consumed": False,
        "recording_identity_tags_read": True,
        "artist_medians": [],
        "artist_genre_memberships": [],
        "audio_requested": False,
        "old_research_wrappers_promoted": False,
        "model_fit_performed": False,
        "product_promotion_performed": False,
        "full_corpus_claim": False,
    }


def _closed_raw(root: Path, expected: set[str]) -> None:
    actual = set()
    raw = _safe_path(root, "raw")
    for path in raw.rglob("*"):
        if path.is_symlink():
            raise ValueError("native raw directory cannot contain symlinks")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        elif path.relative_to(root).as_posix() not in {"raw/sonic", "raw/credits"}:
            raise ValueError("native raw directory contains an undeclared directory")
    if actual != expected:
        raise ValueError("native raw file set differs from the complete custody ledger")


def verify_native_sonic(root: Path) -> dict[str, Any]:
    """Check exact file bytes and replay all per-record outputs without upstream requests."""
    receipt = json_document(_safe_path(root, "receipt.json").read_bytes())
    if set(receipt) != {"revision", "files"} or receipt["revision"] != REVISION:
        raise ValueError("native sonic receipt scope differs")
    bindings = receipt["files"]
    if not isinstance(bindings, dict):
        raise TypeError("native sonic file bindings must be an object")
    for name, binding in bindings.items():
        parsed_binding = FileBinding.model_validate(binding)
        _raw(root, name, parsed_binding.sha256, parsed_binding.size_bytes)
    manifest_body = _safe_path(root, "manifest.json").read_bytes()
    manifest = NativeSonicManifest.model_validate_json(manifest_body)
    raw = {row.raw_path for row in manifest.sonic_captures} | {
        row.raw_path for row in manifest.credit_captures if row.raw_path is not None
    }
    expected = raw | {"manifest.json", "projection.json", "license-audit.json"}
    if set(bindings) != expected:
        raise ValueError("native sonic receipt omits or adds declared artifacts")
    _closed_raw(root, raw)
    if json_document(_safe_path(root, "license-audit.json").read_bytes()) != LICENSE_AUDIT:
        raise ValueError("independent native source license boundary differs")
    projected = project_native_sonic(root, manifest.model_dump())
    if json_document(_safe_path(root, "projection.json").read_bytes()) != projected:
        raise ValueError("native sonic projection differs from raw source replay")
    return projected
