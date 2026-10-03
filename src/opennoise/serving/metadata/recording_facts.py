"""Replay exact MusicBrainz recording credits from a bounded core-only source pack."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

REVISION = "cc0-exact-recording-facts-v1"
LICENSE = "MusicBrainz core metadata CC0 1.0"
LICENSE_URL = "https://musicbrainz.org/doc/About/Data_License"
MAX_REQUESTS = 50
MAX_BYTES = 1_000_000
_HTTP_OK = 200
_RECORDING_FIELDS = {
    "id",
    "title",
    "length",
    "video",
    "disambiguation",
    "first-release-date",
    "artist-credit",
}
_CREDIT_FIELDS = {"artist", "name", "joinphrase"}
_ARTIST_FIELDS = {"id", "name", "sort-name", "country", "disambiguation", "type", "type-id"}
_CAPTURE_FIELDS = {
    "artist_mbid",
    "recording_mbid",
    "url",
    "fetched_at",
    "status_code",
    "outcome",
    "path",
    "sha256",
    "bytes",
}


def _require_text_fields(payload: dict[str, Any], fields: set[str]) -> None:
    if any(
        value is not None and not isinstance(value, str)
        for key, value in payload.items()
        if key in fields
    ):
        raise ValueError("unexpected nested content in core text metadata")


def _require_uuid(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is None
    ):
        raise ValueError("recording fact requires exact native UUID identities")
    return value


def recording_source_url(recording_mbid: str) -> str:
    """Request credits by exact recording identity, without supplementary fields."""
    _require_uuid(recording_mbid)
    return f"https://musicbrainz.org/ws/2/recording/{recording_mbid}?inc=artist-credits&fmt=json"


def project_recording_fact(body: bytes, recording_mbid: str, artist_mbid: str) -> dict[str, Any]:
    """Reject mixed responses and prove the requested artist's native recording credit."""
    _require_uuid(recording_mbid)
    _require_uuid(artist_mbid)
    payload = json.loads(body)
    if not isinstance(payload, dict) or set(payload) - _RECORDING_FIELDS:
        raise ValueError("unapproved recording source fields; not a core-only CC0 response")
    if payload.get("id") != recording_mbid or not isinstance(payload.get("title"), str):
        raise ValueError("recording response identity or title differs")
    _require_text_fields(payload, {"id", "title", "disambiguation", "first-release-date"})
    if "video" in payload and type(payload["video"]) is not bool:
        raise ValueError("recording video flag must be a boolean")
    length = payload.get("length")
    if length is not None and (type(length) is not int or length < 0):
        raise ValueError("recording duration must be a nonnegative integer or missing")
    artist_credits = payload.get("artist-credit")
    if not isinstance(artist_credits, list):
        raise TypeError("recording source artist credits missing")
    artists = set()
    for credit in artist_credits:
        if not isinstance(credit, dict) or set(credit) - _CREDIT_FIELDS:
            raise ValueError("unapproved recording credit fields")
        _require_text_fields(credit, {"name", "joinphrase"})
        artist = credit.get("artist")
        if not isinstance(artist, dict) or set(artist) - _ARTIST_FIELDS:
            raise ValueError("unapproved credited artist fields")
        _require_text_fields(artist, _ARTIST_FIELDS)
        identity = _require_uuid(artist.get("id"))
        artists.add(identity)
    if artist_mbid not in artists:
        raise ValueError("requested artist is not explicitly credited on this recording")
    return {
        "recording_mbid": recording_mbid,
        "title": payload["title"],
        "length_ms": length,
        "credited_artist_mbids": sorted(artists),
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "url": f"https://musicbrainz.org/recording/{recording_mbid}",
    }


def selection_pairs(selection: dict[str, Any]) -> list[tuple[str, str]]:
    """Validate the frozen cohort, including every requested recording in the denominator."""
    if set(selection) != {"revision", "selection_method", "source_projection_sha256", "artists"}:
        raise ValueError("unexpected recording selection fields")
    if selection["revision"] != REVISION or not isinstance(selection["artists"], list):
        raise ValueError("unknown recording selection revision")
    pairs: list[tuple[str, str]] = []
    seen = set()
    for artist in selection["artists"]:
        if set(artist) != {"artist_mbid", "name", "recording_mbids"}:
            raise ValueError("unexpected selected artist fields")
        _require_uuid(artist["artist_mbid"])
        if artist["artist_mbid"] in seen:
            raise ValueError("repeated selected artist identity")
        seen.add(artist["artist_mbid"])
        for recording in artist["recording_mbids"]:
            _require_uuid(recording)
            pairs.append((_require_uuid(artist["artist_mbid"]), _require_uuid(recording)))
    if not pairs or len(pairs) > MAX_REQUESTS or len(set(pairs)) != len(pairs):
        raise ValueError("empty, duplicate or over-budget recording selections")
    return pairs


def _capture_body(directory: Path, capture: dict[str, Any]) -> bytes:
    if (
        capture["status_code"] != _HTTP_OK
        or capture["path"] != f"raw/{capture['recording_mbid']}.json"
    ):
        raise ValueError("accepted recording source path or status differs")
    source = directory / f"raw/{capture['recording_mbid']}.json"
    if source.is_symlink() or source.parent.is_symlink():
        raise ValueError("symlinked recording source")
    body = source.read_bytes()
    if len(body) != capture["bytes"] or hashlib.sha256(body).hexdigest() != capture["sha256"]:
        raise ValueError("recording source byte binding differs")
    return body


def _verify_closed_raw_directory(directory: Path, captures: list[dict[str, Any]]) -> None:
    """Require the raw directory to contain only accepted, receipt-listed responses."""
    raw_directory = directory / "raw"
    if raw_directory.is_symlink() or not raw_directory.is_dir():
        raise ValueError("recording raw path must be a regular directory")

    expected_paths: set[str] = set()
    for capture in captures:
        if capture.get("outcome") != "accepted_core":
            continue
        recording_id = _require_uuid(capture.get("recording_mbid"))
        expected_path = f"raw/{recording_id}.json"
        if capture.get("path") != expected_path:
            raise ValueError("accepted recording capture has a noncanonical raw path")
        expected_paths.add(f"{recording_id}.json")

    actual_paths: set[str] = set()
    for path in raw_directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("recording raw directory cannot contain symlinks")
        if not path.is_file():
            raise ValueError("recording raw directory cannot contain nested directories")
        actual_paths.add(path.relative_to(raw_directory).as_posix())
    if actual_paths != expected_paths:
        raise ValueError("recording raw file set differs from accepted captures")


def replay_recording_facts(
    directory: Path, selection: dict[str, Any], captures: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reconstruct the complete projection, preserving failed requests as missing facts."""
    pairs = selection_pairs(selection)
    if [(c["artist_mbid"], c["recording_mbid"]) for c in captures] != pairs:
        raise ValueError("recording captures differ from frozen selection")
    grouped: dict[str, list[dict[str, Any]]] = {a["artist_mbid"]: [] for a in selection["artists"]}
    for capture in captures:
        if set(capture) - _CAPTURE_FIELDS:
            raise ValueError("unapproved recording capture provenance fields")
        artist, recording = capture["artist_mbid"], capture["recording_mbid"]
        if capture["url"] != recording_source_url(recording):
            raise ValueError("recording capture does not use exact core-only source URL")
        if capture["outcome"] != "accepted_core":
            if capture["outcome"] not in {
                "http_status",
                "network_error",
                "unapproved_payload",
                "byte_budget",
            }:
                raise ValueError("unknown recording capture failure")
            if "path" in capture:
                raise ValueError("failed recording capture cannot provide source facts")
            continue
        body = _capture_body(directory, capture)
        grouped[artist].append(project_recording_fact(body, recording, artist))
    return {
        "revision": REVISION,
        "license": LICENSE,
        "limitations": (
            "Bounded exact recording credits; no representative quality, genres, popularity, "
            "release credits or listening availability assessed."
        ),
        "artists": [
            {
                "artist_mbid": artist["artist_mbid"],
                "name": artist["name"],
                "requested_recordings": len(artist["recording_mbids"]),
                "missing_recordings": len(artist["recording_mbids"])
                - len(grouped[artist["artist_mbid"]]),
                "recordings": grouped[artist["artist_mbid"]],
            }
            for artist in selection["artists"]
        ],
    }


def verify_recording_fact_pack(directory: Path) -> dict[str, Any]:
    """Verify every retained raw credit and independently replay the portable projection."""
    receipt = json.loads((directory / "receipt.json").read_bytes())
    selection_body = (directory / "selection.json").read_bytes()
    projection_body = (directory / "recording-facts.json").read_bytes()
    if (
        receipt.get("revision") != REVISION
        or receipt.get("license") != LICENSE
        or receipt.get("license_url") != LICENSE_URL
        or receipt.get("selection_sha256") != hashlib.sha256(selection_body).hexdigest()
        or receipt.get("projection_sha256") != hashlib.sha256(projection_body).hexdigest()
        or receipt.get("max_requests") != MAX_REQUESTS
        or receipt.get("max_response_bytes") != MAX_BYTES
        or receipt.get("scope") != "portable_core_metadata_only"
        or receipt.get("metadata_only") is not True
        or receipt.get("tags_or_genres_requested") is not False
    ):
        raise ValueError("recording fact receipt boundary differs")
    captures = receipt["captures"]
    if receipt["request_count"] != len(captures) or not 0 <= receipt["response_bytes"] <= MAX_BYTES:
        raise ValueError("recording fact budget differs")
    if sum(c.get("bytes", 0) for c in captures) > receipt["response_bytes"]:
        raise ValueError("retained recording bytes exceed captured byte budget")
    _verify_closed_raw_directory(directory, captures)
    projection = replay_recording_facts(directory, json.loads(selection_body), captures)
    if projection != json.loads(projection_body):
        raise ValueError("recording fact projection differs from native source replay")
    return projection
