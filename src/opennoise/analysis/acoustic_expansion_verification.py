"""Offline replay of bounded exact-credit AcousticBrainz expansion evidence."""

from __future__ import annotations

from collections import Counter
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from opennoise.common import sha256_file, sha256_hex
from opennoise.ingest.acousticbrainz.capture import verify_benchmarks, verify_reprojection
from opennoise.ingest.acousticbrainz.models import NumericDescriptor, SourceCapture
from opennoise.ingest.acousticbrainz.projection import (
    json_document,
    project_low_level,
    verify_embedded_recording,
)

MAX_BYTES = 10_000_000
RESPONSE_CAP = 300_000


class ExpansionOutcome(BaseModel):
    """All persisted replay inputs and projected outputs for one recording."""

    model_config = ConfigDict(extra="forbid", strict=True)
    artist_id: str
    recording_id: str
    state: str
    status_code: int | None = Field(ge=100, le=599)
    identity: str
    reused: bool
    payload_path: str
    payload_sha256: str
    payload_bytes: int
    descriptors: tuple[NumericDescriptor, ...]


class Expansion(BaseModel):
    """Retained metadata expansion boundary, with its separate research scope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    scope: dict[str, object]
    outcomes: tuple[ExpansionOutcome, ...]
    new_requests: int
    new_response_bytes: int
    state_counts: dict[str, int]
    source_license: str
    source_attribution: str
    product_promotion_allowed: bool
    representative_sample: bool


def _safe_tree(directory: Path) -> set[str]:
    if directory.is_symlink():
        raise ValueError("symlink evidence root")
    files = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlink evidence path")
        if path.is_file():
            files.add(path.relative_to(directory).as_posix())
    return files


def verify_inventory(directory: Path) -> dict[str, str]:
    """Reject unsafe paths, symlinks, omitted mandatory files and unbound extra bytes."""
    actual = _safe_tree(directory)
    receipt = json_document((directory / "receipt.json").read_bytes())
    files = TypeAdapter(dict[str, str]).validate_python(receipt.get("files"))
    mandatory = {"declaration.json", "projection.json", "executed-script.py"}
    if not mandatory <= files.keys() or actual != files.keys() | {"receipt.json"}:
        raise ValueError("expansion inventory incomplete or extra files present")
    for relative, expected in files.items():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
            raise ValueError("unsafe expansion inventory path")
        if sha256_file(directory / relative)[0] != expected:
            raise ValueError("expansion file hash mismatch")
    return files


def selected_recordings(source: Path, captures: tuple[SourceCapture, ...]) -> list[list[str]]:
    """Reconstruct ten UUID-sorted exact-credit recordings from each bound search."""
    selected = []
    for row in captures:
        if row.kind != "search" or row.artist_mbid is None:
            continue
        document = json_document((source / row.payload_path).read_bytes())
        recordings = TypeAdapter(list[dict[str, object]]).validate_python(
            document.get("recordings")
        )
        eligible = set()
        for recording in recordings:
            artist_credits = TypeAdapter(list[dict[str, object] | str]).validate_python(
                recording.get("artist-credit")
            )
            for credit in artist_credits:
                if (
                    isinstance(credit, dict)
                    and isinstance(artist := credit.get("artist"), dict)
                    and artist.get("id") == str(row.artist_mbid)
                ):
                    eligible.add(str(UUID(str(recording["id"]))))
        selected.extend([str(row.artist_mbid), recording] for recording in sorted(eligible)[:10])
    if len({tuple(row) for row in selected}) != len(selected):
        raise ValueError("duplicate selected artist/recording pair")
    return selected


def _replay_outcome(row: ExpansionOutcome, payload: bytes, remaining: int) -> None:
    identity = "not_checked"
    descriptors: tuple[NumericDescriptor, ...] = ()
    if row.state == "truncated_byte_budget":
        if len(payload) != min(RESPONSE_CAP, remaining):
            raise ValueError("truncation lacks exhausted byte bound")
        state = row.state
    elif row.status_code == HTTPStatus.OK:
        try:
            document = json_document(payload)
            identity = verify_embedded_recording(document, UUID(row.recording_id))
            descriptors = project_low_level(document)
            state = "available" if identity == "matched" else "identity_absent"
        except ValueError:
            state = "invalid_projection"
    elif row.status_code == HTTPStatus.NOT_FOUND:
        state = "missing_http_404"
    elif row.status_code is not None:
        state = "http_error"
    elif remaining <= 0 and not row.reused:
        state = "not_requested_byte_budget"
    else:
        state = "request_failed"
    if (state, identity, descriptors) != (row.state, row.identity, row.descriptors):
        raise ValueError("expansion raw projection replay mismatch")


def verify_expansion(  # noqa: C901, PLR0912, PLR0915 - replay gates stay together.
    directory: Path, corrected_source: Path
) -> tuple[Expansion, dict[str, object]]:
    """Verify complete inventory, source lineage, selection, projections and budgets."""
    _safe_tree(corrected_source)
    verify_reprojection(directory=corrected_source)
    lineage = json_document((corrected_source / "pre-reprojection-declaration.json").read_bytes())
    source = Path(str(lineage["source_directory"]))
    _safe_tree(source)
    verify_benchmarks(directory=source)
    files = verify_inventory(directory)
    declaration = json_document((directory / "declaration.json").read_bytes())
    source_hash = sha256_file(source / "receipt.json")[0]
    if declaration.get("source_receipt_sha256") != source_hash:
        raise ValueError("expansion original source receipt mismatch")
    expected_policy = {
        "scope": "authorized_local_research",
        "max_new_response_bytes": MAX_BYTES,
        "response_cap": RESPONSE_CAP,
        "audio_requested": False,
        "level": "low-level",
        "retries": 0,
        "rate_interval_seconds": 1.1,
        "raw_tags_consumed": False,
    }
    if any(declaration.get(key) != value for key, value in expected_policy.items()):
        raise ValueError("expansion policy or limits mismatch")
    implementation = declaration.get("implementation_sha256")
    if implementation is not None and implementation != files["executed-script.py"]:
        raise ValueError("expansion implementation hash mismatch")
    captures = TypeAdapter(tuple[SourceCapture, ...]).validate_json(
        (source / "source-captures.json").read_bytes()
    )
    selection = selected_recordings(source, captures)
    expansion = Expansion.model_validate_json((directory / "projection.json").read_bytes())
    if declaration.get("recordings") != selection or expansion.scope != declaration:
        raise ValueError("expansion declared selection/scope mismatch")
    if [[row.artist_id, row.recording_id] for row in expansion.outcomes] != selection:
        raise ValueError("expansion outcomes mismatch exact-credit selection")
    expected_files = {"declaration.json", "projection.json", "executed-script.py"} | {
        f"raw/{index:03}.bin" for index in range(len(selection))
    }
    if set(files) != expected_files:
        raise ValueError("expansion mandatory raw inventory mismatch")
    cached = {
        (str(row.artist_mbid), str(row.recording_mbid)): row
        for row in captures
        if row.kind == "low-level"
    }
    total = requests = 0
    for index, row in enumerate(expansion.outcomes):
        if row.payload_path != f"raw/{index:03}.bin":
            raise ValueError("outcome raw path differs")
        payload = (directory / row.payload_path).read_bytes()
        if row.payload_bytes != len(payload) or row.payload_sha256 != sha256_hex(payload):
            raise ValueError("outcome payload identity mismatch")
        old = cached.get((row.artist_id, row.recording_id))
        if row.reused != (old is not None):
            raise ValueError("cached reuse differs")
        if old is not None:
            if (
                payload != (source / old.payload_path).read_bytes()
                or row.status_code != old.status_code
            ):
                raise ValueError("cached payload/status mismatch")
        else:
            if len(payload) > min(RESPONSE_CAP, MAX_BYTES - total):
                raise ValueError("expansion response byte budget exceeded")
            requests += int(total < MAX_BYTES)
        _replay_outcome(row, payload, MAX_BYTES - total)
        if old is None:
            total += len(payload)
    if (total, requests) != (expansion.new_response_bytes, expansion.new_requests):
        raise ValueError("expansion request/byte counters mismatch")
    if dict(Counter(row.state for row in expansion.outcomes)) != expansion.state_counts:
        raise ValueError("expansion state counters mismatch")
    if (
        expansion.source_license != "CC0-1.0"
        or expansion.source_attribution != "AcousticBrainz / MusicBrainz contributors"
        or expansion.product_promotion_allowed
        or expansion.representative_sample
    ):
        raise ValueError("expansion source/scope flags mismatch")
    return expansion, {
        "verified": True,
        "network_requests": 0,
        "selected_recordings": len(selection),
        "source_receipt_sha256": source_hash,
        "expansion_receipt_sha256": sha256_file(directory / "receipt.json")[0],
        "available_recordings": expansion.state_counts.get("available", 0),
        "new_response_bytes_replayed": total,
        "limits": (
            "Saved bytes prove projection and counters; "
            "HTTP authenticity/timing are not independently verified."
        ),
    }
