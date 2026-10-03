"""Freeze and replay arbitrary native first-page recording discovery; no musical ranking."""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from opennoise.serving.metadata.recording_facts import (
    project_recording_fact,
    recording_source_url,
    verify_recording_fact_pack,
)

if TYPE_CHECKING:
    from pathlib import Path

CULTURAL_PACKS = ("cultural-context", "independent-cultural-context")
HTTP_OK = 200
COHORT_COUNT = 150
MIN_SPACING = 1.1
REVISION = "selected-150-native-recording-catalog-v1"
ROSTER_SHA = "373593fec761fdc5e9ebc512fe1858e8655af0b48bb1129a8fa9377111e54d79"
MAX_RSS_BYTES = 40_000_000
MAX_REQUESTS = 450
MAX_BODY = 200_000
MAX_NATIVE_BYTES = 3_000_000  # Raw custody + strict shard duplicates + metadata stay below8MB.
MAX_PACK_BYTES = 8_000_000
PAGE_LIMIT = 2
SHARD_PAIRS = 4  # Four capped responses cannot exceed the unchanged strict shard's 1MB budget.


def canonical_json(value: object) -> bytes:
    """Use the repository's exact canonical JSON policy without Pydantic in HTTP process."""
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def sha256_file(path: Path) -> tuple[str, int]:
    """Stream small custody blocks without loading schema/type machinery during HTTP."""
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
            length += len(chunk)
    return digest.hexdigest(), length


def roster(root: Path) -> dict[str, Any]:
    """Replay both existing CC0 cohorts and freeze all exact identities before HTTP."""
    from opennoise.pipeline.portable_foundation import (  # noqa: PLC0415 - separate strict freeze/replay process.
        _verified_cultural,
    )

    artists: dict[str, str] = {}
    pins = {}
    for pack in CULTURAL_PACKS:
        directory = root / "data/examples" / pack
        manifest, _ = _verified_cultural(directory)
        for row in manifest["cohort"]:
            artists.setdefault(row["artist_mbid"], row["name"])
        for filename in ("manifest.json", "receipt.json"):
            pins[f"data/examples/{pack}/{filename}"] = sha256_file(directory / filename)[0]
    rows = [{"artist_mbid": identity, "name": name} for identity, name in sorted(artists.items())]
    if len(rows) != COHORT_COUNT or hashlib.sha256(canonical_json(rows)).hexdigest() != ROSTER_SHA:
        raise ValueError("selected-150 cohort differs from the frozen native identity roster")
    return {
        "revision": REVISION,
        "artists": rows,
        "source_pins": pins,
        "roster_sha256": ROSTER_SHA,
        "selection_policy": (
            "Native first browse page, limit2 offset0; arbitrary order, not representative, "
            "defining, relevant or complete. Exact recording/artist credit only."
        ),
        "limits": {
            "requests": MAX_REQUESTS,
            "response_bytes": MAX_BODY,
            "native_bytes": MAX_NATIVE_BYTES,
            "pack_bytes": MAX_PACK_BYTES,
            "spacing_seconds": 1.1,
            "shard_pairs": SHARD_PAIRS,
            "max_process_rss_bytes": MAX_RSS_BYTES,
        },
    }


def verify_frozen_roster(directory: Path, root: Path) -> dict[str, Any]:
    """Check sealed source closure after the separate strict roster replay, before HTTP."""
    freeze = json.loads((directory / "freeze.json").read_bytes())
    selection = json.loads((directory / "selection.json").read_bytes())
    if (
        freeze["revision"] != REVISION
        or sha256_file(directory / "selection.json")[0] != freeze["selection_sha256"]
    ):
        raise ValueError("frozen selected artist declaration differs")
    if hashlib.sha256(canonical_json(selection["artists"])).hexdigest() != ROSTER_SHA:
        raise ValueError("frozen 150 exact source identities differ")
    if (
        freeze["roster_verifier_sha256"]
        != sha256_file(root / "src/opennoise/pipeline/portable_foundation.py")[0]
    ):
        raise ValueError("strict roster verifier changed after pre-HTTP freeze")
    expected = {
        str(p.relative_to(root))
        for pack in CULTURAL_PACKS
        for p in (root / "data/examples" / pack).rglob("*")
        if p.is_file()
    }
    if expected != set(freeze["source_files"]):
        raise ValueError("frozen cohort source closure differs")
    for relative, binding in freeze["source_files"].items():
        if sha256_file(root / relative) != (binding["sha256"], binding["bytes"]):
            raise ValueError("strictly replayed cohort source bytes changed before HTTP")
    return selection


def browse_url(identity: str) -> str:
    """Use an exact native artist ID, without supplementary inclusion parameters."""
    if str(UUID(identity)) != identity:
        raise ValueError("artist identity is not a canonical UUID")
    return f"https://musicbrainz.org/ws/2/recording?artist={identity}&limit=2&offset=0&inc=artist-credits&fmt=json"


def project_browse(body: bytes, identity: str) -> dict[str, Any]:
    """Account for native counts while allowing only strict credited core candidate rows."""
    browse_url(identity)
    payload = json.loads(body)
    if not isinstance(payload, dict) or set(payload) != {
        "recording-count",
        "recording-offset",
        "recordings",
    }:
        raise ValueError("unexpected browse envelope; raw custody only")
    count, offset, rows = (
        payload["recording-count"],
        payload["recording-offset"],
        payload["recordings"],
    )
    if type(count) is not int or count < 0 or type(offset) is not int or offset != 0:
        raise ValueError("native browse count or offset is invalid")
    if not isinstance(rows, list) or len(rows) > PAGE_LIMIT or len(rows) > count:
        raise ValueError("native browse pagination exceeds declared first-page bounds")
    admitted, rejected, seen = [], [], set()
    for index, row in enumerate(rows):
        recording = row.get("id") if isinstance(row, dict) else None
        try:
            if not isinstance(recording, str):
                raise TypeError("recording UUID is missing")  # noqa: TRY301 - source row abstention.
            if recording in seen:
                raise ValueError("duplicate native page recording")  # noqa: TRY301 - source row abstention.
            project_recording_fact(canonical_json(row), recording, identity)
        except (ValueError, TypeError, KeyError):
            rejected.append({"row_index": index, "reason": "not_strict_core_exact_credit"})
        else:
            admitted.append(recording)
            seen.add(recording)
    return {
        "artist_mbid": identity,
        "advertised_recording_count": count,
        "returned_count": len(rows),
        "recording_mbids": admitted,
        "rejected_rows": rejected,
        "unfetched_recording_count": count - len(rows),
        "complete_catalog_fetched": count == len(rows) and not rejected,
        "representativeness": "not_assessed_native_first_page",
    }


def candidates(
    selection: dict[str, Any], captures: list[dict[str, Any]], directory: Path
) -> dict[str, Any]:
    """Keep all 150 source outcomes and exact-pair candidates in a frozen declaration."""
    if [c["artist_mbid"] for c in captures] != [a["artist_mbid"] for a in selection["artists"]]:
        raise ValueError("browse outcomes omit or reorder the frozen 150-artist cohort")
    rows = []
    for capture in captures:
        identity = capture["artist_mbid"]
        projected = None
        if capture["outcome"] == "complete_http_200":
            with suppress(ValueError, TypeError, KeyError):
                projected = project_browse((directory / capture["path"]).read_bytes(), identity)
        rows.append(
            projected
            or {
                "artist_mbid": identity,
                "advertised_recording_count": None,
                "returned_count": None,
                "recording_mbids": [],
                "rejected_rows": [],
                "unfetched_recording_count": None,
                "complete_catalog_fetched": False,
                "representativeness": "not_assessed_native_first_page",
                "missing_reason": capture["outcome"]
                if capture["outcome"] != "complete_http_200"
                else "unapproved_native_envelope",
            }
        )
    pairs = [
        [row["artist_mbid"], recording] for row in rows for recording in row["recording_mbids"]
    ]
    return {
        "revision": REVISION,
        "roster_sha256": selection["roster_sha256"],
        "artists": rows,
        "pairs": pairs,
        "shards": [
            pairs[index : index + SHARD_PAIRS] for index in range(0, len(pairs), SHARD_PAIRS)
        ],
        "scope": (
            "Discovery IDs and advertised per-artist source counts; only strict individual "
            "lookup shards publish CC0 facts. No media or musical relevance inference."
        ),
    }


def expected_core_captures(directory: Path, captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Independently reconstruct strict accepted/missing outcomes from native custody."""
    result = []
    seen = {}
    for native in captures:
        row = {
            key: native[key]
            for key in ("artist_mbid", "recording_mbid", "url", "fetched_at", "status_code")
        }
        row["outcome"] = "unapproved_payload" if native["status_code"] == HTTP_OK else "http_status"
        if native["status_code"] is None:
            row["outcome"] = "network_error"
        if native["outcome"] in {"native_byte_budget", "response_or_native_byte_budget"}:
            row["outcome"] = "byte_budget"
        if native["outcome"] == "complete_http_200" and "path" in native:
            body = (directory / native["path"]).read_bytes()
            try:
                project_recording_fact(body, native["recording_mbid"], native["artist_mbid"])
            except (ValueError, TypeError, KeyError):
                pass
            else:
                previous = seen.get(native["recording_mbid"])
                if previous is None or previous == native["sha256"]:
                    seen[native["recording_mbid"]] = native["sha256"]
                    row.update(
                        outcome="accepted_core",
                        path=f"raw/{native['recording_mbid']}.json",
                        sha256=native["sha256"],
                        bytes=native["bytes"],
                    )
        result.append(row)
    return result


def verify_catalog(  # noqa: C901, PLR0912, PLR0915 - source custody, count and unchanged strict-shard replay.
    directory: Path, root: Path
) -> dict[str, Any]:
    """Replay closed raw custody, native browse counts and every unchanged core-only shard."""
    receipt = json.loads((directory / "receipt.json").read_bytes())
    if receipt["revision"] != REVISION:
        raise ValueError("unknown recording catalog revision")
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != set(receipt["files"]) | {"receipt.json"} or any(
        p.is_symlink() for p in directory.rglob("*")
    ):
        raise ValueError("recording catalog closed file custody differs")
    for filename, binding in receipt["files"].items():
        if sha256_file(directory / filename) != (binding["sha256"], binding["bytes"]):
            raise ValueError("recording catalog source bytes differ")
    selected = verify_frozen_roster(directory, root)
    if selected != roster(root):
        raise ValueError("catalog frozen roster or policy differs")
    ledger = json.loads((directory / "captures.json").read_bytes())
    if len(ledger) > MAX_REQUESTS or sum(row["bytes"] for row in ledger) > MAX_NATIVE_BYTES:
        raise ValueError("catalog native transfer budget differs")
    for index, capture in enumerate(ledger):
        if json.loads((directory / f"ledger/{index:03d}.json").read_bytes()) != capture:
            raise ValueError("catalog aggregate ledger differs from preserved individual outcomes")
        if "path" in capture and capture["path"] != f"custody/{index:03d}.body":
            raise ValueError("catalog custody response path differs from frozen request sequence")
        if capture["outcome"] not in {
            "complete_http_200",
            "network_error",
            "http_status",
            "native_byte_budget",
            "response_or_native_byte_budget",
        }:
            raise ValueError("catalog unknown source capture outcome")
        offset = datetime.fromisoformat(capture["fetched_at"]).utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("catalog capture lacks actual UTC timestamp")
        if capture["outcome"] == "complete_http_200" and (
            capture["status_code"] != HTTP_OK or capture["complete_body"] is not True
        ):
            raise ValueError("catalog accepted response status or body completeness differs")
        if capture["sequence"] != index or not 0 <= capture["bytes"] <= MAX_BODY:
            raise ValueError("catalog request ordering or response budget differs")
        if (
            index
            and capture["started_elapsed_seconds"] - ledger[index - 1]["started_elapsed_seconds"]
            < MIN_SPACING
        ):
            raise ValueError("catalog serialized request spacing differs")
        if "path" in capture and sha256_file(directory / capture["path"]) != (
            capture["sha256"],
            capture["bytes"],
        ):
            raise ValueError("catalog raw custody differs")
    browse = [row for row in ledger if row["stage"] == "browse"]
    for capture in browse:
        if capture["url"] != browse_url(capture["artist_mbid"]):
            raise ValueError("catalog native browse URL differs")
    projected = candidates(selected, browse, directory)
    if projected != json.loads((directory / "candidates.json").read_bytes()):
        raise ValueError("catalog native count, pagination or credit projection differs")
    lookups = [row for row in ledger if row["stage"] == "lookup"]
    if [[row["artist_mbid"], row["recording_mbid"]] for row in lookups] != projected["pairs"]:
        raise ValueError("catalog exact lookup plan differs from frozen candidates")
    for capture in lookups:
        if capture["url"] != recording_source_url(capture["recording_mbid"]):
            raise ValueError("catalog exact core lookup URL differs")
    observed = 0
    lookup_index = 0
    for index, pairs in enumerate(projected["shards"]):
        path = directory / "shards" / f"{index:03d}"
        artifact = verify_recording_fact_pack(path)
        frozen = json.loads((path / "selection.json").read_bytes())
        actual_pairs = [
            [a["artist_mbid"], r] for a in frozen["artists"] for r in a["recording_mbids"]
        ]
        if actual_pairs != pairs:
            raise ValueError("strict lookup shard differs from frozen native candidate pairs")
        if frozen["source_projection_sha256"] != sha256_file(directory / "candidates.json")[0]:
            raise ValueError("strict lookup shard lost its frozen candidate declaration")
        shard_receipt = json.loads((path / "receipt.json").read_bytes())
        shard_native = lookups[lookup_index : lookup_index + len(pairs)]
        if shard_receipt["captures"] != expected_core_captures(directory, shard_native):
            raise ValueError(
                "strict lookup accepted or missing facts differ from native source replay"
            )
        for core_capture in shard_receipt["captures"]:
            native = lookups[lookup_index]
            lookup_index += 1
            if core_capture["outcome"] == "accepted_core" and (
                native["outcome"] != "complete_http_200"
                or native["sha256"] != core_capture["sha256"]
            ):
                raise ValueError("strict CC0 recording bytes differ from native catalog custody")
        observed += sum(len(a["recordings"]) for a in artifact["artists"])
    total_bytes = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
    if total_bytes > MAX_PACK_BYTES:
        raise ValueError("catalog total pack exceeds backup budget")
    known = [a for a in projected["artists"] if a["advertised_recording_count"] is not None]
    return {
        "verified": True,
        "selected_artists": 150,
        "artists_with_advertised_count": len(known),
        "advertised_per_artist_recording_count_sum": sum(
            a["advertised_recording_count"] for a in known
        ),
        "advertised_count_sum_is_not_unique_recordings": True,
        "unfetched_per_artist_recording_count_sum": sum(
            a["unfetched_recording_count"] for a in known
        ),
        "candidate_pairs": len(projected["pairs"]),
        "verified_recording_artist_pairs": observed,
        "unknown_catalog_count_artists": 150 - len(known),
        "actual_requests": len(ledger),
        "observed_native_body_bytes": sum(row["bytes"] for row in ledger),
        "pack_bytes": total_bytes,
        "representative_recordings_reviewed": 0,
        "media_requested": False,
    }
