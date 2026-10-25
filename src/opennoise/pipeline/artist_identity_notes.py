"""Project exact core disambiguation notes from closed, already-public captures."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from opennoise.pipeline.catalog_demo import digest, read

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SNAPSHOT = "data/examples/native-artist-network-sparse-v2/snapshot.json.gz"
SNAPSHOT_SHA256 = "9fc2297387fc1ab53054c164462b5011868de444763ddd24a3a2eef87597424d"
PACKETS = (
    (
        "data/examples/native-artist-neighborhoods-20261024/captures.jsonl.gz",
        "163199d027975191cf40c66bd50d2c5fd6c651f003dfa5ef2c8591f0cfa896cd",
    ),
    (
        "data/examples/native-artist-neighborhoods-sparse-20261025/captures.jsonl.gz",
        "ccd284906615dd4ae92468821b23a309d0c8d39f41e0656865f0659b066f44c3",
    ),
)
NOTES = "data/examples/native-artist-identity-notes-v1/notes.json"
CORE_FIELDS = {"artist_mbid", "reference_mbid", "name", "comment", "type", "gender", "score"}
CAPTURE_FIELDS = {"body_base64", "bytes", "captured_utc", "reference", "sha256", "status", "url"}
MAX_RECORD_BYTES = 1_000_000
MAX_SNAPSHOT_BYTES = 40_000_000
MAX_COMMENT_CHARS = 500
MAX_ROWS = 100
HTTP_OK = 200
FIRST_PRINTABLE_ASCII = 32
ASCII_DELETE = 127


def normalized_name(value: str) -> str:
    """Compare source names without joining different source IDs."""
    return unicodedata.normalize("NFKC", value).lower().strip()


def _pinned(root: Path, relative: str, expected: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError(f"Identity-note source differs: {relative}")
    return path


def observation_reason(row: object, reference: str, names: dict[str, str]) -> str | None:
    """Reject malformed scope and account for unsupported identity observations."""
    if not isinstance(row, dict) or set(row) - CORE_FIELDS:
        raise ValueError("Identity-note row contains undeclared fields or is not an object")
    for key, value in row.items():
        allowed = (str, int, float, bool) if key == "score" else (str,)
        if value is not None and not isinstance(value, allowed):
            raise ValueError("Identity-note core field has an undeclared value shape")
    if row.get("reference_mbid") != reference:
        return "missing_or_different_reference"
    artist = row.get("artist_mbid")
    if artist not in names:
        return "outside_native_gallery"
    score = row.get("score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or score <= 0
    ):
        return "invalid_score"
    if artist == reference:
        return "self_row"
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return "missing_name"
    return (
        "different_native_name" if normalized_name(name) != normalized_name(names[artist]) else None
    )


def valid_comment(value: object) -> bool:
    """Keep bounded literal source text, excluding empty and control-containing notes."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_COMMENT_CHARS
        and not any(
            ord(char) < FIRST_PRINTABLE_ASCII or ord(char) == ASCII_DELETE for char in value
        )
    )


def _captures(root: Path, names: dict[str, str]) -> Iterator[tuple[str, str, list[Any]]]:
    """Read only hash-verified bounded publisher responses from fixed packets."""
    references = set()
    for relative, expected in PACKETS:
        packet = _pinned(root, relative, expected)
        with gzip.open(packet, "rb") as stream:
            while line := stream.readline(MAX_RECORD_BYTES + 1):
                if len(line) > MAX_RECORD_BYTES:
                    raise ValueError("Identity-note capture record exceeds bounds")
                record = json.loads(line)
                if not isinstance(record, dict) or set(record) != CAPTURE_FIELDS:
                    raise ValueError("Identity-note capture envelope differs")
                reference = record["reference"]
                if reference not in names or reference in references or record["status"] != HTTP_OK:
                    raise ValueError("Invalid or repeated note capture reference")
                references.add(reference)
                raw = base64.b64decode(record["body_base64"], validate=True)
                if (
                    len(raw) != record["bytes"]
                    or hashlib.sha256(raw).hexdigest() != record["sha256"]
                ):
                    raise ValueError("Identity-note raw capture differs")
                rows = json.loads(raw)
                if not isinstance(rows, list) or len(rows) > MAX_ROWS:
                    raise ValueError("Identity-note response exceeds its row scope")
                yield reference, record["sha256"], rows


def _names(root: Path) -> dict[str, str]:
    """Use the unchanged native source roster, never a name-based cross-source join."""
    source = _pinned(root, SNAPSHOT, SNAPSHOT_SHA256)
    with gzip.open(source, "rb") as stream:
        body = stream.read(MAX_SNAPSHOT_BYTES + 1)
    if len(body) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Identity-note snapshot exceeds bounds")
    artists = json.loads(body)["artists"]
    if not isinstance(artists, list):
        raise TypeError("Identity-note baseline is not an artist list")
    names: dict[str, str] = {}
    for row in artists:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "name"}
            or not isinstance(row["id"], str)
            or not isinstance(row["name"], str)
            or not row["name"].strip()
            or row["id"] in names
        ):
            raise ValueError("Invalid or repeated identity in note baseline")
        names[row["id"]] = row["name"]
    return names


def project(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild all accepted notes and the complete source/identity accounting."""
    names = _names(root)
    observations: Counter[str] = Counter()
    comments: dict[str, set[str]] = defaultdict(set)
    invalid_comments: Counter[str] = Counter()
    proofs: dict[tuple[str, str], dict[str, Any]] = {}
    causes: Counter[str] = Counter()
    rejected = []
    references = set()
    raw_rows = 0
    for reference, body_sha256, rows in _captures(root, names):
        references.add(reference)
        for index, row in enumerate(rows, start=1):
            raw_rows += 1
            reason = observation_reason(row, reference, names)
            if reason:
                causes[reason] += 1
                rejected.append({"reference": reference, "row_1based": index, "reason": reason})
                continue
            artist = row["artist_mbid"]
            observations[artist] += 1
            value = row.get("comment")
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if not valid_comment(value):
                invalid_comments[artist] += 1
                continue
            comments[artist].add(value)
            proof = {
                "reference": reference,
                "body_sha256": body_sha256,
                "row_1based": index,
            }
            key = artist, value
            if key not in proofs or (reference, index) < (
                proofs[key]["reference"],
                proofs[key]["row_1based"],
            ):
                proofs[key] = proof
    notes = {}
    ledger = []
    groups: dict[str, list[str]] = defaultdict(list)
    for artist in sorted(names):
        groups[normalized_name(names[artist])].append(artist)
        values = sorted(comments[artist])
        reason = (
            "no_matching_observation"
            if not observations[artist]
            else "invalid_comment"
            if invalid_comments[artist]
            else "conflicting_comments"
            if len(values) > 1
            else "no_nonempty_comment"
            if not values
            else "admitted"
        )
        if reason == "admitted":
            notes[artist] = values[0]
        ledger.append(
            {
                "id": artist,
                "name": names[artist],
                "reason": reason,
                "matching_observations": observations[artist],
                "comment_values": values,
                "invalid_comment_observations": invalid_comments[artist],
                "proof": proofs.get((artist, values[0])) if reason == "admitted" else None,
            }
        )
    ambiguous = [group for group in groups.values() if len(group) > 1]
    counts = {
        "artists": len(names),
        "artists_with_notes": len(notes),
        "ambiguous_name_groups": len(ambiguous),
        "ambiguous_artists": sum(map(len, ambiguous)),
        "ambiguous_artists_with_notes": sum(a in notes for group in ambiguous for a in group),
        "ambiguous_groups_with_distinct_notes": sum(
            all(a in notes for a in group) and len({notes.get(a) for a in group}) == len(group)
            for group in ambiguous
        ),
    }
    payload = {
        "revision": "native-artist-identity-notes-v1",
        "rights": "CC0-1.0",
        "policy": {
            "comment_max_characters": MAX_COMMENT_CHARS,
            "excluded_character_ranges_inclusive": [
                [0, FIRST_PRINTABLE_ASCII - 1],
                [ASCII_DELETE, ASCII_DELETE],
            ],
            "same_native_MBID_and_normalized_name_required": True,
            "name_normalization": "NFKC,lower,strip",
            "finite_positive_numeric_nonboolean_score_required": True,
            "nonempty_comment_consensus": (
                "one exact value across all admitted observations; otherwise abstain"
            ),
            "served_core_fields": ["comment"],
            "cross_catalog_identity_joins": False,
        },
        "snapshot_sha256": SNAPSHOT_SHA256,
        "packets": [{"path": path, "sha256": sha} for path, sha in PACKETS],
        "counts": counts,
        "notes": notes,
    }
    report = {
        "counts": counts,
        "capture_bodies": len(references),
        "raw_rows": raw_rows,
        "accepted_observations": sum(observations.values()),
        "rejected_rows": dict(causes),
        "identity_exclusion_counts": dict(Counter(row["reason"] for row in ledger)),
        "identity_ledger": ledger,
        "row_exclusions": rejected,
        "identity_merges": 0,
        "graph_or_ranking_changes": 0,
    }
    return payload, report


def load(root: Path, spec: dict[str, Any]) -> dict[str, str]:
    """Require exact pinned notes and a fresh replay from the closed public inputs."""
    if set(spec) != {"path", "sha256", "bytes", "counts"} or spec["path"] != NOTES:
        raise ValueError("Identity-note contract contains an undeclared input")
    path = _pinned(root, NOTES, spec["sha256"])
    if path.stat().st_size != spec["bytes"]:
        raise ValueError("Identity-note artifact length differs")
    actual = read(path)
    expected, _ = project(root)
    if actual != expected or actual["counts"] != spec["counts"]:
        raise ValueError("Identity notes do not replay from retained core observations")
    result: dict[str, str] = {}
    for artist, note in actual["notes"].items():
        if not isinstance(artist, str) or not isinstance(note, str):
            raise TypeError("Identity-note artifact contains a nontext value")
        result[artist] = note
    return result
