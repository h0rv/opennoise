"""Exact native P136 vocabulary and literal P279 context, independent of music inference."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import zstandard

from opennoise.ingest.wikidata.entity_evidence import (
    ENDPOINT,
    LANGUAGES,
    MAX_BODY,
    USER_AGENT,
    artist_identity_status,
    claims,
    digest,
    entities,
    file_digest,
    json_digest,
    verify,
    write,
)

BATCH_SIZE = 50
MAX_PARENT_IDS = 1450
MAX_OBSERVED_QIDS = 1003
HTTP_OK = 200


def genre_roster(source: Path) -> list[str]:
    """Derive the exact observed P136 vocabulary from native raw entity facts."""
    selected = json.loads((source / "selection.json").read_bytes())["artists"]
    wanted = {row["wikidata_qid"]: row["artist_mbid"] for row in selected}
    vocabulary = set()
    for record in json.loads((source / "captures.json").read_bytes()):
        if record["kind"] != "artists" or not record["admitted"]:
            continue
        native = entities((source / record["raw_path"]).read_bytes(), record["requested"])
        for qid, entity in native.items():
            if artist_identity_status(entity, wanted[qid]) != "exact_identity":
                continue
            for statement in claims(entity, "P136"):
                qid_value = native_item_reference(statement)
                if qid_value is not None:
                    vocabulary.add(qid_value)
    return sorted(vocabulary, key=lambda qid: int(qid[1:]))


def capture(root: Path, phase: str, index: int, requested: list[str]) -> dict[str, Any]:
    """Retain compressed exact native bytes and complete observed transport ledger."""
    params = {
        "action": "wbgetentities",
        "ids": "|".join(requested),
        "props": "claims|labels",
        "languages": LANGUAGES,
        "format": "json",
        "maxlag": "5",
    }
    started = datetime.now(UTC).isoformat()
    body = bytearray()
    status = None
    failure = None
    complete = False
    try:
        with (
            httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=45) as client,
            client.stream("GET", ENDPOINT, params=params) as response,
        ):
            status = response.status_code
            for chunk in response.iter_bytes(65536):
                if len(body) + len(chunk) > MAX_BODY:
                    failure = "response_byte_limit"
                    break
                body.extend(chunk)
            else:
                complete = True
    except httpx.HTTPError as error:
        failure = type(error).__name__
    original = bytes(body)
    admitted = False
    if status == HTTP_OK and complete:
        try:
            entities(original, requested)
            admitted = True
        except (ValueError, TypeError, KeyError) as error:
            failure = str(error)
    compressed = zstandard.ZstdCompressor(level=3).compress(original)
    stem = f"raw/{phase}-{index:03d}"
    with (root / (stem + ".json.zst")).open("xb") as stream:
        stream.write(compressed)
    record = {
        "phase": phase,
        "index": index,
        "requested": requested,
        "endpoint": ENDPOINT,
        "params": params,
        "started_utc": started,
        "finished_utc": datetime.now(UTC).isoformat(),
        "http_status": status,
        "body_complete": complete,
        "admitted": admitted,
        "failure": failure,
        "raw_path": stem + ".json.zst",
        "bytes": len(original),
        "sha256": digest(original),
        "compressed_bytes": len(compressed),
        "compressed_sha256": digest(compressed),
    }
    write(root / (stem + ".receipt.json"), record)
    time.sleep(0.25)
    return record


def project(root: Path, roster: list[str], captures: list[dict[str, Any]]) -> dict[str, Any]:
    """Project literal typed source claims; P31 is never a similarity edge."""
    found = {}
    for record in captures:
        if not record["admitted"]:
            continue
        body = zstandard.ZstdDecompressor().decompress(
            (root / record["raw_path"]).read_bytes(), max_output_size=MAX_BODY
        )
        for qid, entity in entities(body, record["requested"]).items():
            if qid in found:
                raise ValueError("duplicate native genre context identity")
            found[qid] = {
                "qid": qid,
                "role": "observed_P136" if qid in roster else "native_P279_parent",
                "status": "missing" if "missing" in entity else "native_entity",
                "labels": entity.get("labels", {}),
                "claims": {prop: claims(entity, prop) for prop in ("P31", "P279")},
                "raw_path": record["raw_path"],
                "raw_sha256": record["sha256"],
            }
    for qid in roster:
        found.setdefault(
            qid,
            {
                "qid": qid,
                "role": "observed_P136",
                "status": "response_unavailable",
                "labels": {},
                "claims": {"P31": [], "P279": []},
            },
        )
    return {
        "revision": "wikidata-native-genre-context-v1",
        "license": "CC0-1.0",
        "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
        "scope": "literal P31 type/P279 subclass source statements; no broad/sub/micro inference",
        "observed_P136_qids": roster,
        "entities": dict(sorted(found.items())),
    }


def parents(projection: dict[str, Any]) -> list[str]:
    """Freeze one outward native P279 hop, including explicit coverage gaps."""
    result = set()
    for qid in projection["observed_P136_qids"]:
        for claim in projection["entities"][qid]["claims"]["P279"]:
            qid_value = native_item_reference(claim)
            if qid_value is not None:
                result.add(qid_value)
    return sorted(result - set(projection["observed_P136_qids"]), key=lambda qid: int(qid[1:]))


def acquire(root: Path, source: Path, core: Path) -> dict[str, Any]:
    """Capture a separately named new pack without mutating the artist evidence."""
    source_verified = verify(source, core)
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    roster = genre_roster(source)
    if len(roster) > MAX_OBSERVED_QIDS:
        raise ValueError("this fixed experiment permits at most 1003 observed QIDs")
    selection = {
        "source_receipt_sha256": source_verified["receipt_sha256"],
        "source_projection_sha256": source_verified["projection_sha256"],
        "observed_P136_qids": roster,
        "parent_qid_cap": MAX_PARENT_IDS,
        "request_cap": 50,
        "body_byte_cap": MAX_BODY,
    }
    write(root / "selection.json", selection)
    batches = [roster[index : index + BATCH_SIZE] for index in range(0, len(roster), BATCH_SIZE)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        captures = list(pool.map(lambda pair: capture(root, "genres", *pair), enumerate(batches)))
    outward = parents(project(root, roster, captures))
    parent_roster = outward[:MAX_PARENT_IDS]
    batches = [
        parent_roster[index : index + BATCH_SIZE]
        for index in range(0, len(parent_roster), BATCH_SIZE)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        captures.extend(pool.map(lambda pair: capture(root, "parents", *pair), enumerate(batches)))
    write(root / "captures.json", captures)
    result = project(root, roster, captures)
    result["parent_qids_requested"] = parent_roster
    result["parent_qids_omitted_due_to_cap"] = outward[MAX_PARENT_IDS:]
    write(root / "projection.json", result)
    files = {
        str(path.relative_to(root)): {"bytes": path.stat().st_size, "sha256": file_digest(path)}
        for path in root.rglob("*")
        if path.is_file()
    }
    write(
        root / "receipt.json",
        {
            "revision": result["revision"],
            "files": files,
            "source_receipt_sha256": source_verified["receipt_sha256"],
        },
    )
    return verify_pack(root, source, core)


def verify_pack(root: Path, source: Path, core: Path) -> dict[str, Any]:
    """Replay compressed native bytes, fixed plan and exact upstream source custody."""
    upstream = verify(source, core)
    receipt = json.loads((root / "receipt.json").read_bytes())
    if receipt["revision"] != "wikidata-native-genre-context-v1":
        raise ValueError("unexpected genre context revision")
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if any(path.is_symlink() for path in root.rglob("*")) or root.is_symlink():
        raise ValueError("symlink in source pack")
    if actual != set(receipt["files"]) | {"receipt.json"}:
        raise ValueError("source file set differs from receipt")
    for relative, expected in receipt["files"].items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe source path")
        if expected != {"bytes": path.stat().st_size, "sha256": file_digest(path)}:
            raise ValueError("compressed source file hash differs")
    roster = genre_roster(source)
    selection = json.loads((root / "selection.json").read_bytes())
    if selection != {
        "source_receipt_sha256": upstream["receipt_sha256"],
        "source_projection_sha256": upstream["projection_sha256"],
        "observed_P136_qids": roster,
        "parent_qid_cap": MAX_PARENT_IDS,
        "request_cap": 50,
        "body_byte_cap": MAX_BODY,
    }:
        raise ValueError("genre selection differs from verified native artist source")
    captures = json.loads((root / "captures.json").read_bytes())
    verify_captures(root, captures, actual)
    result = project(root, roster, captures)
    outward = parents(result)
    result["parent_qids_requested"] = outward[:MAX_PARENT_IDS]
    result["parent_qids_omitted_due_to_cap"] = outward[MAX_PARENT_IDS:]
    expected = [
        ("genres", index // BATCH_SIZE, roster[index : index + BATCH_SIZE])
        for index in range(0, len(roster), BATCH_SIZE)
    ]
    expected += [
        ("parents", index // BATCH_SIZE, outward[index : index + BATCH_SIZE])
        for index in range(0, min(len(outward), MAX_PARENT_IDS), BATCH_SIZE)
    ]
    if [(row["phase"], row["index"], row["requested"]) for row in captures] != expected:
        raise ValueError("native genre request plan differs")
    if json_digest(result) != file_digest(root / "projection.json"):
        raise ValueError("native genre raw projection replay differs")
    return {
        "verified": True,
        "observed_P136_qid_count": len(roster),
        "parent_qids_requested": len(result["parent_qids_requested"]),
        "parent_qids_omitted_due_to_cap": len(result["parent_qids_omitted_due_to_cap"]),
        "native_entity_count": sum(
            row["status"] == "native_entity" for row in result["entities"].values()
        ),
        "P279_statement_count": sum(
            len(row["claims"]["P279"]) for row in result["entities"].values()
        ),
        "P31_statement_count": sum(
            len(row["claims"]["P31"]) for row in result["entities"].values()
        ),
        "source_receipt_sha256": upstream["receipt_sha256"],
        "receipt_sha256": file_digest(root / "receipt.json"),
        "projection_sha256": file_digest(root / "projection.json"),
        "http_statuses": dict(Counter(str(row["http_status"]) for row in captures)),
        "pack_bytes": sum((root / name).stat().st_size for name in actual),
        "pack_files": len(actual),
    }


def verify_captures(root: Path, captures: list[dict[str, Any]], actual: set[str]) -> None:
    """Reject unapproved capture files, falsified ledger and decompressed byte mismatches."""
    expected_files = {"selection.json", "captures.json", "projection.json", "receipt.json"}
    for row in captures:
        if (
            row["phase"] not in {"genres", "parents"}
            or type(row["index"]) is not int
            or row["index"] < 0
        ):
            raise ValueError("unapproved native capture identity")
        stem = f"raw/{row['phase']}-{row['index']:03d}"
        expected_files.update({stem + ".json.zst", stem + ".receipt.json"})
        verify_capture(root, row, stem)
    if actual != expected_files:
        raise ValueError("unapproved native source file")


def verify_capture(root: Path, row: dict[str, Any], stem: str) -> None:
    """Check one compressed-body ledger with bounded decompression."""
    if row["raw_path"] != stem + ".json.zst":
        raise ValueError("noncanonical capture path")
    if row != json.loads((root / (stem + ".receipt.json")).read_bytes()):
        raise ValueError("native transport ledger differs")
    started, finished = (
        datetime.fromisoformat(row[key]) for key in ("started_utc", "finished_utc")
    )
    if (
        started.utcoffset() != UTC.utcoffset(None)
        or finished.utcoffset() != UTC.utcoffset(None)
        or finished < started
    ):
        raise ValueError("invalid UTC transport timestamps")
    compressed = (root / row["raw_path"]).read_bytes()
    if zstandard.frame_content_size(compressed) > MAX_BODY or row["bytes"] > MAX_BODY:
        raise ValueError("native response exceeds fixed byte cap")
    original = zstandard.ZstdDecompressor().decompress(compressed, max_output_size=MAX_BODY)
    if len(original) != row["bytes"] or digest(original) != row["sha256"]:
        raise ValueError("decompressed native bytes differ")
    if len(compressed) != row["compressed_bytes"] or digest(compressed) != row["compressed_sha256"]:
        raise ValueError("compressed native bytes differ")
    if row["endpoint"] != ENDPOINT or row["params"] != {
        "action": "wbgetentities",
        "ids": "|".join(row["requested"]),
        "props": "claims|labels",
        "languages": LANGUAGES,
        "format": "json",
        "maxlag": "5",
    }:
        raise ValueError("native capture parameters differ")
    admitted = capture_admission(row, original)
    if row["admitted"] != admitted:
        raise ValueError("native status admission differs")


def capture_admission(row: dict[str, Any], original: bytes) -> bool:
    """Replay native status/schema admission without inventing HTTP success."""
    admitted = False
    if row["http_status"] == HTTP_OK and row["body_complete"]:
        try:
            entities(original, row["requested"])
            admitted = True
        except (ValueError, TypeError, KeyError):
            pass
    return admitted


def native_item_reference(statement: dict[str, Any]) -> str | None:
    """Admit only literal native item references with canonical QIDs."""
    data = statement["datavalue"]
    value = data.get("value")
    if data.get("type") != "wikibase-entityid" or not isinstance(value, dict):
        return None
    qid = value.get("id")
    if not isinstance(qid, str) or not re.fullmatch(r"Q[1-9][0-9]*", qid):
        return None
    if value.get("entity-type", "item") != "item":
        return None
    return qid
