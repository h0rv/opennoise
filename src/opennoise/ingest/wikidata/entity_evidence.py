"""Bounded CC0 entity evidence with a frozen source-only roster and offline replay."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

import httpx

from opennoise.ingest.wikidata.global_artist_genres import (
    _core_names_for,
    _mbid,
    _parse_scan,
    _verify_core_source,
)

ENDPOINT = "https://www.wikidata.org/w/api.php"
LANGUAGES = "en|es|fr|de|ja|zh|pt|ar|ru|hi|ko|it|id|tr|pl|sv"
PROPERTIES = (
    "P136",
    "P31",
    "P279",
    "P17",
    "P27",
    "P495",
    "P740",
    "P19",
    "P1412",
    "P571",
    "P569",
    "P570",
    "P576",
)
MAX_BODY = 10_000_000
MAX_ARTISTS = 20_000
HTTP_OK = 200
USER_AGENT = (
    "OpenNoiseResearch/0.1 (https://github.com/h0rv/opennoise; CC0 music evidence research)"
)


def digest(body: bytes) -> str:
    """Return the SHA256 of exact bytes."""
    return hashlib.sha256(body).hexdigest()


def write(path: Path, value: object) -> None:
    """Write immutable canonical JSON without replacing existing work."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def claims(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    """Retain literal non-deprecated statements; never infer musical semantics."""
    result = []
    for claim in entity.get("claims", {}).get(prop, []):
        snak = claim.get("mainsnak", {})
        if claim.get("rank") == "deprecated" or snak.get("snaktype") != "value":
            continue
        value = snak.get("datavalue")
        if isinstance(value, dict):
            result.append(
                {
                    "statement_id": claim.get("id"),
                    "rank": claim.get("rank"),
                    "datavalue": value,
                    "qualifiers": claim.get("qualifiers", {}),
                    "reference_count": len(claim.get("references", [])),
                    "references_retained_in_raw": True,
                }
            )
    return sorted(result, key=lambda row: json.dumps(row, sort_keys=True))


def entities(body: bytes, requested: list[str]) -> dict[str, Any]:
    """Validate exact requested entity identities."""
    data = json.loads(body)
    if "error" in data or not isinstance(data.get("entities"), dict):
        raise ValueError("entity response has no successful entity map")
    result = data["entities"]
    if set(result) != set(requested):
        raise ValueError("entity response IDs differ from the frozen request")
    for qid, entity in result.items():
        if (entity.get("id") != qid or entity.get("type") != "item") and "missing" not in entity:
            raise ValueError("unexpected entity identity or type")
    return result


def roster(
    scan: bytes, core: Path, limit: int, *, raw_binding_cap: bool = True
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Freeze UUID-hash selection before labels or target hydration."""
    if not 1 <= limit <= MAX_ARTISTS:
        raise ValueError("artist limit must be 1..20000")
    scan_body = scan
    if raw_binding_cap:
        payload = json.loads(scan)
        payload["results"]["bindings"] = payload["results"]["bindings"][:MAX_ARTISTS]
        scan_body = json.dumps(payload).encode()
        del payload
    parsed, rejected = _parse_scan(scan_body)
    mbids: dict[str, set[str]] = {}
    qids: dict[str, set[str]] = {}
    for qid, mbid, _genre in parsed[:MAX_ARTISTS]:
        mbids.setdefault(mbid, set()).add(qid)
        qids.setdefault(qid, set()).add(mbid)
    receipt, data_path = _verify_core_source(core)
    names = _core_names_for(set(mbids), data_path, receipt["artist_count"])
    eligible = [
        {"artist_mbid": mbid, "wikidata_qid": next(iter(qset)), "name": names[mbid][0]}
        for mbid, qset in mbids.items()
        if len(qset) == 1 and len(qids[next(iter(qset))]) == 1 and len(names.get(mbid, [])) == 1
    ]
    eligible.sort(key=lambda row: digest(("entity-evidence-v1:" + row["artist_mbid"]).encode()))
    accounting = {
        "scan_rows": len(parsed),
        "scan_rejected_rows": rejected,
        "unique_source_mbids": len(mbids),
        "core_eligible_unambiguous": len(eligible),
        "selection": "SHA256 entity-evidence-v1:UUID before hydration; no labels or targets",
        "core_receipt_sha256": digest((core / "receipt.json").read_bytes()),
        "core_output_sha256": receipt["output_sha256"],
    }
    if raw_binding_cap:
        accounting["scan_raw_binding_limit"] = MAX_ARTISTS
    return eligible[:limit], accounting


def capture(root: Path, kind: str, index: int, requested: list[str]) -> dict[str, Any]:
    """Save bounded response bytes and actual status/time ledger."""
    params = {
        "action": "wbgetentities",
        "ids": "|".join(requested),
        "props": "claims|labels" if kind == "artists" else "labels",
        "languages": LANGUAGES,
        "format": "json",
        "maxlag": "5",
    }
    started = datetime.now(UTC).isoformat()
    body = b""
    status = None
    failure = None
    complete = False
    try:
        with (
            httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=45) as client,
            client.stream("GET", ENDPOINT, params=params) as response,
        ):
            status = response.status_code
            collected = bytearray()
            for chunk in response.iter_bytes(65536):
                if len(collected) + len(chunk) > MAX_BODY:
                    failure = "response_byte_limit"
                    break
                collected.extend(chunk)
            else:
                complete = True
            body = bytes(collected)
    except httpx.HTTPError as error:
        failure = type(error).__name__
    raw_path = f"raw/{kind}-{index:04d}.json"
    with (root / raw_path).open("xb") as stream:
        stream.write(body)
    admitted = False
    if status == HTTP_OK and complete:
        try:
            entities(body, requested)
            admitted = True
        except (ValueError, TypeError, KeyError) as error:
            failure = str(error)
    record = {
        "kind": kind,
        "index": index,
        "endpoint": ENDPOINT,
        "params": params,
        "requested": requested,
        "started_utc": started,
        "finished_utc": datetime.now(UTC).isoformat(),
        "http_status": status,
        "failure": failure,
        "body_complete": complete,
        "admitted": admitted,
        "raw_path": raw_path,
        "bytes": len(body),
        "sha256": digest(body),
    }
    write(root / f"raw/{kind}-{index:04d}.receipt.json", record)
    time.sleep(0.25)
    return record


def project(
    root: Path, selected: list[dict[str, str]], captures: list[dict[str, Any]]
) -> dict[str, Any]:
    """Replay direct non-deprecated statements from successful captures."""
    selected_by_qid = {row["wikidata_qid"]: row for row in selected}
    rows_by_qid = {}
    vocabulary = {}
    seen = set()
    for record in captures:
        if not record["admitted"]:
            continue
        parsed = entities((root / record["raw_path"]).read_bytes(), record["requested"])
        for qid, entity in parsed.items():
            key = (record["kind"], qid)
            if key in seen:
                raise ValueError("duplicate hydrated QIDs")
            seen.add(key)
            if record["kind"] == "context":
                if "missing" not in entity:
                    vocabulary[qid] = {
                        "qid": qid,
                        "labels": entity.get("labels", {}),
                        "claims": {},
                        "scope": "native multilingual labels only",
                    }
                continue
            row = selected_by_qid[qid]
            reason = artist_identity_status(entity, row["artist_mbid"])
            projected = {
                **row,
                "status": reason,
                "raw_path": record["raw_path"],
                "raw_sha256": record["sha256"],
            }
            if reason == "exact_identity":
                projected.update(
                    {
                        "labels": entity.get("labels", {}),
                        "claims": {prop: claims(entity, prop) for prop in PROPERTIES},
                    }
                )
            rows_by_qid[qid] = projected
        del parsed
    artist_rows = [
        rows_by_qid.get(row["wikidata_qid"], {**row, "status": "response_unavailable"})
        for row in selected
    ]
    outcomes = Counter(row["status"] for row in artist_rows)
    context = dict(sorted(vocabulary.items()))
    return {
        "revision": "wikidata-entity-evidence-v1",
        "license": "CC0-1.0",
        "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
        "scope": "literal source statements only; no calibrated membership or completeness claim",
        "selected_artist_count": len(selected),
        "outcomes": dict(sorted(outcomes.items())),
        "artists": artist_rows,
        "context_entities": context,
    }


def acquire(root: Path, scan_path: Path, core: Path, limit: int) -> dict[str, Any]:
    """Acquire a new pack without mutating any prior source."""
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    scan = scan_path.read_bytes()
    (root / "source-scan.json").write_bytes(scan)
    selected, accounting = roster(scan, core, limit)
    write(root / "selection.json", {"artists": selected, "accounting": accounting})
    batches = [
        sorted({row["wikidata_qid"] for row in selected[index : index + 50]})
        for index in range(0, len(selected), 50)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        captures = list(pool.map(lambda pair: capture(root, "artists", *pair), enumerate(batches)))
    return finish(root, core, captures=captures)


def finish(
    root: Path, core: Path, *, captures: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Finish an interrupted capture without replacing any existing artifact."""
    selection = json.loads((root / "selection.json").read_bytes())
    selected = selection["artists"]
    accounting = selection["accounting"]
    limit = len(selected)
    if captures is None:
        replayed, replay_accounting = roster(
            (root / "source-scan.json").read_bytes(),
            core,
            limit,
            raw_binding_cap="scan_raw_binding_limit" in accounting,
        )
        if selected != replayed or accounting != replay_accounting:
            raise ValueError("cannot resume a changed frozen source roster")
        captures = [
            json.loads(path.read_bytes())
            for path in sorted(root.glob("raw/artists-*.receipt.json"))
        ]
        expected = [
            sorted({row["wikidata_qid"] for row in selected[index : index + 50]})
            for index in range(0, len(selected), 50)
        ]
        if [(row["index"], row["requested"]) for row in captures] != list(enumerate(expected)):
            raise ValueError("cannot finish an incomplete frozen artist capture plan")
        verify_capture_receipts(root, captures)
    interim = project(root, selected, captures)
    context_qids = set()
    for row in interim["artists"]:
        for values in row.get("claims", {}).values():
            for claim in values:
                value = claim["datavalue"].get("value")
                if isinstance(value, dict) and re.fullmatch(
                    r"Q[1-9][0-9]*", str(value.get("id", ""))
                ):
                    context_qids.add(value["id"])
    context_list = sorted(context_qids, key=lambda qid: int(qid[1:]))[:5000]
    del interim
    batches = [context_list[index : index + 50] for index in range(0, len(context_list), 50)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        captures.extend(pool.map(lambda pair: capture(root, "context", *pair), enumerate(batches)))
    write(root / "captures.json", captures)
    result = project(root, selected, captures)
    result["context_requested"] = context_list
    result["context_omitted_due_to_cap"] = len(context_qids) - len(context_list)
    write(root / "projection.json", result)
    files = {
        str(path.relative_to(root)): {
            "bytes": path.stat().st_size,
            "sha256": file_digest(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    write(
        root / "receipt.json",
        {
            "revision": result["revision"],
            "files": files,
            "core": accounting,
            "limit": limit,
            "http_statuses": dict(Counter(str(row["http_status"]) for row in captures)),
        },
    )
    return verify(root, core)


def verify(root: Path, core: Path) -> dict[str, Any]:
    """Replay all raw bytes, frozen selection, request plan and projections."""
    receipt = json.loads((root / "receipt.json").read_bytes())
    if receipt.get("revision") != "wikidata-entity-evidence-v1":
        raise ValueError("unexpected evidence revision")
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("symlink in evidence pack")
    if actual != set(receipt["files"]) | {"receipt.json"}:
        raise ValueError("evidence file set is not closed")
    for relative, expected in receipt["files"].items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe evidence path")
        if expected != {"bytes": path.stat().st_size, "sha256": file_digest(path)}:
            raise ValueError("evidence byte integrity failure")
    selected, accounting = roster(
        (root / "source-scan.json").read_bytes(),
        core,
        receipt["limit"],
        raw_binding_cap="scan_raw_binding_limit" in receipt["core"],
    )
    if json.loads((root / "selection.json").read_bytes()) != {
        "artists": selected,
        "accounting": accounting,
    }:
        raise ValueError("source-only roster replay differs")
    captures = json.loads((root / "captures.json").read_bytes())
    verify_closed_capture_files(actual, captures)
    verify_capture_receipts(root, captures)
    validate_capture_plan(root, selected, captures)
    result = streaming_projection(root, selected, captures)
    expected_context = context_plan_from_captures(root, selected, captures)
    result["context_requested"] = expected_context[:5000]
    result["context_omitted_due_to_cap"] = max(0, len(expected_context) - 5000)
    if json_digest(result) != file_digest(root / "projection.json"):
        raise ValueError("raw entity projection replay differs")
    return {
        "verified": True,
        "selected_artist_count": len(selected),
        "outcomes": result["outcomes"],
        "context_entity_count": len(result["context_entities"]),
        "pack_files": len(actual),
        "pack_bytes": sum((root / name).stat().st_size for name in actual),
        "projection_sha256": file_digest(root / "projection.json"),
        "receipt_sha256": digest((root / "receipt.json").read_bytes()),
    }


def context_plan(projection: dict[str, Any]) -> list[str]:
    """Derive context QIDs from exact artist entity references without labels."""
    qids = set()
    for row in projection["artists"]:
        for values in row.get("claims", {}).values():
            for claim in values:
                value = claim["datavalue"].get("value")
                if isinstance(value, dict) and re.fullmatch(
                    r"Q[1-9][0-9]*", str(value.get("id", ""))
                ):
                    qids.add(value["id"])
    return sorted(qids, key=lambda qid: int(qid[1:]))


def validate_capture_plan(
    root: Path, selected: list[dict[str, str]], captures: list[dict[str, Any]]
) -> None:
    """Reject post hoc request selection and forged successful admission flags."""
    artists = [record for record in captures if record["kind"] == "artists"]
    expected = [
        sorted({row["wikidata_qid"] for row in selected[index : index + 50]})
        for index in range(0, len(selected), 50)
    ]
    context = context_plan_from_captures(root, selected, artists)[:5000]
    context_batches = [context[index : index + 50] for index in range(0, len(context), 50)]
    expected_pairs = [("artists", index, batch) for index, batch in enumerate(expected)]
    expected_pairs.extend(("context", index, batch) for index, batch in enumerate(context_batches))
    if [(row["kind"], row["index"], row["requested"]) for row in captures] != expected_pairs:
        raise ValueError("request plan differs from frozen raw-derived roster")
    for row in captures:
        admitted = False
        if row["http_status"] == HTTP_OK and row["body_complete"]:
            try:
                entities((root / row["raw_path"]).read_bytes(), row["requested"])
                admitted = True
            except (ValueError, TypeError, KeyError):
                pass
        if row["admitted"] != admitted:
            raise ValueError("capture admission disagrees with response status/body")


def verify_capture_receipts(root: Path, captures: list[dict[str, Any]]) -> None:
    """Validate each raw response against its separately persisted request ledger."""
    for capture_row in captures:
        kind = capture_row["kind"]
        index = capture_row["index"]
        if kind not in {"artists", "context"} or type(index) is not int or index < 0:
            raise ValueError("unapproved capture identity")
        for field in ("started_utc", "finished_utc"):
            stamp = capture_row[field]
            if not isinstance(stamp, str) or datetime.fromisoformat(
                stamp
            ).utcoffset() != UTC.utcoffset(None):
                raise ValueError("capture timestamp must be actual UTC ledger text")
        if datetime.fromisoformat(capture_row["finished_utc"]) < datetime.fromisoformat(
            capture_row["started_utc"]
        ):
            raise ValueError("capture finish precedes start")
        expected_path = f"raw/{kind}-{index:04d}.json"
        if capture_row["raw_path"] != expected_path or capture_row["bytes"] > MAX_BODY:
            raise ValueError("capture path or byte limit differs")
        if capture_row != json.loads(
            (
                root / f"raw/{capture_row['kind']}-{capture_row['index']:04d}.receipt.json"
            ).read_bytes()
        ):
            raise ValueError("capture receipt differs")
        body = (root / capture_row["raw_path"]).read_bytes()
        if capture_row["sha256"] != digest(body) or capture_row["bytes"] != len(body):
            raise ValueError("capture byte seal differs")
        if capture_row["endpoint"] != ENDPOINT or capture_row["params"] != {
            "action": "wbgetentities",
            "ids": "|".join(capture_row["requested"]),
            "props": "claims|labels" if capture_row["kind"] == "artists" else "labels",
            "languages": LANGUAGES,
            "format": "json",
            "maxlag": "5",
        }:
            raise ValueError("capture request differs")


def file_digest(path: Path) -> str:
    """Hash immutable bytes with bounded memory."""
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for body in iter(lambda: stream.read(65536), b""):
            hashed.update(body)
    return hashed.hexdigest()


def json_digest(value: object) -> str:
    """Hash the canonical replay projection without duplicating its serialized bytes."""
    hashed = hashlib.sha256()
    for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True, indent=2).iterencode(value):
        hashed.update(chunk.encode())
    hashed.update(b"\n")
    return hashed.hexdigest()


def verify_closed_capture_files(actual: set[str], captures: list[dict[str, Any]]) -> None:
    """Reject even self-rehashed unrelated files outside the exact capture plan."""
    expected_files = {
        "source-scan.json",
        "selection.json",
        "captures.json",
        "projection.json",
        "receipt.json",
    }
    for record in captures:
        stem = f"raw/{record['kind']}-{record['index']:04d}"
        expected_files.update({stem + ".json", stem + ".receipt.json"})
    if actual != expected_files:
        raise ValueError("evidence pack contains unapproved files")


def artist_identity_status(entity: dict[str, Any], expected: str) -> str:
    """Quarantine malformed/nonunique native identifiers instead of guessing joins."""
    identifiers = set()
    try:
        for row in claims(entity, "P434"):
            if row["datavalue"].get("type") != "string":
                return "P434_malformed"
            identifiers.add(_mbid(row["datavalue"].get("value")))
    except ValueError:
        return "P434_malformed"
    return "exact_identity" if identifiers == {expected} else "P434_not_unique_exact"


class StreamingRows(list[dict[str, Any]]):
    """Present canonical JSON list semantics without retaining all projected artist rows."""

    def __init__(self, factory: Callable[[], Iterator[dict[str, Any]]], count: int) -> None:
        """Bind a fresh deterministic iterator for every serialization."""
        super().__init__()
        self.factory = factory
        self.row_count = count

    @override
    def __len__(self) -> int:
        return self.row_count

    @override
    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self.factory()


def iter_artist_rows(
    root: Path, selected: list[dict[str, str]], captures: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Replay one original fifty-entity artist batch at a time, preserving frozen order."""
    batches = {row["index"]: row for row in captures if row["kind"] == "artists"}
    for index in range(0, len(selected), 50):
        part = selected[index : index + 50]
        batch = batches.get(index // 50)
        yield from project(root, part, [batch] if batch is not None else [])["artists"]


def context_plan_from_captures(
    root: Path, selected: list[dict[str, str]], captures: list[dict[str, Any]]
) -> list[str]:
    """Derive the exact context request plan with bounded per-batch projection memory."""
    return context_plan(
        {
            "artists": StreamingRows(
                lambda: iter_artist_rows(root, selected, captures), len(selected)
            )
        }
    )


def streaming_projection(
    root: Path, selected: list[dict[str, str]], captures: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reconstruct every canonical projection byte without storing all ten thousand rows."""
    contexts = [row for row in captures if row["kind"] == "context"]
    result = project(root, [], contexts)
    outcomes = Counter(row["status"] for row in iter_artist_rows(root, selected, captures))
    result["selected_artist_count"] = len(selected)
    result["outcomes"] = dict(sorted(outcomes.items()))
    result["artists"] = StreamingRows(
        lambda: iter_artist_rows(root, selected, captures), len(selected)
    )
    return result
