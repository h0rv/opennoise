"""Strict offline validation and bounded ranking for ListenBrainz counts.

This source role contains ListenBrainz aggregate listening counts only. It is
not genre evidence, music identity, playback availability, or a probability.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MIN_PUBLIC_LISTENERS = 5
MAX_RECORDINGS_PER_REQUEST = 100
MAX_RESPONSE_BYTES = 100_000
EXPECTED_ROSTER_SIZE = 36
HTTP_OK = 200


def _read_json(path: Path) -> Any:  # noqa: ANN401
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_roster(facts_path: Path) -> list[dict[str, Any]]:
    """Read exact, credited MusicBrainz recordings from the closed facts pack."""
    facts = verify_recording_fact_pack(facts_path.parent)
    if facts.get("revision") != "cc0-exact-recording-facts-v1":
        raise ValueError("unexpected recording-facts revision")
    roster: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artist in facts.get("artists", []):
        artist_mbid = artist.get("artist_mbid")
        if not isinstance(artist_mbid, str) or not UUID_RE.fullmatch(artist_mbid):
            raise ValueError("noncanonical artist MBID in recording facts")
        for recording in artist.get("recordings", []):
            mbid = recording.get("recording_mbid")
            credited_artists = recording.get("credited_artist_mbids")
            if not isinstance(mbid, str) or not UUID_RE.fullmatch(mbid):
                raise ValueError("noncanonical recording MBID in recording facts")
            if not isinstance(credited_artists, list) or artist_mbid not in credited_artists:
                raise ValueError(f"recording is not explicitly credited to artist: {mbid}")
            if mbid in seen:
                raise ValueError(f"duplicate recording in frozen roster: {mbid}")
            seen.add(mbid)
            roster.append(
                {
                    "recording_mbid": mbid,
                    "title": recording.get("title"),
                    "artist_mbid": artist_mbid,
                    "artist_name": artist.get("name"),
                }
            )
    if len(roster) != EXPECTED_ROSTER_SIZE:
        raise ValueError(
            f"expected {EXPECTED_ROSTER_SIZE} native credited recordings, found {len(roster)}"
        )
    return roster


def _validate_source_rows(
    rows: Any,  # noqa: ANN401
    roster: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(roster):
        raise ValueError("response must contain exactly one row per requested recording")
    expected = [item["recording_mbid"] for item in roster]
    found: list[str] = []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "recording_mbid",
            "total_listen_count",
            "total_user_count",
        }:
            raise ValueError("unexpected popularity row fields")
        mbid = row["recording_mbid"]
        if not isinstance(mbid, str) or not UUID_RE.fullmatch(mbid):
            raise ValueError("noncanonical recording MBID in response")
        found.append(mbid)
        listens, users = row["total_listen_count"], row["total_user_count"]
        if (listens is None) != (users is None):
            raise ValueError(f"count fields must both be null or both be integers: {mbid}")
        if listens is not None:
            if type(listens) is not int or type(users) is not int or listens < 0 or users < 0:
                raise ValueError(f"counts must be nonnegative integers: {mbid}")
            if users > listens:
                raise ValueError(f"unique listeners cannot exceed listens: {mbid}")
        cleaned.append(
            {
                "recording_mbid": mbid,
                "total_listen_count": listens,
                "total_user_count": users,
            }
        )
    if found != expected:
        raise ValueError("response recording IDs/order do not exactly match frozen request")
    return cleaned


def build_projection(
    rows: Any,  # noqa: ANN401
    roster: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a display-gated, roster-bounded projection from validated rows."""
    checked = _validate_source_rows(rows, roster)
    joined: list[dict[str, Any]] = []
    for identity, counts in zip(roster, checked, strict=True):
        users = counts["total_user_count"]
        eligible = users is not None and users >= MIN_PUBLIC_LISTENERS
        joined.append(
            {
                **identity,
                **counts,
                "public_display_eligible": eligible,
                "bounded_example_rank": None,
            }
        )

    # This is an ordinal among the bounded, sufficiently aggregated examples
    # only; IDs break ties reproducibly. It says nothing about other music.
    ranked = sorted(
        (row for row in joined if row["public_display_eligible"]),
        key=lambda row: (-row["total_listen_count"], row["recording_mbid"]),
    )
    for rank, row in enumerate(ranked, start=1):
        row["bounded_example_rank"] = rank
    return {
        "revision": "listenbrainz-recording-aggregate-counts-v1",
        "source_role": "aggregate listening counts; not genre evidence",
        "public_display_minimum_total_user_count": MIN_PUBLIC_LISTENERS,
        "ranking_scope": "eligible rows among these 36 frozen credited examples only",
        "rows": joined,
        "missing_ids": [
            row["recording_mbid"] for row in joined if row["total_listen_count"] is None
        ],
        "suppressed_ids": [
            row["recording_mbid"]
            for row in joined
            if row["total_listen_count"] is not None and not row["public_display_eligible"]
        ],
    }


def verify_pack(pack_dir: Path) -> dict[str, Any]:  # noqa: C901, PLR0912
    """Verify hashes, closed file set, source rows and derived projection offline."""
    root = Path(pack_dir)
    receipt = _read_json(root / "receipt.json")
    facts_path = root.parents[2] / "data/examples/recording-facts/recording-facts.json"
    # The source roster remains the committed, raw-verified core facts pack.
    if not facts_path.exists():
        raise ValueError("sibling recording-facts pack is required for offline replay")
    roster = _native_roster(facts_path)
    body_path = root / "raw" / "recording-counts-request.json"
    response_path = root / "raw" / "recording-counts-response.json"
    projection_path = root / "recording-counts.json"
    if _sha256(body_path) != receipt["request_sha256"]:
        raise ValueError("request body hash mismatch")
    if _sha256(response_path) != receipt["response_sha256"]:
        raise ValueError("response body hash mismatch")
    if _sha256(projection_path) != receipt["projection_sha256"]:
        raise ValueError("projection hash mismatch")
    expected_files = {
        "receipt.json",
        "recording-counts.json",
        "raw/recording-counts-request.json",
        "raw/recording-counts-response.json",
        "README.md",
        "legal-proof/manifest.json",
    }
    legal_manifest = _read_json(root / "legal-proof" / "manifest.json")
    for item in legal_manifest["sources"]:
        source_path = root / "legal-proof" / item["path"]
        if not source_path.is_file() or source_path.stat().st_size != item["bytes"]:
            raise ValueError(f"legal proof size/path mismatch: {item['path']}")
        if _sha256(source_path) != item["sha256"] or item["status_code"] != HTTP_OK:
            raise ValueError(f"legal proof hash/status mismatch: {item['path']}")
        source_body = (
            gzip.decompress(source_path.read_bytes())
            if item.get("encoding") == "gzip"
            else source_path.read_bytes()
        )
        if "source_bytes" in item and len(source_body) != item["source_bytes"]:
            raise ValueError(f"legal proof uncompressed size mismatch: {item['path']}")
        if (
            "source_sha256" in item
            and hashlib.sha256(source_body).hexdigest() != item["source_sha256"]
        ):
            raise ValueError(f"legal proof uncompressed hash mismatch: {item['path']}")
        expected_files.add("legal-proof/" + item["path"])
    actual_files = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if actual_files != expected_files:
        raise ValueError(
            "pack file set differs: "
            f"unexpected={actual_files - expected_files}, "
            f"missing={expected_files - actual_files}"
        )
    body = json.loads(body_path.read_bytes())
    ids = [item["recording_mbid"] for item in roster]
    if (
        body != {"recording_mbids": ids}
        or len(ids) > MAX_RECORDINGS_PER_REQUEST
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("request body is not the exact bounded frozen roster")
    raw = response_path.read_bytes()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds 100 KB cap")
    rows = _validate_source_rows(json.loads(raw), roster)
    projection = build_projection(rows, roster)
    if projection != _read_json(projection_path):
        raise ValueError("projection does not reconstruct from exact provider response")
    if receipt.get("status_code") != HTTP_OK or receipt.get("requested_count") != len(ids):
        raise ValueError("receipt status or request count mismatch")
    if receipt.get("missing_ids") != projection["missing_ids"]:
        raise ValueError("receipt missing ID list mismatch")
    if (
        receipt.get("data_license") != "unresolved blended ListenBrainz + MLHD+ aggregate"
        or receipt.get("license_scope")
        != "private cache pending explicit redistribution rights proof for both inputs"
        or receipt.get("export_allowed") is not False
        or receipt.get("serving_allowed") is not False
        or receipt.get("model_input_allowed") is not False
    ):
        raise ValueError("unresolved license and downstream-use block must remain explicit")
    return {
        "ok": True,
        "recordings": len(ids),
        "missing": len(projection["missing_ids"]),
        "suppressed": len(projection["suppressed_ids"]),
        "response_bytes": len(raw),
    }
