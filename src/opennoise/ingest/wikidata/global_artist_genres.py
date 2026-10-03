"""Acquire and replay a bounded, source-driven Wikidata artist-genre cohort."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import zstandard

ENDPOINT = "https://query.wikidata.org/sparql"
LICENSE = "CC0"
LICENSE_URL = "https://www.wikidata.org/wiki/Wikidata:Licensing"
CORE_LICENSE = "CC0-1.0"
CORE_DEFAULT = Path("/workspace/opennoise/.cache/musicbrainz-core-artist-identities-20261002-v1")
DEFAULT_PACK = Path("/workspace/opennoise/.cache/wikidata-global-musical-artists-20261002-v1")
INITIAL_QUERY = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wd: <http://www.wikidata.org/entity/>
SELECT ?artist ?mbid ?genre WHERE {
  ?genre wdt:P31 wd:Q188451 .
  ?artist wdt:P434 ?mbid; wdt:P136 ?genre .
}
LIMIT 20001"""
MAX_SCAN_ROWS = 20_000
MAX_SCAN_RESPONSE_BYTES = 10_000_000
MAX_DETAIL_RESPONSE_BYTES = 2_000_000
MAX_TOTAL_RESPONSE_BYTES = 20_000_000
MAX_PACK_BYTES = 30_000_000
MAX_FOLLOWUP_REQUESTS = 20
MAX_ENTITIES_PER_BATCH = 500
RETRY_ENTITIES_PER_BATCH = 50
MAX_ARTISTS = 3_000
HTTP_OK = 200
DIRECT_CLAIM_SCOPE = (
    "direct Wikidata P136 statement; source assertion, not a human-reviewed genre judgment"
)
LICENSE_SCOPE = (
    "Wikidata structured data only: raw query responses, exact P434/P136 crosswalks "
    "and direct P31/label context; CC0"
)


class GlobalArtistGenreError(ValueError):
    """Reject invalid source captures, crosswalks, or offline projections."""


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
            count += len(chunk)
    return digest.hexdigest(), count


def _write_json(path: Path, value: object) -> bytes:
    body = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(body)
    return body


def _replace_json(path: Path, value: object) -> bytes:
    body = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(body)
    return body


def _safe_file(directory: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise GlobalArtistGenreError("pack paths must be safe relative paths")
    candidate = directory.joinpath(*path.parts)
    current = directory
    if current.is_symlink():
        raise GlobalArtistGenreError("pack root cannot be a symlink")
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise GlobalArtistGenreError("pack files cannot traverse symlinks")
    if not candidate.resolve().is_relative_to(directory.resolve()):
        raise GlobalArtistGenreError("pack path escapes its root")
    return candidate


def _qid(value: object) -> str:
    if not isinstance(value, str):
        raise GlobalArtistGenreError("Wikidata entity QID must be a string")
    parsed = urlparse(value)
    qid = parsed.path.rsplit("/", 1)[-1]
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc != "www.wikidata.org"
        or parsed.path != f"/entity/{qid}"
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"Q[1-9][0-9]*", qid)
    ):
        raise GlobalArtistGenreError("Wikidata result contains a noncanonical QID")
    return qid


def _mbid(value: object) -> str:
    if not isinstance(value, str):
        raise GlobalArtistGenreError("MusicBrainz ID must be a canonical UUID")
    try:
        if str(UUID(value)) != value:
            raise GlobalArtistGenreError("MusicBrainz ID must be a canonical UUID")
    except ValueError as error:
        raise GlobalArtistGenreError("MusicBrainz ID must be a canonical UUID") from error
    return value


def _english(binding: dict[str, Any], name: str) -> str | None:
    item = binding.get(name)
    if item is None:
        return None
    if (
        not isinstance(item, dict)
        or item.get("xml:lang") != "en"
        or not isinstance(item.get("value"), str)
    ):
        raise GlobalArtistGenreError(f"{name} must be an English Wikidata label")
    value = item["value"]
    if not isinstance(value, str):
        raise GlobalArtistGenreError(f"{name} must be an English Wikidata label")
    return value


def _capture(
    client: httpx.Client,
    query: str,
    raw_path: Path,
    byte_limit: int,
) -> dict[str, Any]:
    """Preserve response status and bounded bytes, including non-success bodies."""
    body = bytearray()
    status: int | None = None
    failure: str | None = None
    over_limit = False
    try:
        with client.stream("GET", ENDPOINT, params={"query": query}) as response:
            status = response.status_code
            for chunk in response.iter_bytes(chunk_size=65_536):
                room = byte_limit - len(body)
                if len(chunk) > room:
                    body.extend(chunk[: max(0, room)])
                    over_limit = True
                    failure = "response_byte_limit"
                    break
                body.extend(chunk)
    except httpx.HTTPError as error:
        failure = f"network_error:{type(error).__name__}"
    raw_path.write_bytes(body)
    return {
        "http_status": status,
        "response_bytes": len(body),
        "response_sha256": _sha256_bytes(bytes(body)),
        "body_complete": not over_limit and failure is None,
        "failure": failure,
        "raw_path": raw_path.name,
    }


def _parse_scan(body: bytes) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]]]:
    try:
        payload = json.loads(body)
        bindings = payload["results"]["bindings"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise GlobalArtistGenreError("initial Wikidata response is not SPARQL JSON") from error
    if not isinstance(bindings, list):
        raise GlobalArtistGenreError("initial Wikidata bindings must be a list")
    rows: list[tuple[str, str, str]] = []
    rejected: list[dict[str, Any]] = []
    for index, binding in enumerate(bindings[:MAX_SCAN_ROWS]):
        if not isinstance(binding, dict):
            rejected.append(
                {
                    "row_index": index,
                    "reason": "binding_not_object",
                    "binding_sha256": _sha256_bytes(json.dumps(binding, sort_keys=True).encode()),
                }
            )
            continue
        try:
            row = (
                _qid(binding.get("artist", {}).get("value")),
                _mbid(binding.get("mbid", {}).get("value")),
                _qid(binding.get("genre", {}).get("value")),
            )
        except (AttributeError, GlobalArtistGenreError) as error:
            rejected.append(
                {
                    "row_index": index,
                    "reason": type(error).__name__,
                    "binding_sha256": _sha256_bytes(json.dumps(binding, sort_keys=True).encode()),
                }
            )
            continue
        rows.append(row)
    return rows, rejected


def _verify_core_source(core_dir: Path) -> tuple[dict[str, Any], Path]:
    receipt_path = core_dir / "receipt.json"
    data_path = core_dir / "artist-identities.jsonl.zst"
    if core_dir.is_symlink() or receipt_path.is_symlink() or data_path.is_symlink():
        raise GlobalArtistGenreError("core identity source cannot contain symlinked paths")
    receipt = json.loads(receipt_path.read_bytes())
    if (
        receipt.get("revision") != "musicbrainz-core-artist-identities-v1"
        or receipt.get("license") != CORE_LICENSE
        or receipt.get("verified_complete") is not True
        or receipt.get("fields") != ["artist_mbid", "name"]
        or receipt.get("genre_memberships") != "absent; identities are not genre evidence"
        or receipt.get("derived_tables_consumed") != []
        or receipt.get("output_file") != data_path.name
        or receipt.get("source_archive_sha256_verified") is not False
    ):
        raise GlobalArtistGenreError(
            "core identity receipt does not describe the CC0 identity-only source"
        )
    digest, byte_count = _sha256_file(data_path)
    if digest != receipt.get("output_sha256") or byte_count != receipt.get("output_bytes"):
        raise GlobalArtistGenreError("core identity output hash or byte count differs from receipt")
    return receipt, data_path


def _core_names_for(
    candidates: set[str], core_path: Path, expected_rows: int
) -> dict[str, list[str]]:
    """Stream the full compressed core table while retaining names for target UUIDs only."""
    found: dict[str, list[str]] = defaultdict(list)
    count = 0
    try:
        with core_path.open("rb") as compressed:
            reader = zstandard.ZstdDecompressor().stream_reader(compressed)
            with reader:
                buffered = io.BufferedReader(reader)
                for line in buffered:
                    if not line.strip():
                        continue
                    count += 1
                    row = json.loads(line)
                    if not isinstance(row, dict) or set(row) != {"artist_mbid", "name"}:
                        raise GlobalArtistGenreError("core identity row has an unexpected schema")
                    artist_id = _mbid(row["artist_mbid"])
                    name = row["name"]
                    if not isinstance(name, str) or not name:
                        raise GlobalArtistGenreError("core identity row has an empty native name")
                    if artist_id in candidates:
                        found[artist_id].append(name)
    except (OSError, zstandard.ZstdError, json.JSONDecodeError) as error:
        raise GlobalArtistGenreError("core identity output cannot be streamed") from error
    if count != expected_rows:
        raise GlobalArtistGenreError("core identity row count differs from receipt")
    return found


def _scan_groups(
    rows: list[tuple[str, str, str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    qids_by_mbid: dict[str, set[str]] = defaultdict(set)
    genres_by_mbid: dict[str, set[str]] = defaultdict(set)
    mbids_by_qid: dict[str, set[str]] = defaultdict(set)
    for qid, artist_id, genre_qid in rows:
        qids_by_mbid[artist_id].add(qid)
        genres_by_mbid[artist_id].add(genre_qid)
        mbids_by_qid[qid].add(artist_id)
    return qids_by_mbid, genres_by_mbid, mbids_by_qid


def _hash_rank(artist_id: str) -> str:
    return hashlib.sha256(f"wikidata-global-musical-artists-v1:{artist_id}".encode()).hexdigest()


def _values_qids(qids: list[str]) -> str:
    return " ".join(f"wd:{qid}" for qid in sorted(qids))


def _identity_query(pairs: list[tuple[str, str]]) -> str:
    values = " ".join(f'(wd:{qid} "{artist_id}")' for qid, artist_id in sorted(pairs))
    p31_labels = (
        "  OPTIONAL { ?artist wdt:P31 ?type. OPTIONAL { ?type rdfs:label "
        '?typeLabel. FILTER(LANG(?typeLabel) = "en") } }'
    )
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?artist ?mbid ?label ?type ?typeLabel WHERE {{
  VALUES (?artist ?mbid) {{ {values} }}
  ?artist wdt:P434 ?mbid.
  OPTIONAL {{ ?artist rdfs:label ?label. FILTER(LANG(?label) = "en") }}
{p31_labels}
}}"""


def _genre_query(qids: list[str]) -> str:
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?genre ?label WHERE {{
  VALUES ?genre {{ {_values_qids(qids)} }}
  OPTIONAL {{ ?genre rdfs:label ?label. FILTER(LANG(?label) = "en") }}
}}"""


def _parse_identity_bindings(
    body: bytes, requested: set[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, Any]]:
    payload = json.loads(body)
    bindings = payload["results"]["bindings"]
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in bindings:
        qid = _qid(binding.get("artist", {}).get("value"))
        artist_id = _mbid(binding.get("mbid", {}).get("value"))
        key = (qid, artist_id)
        if key not in requested:
            raise GlobalArtistGenreError(
                "artist detail response contains an unrequested QID/MBID pair"
            )
        row = result.setdefault(key, {"english_labels": set(), "types": {}})
        label = _english(binding, "label")
        if label is not None:
            row["english_labels"].add(label)
        type_value = binding.get("type")
        if type_value is not None:
            type_qid = _qid(type_value.get("value"))
            type_label = _english(binding, "typeLabel")
            row["types"][type_qid] = type_label
    return result


def _parse_genre_bindings(body: bytes, requested: set[str]) -> dict[str, set[str]]:
    payload = json.loads(body)
    bindings = payload["results"]["bindings"]
    labels: dict[str, set[str]] = defaultdict(set)
    for binding in bindings:
        qid = _qid(binding.get("genre", {}).get("value"))
        if qid not in requested:
            raise GlobalArtistGenreError("genre label response contains an unrequested QID")
        label = _english(binding, "label")
        if label is not None:
            labels[qid].add(label)
    return labels


def _capture_batches(
    client: httpx.Client,
    output: Path,
    batch_specs: list[tuple[str, list[Any], str]],
    total_so_far: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[Any, Any]], int]:
    captures: list[dict[str, Any]] = []
    parsed: dict[str, dict[Any, Any]] = {}
    total = total_so_far
    for index, (kind, values, query) in enumerate(batch_specs):
        batch_path = f"raw/{kind}-{index:02d}.json"
        request_meta: dict[str, Any] = {
            "kind": kind,
            "index": index,
            "requested": values,
            "query_sha256": _sha256_bytes(query.encode()),
            "raw_path": batch_path,
        }
        if total >= MAX_TOTAL_RESPONSE_BYTES:
            request_meta.update(
                {
                    "http_status": None,
                    "response_bytes": 0,
                    "response_sha256": _sha256_bytes(b""),
                    "body_complete": False,
                    "failure": "total_byte_budget",
                }
            )
            (output / batch_path).write_bytes(b"")
            captures.append(request_meta)
            continue
        limit = min(MAX_DETAIL_RESPONSE_BYTES, MAX_TOTAL_RESPONSE_BYTES - total)
        response = _capture(client, query, output / batch_path, limit)
        request_meta.update(response)
        body = (output / batch_path).read_bytes()
        total += len(body)
        if response["http_status"] != HTTP_OK or not response["body_complete"]:
            request_meta["failure"] = (
                response["failure"] or f"http_status:{response['http_status']}"
            )
        else:
            try:
                if kind == "artist-detail":
                    pairs = {(qid, artist_id) for qid, artist_id in values}
                    parsed[f"{kind}-{index:02d}"] = _parse_identity_bindings(body, pairs)
                else:
                    parsed[f"{kind}-{index:02d}"] = _parse_genre_bindings(body, set(values))
            except (ValueError, TypeError, KeyError) as error:
                request_meta["failure"] = f"invalid_response:{type(error).__name__}"
        request_meta["binding_count"] = (
            len(json.loads(body)["results"]["bindings"])
            if "failure" not in request_meta and body
            else 0
        )
        captures.append(request_meta)
    return captures, parsed, total


def _identity_status(
    qids: set[str],
    mbids_by_qid: dict[str, set[str]],
    detail: dict[str, Any] | None,
    core_name: str,
) -> tuple[str, dict[str, Any] | None]:
    qid = next(iter(qids)) if len(qids) == 1 else None
    if qid is None or len(mbids_by_qid.get(qid, set())) != 1:
        status = "duplicate_p434_qids" if qid is None else "p434_qid_reused_for_multiple_mbids"
        return status, None
    if detail is None:
        return "artist_detail_unavailable", None
    labels = sorted(detail["english_labels"])
    if len(labels) != 1:
        return "english_label_missing_or_ambiguous", {
            "qid": qid,
            "english_labels": labels,
            "types": detail["types"],
        }
    if not detail["types"]:
        return "instance_type_missing", {"qid": qid, "label": labels[0], "types": {}}
    normalized_core = unicodedata.normalize("NFKC", core_name).casefold()
    normalized_wikidata = unicodedata.normalize("NFKC", labels[0]).casefold()
    if normalized_core != normalized_wikidata:
        return "core_name_mismatch", {"qid": qid, "label": labels[0], "types": detail["types"]}
    return "resolved_exact_p434_core_name", {
        "qid": qid,
        "label": labels[0],
        "types": detail["types"],
    }


@dataclass(frozen=True)
class _ProjectionInput:
    selected_ids: list[str]
    qids_by_mbid: dict[str, set[str]]
    genres_by_mbid: dict[str, set[str]]
    mbids_by_qid: dict[str, set[str]]
    core_by_mbid: dict[str, list[str]]
    artist_detail: dict[tuple[str, str], dict[str, Any]]
    genre_labels: dict[str, set[str]]


@dataclass(frozen=True)
class _SelectionPlan:
    selection: dict[str, Any]
    qids_by_mbid: dict[str, set[str]]
    genres_by_mbid: dict[str, set[str]]
    mbids_by_qid: dict[str, set[str]]
    core_by_mbid: dict[str, list[str]]
    selected_ids: list[str]
    artist_specs: list[tuple[str, list[Any], str]]
    genre_specs: list[tuple[str, list[Any], str]]
    all_genre_qids: list[str]
    genre_qids: list[str]


@dataclass(frozen=True)
class _SelectionInput:
    output: Path
    initial_rows: list[tuple[str, str, str]]
    rejected_rows: list[dict[str, Any]]
    initial_bindings_count: int
    core_receipt: dict[str, Any]
    core_path: Path
    max_artists: int


def _project_selected(data: _ProjectionInput) -> tuple[list[dict[str, Any]], dict[str, int]]:
    projection: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    for artist_id in data.selected_ids:
        qids = data.qids_by_mbid[artist_id]
        qid = next(iter(qids)) if len(qids) == 1 else None
        detail = data.artist_detail.get((qid, artist_id)) if qid is not None else None
        status, identity = _identity_status(
            qids, data.mbids_by_qid, detail, data.core_by_mbid[artist_id][0]
        )
        status_counts[status] += 1
        record: dict[str, Any] = {
            "artist_mbid": artist_id,
            "core_name": data.core_by_mbid[artist_id][0],
            "candidate_wikidata_qids": sorted(qids),
            "identity_status": status,
            "wikidata_artist_qid": identity["qid"] if identity else None,
            "wikidata_english_label": identity.get("label") if identity else None,
            "instance_types": [
                {"qid": q, "english_label": label}
                for q, label in sorted((identity or {}).get("types", {}).items())
            ],
            "claims": [],
        }
        if status == "resolved_exact_p434_core_name":
            record["claims"] = [
                {
                    "property_id": "P136",
                    "value_qid": genre,
                    "value_label": next(iter(sorted(data.genre_labels.get(genre, set()))), None),
                    "source": ENDPOINT,
                    "license": LICENSE,
                    "assertion_scope": DIRECT_CLAIM_SCOPE,
                }
                for genre in sorted(data.genres_by_mbid[artist_id])
            ]
        projection.append(record)
    return projection, dict(sorted(status_counts.items()))


def _record_compact_accounting(
    manifest: dict[str, Any], selection: dict[str, Any], status_counts: dict[str, int]
) -> None:
    unknown_status_count = sum(
        capture.get("http_status") is None for capture in manifest["followup_captures"]
    )
    manifest["source_rows_quarantined_count"] = len(selection["source_rows_quarantined"])
    manifest["selected_terminal_status_denominator"] = sum(status_counts.values())
    manifest["retry_response_http_status_unknown_count"] = unknown_status_count
    manifest["source_response_scope"] = (
        "captured response bytes, deterministic query hashes, and exact requested QID/UUID pairs; "
        "HTTP status is unknown for the explicitly marked retry bodies"
        if unknown_status_count
        else (
            "captured response bytes with recorded HTTP status, deterministic query hashes, "
            "and exact requested QID/UUID pairs"
        )
    )


def _freeze_selection_plan(inputs: _SelectionInput) -> _SelectionPlan:
    output = inputs.output
    initial_rows = inputs.initial_rows
    rejected_rows = inputs.rejected_rows
    initial_bindings_count = inputs.initial_bindings_count
    core_receipt = inputs.core_receipt
    core_path = inputs.core_path
    max_artists = inputs.max_artists
    qids_by_mbid, genres_by_mbid, mbids_by_qid = _scan_groups(initial_rows)
    core_by_mbid = _core_names_for(set(qids_by_mbid), core_path, core_receipt["artist_count"])
    eligible = sorted(
        (artist_id for artist_id, names in core_by_mbid.items() if len(names) == 1),
        key=_hash_rank,
    )
    selected_ids = eligible[:max_artists]
    missing_core = sorted(set(qids_by_mbid) - set(core_by_mbid))
    duplicate_core = sorted(
        artist_id for artist_id, names in core_by_mbid.items() if len(names) > 1
    )
    selection_rows = [
        {
            "artist_mbid": artist_id,
            "core_name": core_by_mbid[artist_id][0],
            "qid_candidates": sorted(qids_by_mbid[artist_id]),
            "genre_qids": sorted(genres_by_mbid[artist_id]),
        }
        for artist_id in selected_ids
    ]
    selection = {
        "revision": "wikidata-global-musical-artists-selection-v1",
        "selection_method": (
            "SHA256 rank of exact UUIDs in the initial Wikidata P434/P136 response "
            "that occur once in the verified core artist table; no labels, historical "
            "names or genre values influence selection"
        ),
        "max_artists": max_artists,
        "source_query_sha256": _sha256_bytes(INITIAL_QUERY.encode()),
        "source_bindings_seen": initial_bindings_count,
        "source_rows_used": len(initial_rows),
        "source_rows_quarantined": rejected_rows,
        "source_rows_quarantined_count": len(rejected_rows),
        "source_selection_possibly_truncated": initial_bindings_count >= MAX_SCAN_ROWS,
        "source_artist_uuid_count": len(qids_by_mbid),
        "core_eligible_artist_uuid_count": len(eligible),
        "missing_core_artist_mbids": missing_core,
        "duplicate_core_artist_mbids": duplicate_core,
        "selected_artist_count": len(selection_rows),
        "selected": selection_rows,
    }
    _write_json(output / "selection.json", selection)
    artist_pairs = [
        (next(iter(qids_by_mbid[artist_id])), artist_id)
        for artist_id in selected_ids
        if len(qids_by_mbid[artist_id]) == 1
        and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1
    ]
    artist_specs = [
        (
            "artist-detail",
            artist_pairs[i : i + MAX_ENTITIES_PER_BATCH],
            _identity_query(artist_pairs[i : i + MAX_ENTITIES_PER_BATCH]),
        )
        for i in range(0, len(artist_pairs), MAX_ENTITIES_PER_BATCH)
    ]
    all_genre_qids = sorted(
        {
            genre
            for artist_id in selected_ids
            if len(qids_by_mbid[artist_id]) == 1
            and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1
            for genre in genres_by_mbid[artist_id]
        }
    )
    genre_slots = max(0, MAX_FOLLOWUP_REQUESTS - len(artist_specs))
    genre_qids = all_genre_qids[: genre_slots * MAX_ENTITIES_PER_BATCH]
    genre_specs = [
        (
            "genre-label",
            genre_qids[i : i + MAX_ENTITIES_PER_BATCH],
            _genre_query(genre_qids[i : i + MAX_ENTITIES_PER_BATCH]),
        )
        for i in range(0, len(genre_qids), MAX_ENTITIES_PER_BATCH)
    ]
    if len(artist_specs) + len(genre_specs) > MAX_FOLLOWUP_REQUESTS:
        raise GlobalArtistGenreError("bounded label hydration exceeds 20 follow-up requests")
    return _SelectionPlan(
        selection,
        qids_by_mbid,
        genres_by_mbid,
        mbids_by_qid,
        core_by_mbid,
        selected_ids,
        artist_specs,
        genre_specs,
        all_genre_qids,
        genre_qids,
    )


def _capture_followups(
    client: httpx.Client,
    output: Path,
    specs: list[tuple[str, list[Any], str]],
    initial_response_bytes: int,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, set[str]], int]:
    captures: list[dict[str, Any]] = []
    artist_details: dict[tuple[str, str], dict[str, Any]] = {}
    genre_labels: dict[str, set[str]] = defaultdict(set)
    total_bytes = initial_response_bytes
    for index, (kind, values, query) in enumerate(specs):
        if total_bytes >= MAX_TOTAL_RESPONSE_BYTES:
            break
        time.sleep(1.1)
        key = f"{kind}-{index:02d}"
        raw_name = f"{key}.json"
        capture = _capture(
            client,
            query,
            output / "raw" / raw_name,
            min(MAX_DETAIL_RESPONSE_BYTES, MAX_TOTAL_RESPONSE_BYTES - total_bytes),
        )
        capture.update(
            {
                "kind": kind,
                "index": index,
                "requested": values,
                "query_sha256": _sha256_bytes(query.encode()),
                "raw_path": f"raw/{raw_name}",
            }
        )
        body = (output / "raw" / raw_name).read_bytes()
        total_bytes += len(body)
        if not _admit_http_response(capture):
            captures.append(capture)
            continue
        try:
            if kind == "artist-detail":
                artist_details.update(_parse_identity_bindings(body, set(values)))
            else:
                for qid, labels in _parse_genre_bindings(body, set(values)).items():
                    genre_labels[qid].update(labels)
        except (GlobalArtistGenreError, ValueError, TypeError, KeyError) as error:
            capture["failure"] = f"invalid_response:{type(error).__name__}"
        captures.append(capture)
    return captures, artist_details, genre_labels, total_bytes


def _admit_http_response(capture: dict[str, Any]) -> bool:
    if capture["http_status"] == HTTP_OK and capture["body_complete"]:
        return True
    if capture["failure"] is None:
        capture["failure"] = f"http_status:{capture['http_status']}"
    return False


def acquire_global_artist_genres(
    output: Path,
    core_directory: Path,
    *,
    max_artists: int = MAX_ARTISTS,
) -> dict[str, Any]:
    """Capture one bounded source scan and hydrate a hash-selected exact-ID cohort."""
    if not 1 <= max_artists <= MAX_ARTISTS:
        raise ValueError(f"max_artists must be from 1 to {MAX_ARTISTS}")
    core_receipt, core_path = _verify_core_source(core_directory)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    client_headers = {
        "User-Agent": "OpenNoise/0.1 (bounded open CC0 music metadata research)",
        "Accept": "application/sparql-results+json",
    }
    with httpx.Client(timeout=30, follow_redirects=False, headers=client_headers) as client:
        initial_meta = _capture(
            client, INITIAL_QUERY, output / "raw/initial.json", MAX_SCAN_RESPONSE_BYTES
        )
        initial_body = (output / "raw/initial.json").read_bytes()
        if initial_meta["http_status"] != HTTP_OK or not initial_meta["body_complete"]:
            return _write_blocked_pack(
                output, initial_meta, core_receipt, core_path, "initial_capture_failed"
            )
        try:
            initial_rows, rejected_rows = _parse_scan(initial_body)
            initial_bindings = json.loads(initial_body)["results"]["bindings"]
        except (ValueError, TypeError, KeyError) as error:
            initial_meta["failure"] = f"invalid_response:{type(error).__name__}"
            return _write_blocked_pack(
                output, initial_meta, core_receipt, core_path, "initial_response_invalid"
            )
        if len(initial_bindings) > MAX_SCAN_ROWS + 1:
            initial_meta["failure"] = "unexpected_rows_over_scan_limit"
            return _write_blocked_pack(
                output, initial_meta, core_receipt, core_path, "initial_response_invalid"
            )
        plan = _freeze_selection_plan(
            _SelectionInput(
                output,
                initial_rows,
                rejected_rows,
                len(initial_bindings),
                core_receipt,
                core_path,
                max_artists,
            )
        )
        followup_specs = plan.artist_specs + plan.genre_specs
        followups, artist_detail, genre_labels, total_bytes = _capture_followups(
            client, output, followup_specs, initial_meta["response_bytes"]
        )
        projection_artists, status_counts = _project_selected(
            _ProjectionInput(
                plan.selected_ids,
                plan.qids_by_mbid,
                plan.genres_by_mbid,
                plan.mbids_by_qid,
                plan.core_by_mbid,
                artist_detail,
                genre_labels,
            )
        )
        selection = json.loads((output / "selection.json").read_bytes())
        manifest = {
            "revision": "wikidata-global-musical-artists-v1",
            "acquired_utc": datetime.now(UTC).isoformat(),
            "source": ENDPOINT,
            "license": LICENSE,
            "license_scope": LICENSE_SCOPE,
            "query_service_docs": "https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service",
            "selection_sha256": _sha256_file(output / "selection.json")[0],
            "source_selection_possibly_truncated": selection["source_selection_possibly_truncated"],
            "source_scan_bindings_seen": len(initial_bindings),
            "source_scan_rows_projected": len(initial_rows),
            "source_unique_artist_uuids": len(plan.qids_by_mbid),
            "genre_qids_with_selected_artist_claims": len(plan.all_genre_qids),
            "genre_qids_hydrated": len(plan.genre_qids),
            "genre_qids_not_hydrated_due_to_request_cap": len(plan.all_genre_qids)
            - len(plan.genre_qids),
            "source_selection_limit": MAX_SCAN_ROWS,
            "selected_core_artist_count": len(plan.selected_ids),
            "identity_status_counts": dict(sorted(status_counts.items())),
            "resolved_artist_count": status_counts["resolved_exact_p434_core_name"],
            "projected_direct_claim_count": sum(len(a["claims"]) for a in projection_artists),
            "missing_english_genre_label_count": sum(
                c["value_label"] is None for a in projection_artists for c in a["claims"]
            ),
            "candidate_genre_qids_not_hydrated_due_to_request_cap": len(plan.all_genre_qids)
            - len(plan.genre_qids),
            "projected_claim_genre_qids_not_hydrated": len(
                {c["value_qid"] for a in projection_artists for c in a["claims"]}
                - set(plan.genre_qids)
            ),
            "core_identity_source": {
                "revision": core_receipt["revision"],
                "license": core_receipt["license"],
                "snapshot": core_receipt["snapshot"],
                "artist_count": core_receipt["artist_count"],
                "output_bytes": core_receipt["output_bytes"],
                "output_sha256": core_receipt["output_sha256"],
                "receipt_sha256": _sha256_file(core_directory / "receipt.json")[0],
                "full_archive_sha256_verified": False,
            },
            "request_count": 1 + len(followups),
            "response_bytes_total": total_bytes,
            "initial_capture": initial_meta,
            "followup_captures": followups,
            "status": "partial_source_sample"
            if selection["source_selection_possibly_truncated"]
            else "source_sample",
            "completeness_claim": "none; source query is capped and UUID-hash selected",
        }
        _record_compact_accounting(manifest, selection, dict(sorted(status_counts.items())))
        _write_json(
            output / "projection.json",
            {"revision": manifest["revision"], "license": LICENSE, "artists": projection_artists},
        )
        _write_json(output / "manifest.json", manifest)
        _write_receipt(output)
    verify_global_artist_genres(output, core_directory)
    return manifest


@dataclass(frozen=True)
class _RetryPlan:
    selected_ids: list[str]
    qids_by_mbid: dict[str, set[str]]
    genres_by_mbid: dict[str, set[str]]
    mbids_by_qid: dict[str, set[str]]
    core_by_mbid: dict[str, list[str]]
    candidate_pairs: list[tuple[str, str]]
    pending_pairs: list[tuple[str, str]]
    retry_pairs: list[tuple[str, str]]
    batch_count: int


def _retry_preflight(
    directory: Path, core_directory: Path, retry_files: list[Path]
) -> dict[str, Any] | None:
    if not retry_files:
        verify_global_artist_genres(directory, core_directory)
        return None
    receipt = json.loads(_safe_file(directory, "receipt.json").read_bytes())
    expected = receipt.get("sha256", {})
    retry_paths = {path.relative_to(directory).as_posix() for path in retry_files}
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != "receipt.json"
    }
    if actual == set(expected):
        manifest = verify_global_artist_genres(directory, core_directory)
        if len(manifest["followup_captures"]) < MAX_FOLLOWUP_REQUESTS:
            return None
        selection = json.loads(_safe_file(directory, "selection.json").read_bytes())
        _record_compact_accounting(manifest, selection, manifest["identity_status_counts"])
        _replace_json(directory / "manifest.json", manifest)
        _write_receipt(directory)
        verify_global_artist_genres(directory, core_directory)
        return manifest
    if actual - retry_paths != set(expected):
        raise GlobalArtistGenreError("interrupted hydration left unexpected pack files")
    for relative, digest in expected.items():
        if _sha256_file(_safe_file(directory, relative))[0] != digest:
            raise GlobalArtistGenreError("frozen source pack changed before retry recovery")
    if any(path.stat().st_size > MAX_DETAIL_RESPONSE_BYTES for path in retry_files):
        raise GlobalArtistGenreError("interrupted retry response exceeds its byte limit")
    return None


def _build_retry_plan(
    directory: Path, manifest: dict[str, Any], selection: dict[str, Any]
) -> _RetryPlan:
    initial_body = _safe_file(directory, "raw/initial.json").read_bytes()
    initial_rows, _ = _parse_scan(initial_body)
    qids_by_mbid, genres_by_mbid, mbids_by_qid = _scan_groups(initial_rows)
    selected_ids = [row["artist_mbid"] for row in selection["selected"]]
    core_by_mbid = {row["artist_mbid"]: [row["core_name"]] for row in selection["selected"]}
    candidate_pairs = [
        (next(iter(qids_by_mbid[artist_id])), artist_id)
        for artist_id in selected_ids
        if len(qids_by_mbid[artist_id]) == 1
        and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1
    ]
    successful_pairs = {
        (item[0], item[1])
        for capture in manifest["followup_captures"]
        if capture["kind"] == "artist-detail" and not capture.get("failure")
        for item in capture["requested"]
    }
    pending_pairs = [pair for pair in candidate_pairs if pair not in successful_pairs]
    slots = max(0, MAX_FOLLOWUP_REQUESTS - len(manifest["followup_captures"]))
    batch_count = min(
        slots, (len(pending_pairs) + RETRY_ENTITIES_PER_BATCH - 1) // RETRY_ENTITIES_PER_BATCH
    )
    retry_pairs = pending_pairs[: batch_count * RETRY_ENTITIES_PER_BATCH]
    return _RetryPlan(
        selected_ids,
        qids_by_mbid,
        genres_by_mbid,
        mbids_by_qid,
        core_by_mbid,
        candidate_pairs,
        pending_pairs,
        retry_pairs,
        batch_count,
    )


def _recover_retry_captures(
    directory: Path,
    manifest: dict[str, Any],
    retry_files: list[Path],
    retry_pairs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for batch_index, raw_path in enumerate(retry_files):
        start = batch_index * RETRY_ENTITIES_PER_BATCH
        values = retry_pairs[start : start + RETRY_ENTITIES_PER_BATCH]
        if not values:
            raise GlobalArtistGenreError("orphaned retry response has no frozen request batch")
        raw = raw_path.read_bytes()
        complete = True
        failure = None
        try:
            _parse_identity_bindings(raw, set(values))
        except (GlobalArtistGenreError, ValueError, TypeError, KeyError) as error:
            failure = f"uncommitted_retry_response_invalid:{type(error).__name__}"
            complete = False
        query = _identity_query(values)
        recovered.append(
            {
                "http_status": None,
                "status_metadata": "capture process ended before status metadata was committed",
                "response_bytes": len(raw),
                "response_sha256": _sha256_bytes(raw),
                "body_complete": complete,
                "failure": failure,
                "kind": "artist-detail",
                "index": len(manifest["followup_captures"]) + batch_index,
                "retry_index": batch_index,
                "requested": values,
                "query_sha256": _sha256_bytes(query.encode()),
                "raw_path": raw_path.relative_to(directory).as_posix(),
            }
        )
    return recovered


def _send_retry_captures(
    directory: Path, manifest: dict[str, Any], plan: _RetryPlan
) -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "OpenNoise/0.1 (bounded open CC0 music metadata research)",
        "Accept": "application/sparql-results+json",
    }
    captures: list[dict[str, Any]] = []
    with httpx.Client(timeout=30, follow_redirects=False, headers=headers) as client:
        for batch_index in range(plan.batch_count):
            start = batch_index * RETRY_ENTITIES_PER_BATCH
            values = plan.retry_pairs[start : start + RETRY_ENTITIES_PER_BATCH]
            query = _identity_query(values)
            total = manifest["response_bytes_total"]
            if total >= MAX_TOTAL_RESPONSE_BYTES:
                break
            time.sleep(1.1)
            raw_name = f"artist-detail-retry-{batch_index:02d}.json"
            raw_path = _safe_file(directory, f"raw/{raw_name}")
            capture = _capture(
                client,
                query,
                raw_path,
                min(MAX_DETAIL_RESPONSE_BYTES, MAX_TOTAL_RESPONSE_BYTES - total),
            )
            capture.update(
                {
                    "kind": "artist-detail",
                    "index": len(manifest["followup_captures"]) + batch_index,
                    "retry_index": batch_index,
                    "requested": values,
                    "query_sha256": _sha256_bytes(query.encode()),
                    "raw_path": f"raw/{raw_name}",
                }
            )
            body = raw_path.read_bytes()
            if _admit_http_response(capture):
                try:
                    _parse_identity_bindings(body, set(values))
                except (GlobalArtistGenreError, ValueError, TypeError, KeyError) as error:
                    capture["failure"] = f"invalid_response:{type(error).__name__}"
            manifest["response_bytes_total"] += len(body)
            captures.append(capture)
    return captures


def _rebuild_retry_projection(
    directory: Path,
    manifest: dict[str, Any],
    selection: dict[str, Any],
    plan: _RetryPlan,
) -> list[dict[str, Any]]:
    details: dict[tuple[str, str], dict[str, Any]] = {}
    genre_labels: dict[str, set[str]] = defaultdict(set)
    for capture in manifest["followup_captures"]:
        if capture.get("failure"):
            continue
        raw = _safe_file(directory, capture["raw_path"]).read_bytes()
        if capture["kind"] == "artist-detail":
            details.update(
                _parse_identity_bindings(raw, {(item[0], item[1]) for item in capture["requested"]})
            )
        else:
            for qid, labels in _parse_genre_bindings(raw, set(capture["requested"])).items():
                genre_labels[qid].update(labels)
    projected, status_counts = _project_selected(
        _ProjectionInput(
            plan.selected_ids,
            plan.qids_by_mbid,
            plan.genres_by_mbid,
            plan.mbids_by_qid,
            plan.core_by_mbid,
            details,
            genre_labels,
        )
    )
    manifest["request_count"] = 1 + len(manifest["followup_captures"])
    manifest["artist_identity_pairs_eligible_for_hydration"] = len(plan.candidate_pairs)
    manifest["artist_identity_pairs_retried_in_small_batches"] = sum(
        len(capture["requested"])
        for capture in manifest["followup_captures"]
        if capture.get("retry_index") is not None
    )
    manifest["artist_identity_pairs_not_retried_due_to_request_cap"] = max(
        0,
        len(plan.pending_pairs)
        - sum(
            len(capture["requested"])
            for capture in manifest["followup_captures"]
            if capture.get("retry_index") is not None
        ),
    )
    manifest["retry_response_http_status_unknown_count"] = sum(
        capture.get("http_status") is None
        for capture in manifest["followup_captures"]
        if capture.get("retry_index") is not None
    )
    manifest["retry_response_bodies_validated_count"] = sum(
        capture.get("failure") is None
        for capture in manifest["followup_captures"]
        if capture.get("retry_index") is not None
    )
    manifest["identity_status_counts"] = status_counts
    manifest["resolved_artist_count"] = status_counts.get("resolved_exact_p434_core_name", 0)
    manifest["projected_direct_claim_count"] = sum(len(row["claims"]) for row in projected)
    manifest["missing_english_genre_label_count"] = sum(
        claim["value_label"] is None for row in projected for claim in row["claims"]
    )
    hydrated_genres = {
        qid
        for capture in manifest["followup_captures"]
        if capture["kind"] == "genre-label" and not capture.get("failure")
        for qid in capture["requested"]
    }
    manifest["projected_claim_genre_qids_not_hydrated"] = len(
        {claim["value_qid"] for row in projected for claim in row["claims"]} - hydrated_genres
    )
    _record_compact_accounting(manifest, selection, status_counts)
    _replace_json(
        directory / "projection.json",
        {"revision": manifest["revision"], "license": LICENSE, "artists": projected},
    )
    _replace_json(directory / "manifest.json", manifest)
    _write_receipt(directory)
    return projected


def retry_global_artist_genres_hydration(directory: Path, core_directory: Path) -> dict[str, Any]:
    """Retry smaller exact-QID detail queries against an already frozen source roster."""
    retry_files = sorted((directory / "raw").glob("artist-detail-retry-*.json"))
    completed = _retry_preflight(directory, core_directory, retry_files)
    if completed is not None:
        return completed
    manifest = json.loads(_safe_file(directory, "manifest.json").read_bytes())
    selection = json.loads(_safe_file(directory, "selection.json").read_bytes())
    plan = _build_retry_plan(directory, manifest, selection)
    captures = (
        _recover_retry_captures(directory, manifest, retry_files, plan.retry_pairs)
        if retry_files
        else _send_retry_captures(directory, manifest, plan)
    )
    manifest["followup_captures"].extend(captures)
    manifest["response_bytes_total"] += (
        sum(capture["response_bytes"] for capture in captures) if retry_files else 0
    )
    _rebuild_retry_projection(directory, manifest, selection, plan)
    verify_global_artist_genres(directory, core_directory)
    return manifest


def _write_blocked_pack(
    output: Path, initial: dict[str, Any], core_receipt: dict[str, Any], core_path: Path, state: str
) -> dict[str, Any]:
    manifest = {
        "revision": "wikidata-global-musical-artists-v1",
        "acquired_utc": datetime.now(UTC).isoformat(),
        "source": ENDPOINT,
        "license": LICENSE,
        "status": state,
        "completeness_claim": "none",
        "source_selection_possibly_truncated": False,
        "initial_capture": initial,
        "followup_captures": [],
        "request_count": 1,
        "response_bytes_total": initial["response_bytes"],
        "core_source_receipt_sha256": _sha256_file(core_path.parent / "receipt.json")[0],
        "core_source_output_sha256": core_receipt["output_sha256"],
        "projected_direct_claim_count": 0,
    }
    _write_json(output / "manifest.json", manifest)
    _write_receipt(output)
    return manifest


def _write_receipt(output: Path) -> None:
    paths = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name != "receipt.json"
    )
    hashes = {str(path.relative_to(output)): _sha256_file(path)[0] for path in paths}
    receipt = {
        "revision": "wikidata-global-musical-artists-receipt-v1",
        "source": ENDPOINT,
        "license": LICENSE,
        "sha256": hashes,
    }
    _replace_json(output / "receipt.json", receipt)


def _normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _verify_receipt_files(directory: Path) -> dict[str, Any]:
    receipt = json.loads(_safe_file(directory, "receipt.json").read_bytes())
    if receipt.get("source") != ENDPOINT or receipt.get("license") != LICENSE:
        raise GlobalArtistGenreError("receipt source/license differs")
    expected = receipt.get("sha256")
    if not isinstance(expected, dict):
        raise GlobalArtistGenreError("receipt has no file hashes")
    actual: set[str] = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise GlobalArtistGenreError("pack cannot contain symlinks")
        if path.is_file() and path.name != "receipt.json":
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(expected):
        raise GlobalArtistGenreError("pack file set differs from receipt")
    for relative, digest in expected.items():
        if _sha256_file(_safe_file(directory, relative))[0] != digest:
            raise GlobalArtistGenreError(f"pack hash mismatch: {relative}")
    return receipt


@dataclass(frozen=True)
class _ReplayBase:
    directory: Path
    core_directory: Path
    manifest: dict[str, Any]
    selection: dict[str, Any]
    initial_rows: list[tuple[str, str, str]]
    binding_count: int


@dataclass(frozen=True)
class _ReplayContext:
    base: _ReplayBase
    followups: list[dict[str, Any]]
    qids_by_mbid: dict[str, set[str]]
    genres_by_mbid: dict[str, set[str]]
    mbids_by_qid: dict[str, set[str]]
    selection_rows: list[dict[str, Any]]
    selected_ids: list[str]
    core_map: dict[str, list[str]]
    artist_pairs: list[tuple[str, str]]
    initial_specs: list[tuple[str, list[Any], str]]


@dataclass(frozen=True)
class _ReplayDetails:
    by_pair: dict[tuple[str, str], dict[str, Any]]
    genre_labels: dict[str, set[str]]
    hydrated_genres: set[str]
    response_bytes: int


@dataclass(frozen=True)
class _ReplayBatch:
    directory: Path
    capture: dict[str, Any]
    kind: str
    values: list[Any]
    query: str
    index: int
    retry_index: int | None = None


def _read_replay_base(
    directory: Path, core_directory: Path
) -> tuple[dict[str, Any], _ReplayBase | None]:
    manifest = json.loads(_safe_file(directory, "manifest.json").read_bytes())
    if manifest["status"] in {"initial_capture_failed", "initial_response_invalid"}:
        return _read_blocked_initial(directory, manifest)
    selection = _read_selection(directory, manifest)
    initial_rows, binding_count = _replay_initial_capture(directory, manifest, selection)
    base = _ReplayBase(directory, core_directory, manifest, selection, initial_rows, binding_count)
    return manifest, base


def _read_selection(directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    body = _safe_file(directory, "selection.json").read_bytes()
    selection = json.loads(body)
    if _sha256_bytes(body) != manifest["selection_sha256"]:
        raise GlobalArtistGenreError("selection hash differs from manifest")
    if selection["source_query_sha256"] != _sha256_bytes(INITIAL_QUERY.encode()):
        raise GlobalArtistGenreError("initial query is not the pinned source query")
    return selection


def _replay_initial_capture(
    directory: Path, manifest: dict[str, Any], selection: dict[str, Any]
) -> tuple[list[tuple[str, str, str]], int]:
    initial = manifest["initial_capture"]
    if (
        initial.get("raw_path") != "initial.json"
        or initial.get("http_status") != HTTP_OK
        or initial.get("body_complete") is not True
        or initial.get("failure") is not None
        or manifest.get("source") != ENDPOINT
        or manifest.get("license") != LICENSE
    ):
        raise GlobalArtistGenreError(
            "initial source response was not admitted as a complete capture"
        )
    followups = manifest["followup_captures"]
    if len(followups) > MAX_FOLLOWUP_REQUESTS or manifest["request_count"] != 1 + len(followups):
        raise GlobalArtistGenreError("request count exceeds the bounded capture plan")
    if initial["response_bytes"] > MAX_SCAN_RESPONSE_BYTES or any(
        capture["response_bytes"] > MAX_DETAIL_RESPONSE_BYTES for capture in followups
    ):
        raise GlobalArtistGenreError("a response exceeds its byte limit")
    if manifest["response_bytes_total"] > MAX_TOTAL_RESPONSE_BYTES:
        raise GlobalArtistGenreError("total response bytes exceed the capture budget")
    initial_body = _safe_file(directory, f"raw/{initial['raw_path']}").read_bytes()
    if (
        _sha256_bytes(initial_body) != initial["response_sha256"]
        or len(initial_body) != initial["response_bytes"]
    ):
        raise GlobalArtistGenreError("initial response capture hash or bytes differ")
    initial_rows, rejected = _parse_scan(initial_body)
    bindings = json.loads(initial_body)["results"]["bindings"]
    possibly_truncated = len(bindings) >= MAX_SCAN_ROWS
    if (
        selection["source_selection_possibly_truncated"] != possibly_truncated
        or manifest["source_selection_possibly_truncated"] != possibly_truncated
    ):
        raise GlobalArtistGenreError("source truncation status is inaccurate")
    if selection["source_rows_quarantined"] != rejected:
        raise GlobalArtistGenreError("source row quarantine does not replay")
    if (
        manifest.get("source_scan_bindings_seen") != len(bindings)
        or manifest.get("source_scan_rows_projected") != len(initial_rows)
        or manifest.get("source_unique_artist_uuids") != len({row[1] for row in initial_rows})
        or manifest.get("source_rows_quarantined_count") != len(rejected)
    ):
        raise GlobalArtistGenreError("initial source scan accounting differs")
    return initial_rows, len(bindings)


def _read_blocked_initial(directory: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], None]:
    files = {
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    }
    if "projection.json" in files:
        raise GlobalArtistGenreError(
            "blocked initial capture cannot contain a successful projection"
        )
    return manifest, None


def _replay_core_roster(
    base: _ReplayBase, qids_by_mbid: dict[str, set[str]]
) -> tuple[list[dict[str, Any]], list[str], dict[str, list[str]]]:
    selection_rows = base.selection["selected"]
    selected_ids = [row["artist_mbid"] for row in selection_rows]
    if len(set(selected_ids)) != len(selected_ids) or any(
        artist_id not in qids_by_mbid for artist_id in selected_ids
    ):
        raise GlobalArtistGenreError("selected IDs do not replay from source scan")
    receipt, core_path = _verify_core_source(base.core_directory)
    core_names = _core_names_for(set(qids_by_mbid), core_path, receipt["artist_count"])
    eligible = sorted(
        (artist_id for artist_id, names in core_names.items() if len(names) == 1),
        key=_hash_rank,
    )
    cap = base.selection["max_artists"]
    if not isinstance(cap, int) or not 1 <= cap <= MAX_ARTISTS:
        raise GlobalArtistGenreError("selection cap is outside its permitted range")
    if selected_ids != eligible[:cap]:
        raise GlobalArtistGenreError("selected roster does not replay from core IDs and hash rank")
    if (
        len(selected_ids) > MAX_ARTISTS
        or len(selected_ids) != base.selection["selected_artist_count"]
    ):
        raise GlobalArtistGenreError("selected artist count exceeds its cap")
    if base.selection["core_eligible_artist_uuid_count"] != len(eligible):
        raise GlobalArtistGenreError("core eligible UUID accounting differs")
    if base.selection["missing_core_artist_mbids"] != sorted(set(qids_by_mbid) - set(core_names)):
        raise GlobalArtistGenreError("missing core UUID accounting differs")
    duplicates = sorted(artist_id for artist_id, names in core_names.items() if len(names) > 1)
    if base.selection["duplicate_core_artist_mbids"] != duplicates:
        raise GlobalArtistGenreError("duplicate core UUID accounting differs")
    core_source = base.manifest["core_identity_source"]
    expected_source = {
        "revision": receipt["revision"],
        "license": receipt["license"],
        "snapshot": receipt["snapshot"],
        "artist_count": receipt["artist_count"],
        "output_bytes": receipt["output_bytes"],
        "output_sha256": receipt["output_sha256"],
        "receipt_sha256": _sha256_file(base.core_directory / "receipt.json")[0],
        "full_archive_sha256_verified": False,
    }
    if core_source != expected_source:
        raise GlobalArtistGenreError(
            "manifest core source does not match the verified identity receipt"
        )
    return selection_rows, selected_ids, core_names


def _expected_followup_specs(
    selected_ids: list[str],
    qids_by_mbid: dict[str, set[str]],
    genres_by_mbid: dict[str, set[str]],
    mbids_by_qid: dict[str, set[str]],
) -> tuple[list[tuple[str, list[Any], str]], list[tuple[str, str]]]:
    artist_pairs = [
        (next(iter(qids_by_mbid[artist_id])), artist_id)
        for artist_id in selected_ids
        if len(qids_by_mbid[artist_id]) == 1
        and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1
    ]
    artist_specs = [
        (
            "artist-detail",
            artist_pairs[i : i + MAX_ENTITIES_PER_BATCH],
            _identity_query(artist_pairs[i : i + MAX_ENTITIES_PER_BATCH]),
        )
        for i in range(0, len(artist_pairs), MAX_ENTITIES_PER_BATCH)
    ]
    genre_qids = sorted(
        {
            genre
            for artist_id in selected_ids
            if len(qids_by_mbid[artist_id]) == 1
            and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1
            for genre in genres_by_mbid[artist_id]
        }
    )
    genre_cap = max(0, MAX_FOLLOWUP_REQUESTS - len(artist_specs)) * MAX_ENTITIES_PER_BATCH
    genre_qids = genre_qids[:genre_cap]
    genre_specs = [
        (
            "genre-label",
            genre_qids[i : i + MAX_ENTITIES_PER_BATCH],
            _genre_query(genre_qids[i : i + MAX_ENTITIES_PER_BATCH]),
        )
        for i in range(0, len(genre_qids), MAX_ENTITIES_PER_BATCH)
    ]
    return artist_specs + genre_specs, artist_pairs


def _reconstruct_context(base: _ReplayBase) -> _ReplayContext:
    qids_by_mbid, genres_by_mbid, mbids_by_qid = _scan_groups(base.initial_rows)
    selection_rows, selected_ids, core_names = _replay_core_roster(base, qids_by_mbid)
    specs, artist_pairs = _expected_followup_specs(
        selected_ids, qids_by_mbid, genres_by_mbid, mbids_by_qid
    )
    if len(specs) > MAX_FOLLOWUP_REQUESTS:
        raise GlobalArtistGenreError("replayed query plan exceeds the follow-up request cap")
    core_map = {
        artist_id: names for artist_id, names in core_names.items() if artist_id in selected_ids
    }
    return _ReplayContext(
        base,
        base.manifest["followup_captures"],
        qids_by_mbid,
        genres_by_mbid,
        mbids_by_qid,
        selection_rows,
        selected_ids,
        core_map,
        artist_pairs,
        specs,
    )


def _validate_capture_admission(capture: dict[str, Any], *, retry: bool) -> bool:
    status = capture.get("http_status")
    failure = capture.get("failure")
    if (
        status is None
        and capture.get("status_metadata")
        == "capture process ended before status metadata was committed"
    ):
        if not retry:
            raise GlobalArtistGenreError("unknown HTTP status is only allowed for a recorded retry")
    elif status is None and isinstance(failure, str) and failure.startswith("network_error:"):
        if capture.get("body_complete") is not False:
            raise GlobalArtistGenreError("network failure cannot have a complete response body")
    elif status == HTTP_OK:
        if failure is not None and not (
            isinstance(failure, str)
            and (failure.startswith("invalid_response:") or failure == "response_byte_limit")
        ):
            raise GlobalArtistGenreError("HTTP 200 capture has an invalid failure reason")
    elif isinstance(status, int):
        if failure not in {f"http_status:{status}", "response_byte_limit"}:
            raise GlobalArtistGenreError("non-200 capture failure does not match its HTTP status")
    else:
        raise GlobalArtistGenreError("capture has no admissible HTTP status or transport failure")
    if failure is None and capture.get("body_complete") is not True:
        raise GlobalArtistGenreError("incomplete response cannot be admitted")
    return failure is None


def _replay_capture_batch(batch: _ReplayBatch) -> tuple[bytes | None, int]:
    serialized = [list(item) if isinstance(item, tuple) else item for item in batch.values]
    retry = batch.retry_index is not None
    expected_path = (
        f"raw/artist-detail-retry-{batch.retry_index:02d}.json"
        if retry
        else f"raw/{batch.kind}-{batch.index:02d}.json"
    )
    if (
        batch.capture.get("kind") != batch.kind
        or batch.capture.get("index") != batch.index
        or batch.capture.get("requested") != serialized
        or batch.capture.get("query_sha256") != _sha256_bytes(batch.query.encode())
        or batch.capture.get("raw_path") != expected_path
        or batch.capture.get("retry_index") != batch.retry_index
    ):
        raise GlobalArtistGenreError("follow-up capture differs from the deterministic query plan")
    raw = _safe_file(batch.directory, batch.capture["raw_path"]).read_bytes()
    if (
        _sha256_bytes(raw) != batch.capture["response_sha256"]
        or len(raw) != batch.capture["response_bytes"]
    ):
        raise GlobalArtistGenreError("follow-up response hash or byte count differs")
    if not _validate_capture_admission(batch.capture, retry=retry):
        return None, len(raw)
    return raw, len(raw)


def _replay_followup_evidence(context: _ReplayContext) -> _ReplayDetails:
    details: dict[tuple[str, str], dict[str, Any]] = {}
    genre_labels: dict[str, set[str]] = defaultdict(set)
    hydrated_genres: set[str] = set()
    followups = context.followups
    expected = context.initial_specs
    if len(followups) < len(expected):
        raise GlobalArtistGenreError("follow-up capture set omits planned initial requests")
    byte_count = _safe_file(context.base.directory, "raw/initial.json").stat().st_size
    for index, (kind, values, query) in enumerate(expected):
        raw, size = _replay_capture_batch(
            _ReplayBatch(context.base.directory, followups[index], kind, values, query, index)
        )
        byte_count += size
        if raw is None:
            continue
        if kind == "artist-detail":
            details.update(_parse_identity_bindings(raw, set(values)))
        else:
            hydrated_genres.update(values)
            for qid, labels in _parse_genre_bindings(raw, set(values)).items():
                genre_labels[qid].update(labels)
    pending = [pair for pair in context.artist_pairs if pair not in details]
    retry_captures = followups[len(expected) :]
    capacity = MAX_FOLLOWUP_REQUESTS - len(expected)
    if len(retry_captures) > capacity:
        raise GlobalArtistGenreError("retry requests exceed the remaining follow-up cap")
    for retry_index, capture in enumerate(retry_captures):
        values = pending[
            retry_index * RETRY_ENTITIES_PER_BATCH : (retry_index + 1) * RETRY_ENTITIES_PER_BATCH
        ]
        if not values:
            raise GlobalArtistGenreError("retry request exists without a remaining frozen roster")
        query = _identity_query(values)
        raw, size = _replay_capture_batch(
            _ReplayBatch(
                context.base.directory,
                capture,
                "artist-detail",
                values,
                query,
                len(expected) + retry_index,
                retry_index,
            )
        )
        byte_count += size
        if raw is not None:
            details.update(_parse_identity_bindings(raw, set(values)))
    return _ReplayDetails(details, genre_labels, hydrated_genres, byte_count)


def _replay_projection(directory: Path, context: _ReplayContext, evidence: _ReplayDetails) -> None:
    projected, counts = _project_selected(
        _ProjectionInput(
            context.selected_ids,
            context.qids_by_mbid,
            context.genres_by_mbid,
            context.mbids_by_qid,
            context.core_map,
            evidence.by_pair,
            evidence.genre_labels,
        )
    )
    expected = {
        "revision": context.base.manifest["revision"],
        "license": LICENSE,
        "artists": projected,
    }
    actual = json.loads(_safe_file(directory, "projection.json").read_bytes())
    if actual != expected:
        raise GlobalArtistGenreError("projection does not replay from exact source QIDs")
    manifest = context.base.manifest
    denominator = len(context.selected_ids)
    if (
        manifest["identity_status_counts"] != counts
        or sum(counts.values()) != denominator
        or manifest.get("selected_terminal_status_denominator") != denominator
    ):
        raise GlobalArtistGenreError("selected artist terminal status accounting is not closed")
    if manifest["resolved_artist_count"] != counts.get("resolved_exact_p434_core_name", 0):
        raise GlobalArtistGenreError("resolved artist accounting differs")
    claim_count = sum(len(row["claims"]) for row in projected)
    if manifest["projected_direct_claim_count"] != claim_count:
        raise GlobalArtistGenreError("direct claim accounting differs")
    claims_genres = {claim["value_qid"] for row in projected for claim in row["claims"]}
    if manifest["projected_claim_genre_qids_not_hydrated"] != len(
        claims_genres - evidence.hydrated_genres
    ):
        raise GlobalArtistGenreError("unhydrated genre QID accounting differs")
    unknown = sum(capture.get("http_status") is None for capture in context.followups)
    if manifest.get("retry_response_http_status_unknown_count") != unknown:
        raise GlobalArtistGenreError("unknown HTTP status accounting differs")
    if unknown and "HTTP status is unknown" not in manifest.get("source_response_scope", ""):
        raise GlobalArtistGenreError("unknown HTTP status is omitted from response scope")
    if evidence.response_bytes != manifest["response_bytes_total"]:
        raise GlobalArtistGenreError("manifest total response bytes do not equal captured bodies")


def verify_global_artist_genres(
    directory: Path, core_directory: Path = CORE_DEFAULT
) -> dict[str, Any]:
    """Offline replay raw captures, identity decisions, direct claims, and receipt."""
    _verify_receipt_files(directory)
    manifest, base = _read_replay_base(directory, core_directory)
    if base is None:
        return manifest
    context = _reconstruct_context(base)
    _validate_selection_rows(context)
    evidence = _replay_followup_evidence(context)
    _replay_projection(directory, context, evidence)
    return manifest


def _validate_selection_rows(context: _ReplayContext) -> None:
    for row in context.selection_rows:
        artist_id = row["artist_mbid"]
        if row["qid_candidates"] != sorted(context.qids_by_mbid[artist_id]) or row[
            "genre_qids"
        ] != sorted(context.genres_by_mbid[artist_id]):
            raise GlobalArtistGenreError("selected identity or genre QIDs differ from source scan")
        if row["core_name"] != context.core_map[artist_id][0]:
            raise GlobalArtistGenreError("selected core name differs from the identity source")
