"""Bounded source-selected CC0 genre entities and typed Wikidata taxonomy claims."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from opennoise.pipeline.foundation import _safe_path

if TYPE_CHECKING:
    from pathlib import Path

ENDPOINT: Final = "https://query.wikidata.org/sparql"
CLASS_URL: Final = "https://www.wikidata.org/wiki/Special:EntityData/Q188451.json"
CLASS_QID: Final = "Q188451"
SELECTION_LIMIT: Final = 1_000
ROW_LIMIT: Final = 2_000
BATCH_SIZE: Final = 200
REQUEST_LIMIT: Final = 10
RESPONSE_BYTE_LIMIT: Final = 2_000_000
TOTAL_BYTE_LIMIT: Final = 10_000_000
TIMEOUT_SECONDS: Final = 30.0
PREAMBLE_REQUESTS: Final = 2
PREFIXES: Final = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""
SELECTION_QUERY: Final = (
    PREFIXES
    + """SELECT DISTINCT ?genre ?anchor WHERE {
  VALUES ?anchor { wd:Q188451 }
  ?genre wdt:P31 ?anchor.
}
LIMIT 1000"""
)
QUERY_PLAN: Final[dict[str, object]] = {
    "version": 1,
    "class_qid": CLASS_QID,
    "class_url": CLASS_URL,
    "selection_query": SELECTION_QUERY,
    "selection": "direct Wikidata P31 Q188451, bounded endpoint order; no name/artist inputs",
    "selection_limit": SELECTION_LIMIT,
    "taxonomy_batch_size": BATCH_SIZE,
    "taxonomy_row_limit": ROW_LIMIT,
    "taxonomy_properties": ["P31", "P279"],
    "label_language": "en",
    "request_limit": REQUEST_LIMIT,
    "response_byte_limit": RESPONSE_BYTE_LIMIT,
    "total_byte_limit": TOTAL_BYTE_LIMIT,
    "timeout_seconds": TIMEOUT_SECONDS,
    "license": "CC0-1.0",
    "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
    "historical_inputs": [],
    "artist_membership_claims": [],
}


class CaptureRecord(BaseModel):
    """One successful or failed request and its preserved body byte binding."""

    model_config = ConfigDict(strict=True, extra="forbid")
    phase: Literal["class", "selection", "taxonomy"]
    requested_qids: list[str]
    query: str | None
    url: str
    observed_at: str
    elapsed_seconds: float = Field(ge=0)
    status_code: int | None
    error: str | None
    complete: bool
    raw_path: str
    size_bytes: int = Field(ge=0, le=RESPONSE_BYTE_LIMIT)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaxonomyManifest(BaseModel):
    """Frozen source-driven query policy and sequential request accounting."""

    model_config = ConfigDict(strict=True, extra="forbid")
    version: int = Field(ge=1, le=1)
    query_plan: dict[str, Any]
    requests: list[CaptureRecord] = Field(max_length=REQUEST_LIMIT)


class ArtifactBinding(BaseModel):
    """One exact artifact binding, shared by every source and projection file."""

    model_config = ConfigDict(strict=True, extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class TaxonomyReceipt(BaseModel):
    """Complete file-binding receipt for the source pack, with no implicit license upgrade."""

    model_config = ConfigDict(strict=True, extra="forbid")
    version: int = Field(ge=1, le=1)
    license: Literal["CC0-1.0"]
    files: dict[str, ArtifactBinding]


def taxonomy_query(qids: list[str]) -> str:
    """Expand only independently selected QIDs into direct P31/P279 source rows."""
    if not qids or len(qids) > BATCH_SIZE or len(qids) != len(set(qids)):
        raise ValueError("taxonomy batch must contain 1..200 unique QIDs")
    if any(re.fullmatch(r"Q[1-9][0-9]*", value) is None for value in qids):
        raise ValueError("taxonomy input must contain canonical QIDs, never name queries")
    values = " ".join(f"wd:{value}" for value in sorted(qids))
    return (
        PREFIXES
        + f"""SELECT ?genre ?genreLabel ?property ?value ?valueLabel WHERE {{
  VALUES ?genre {{ {values} }}
  VALUES ?property {{ wdt:P31 wdt:P279 }}
  ?genre ?property ?value.
  OPTIONAL {{ ?genre rdfs:label ?genreLabel. FILTER(LANG(?genreLabel) = "en") }}
  OPTIONAL {{ ?value rdfs:label ?valueLabel. FILTER(LANG(?valueLabel) = "en") }}
}}
LIMIT 2000"""
    )


def _qid(binding: dict[str, Any], key: str) -> str:
    term = binding.get(key)
    if not isinstance(term, dict) or term.get("type") != "uri":
        raise ValueError(f"{key} must be a Wikidata entity URI")
    value = term.get("value")
    if (
        not isinstance(value, str)
        or re.fullmatch(r"https?://www\.wikidata\.org/entity/Q[1-9][0-9]*", value) is None
    ):
        raise ValueError(f"invalid Wikidata entity URI in {key}")
    return str(value).rsplit("/", 1)[-1]


def _label(binding: dict[str, Any], key: str) -> str | None:
    term = binding.get(key)
    if term is None:
        return None
    if (
        not isinstance(term, dict)
        or term.get("type") != "literal"
        or term.get("xml:lang") != "en"
        or not isinstance(term.get("value"), str)
    ):
        raise ValueError(f"{key} must be an English label literal or absent")
    return str(term["value"])


def _bindings(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    results = payload.get("results")
    bindings = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(bindings, list) or len(bindings) > limit:
        raise ValueError("SPARQL bindings missing or exceed frozen row limit")
    if any(not isinstance(binding, dict) for binding in bindings):
        raise ValueError("SPARQL binding must be an object")
    return bindings


def parse_selection(payload: dict[str, Any]) -> list[str]:
    """Retain a bounded exact-ID source cohort; cap hits remain explicit."""
    bindings = _bindings(payload, SELECTION_LIMIT)
    qids = []
    for binding in bindings:
        if _qid(binding, "anchor") != CLASS_QID:
            raise ValueError("selection includes an unexpected type anchor")
        qids.append(_qid(binding, "genre"))
    if len(qids) != len(set(qids)):
        raise ValueError("selection contains duplicate entities")
    return sorted(qids)


def parse_taxonomy(payload: dict[str, Any], requested: list[str]) -> list[dict[str, Any]]:
    """Keep instance-of and subclass-of distinct; reject contextual properties."""
    rows = []
    for binding in _bindings(payload, ROW_LIMIT):
        genre = _qid(binding, "genre")
        if genre not in requested:
            raise ValueError("taxonomy response contains an unrequested genre QID")
        prop = binding.get("property", {})
        if prop.get("type") != "uri" or prop.get("value") not in {
            "http://www.wikidata.org/prop/direct/P31",
            "http://www.wikidata.org/prop/direct/P279",
        }:
            raise ValueError("taxonomy response contains a non-taxonomy property")
        property_id = prop["value"].rsplit("/", 1)[-1]
        rows.append(
            {
                "genre_qid": genre,
                "genre_label": _label(binding, "genreLabel"),
                "property_id": property_id,
                "property_role": "instance_of" if property_id == "P31" else "subclass_of",
                "value_qid": _qid(binding, "value"),
                "value_label": _label(binding, "valueLabel"),
                "statement_scope": "direct truthy Wikidata property; no rank/qualifier projection",
            }
        )
    return rows


def _body(root: Path, record: CaptureRecord) -> bytes:
    path = _safe_path(root, record.raw_path)
    if not path.is_file():
        raise ValueError("raw response is not a regular file")
    if path.stat().st_size != record.size_bytes:
        raise ValueError("raw response byte length mismatch")
    body = path.read_bytes()
    if len(body) != record.size_bytes or hashlib.sha256(body).hexdigest() != record.sha256:
        raise ValueError("raw response byte binding mismatch")
    return body


def _payload(root: Path, record: CaptureRecord) -> dict[str, Any]:
    body = _body(root, record)
    if record.status_code != httpx.codes.OK or record.error or not record.complete:
        raise ValueError(record.error or "request unsuccessful or response incomplete")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise TypeError("source response must be a JSON object")
    return parsed


def _verify_class(payload: dict[str, Any]) -> None:
    entity = payload.get("entities", {}).get(CLASS_QID, {})
    if (
        entity.get("id") != CLASS_QID
        or entity.get("labels", {}).get("en", {}).get("value") != "music genre"
    ):
        raise ValueError("Q188451 entity identity/English music genre class label is unverified")


def _expected_request(phase: str, qids: list[str]) -> tuple[str | None, str]:
    if phase == "class":
        return None, CLASS_URL
    query = SELECTION_QUERY if phase == "selection" else taxonomy_query(qids)
    return query, str(httpx.URL(ENDPOINT, params={"query": query, "format": "json"}))


def _validate_request(root: Path, record: CaptureRecord, index: int) -> None:
    query, url = _expected_request(record.phase, record.requested_qids)
    if record.query != query or record.url != url:
        raise ValueError("request does not match frozen source-only query")
    if record.raw_path != f"raw/request-{index:02d}.body":
        raise ValueError("raw path does not match sequential request ledger")
    timestamp = datetime.fromisoformat(record.observed_at)
    if timestamp.tzinfo is None:
        raise ValueError("capture time must include a timezone")
    _body(root, record)


def project_pack(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Replay exact raw source responses, including failure and truncation accounting."""
    parsed = TaxonomyManifest.model_validate(manifest)
    if parsed.query_plan != QUERY_PLAN:
        raise ValueError("manifest query plan differs from frozen independent selection policy")
    if sum(record.size_bytes for record in parsed.requests) > TOTAL_BYTE_LIMIT:
        raise ValueError("total source response budget exceeded")
    for index, record in enumerate(parsed.requests):
        _validate_request(root, record, index)
    class_verified, selected, selection_error = _selection_state(root, parsed.requests)
    batches = [
        selected[index : index + BATCH_SIZE] for index in range(0, len(selected), BATCH_SIZE)
    ]
    claims, taxonomy_status = _taxonomy_state(root, parsed.requests[2:], batches)
    labels = dict[str, str | None].fromkeys(selected)
    label_sources = dict[str, str | None].fromkeys(selected)
    for claim in claims:
        prior = labels[claim["genre_qid"]]
        label = claim["genre_label"]
        if prior is not None and label is not None and prior != label:
            raise ValueError("conflicting English labels for the same genre entity")
        if label is not None:
            labels[claim["genre_qid"]] = label
            label_sources[claim["genre_qid"]] = claim["source_capture_id"]
        claim["value_in_selected_cohort"] = claim["value_qid"] in labels
    observed_ids = {claim["genre_qid"] for claim in claims}
    return {
        "version": 1,
        "license": "CC0-1.0",
        "construction_scope": "bounded source-selected Wikidata genre taxonomy; incomplete corpus",
        "class_verified": class_verified,
        "selection_error": selection_error,
        "selection_possibly_truncated": len(selected) == SELECTION_LIMIT,
        "selection_order": "endpoint order without global sort; snapshot freezes returned IDs",
        "selected_qids": selected,
        "entities": [
            {
                "qid": qid,
                "english_label": labels[qid],
                "type_anchor": CLASS_QID,
                "type_anchor_source_capture_id": "raw/request-01.body",
                "english_label_source_capture_id": label_sources[qid],
                "source_type_role": "musical_genre_entity",
                "broad_sub_micro_level": None,
                "taxonomy_observed": qid in observed_ids,
            }
            for qid in selected
        ],
        "claims": claims,
        "source_captures": [
            {
                "id": record.raw_path,
                "phase": record.phase,
                "query_url": record.url,
                "observed_at": record.observed_at,
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
                "license": "CC0-1.0",
            }
            for record in parsed.requests
        ],
        "artist_memberships": [],
        "historical_inputs": [],
        "taxonomy_batches": taxonomy_status,
        "missing_taxonomy_qids": sorted(set(selected) - observed_ids),
        "taxonomy_complete_for_selected_cohort": bool(selected)
        and set(selected) == observed_ids
        and all(
            not batch["error"] and not batch.get("possibly_truncated") for batch in taxonomy_status
        ),
        "missing_english_labels": sorted(qid for qid, label in labels.items() if label is None),
        "request_count": len(parsed.requests),
        "response_bytes": sum(record.size_bytes for record in parsed.requests),
        "failed_request_count": sum(
            record.error is not None or record.status_code != httpx.codes.OK or not record.complete
            for record in parsed.requests
        ),
        "full_corpus_claim": False,
    }


def _selection_state(
    root: Path, requests: list[CaptureRecord]
) -> tuple[bool, list[str], str | None]:
    if not requests or requests[0].phase != "class" or requests[0].requested_qids != [CLASS_QID]:
        raise ValueError("first request must verify the musical genre class")
    try:
        _verify_class(_payload(root, requests[0]))
    except (TypeError, ValueError, AttributeError) as error:
        if len(requests) > 1:
            raise ValueError("selection must not continue after unverified class") from error
        return False, [], str(error)
    if len(requests) < PREAMBLE_REQUESTS:
        return True, [], "selection request absent"
    if requests[1].phase != "selection" or requests[1].requested_qids:
        raise ValueError("second request must be the frozen genre selection query")
    try:
        selected = parse_selection(_payload(root, requests[1]))
    except (TypeError, ValueError, AttributeError) as error:
        if len(requests) > PREAMBLE_REQUESTS:
            raise ValueError("taxonomy must not continue after failed selection") from error
        return True, [], str(error)
    return True, selected, None


def _taxonomy_state(
    root: Path, requests: list[CaptureRecord], batches: list[list[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(requests) > len(batches):
        raise ValueError("more taxonomy requests than frozen source cohort batches")
    claims: dict[str, dict[str, Any]] = {}
    statuses = []
    for index, qids in enumerate(batches):
        if index >= len(requests):
            statuses.append({"requested_qids": qids, "error": "batch not requested", "rows": 0})
            continue
        record = requests[index]
        if record.phase != "taxonomy" or record.requested_qids != qids:
            raise ValueError("taxonomy batches must match the exact frozen source cohort")
        try:
            payload = _payload(root, record)
            rows = parse_taxonomy(payload, qids)
        except (TypeError, ValueError, AttributeError) as error:
            statuses.append({"requested_qids": qids, "error": str(error), "rows": 0})
            continue
        for row in rows:
            claim = {
                **row,
                "source": ENDPOINT,
                "source_url": ENDPOINT,
                "source_capture_id": record.raw_path,
                "source_body_sha256": record.sha256,
                "observed_at": record.observed_at,
                "license": "CC0-1.0",
            }
            claims[json.dumps(row, sort_keys=True)] = claim
        statuses.append(
            {
                "requested_qids": qids,
                "error": None,
                "rows": len(rows),
                "possibly_truncated": len(rows) == ROW_LIMIT,
            }
        )
    return [claims[key] for key in sorted(claims)], statuses


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_chunk(body: bytearray, chunk: bytes, remaining: int, started: float) -> None:
    if time.monotonic() - started > TIMEOUT_SECONDS:
        raise TimeoutError("response exceeded request wall-clock budget")
    if len(body) + len(chunk) > min(remaining, RESPONSE_BYTE_LIMIT):
        raise ValueError("response or total byte budget exceeded; prefix retained")
    body.extend(chunk)


def _capture_request(
    root: Path,
    records: list[CaptureRecord],
    phase: Literal["class", "selection", "taxonomy"],
    qids: list[str],
    client: httpx.Client,
) -> None:
    if len(records) >= REQUEST_LIMIT:
        raise ValueError("request budget exhausted")
    remaining = TOTAL_BYTE_LIMIT - sum(record.size_bytes for record in records)
    query, url = _expected_request(phase, qids)
    started = time.monotonic()
    observed_at = datetime.now(UTC).isoformat()
    body = bytearray()
    status, error, complete = None, None, False
    try:
        with client.stream("GET", url, timeout=TIMEOUT_SECONDS) as response:
            status = response.status_code
            for chunk in response.iter_bytes(chunk_size=65_536):
                _append_chunk(body, chunk, remaining, started)
            complete = True
            if status != httpx.codes.OK:
                error = f"HTTP {status}"
    except (httpx.HTTPError, TimeoutError, ValueError) as failure:
        error = str(failure) or type(failure).__name__
    raw_path = f"raw/request-{len(records):02d}.body"
    (root / raw_path).write_bytes(body)
    records.append(
        CaptureRecord(
            phase=phase,
            requested_qids=qids,
            query=query,
            url=url,
            observed_at=observed_at,
            elapsed_seconds=time.monotonic() - started,
            status_code=status,
            error=error,
            complete=complete,
            raw_path=raw_path,
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
        )
    )
    _write_json(
        root / "manifest.json",
        {
            "version": 1,
            "query_plan": QUERY_PLAN,
            "requests": [record.model_dump() for record in records],
        },
    )


def capture_pack(root: Path, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Write a fresh bounded source pack; preserve endpoint failures as data."""
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    _write_json(root / "query-plan.json", QUERY_PLAN)
    records: list[CaptureRecord] = []
    session = client or httpx.Client(
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded CC0 musical genre taxonomy research)",
            "Accept": "application/sparql-results+json, application/json",
            "Accept-Encoding": "identity",
        }
    )
    try:
        _capture_request(root, records, "class", [CLASS_QID], session)
        manifest = {
            "version": 1,
            "query_plan": QUERY_PLAN,
            "requests": [r.model_dump() for r in records],
        }
        projection = project_pack(root, manifest)
        if projection["class_verified"]:
            _capture_request(root, records, "selection", [], session)
            manifest["requests"] = [r.model_dump() for r in records]
            projection = project_pack(root, manifest)
            selected = projection["selected_qids"]
            for index in range(0, len(selected), BATCH_SIZE):
                _capture_request(
                    root, records, "taxonomy", selected[index : index + BATCH_SIZE], session
                )
    finally:
        if client is None:
            session.close()
    manifest["requests"] = [r.model_dump() for r in records]
    projection = project_pack(root, manifest)
    _write_json(root / "projection.json", projection)
    names = ["query-plan.json", "manifest.json", "projection.json"] + [r.raw_path for r in records]
    _write_json(
        root / "receipt.json",
        {
            "version": 1,
            "license": "CC0-1.0",
            "files": {
                name: {
                    "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
                    "size_bytes": (root / name).stat().st_size,
                }
                for name in names
            },
        },
    )
    return verify_pack(root)


def verify_pack(root: Path) -> dict[str, Any]:
    """Verify declared bytes, source-only query policy and exact offline projection."""
    receipt = TaxonomyReceipt.model_validate_json(
        _safe_path(root, "receipt.json").read_text(encoding="utf-8")
    )
    for name, binding in receipt.files.items():
        path = _safe_path(root, name)
        if path.stat().st_size != binding.size_bytes:
            raise ValueError(f"artifact byte length mismatch: {name}")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != binding.sha256:
            raise ValueError(f"artifact byte binding mismatch: {name}")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = {"query-plan.json", "manifest.json", "projection.json"} | {
        record["raw_path"] for record in manifest["requests"]
    }
    if set(receipt.files) != expected:
        raise ValueError("receipt does not bind the complete declared artifact set")
    if json.loads((root / "query-plan.json").read_text(encoding="utf-8")) != QUERY_PLAN:
        raise ValueError("frozen query plan changed")
    projected = project_pack(root, manifest)
    if json.loads((root / "projection.json").read_text(encoding="utf-8")) != projected:
        raise ValueError("projected taxonomy differs from independent raw replay")
    return projected
