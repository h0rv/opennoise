"""Acquire and replay a bounded, source-driven Wikidata artist-genre cohort."""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from collections import defaultdict
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
    if not isinstance(item, dict) or item.get("xml:lang") != "en" or not isinstance(item.get("value"), str):
        raise GlobalArtistGenreError(f"{name} must be an English Wikidata label")
    return item["value"]


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
            rejected.append({"row_index": index, "reason": "binding_not_object", "binding_sha256": _sha256_bytes(json.dumps(binding, sort_keys=True).encode())})
            continue
        try:
            row = (
                _qid(binding.get("artist", {}).get("value")),
                _mbid(binding.get("mbid", {}).get("value")),
                _qid(binding.get("genre", {}).get("value")),
            )
        except (AttributeError, GlobalArtistGenreError) as error:
            rejected.append({"row_index": index, "reason": type(error).__name__, "binding_sha256": _sha256_bytes(json.dumps(binding, sort_keys=True).encode())})
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
        raise GlobalArtistGenreError("core identity receipt does not describe the CC0 identity-only source")
    digest, byte_count = _sha256_file(data_path)
    if digest != receipt.get("output_sha256") or byte_count != receipt.get("output_bytes"):
        raise GlobalArtistGenreError("core identity output hash or byte count differs from receipt")
    return receipt, data_path


def _core_names_for(candidates: set[str], core_path: Path, expected_rows: int) -> dict[str, list[str]]:
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


def _scan_groups(rows: list[tuple[str, str, str]]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
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
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?artist ?mbid ?label ?type ?typeLabel WHERE {{
  VALUES (?artist ?mbid) {{ {values} }}
  ?artist wdt:P434 ?mbid.
  OPTIONAL {{ ?artist rdfs:label ?label. FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?artist wdt:P31 ?type. OPTIONAL {{ ?type rdfs:label ?typeLabel. FILTER(LANG(?typeLabel) = "en") }} }}
}}"""


def _genre_query(qids: list[str]) -> str:
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?genre ?label WHERE {{
  VALUES ?genre {{ {_values_qids(qids)} }}
  OPTIONAL {{ ?genre rdfs:label ?label. FILTER(LANG(?label) = "en") }}
}}"""


def _parse_identity_bindings(body: bytes, requested: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    payload = json.loads(body)
    bindings = payload["results"]["bindings"]
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in bindings:
        qid = _qid(binding.get("artist", {}).get("value"))
        artist_id = _mbid(binding.get("mbid", {}).get("value"))
        key = (qid, artist_id)
        if key not in requested:
            raise GlobalArtistGenreError("artist detail response contains an unrequested QID/MBID pair")
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
        request_meta: dict[str, Any] = {"kind": kind, "index": index, "requested": values, "query_sha256": _sha256_bytes(query.encode()), "raw_path": batch_path}
        if total >= MAX_TOTAL_RESPONSE_BYTES:
            request_meta.update({"http_status": None, "response_bytes": 0, "response_sha256": _sha256_bytes(b""), "body_complete": False, "failure": "total_byte_budget"})
            (output / batch_path).write_bytes(b"")
            captures.append(request_meta)
            continue
        limit = min(MAX_DETAIL_RESPONSE_BYTES, MAX_TOTAL_RESPONSE_BYTES - total)
        response = _capture(client, query, output / batch_path, limit)
        request_meta.update(response)
        body = (output / batch_path).read_bytes()
        total += len(body)
        if response["http_status"] != HTTP_OK or not response["body_complete"]:
            request_meta["failure"] = response["failure"] or f"http_status:{response['http_status']}"
        else:
            try:
                if kind == "artist-detail":
                    pairs = {(qid, artist_id) for qid, artist_id in values}
                    parsed[f"{kind}-{index:02d}"] = _parse_identity_bindings(body, pairs)
                else:
                    parsed[f"{kind}-{index:02d}"] = _parse_genre_bindings(body, set(values))
            except (ValueError, TypeError, KeyError) as error:
                request_meta["failure"] = f"invalid_response:{type(error).__name__}"
        request_meta["binding_count"] = len(json.loads(body)["results"]["bindings"]) if "failure" not in request_meta and body else 0
        captures.append(request_meta)
    return captures, parsed, total


def _identity_status(
    artist_id: str,
    qids: set[str],
    mbids_by_qid: dict[str, set[str]],
    detail: dict[str, Any] | None,
    core_name: str,
) -> tuple[str, dict[str, Any] | None]:
    if len(qids) != 1:
        return "duplicate_p434_qids", None
    qid = next(iter(qids))
    if len(mbids_by_qid.get(qid, set())) != 1:
        return "p434_qid_reused_for_multiple_mbids", None
    if detail is None:
        return "artist_detail_unavailable", None
    labels = sorted(detail["english_labels"])
    if len(labels) != 1:
        return "english_label_missing_or_ambiguous", {"qid": qid, "english_labels": labels, "types": detail["types"]}
    if not detail["types"]:
        return "instance_type_missing", {"qid": qid, "label": labels[0], "types": {}}
    normalized_core = unicodedata.normalize("NFKC", core_name).casefold()
    normalized_wikidata = unicodedata.normalize("NFKC", labels[0]).casefold()
    if normalized_core != normalized_wikidata:
        return "core_name_mismatch", {"qid": qid, "label": labels[0], "types": detail["types"]}
    return "resolved_exact_p434_core_name", {"qid": qid, "label": labels[0], "types": detail["types"]}


def _project_selected(
    selected_ids: list[str],
    qids_by_mbid: dict[str, set[str]],
    genres_by_mbid: dict[str, set[str]],
    mbids_by_qid: dict[str, set[str]],
    core_by_mbid: dict[str, list[str]],
    artist_detail: dict[tuple[str, str], dict[str, Any]],
    genre_labels: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    projection: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    for artist_id in selected_ids:
        qids = qids_by_mbid[artist_id]
        qid = next(iter(qids)) if len(qids) == 1 else None
        detail = artist_detail.get((qid, artist_id)) if qid is not None else None
        status, identity = _identity_status(
            artist_id, qids, mbids_by_qid, detail, core_by_mbid[artist_id][0]
        )
        status_counts[status] += 1
        record: dict[str, Any] = {
            "artist_mbid": artist_id,
            "core_name": core_by_mbid[artist_id][0],
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
                    "value_label": next(iter(sorted(genre_labels.get(genre, set()))), None),
                    "source": ENDPOINT,
                    "license": LICENSE,
                    "assertion_scope": "direct Wikidata P136 statement; source assertion, not a human-reviewed genre judgment",
                }
                for genre in sorted(genres_by_mbid[artist_id])
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
        else "captured response bytes with recorded HTTP status, deterministic query hashes, and exact requested QID/UUID pairs"
    )


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
        initial_meta = _capture(client, INITIAL_QUERY, output / "raw/initial.json", MAX_SCAN_RESPONSE_BYTES)
        initial_body = (output / "raw/initial.json").read_bytes()
        if initial_meta["http_status"] != HTTP_OK or not initial_meta["body_complete"]:
            return _write_blocked_pack(output, initial_meta, core_receipt, core_path, "initial_capture_failed")
        try:
            initial_rows, rejected_rows = _parse_scan(initial_body)
            initial_bindings = json.loads(initial_body)["results"]["bindings"]
        except (ValueError, TypeError, KeyError) as error:
            initial_meta["failure"] = f"invalid_response:{type(error).__name__}"
            return _write_blocked_pack(output, initial_meta, core_receipt, core_path, "initial_response_invalid")
        if len(initial_bindings) > MAX_SCAN_ROWS + 1:
            initial_meta["failure"] = "unexpected_rows_over_scan_limit"
            return _write_blocked_pack(output, initial_meta, core_receipt, core_path, "initial_response_invalid")
        qids_by_mbid, genres_by_mbid, mbids_by_qid = _scan_groups(initial_rows)
        core_by_mbid = _core_names_for(set(qids_by_mbid), core_path, core_receipt["artist_count"])
        eligible = sorted(
            (artist_id for artist_id, names in core_by_mbid.items() if len(names) == 1),
            key=_hash_rank,
        )
        selected_ids = eligible[:max_artists]
        missing_core = sorted(set(qids_by_mbid) - set(core_by_mbid))
        duplicate_core = sorted(artist_id for artist_id, names in core_by_mbid.items() if len(names) > 1)
        selection_rows = [
            {
                "artist_mbid": artist_id,
                "core_name": core_by_mbid[artist_id][0],
                "qid_candidates": sorted(qids_by_mbid[artist_id]),
                "genre_qids": sorted(genres_by_mbid[artist_id]),
            }
            for artist_id in selected_ids
        ]
        _write_json(output / "selection.json", {
            "revision": "wikidata-global-musical-artists-selection-v1",
            "selection_method": "SHA256 rank of exact UUIDs in the initial Wikidata P434/P136 response that occur once in the verified core artist table; no labels, historical names or genre values influence selection",
            "max_artists": max_artists,
            "source_query_sha256": _sha256_bytes(INITIAL_QUERY.encode()),
            "source_bindings_seen": len(initial_bindings),
            "source_rows_used": len(initial_rows),
            "source_rows_quarantined": rejected_rows,
            "source_rows_quarantined_count": len(rejected_rows),
            "source_selection_possibly_truncated": len(initial_bindings) >= MAX_SCAN_ROWS,
            "source_artist_uuid_count": len(qids_by_mbid),
            "core_eligible_artist_uuid_count": len(eligible),
            "missing_core_artist_mbids": missing_core,
            "duplicate_core_artist_mbids": duplicate_core,
            "selected_artist_count": len(selection_rows),
            "selected": selection_rows,
        })
        artist_pairs: list[tuple[str, str]] = []
        for artist_id in selected_ids:
            qids = qids_by_mbid[artist_id]
            if len(qids) == 1:
                qid = next(iter(qids))
                if len(mbids_by_qid[qid]) == 1:
                    artist_pairs.append((qid, artist_id))
        artist_specs = [
            ("artist-detail", artist_pairs[i : i + MAX_ENTITIES_PER_BATCH], _identity_query(artist_pairs[i : i + MAX_ENTITIES_PER_BATCH]))
            for i in range(0, len(artist_pairs), MAX_ENTITIES_PER_BATCH)
        ]
        # The identity batch names contain only source QIDs and exact MBIDs. Genre labels
        # are requested only for claims belonging to an unambiguous P434 candidate.
        all_genre_qids = sorted({genre for artist_id in selected_ids if len(qids_by_mbid[artist_id]) == 1 and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1 for genre in genres_by_mbid[artist_id]})
        genre_request_slots = max(0, MAX_FOLLOWUP_REQUESTS - len(artist_specs))
        genre_qids = all_genre_qids[: genre_request_slots * MAX_ENTITIES_PER_BATCH]
        genre_specs = [
            ("genre-label", genre_qids[i : i + MAX_ENTITIES_PER_BATCH], _genre_query(genre_qids[i : i + MAX_ENTITIES_PER_BATCH]))
            for i in range(0, len(genre_qids), MAX_ENTITIES_PER_BATCH)
        ]
        if len(artist_specs) + len(genre_specs) > MAX_FOLLOWUP_REQUESTS:
            raise GlobalArtistGenreError("bounded label hydration exceeds 20 follow-up requests")
        followup_specs = artist_specs + genre_specs
        # Preserve source request ordering with the specified 1.1 second minimum interval.
        # The first request has already completed, so pause before every follow-up.
        followups: list[dict[str, Any]] = []
        parsed: dict[str, dict[Any, Any]] = {}
        total_bytes = initial_meta["response_bytes"]
        for index, (kind, values, query) in enumerate(followup_specs):
            if total_bytes >= MAX_TOTAL_RESPONSE_BYTES:
                break
            import time

            time.sleep(1.1)
            key_kind = f"{kind}-{index:02d}"
            raw_name = f"{key_kind}.json"
            capture_meta = _capture(client, query, output / "raw" / raw_name, min(MAX_DETAIL_RESPONSE_BYTES, MAX_TOTAL_RESPONSE_BYTES - total_bytes))
            capture_meta.update({"kind": kind, "index": index, "requested": values, "query_sha256": _sha256_bytes(query.encode()), "raw_path": f"raw/{raw_name}"})
            body = (output / "raw" / raw_name).read_bytes()
            total_bytes += len(body)
            if capture_meta["http_status"] == HTTP_OK and capture_meta["body_complete"]:
                try:
                    if kind == "artist-detail":
                        parsed[key_kind] = _parse_identity_bindings(body, set(values))
                    else:
                        parsed[key_kind] = _parse_genre_bindings(body, set(values))
                except (GlobalArtistGenreError, ValueError, TypeError, KeyError) as error:
                    capture_meta["failure"] = f"invalid_response:{type(error).__name__}"
            elif capture_meta["failure"] is None:
                capture_meta["failure"] = f"http_status:{capture_meta['http_status']}"
            followups.append(capture_meta)
        artist_detail: dict[tuple[str, str], dict[str, Any]] = {}
        genre_labels: dict[str, set[str]] = defaultdict(set)
        for capture in followups:
            if capture.get("failure") is not None:
                continue
            key_kind = f"{capture['kind']}-{capture['index']:02d}"
            if capture["kind"] == "artist-detail":
                artist_detail.update(parsed.get(key_kind, {}))
            else:
                for qid, labels in parsed.get(key_kind, {}).items():
                    genre_labels[qid].update(labels)
        projection_artists: list[dict[str, Any]] = []
        status_counts: dict[str, int] = defaultdict(int)
        for artist_id in selected_ids:
            status, detail = _identity_status(
                artist_id,
                qids_by_mbid[artist_id],
                mbids_by_qid,
                artist_detail.get((next(iter(qids_by_mbid[artist_id])), artist_id)) if len(qids_by_mbid[artist_id]) == 1 else None,
                core_by_mbid[artist_id][0],
            )
            status_counts[status] += 1
            record: dict[str, Any] = {
                "artist_mbid": artist_id,
                "core_name": core_by_mbid[artist_id][0],
                "candidate_wikidata_qids": sorted(qids_by_mbid[artist_id]),
                "identity_status": status,
                "wikidata_artist_qid": detail["qid"] if detail else None,
                "wikidata_english_label": detail["label"] if detail and "label" in detail else None,
                "instance_types": [
                    {"qid": qid, "english_label": label}
                    for qid, label in sorted((detail or {}).get("types", {}).items())
                ],
                "claims": [],
            }
            if status == "resolved_exact_p434_core_name" and detail is not None:
                record["claims"] = [
                    {
                        "property_id": "P136",
                        "value_qid": genre_qid,
                        "value_label": next(iter(sorted(genre_labels.get(genre_qid, set()))), None),
                        "source": ENDPOINT,
                        "license": LICENSE,
                        "assertion_scope": "direct Wikidata P136 statement; source assertion, not a human-reviewed genre judgment",
                    }
                    for genre_qid in sorted(genres_by_mbid[artist_id])
                ]
            projection_artists.append(record)
        selection = json.loads((output / "selection.json").read_bytes())
        manifest = {
            "revision": "wikidata-global-musical-artists-v1",
            "acquired_utc": datetime.now(UTC).isoformat(),
            "source": ENDPOINT,
            "license": LICENSE,
            "license_scope": "Wikidata structured data only: raw query responses, exact P434/P136 crosswalks and direct P31/label context; CC0",
            "query_service_docs": "https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service",
            "selection_sha256": _sha256_file(output / "selection.json")[0],
            "source_selection_possibly_truncated": selection["source_selection_possibly_truncated"],
            "source_scan_bindings_seen": len(initial_bindings),
            "source_scan_rows_projected": len(initial_rows),
            "source_unique_artist_uuids": len(qids_by_mbid),
            "genre_qids_with_selected_artist_claims": len(all_genre_qids),
            "genre_qids_hydrated": len(genre_qids),
            "genre_qids_not_hydrated_due_to_request_cap": len(all_genre_qids) - len(genre_qids),
            "source_selection_limit": MAX_SCAN_ROWS,
            "selected_core_artist_count": len(selected_ids),
            "identity_status_counts": dict(sorted(status_counts.items())),
            "resolved_artist_count": status_counts["resolved_exact_p434_core_name"],
            "projected_direct_claim_count": sum(len(a["claims"]) for a in projection_artists),
            "missing_english_genre_label_count": sum(c["value_label"] is None for a in projection_artists for c in a["claims"]),
            "candidate_genre_qids_not_hydrated_due_to_request_cap": len(all_genre_qids) - len(genre_qids),
            "projected_claim_genre_qids_not_hydrated": len({c["value_qid"] for a in projection_artists for c in a["claims"]} - set(genre_qids)),
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
            "status": "partial_source_sample" if selection["source_selection_possibly_truncated"] else "source_sample",
            "completeness_claim": "none; source query is capped and UUID-hash selected",
        }
        _record_compact_accounting(manifest, selection, dict(sorted(status_counts.items())))
        _write_json(output / "projection.json", {"revision": manifest["revision"], "license": LICENSE, "artists": projection_artists})
        _write_json(output / "manifest.json", manifest)
        _write_receipt(output)
    verify_global_artist_genres(output, core_directory)
    return manifest


def retry_global_artist_genres_hydration(
    directory: Path, core_directory: Path
) -> dict[str, Any]:
    """Retry smaller exact-QID detail queries against an already frozen source roster."""
    retry_files = sorted((directory / "raw").glob("artist-detail-retry-*.json"))
    if retry_files:
        receipt = json.loads(_safe_file(directory, "receipt.json").read_bytes())
        expected = receipt.get("sha256", {})
        retry_paths = {path.relative_to(directory).as_posix() for path in retry_files}
        actual = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() and path.name != "receipt.json"
        }
        if actual == set(expected):
            complete_manifest = verify_global_artist_genres(directory, core_directory)
            if len(complete_manifest["followup_captures"]) >= MAX_FOLLOWUP_REQUESTS:
                complete_selection = json.loads(_safe_file(directory, "selection.json").read_bytes())
                _record_compact_accounting(
                    complete_manifest,
                    complete_selection,
                    complete_manifest["identity_status_counts"],
                )
                _replace_json(directory / "manifest.json", complete_manifest)
                _write_receipt(directory)
                verify_global_artist_genres(directory, core_directory)
                return complete_manifest
        elif actual - retry_paths == set(expected):
            for relative, digest in expected.items():
                if _sha256_file(_safe_file(directory, relative))[0] != digest:
                    raise GlobalArtistGenreError("frozen source pack changed before retry recovery")
            if any(path.stat().st_size > MAX_DETAIL_RESPONSE_BYTES for path in retry_files):
                raise GlobalArtistGenreError("interrupted retry response exceeds its byte limit")
        else:
            raise GlobalArtistGenreError("interrupted hydration left unexpected pack files")
    else:
        verify_global_artist_genres(directory, core_directory)
    core_receipt, core_path = _verify_core_source(core_directory)
    manifest = json.loads(_safe_file(directory, "manifest.json").read_bytes())
    selection = json.loads(_safe_file(directory, "selection.json").read_bytes())
    initial_body = _safe_file(directory, "raw/initial.json").read_bytes()
    initial_rows, _ = _parse_scan(initial_body)
    qids_by_mbid, genres_by_mbid, mbids_by_qid = _scan_groups(initial_rows)
    selected_ids = [row["artist_mbid"] for row in selection["selected"]]
    core_by_mbid = {row["artist_mbid"]: [row["core_name"]] for row in selection["selected"]}
    candidate_pairs: list[tuple[str, str]] = []
    for artist_id in selected_ids:
        qids = qids_by_mbid[artist_id]
        if len(qids) == 1:
            qid = next(iter(qids))
            if len(mbids_by_qid[qid]) == 1:
                candidate_pairs.append((qid, artist_id))
    existing_details: set[tuple[str, str]] = set()
    for capture in manifest["followup_captures"]:
        if capture["kind"] == "artist-detail" and not capture.get("failure"):
            existing_details.update((item[0], item[1]) for item in capture["requested"])
    pending = [pair for pair in candidate_pairs if pair not in existing_details]
    request_slots = MAX_FOLLOWUP_REQUESTS - len(manifest["followup_captures"])
    batch_count = min(request_slots, (len(pending) + RETRY_ENTITIES_PER_BATCH - 1) // RETRY_ENTITIES_PER_BATCH)
    retry_pairs = pending[: batch_count * RETRY_ENTITIES_PER_BATCH]
    headers = {
        "User-Agent": "OpenNoise/0.1 (bounded open CC0 music metadata research)",
        "Accept": "application/sparql-results+json",
    }
    appended: list[dict[str, Any]] = []
    if retry_files:
        # A prior process captured these bodies before it could commit metadata.
        # Reconstruct their deterministic request bindings and label HTTP status unknown.
        for batch_index, raw_path in enumerate(retry_files):
            values = retry_pairs[
                batch_index * RETRY_ENTITIES_PER_BATCH : (batch_index + 1) * RETRY_ENTITIES_PER_BATCH
            ]
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
            appended.append(
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
            manifest["response_bytes_total"] += len(raw)
    else:
        with httpx.Client(timeout=30, follow_redirects=False, headers=headers) as client:
            for batch_index in range(batch_count):
                start = batch_index * RETRY_ENTITIES_PER_BATCH
                values = retry_pairs[start : start + RETRY_ENTITIES_PER_BATCH]
                query = _identity_query(values)
                response_total = int(manifest["response_bytes_total"])
                if response_total >= MAX_TOTAL_RESPONSE_BYTES:
                    break
                import time

                time.sleep(1.1)
                absolute_index = len(manifest["followup_captures"])
                raw_name = f"artist-detail-retry-{batch_index:02d}.json"
                capture_meta = _capture(
                    client,
                    query,
                    _safe_file(directory, f"raw/{raw_name}"),
                    min(MAX_DETAIL_RESPONSE_BYTES, MAX_TOTAL_RESPONSE_BYTES - response_total),
                )
                capture_meta.update(
                    {
                        "kind": "artist-detail",
                        "index": absolute_index,
                        "retry_index": batch_index,
                        "requested": values,
                        "query_sha256": _sha256_bytes(query.encode()),
                        "raw_path": f"raw/{raw_name}",
                    }
                )
                raw = _safe_file(directory, capture_meta["raw_path"]).read_bytes()
                if capture_meta["http_status"] == HTTP_OK and capture_meta["body_complete"]:
                    try:
                        _parse_identity_bindings(raw, set(values))
                    except (GlobalArtistGenreError, ValueError, TypeError, KeyError) as error:
                        capture_meta["failure"] = f"invalid_response:{type(error).__name__}"
                elif capture_meta["failure"] is None:
                    capture_meta["failure"] = f"http_status:{capture_meta['http_status']}"
                manifest["response_bytes_total"] += len(raw)
                appended.append(capture_meta)
    manifest["followup_captures"].extend(appended)
    manifest["request_count"] = 1 + len(manifest["followup_captures"])
    manifest["artist_identity_pairs_eligible_for_hydration"] = len(candidate_pairs)
    manifest["artist_identity_pairs_retried_in_small_batches"] = sum(
        len(capture["requested"]) for capture in appended
    )
    manifest["artist_identity_pairs_not_retried_due_to_request_cap"] = max(
        0, len(pending) - sum(len(capture["requested"]) for capture in appended)
    )
    manifest["retry_response_http_status_unknown_count"] = sum(
        capture.get("http_status") is None for capture in appended
    )
    manifest["retry_response_bodies_validated_count"] = sum(
        capture.get("failure") is None for capture in appended
    )
    details: dict[tuple[str, str], dict[str, Any]] = {}
    genre_labels: dict[str, set[str]] = defaultdict(set)
    for capture in manifest["followup_captures"]:
        if capture.get("failure"):
            continue
        raw = _safe_file(directory, capture["raw_path"]).read_bytes()
        if capture["kind"] == "artist-detail":
            details.update(
                _parse_identity_bindings(
                    raw, {(item[0], item[1]) for item in capture["requested"]}
                )
            )
        else:
            for qid, labels in _parse_genre_bindings(raw, set(capture["requested"])).items():
                genre_labels[qid].update(labels)
    projected, status_counts = _project_selected(
        selected_ids,
        qids_by_mbid,
        genres_by_mbid,
        mbids_by_qid,
        core_by_mbid,
        details,
        genre_labels,
    )
    manifest["identity_status_counts"] = status_counts
    manifest["resolved_artist_count"] = status_counts.get("resolved_exact_p434_core_name", 0)
    manifest["projected_direct_claim_count"] = sum(len(row["claims"]) for row in projected)
    manifest["missing_english_genre_label_count"] = sum(
        claim["value_label"] is None for row in projected for claim in row["claims"]
    )
    hydrated_genres = {
        qid for capture in manifest["followup_captures"]
        if capture["kind"] == "genre-label" and not capture.get("failure")
        for qid in capture["requested"]
    }
    manifest["projected_claim_genre_qids_not_hydrated"] = len(
        {claim["value_qid"] for row in projected for claim in row["claims"]} - hydrated_genres
    )
    _record_compact_accounting(manifest, selection, status_counts)
    _replace_json(directory / "projection.json", {"revision": manifest["revision"], "license": LICENSE, "artists": projected})
    _replace_json(directory / "manifest.json", manifest)
    _write_receipt(directory)
    verify_global_artist_genres(directory, core_directory)
    return manifest


def _write_blocked_pack(output: Path, initial: dict[str, Any], core_receipt: dict[str, Any], core_path: Path, state: str) -> dict[str, Any]:
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
    paths = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "receipt.json")
    hashes = {str(path.relative_to(output)): _sha256_file(path)[0] for path in paths}
    receipt = {"revision": "wikidata-global-musical-artists-receipt-v1", "source": ENDPOINT, "license": LICENSE, "sha256": hashes}
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


def verify_global_artist_genres(
    directory: Path, core_directory: Path = CORE_DEFAULT
) -> dict[str, Any]:
    """Offline replay raw captures, identity decisions, direct claims, and receipt."""
    _verify_receipt_files(directory)
    manifest = json.loads(_safe_file(directory, "manifest.json").read_bytes())
    if manifest["status"] in {"initial_capture_failed", "initial_response_invalid"}:
        if "projection.json" in {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}:
            raise GlobalArtistGenreError("blocked initial capture cannot contain a successful projection")
        return manifest
    selection_body = _safe_file(directory, "selection.json").read_bytes()
    selection = json.loads(selection_body)
    if _sha256_bytes(selection_body) != manifest["selection_sha256"]:
        raise GlobalArtistGenreError("selection hash differs from manifest")
    if selection["source_query_sha256"] != _sha256_bytes(INITIAL_QUERY.encode()):
        raise GlobalArtistGenreError("initial query is not the pinned source query")
    initial_meta = manifest["initial_capture"]
    if (
        initial_meta.get("raw_path") != "initial.json"
        or initial_meta.get("http_status") != HTTP_OK
        or initial_meta.get("body_complete") is not True
        or initial_meta.get("failure") is not None
        or manifest.get("source") != ENDPOINT
        or manifest.get("license") != LICENSE
    ):
        raise GlobalArtistGenreError("initial source response was not admitted as a complete capture")
    followups = manifest["followup_captures"]
    if len(followups) > MAX_FOLLOWUP_REQUESTS or manifest["request_count"] != 1 + len(followups):
        raise GlobalArtistGenreError("request count exceeds the bounded capture plan")
    if initial_meta["response_bytes"] > MAX_SCAN_RESPONSE_BYTES or any(
        capture["response_bytes"] > MAX_DETAIL_RESPONSE_BYTES for capture in followups
    ):
        raise GlobalArtistGenreError("a response exceeds its byte limit")
    if manifest["response_bytes_total"] > MAX_TOTAL_RESPONSE_BYTES:
        raise GlobalArtistGenreError("total response bytes exceed the capture budget")
    initial_body = _safe_file(directory, f"raw/{initial_meta['raw_path']}").read_bytes()
    if _sha256_bytes(initial_body) != initial_meta["response_sha256"] or len(initial_body) != initial_meta["response_bytes"]:
        raise GlobalArtistGenreError("initial response capture hash or bytes differ")
    initial_rows, rejected_rows = _parse_scan(initial_body)
    payload = json.loads(initial_body)
    bindings = payload["results"]["bindings"]
    possibly_truncated = len(bindings) >= MAX_SCAN_ROWS
    if selection["source_selection_possibly_truncated"] != possibly_truncated or manifest["source_selection_possibly_truncated"] != possibly_truncated:
        raise GlobalArtistGenreError("source truncation status is inaccurate")
    if selection["source_rows_quarantined"] != rejected_rows:
        raise GlobalArtistGenreError("source row quarantine does not replay")
    if (
        manifest.get("source_scan_bindings_seen") != len(bindings)
        or manifest.get("source_scan_rows_projected") != len(initial_rows)
        or manifest.get("source_unique_artist_uuids") != len(set(row[1] for row in initial_rows))
        or manifest.get("source_rows_quarantined_count") != len(rejected_rows)
    ):
        raise GlobalArtistGenreError("initial source scan accounting differs")
    qids_by_mbid, genres_by_mbid, mbids_by_qid = _scan_groups(initial_rows)
    selection_rows = selection["selected"]
    ids_from_selection = [row["artist_mbid"] for row in selection_rows]
    if len(set(ids_from_selection)) != len(ids_from_selection) or any(a not in qids_by_mbid for a in ids_from_selection):
        raise GlobalArtistGenreError("selected IDs do not replay from source scan")
    core_receipt, core_path = _verify_core_source(core_directory)
    core_names = _core_names_for(set(qids_by_mbid), core_path, core_receipt["artist_count"])
    eligible_ids = sorted(
        (artist_id for artist_id, names in core_names.items() if len(names) == 1),
        key=_hash_rank,
    )
    selection_cap = selection["max_artists"]
    if not isinstance(selection_cap, int) or not 1 <= selection_cap <= MAX_ARTISTS:
        raise GlobalArtistGenreError("selection cap is outside its permitted range")
    expected_selected = eligible_ids[:selection_cap]
    if ids_from_selection != expected_selected:
        raise GlobalArtistGenreError("selected roster does not replay from core IDs and hash rank")
    if len(ids_from_selection) > MAX_ARTISTS or len(ids_from_selection) != selection["selected_artist_count"]:
        raise GlobalArtistGenreError("selected artist count exceeds its cap")
    if selection["core_eligible_artist_uuid_count"] != len(eligible_ids):
        raise GlobalArtistGenreError("core eligible UUID accounting differs")
    if selection["missing_core_artist_mbids"] != sorted(set(qids_by_mbid) - set(core_names)):
        raise GlobalArtistGenreError("missing core UUID accounting differs")
    if selection["duplicate_core_artist_mbids"] != sorted(
        artist_id for artist_id, names in core_names.items() if len(names) > 1
    ):
        raise GlobalArtistGenreError("duplicate core UUID accounting differs")
    core_source = manifest["core_identity_source"]
    if (
        core_source.get("revision") != core_receipt["revision"]
        or core_source.get("license") != core_receipt["license"]
        or core_source.get("snapshot") != core_receipt["snapshot"]
        or core_source.get("artist_count") != core_receipt["artist_count"]
        or core_source.get("output_bytes") != core_receipt["output_bytes"]
        or core_source.get("output_sha256") != core_receipt["output_sha256"]
        or core_source.get("receipt_sha256") != _sha256_file(core_directory / "receipt.json")[0]
        or core_source.get("full_archive_sha256_verified") is not False
    ):
        raise GlobalArtistGenreError("manifest core source does not match the verified identity receipt")
    for row in selection_rows:
        artist_id = row["artist_mbid"]
        if row["qid_candidates"] != sorted(qids_by_mbid[artist_id]) or row["genre_qids"] != sorted(genres_by_mbid[artist_id]):
            raise GlobalArtistGenreError("selected identity or genre QIDs differ from source scan")
        if row["core_name"] != core_names[artist_id][0]:
            raise GlobalArtistGenreError("selected core name differs from the identity source")
    artist_pairs: list[tuple[str, str]] = []
    for artist_id in ids_from_selection:
        qids = qids_by_mbid[artist_id]
        if len(qids) == 1:
            qid = next(iter(qids))
            if len(mbids_by_qid[qid]) == 1:
                artist_pairs.append((qid, artist_id))
    artist_specs = [
        ("artist-detail", artist_pairs[i : i + MAX_ENTITIES_PER_BATCH], _identity_query(artist_pairs[i : i + MAX_ENTITIES_PER_BATCH]))
        for i in range(0, len(artist_pairs), MAX_ENTITIES_PER_BATCH)
    ]
    all_genre_qids = sorted(
        {
            genre
            for artist_id in ids_from_selection
            if len(qids_by_mbid[artist_id]) == 1
            and len(mbids_by_qid[next(iter(qids_by_mbid[artist_id]))]) == 1
            for genre in genres_by_mbid[artist_id]
        }
    )
    genre_slots = max(0, MAX_FOLLOWUP_REQUESTS - len(artist_specs))
    expected_genre_qids = all_genre_qids[: genre_slots * MAX_ENTITIES_PER_BATCH]
    genre_specs = [
        ("genre-label", expected_genre_qids[i : i + MAX_ENTITIES_PER_BATCH], _genre_query(expected_genre_qids[i : i + MAX_ENTITIES_PER_BATCH]))
        for i in range(0, len(expected_genre_qids), MAX_ENTITIES_PER_BATCH)
    ]
    expected_initial_specs = artist_specs + genre_specs
    if len(expected_initial_specs) > MAX_FOLLOWUP_REQUESTS:
        raise GlobalArtistGenreError("replayed query plan exceeds the follow-up request cap")
    # Rebuild typed details exclusively from query-plan-bound raw follow-up responses.
    detail_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    genre_labels: dict[str, set[str]] = defaultdict(set)
    hydrated_genres: set[str] = set()

    def validate_capture_admission(capture: dict[str, Any], *, retry: bool) -> bool:
        status = capture.get("http_status")
        failure = capture.get("failure")
        if status is None and capture.get("status_metadata") == "capture process ended before status metadata was committed":
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
            if failure != f"http_status:{status}" and failure != "response_byte_limit":
                raise GlobalArtistGenreError("non-200 capture failure does not match its HTTP status")
        else:
            raise GlobalArtistGenreError("capture has no admissible HTTP status or transport failure")
        if failure is None and capture.get("body_complete") is not True:
            raise GlobalArtistGenreError("incomplete response cannot be admitted")
        return failure is None

    response_bytes_sum = len(initial_body)
    for index, capture in enumerate(followups[: len(expected_initial_specs)]):
        expected_kind, expected_values, expected_query = expected_initial_specs[index]
        expected_serialized_values = [
            list(value) if isinstance(value, tuple) else value for value in expected_values
        ]
        if (
            capture.get("kind") != expected_kind
            or capture.get("index") != index
            or capture.get("requested") != expected_serialized_values
            or capture.get("query_sha256") != _sha256_bytes(expected_query.encode())
            or capture.get("raw_path") != f"raw/{expected_kind}-{index:02d}.json"
        ):
            raise GlobalArtistGenreError("follow-up capture differs from the deterministic query plan")
        raw = _safe_file(directory, capture["raw_path"]).read_bytes()
        if _sha256_bytes(raw) != capture["response_sha256"] or len(raw) != capture["response_bytes"]:
            raise GlobalArtistGenreError("follow-up response hash or byte count differs")
        response_bytes_sum += len(raw)
        if not validate_capture_admission(capture, retry=False):
            continue
        if expected_kind == "artist-detail":
            pairs = {(item[0], item[1]) for item in expected_values}
            detail_by_pair.update(_parse_identity_bindings(raw, pairs))
        else:
            hydrated_genres.update(expected_values)
            labels_by_batch = _parse_genre_bindings(raw, set(expected_values))
            for qid, labels in labels_by_batch.items():
                genre_labels[qid].update(labels)
    if len(followups) < len(expected_initial_specs):
        raise GlobalArtistGenreError("follow-up capture set omits planned initial requests")

    successful_initial_pairs = set(detail_by_pair)
    retry_pending = [pair for pair in artist_pairs if pair not in successful_initial_pairs]
    retry_captures = followups[len(expected_initial_specs) :]
    retry_capacity = MAX_FOLLOWUP_REQUESTS - len(expected_initial_specs)
    if len(retry_captures) > retry_capacity:
        raise GlobalArtistGenreError("retry requests exceed the remaining follow-up cap")
    for retry_index, capture in enumerate(retry_captures):
        expected_values = retry_pending[
            retry_index * RETRY_ENTITIES_PER_BATCH : (retry_index + 1) * RETRY_ENTITIES_PER_BATCH
        ]
        if not expected_values:
            raise GlobalArtistGenreError("retry request exists without a remaining frozen roster")
        expected_query = _identity_query(expected_values)
        expected_serialized_values = [list(value) for value in expected_values]
        if (
            capture.get("kind") != "artist-detail"
            or capture.get("retry_index") != retry_index
            or capture.get("index") != len(expected_initial_specs) + retry_index
            or capture.get("requested") != expected_serialized_values
            or capture.get("query_sha256") != _sha256_bytes(expected_query.encode())
            or capture.get("raw_path") != f"raw/artist-detail-retry-{retry_index:02d}.json"
        ):
            raise GlobalArtistGenreError("retry capture differs from the deterministic frozen roster")
        raw = _safe_file(directory, capture["raw_path"]).read_bytes()
        if _sha256_bytes(raw) != capture["response_sha256"] or len(raw) != capture["response_bytes"]:
            raise GlobalArtistGenreError("retry response hash or byte count differs")
        response_bytes_sum += len(raw)
        if not validate_capture_admission(capture, retry=True):
            continue
        detail_by_pair.update(_parse_identity_bindings(raw, set(expected_values)))
    if response_bytes_sum != manifest["response_bytes_total"]:
        raise GlobalArtistGenreError("manifest total response bytes do not equal captured bodies")
    core_map = {row["artist_mbid"]: row["core_name"] for row in selection_rows}
    projected: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    for artist_id in ids_from_selection:
        qids = qids_by_mbid[artist_id]
        qid = next(iter(qids)) if len(qids) == 1 else None
        detail = detail_by_pair.get((qid, artist_id)) if qid is not None else None
        status, identity = _identity_status(artist_id, qids, mbids_by_qid, detail, core_map[artist_id])
        status_counts[status] += 1
        record: dict[str, Any] = {
            "artist_mbid": artist_id,
            "core_name": core_map[artist_id],
            "candidate_wikidata_qids": sorted(qids),
            "identity_status": status,
            "wikidata_artist_qid": identity["qid"] if identity else None,
            "wikidata_english_label": identity.get("label") if identity else None,
            "instance_types": [{"qid": q, "english_label": label} for q, label in sorted((identity or {}).get("types", {}).items())],
            "claims": [],
        }
        if status == "resolved_exact_p434_core_name":
            record["claims"] = [
                {"property_id": "P136", "value_qid": genre, "value_label": next(iter(sorted(genre_labels.get(genre, set()))), None), "source": ENDPOINT, "license": LICENSE, "assertion_scope": "direct Wikidata P136 statement; source assertion, not a human-reviewed genre judgment"}
                for genre in sorted(genres_by_mbid[artist_id])
            ]
        projected.append(record)
    expected = {"revision": manifest["revision"], "license": LICENSE, "artists": projected}
    actual = json.loads(_safe_file(directory, "projection.json").read_bytes())
    if actual != expected:
        raise GlobalArtistGenreError("projection does not replay from exact source QIDs")
    if manifest["identity_status_counts"] != dict(sorted(status_counts.items())):
        raise GlobalArtistGenreError("identity status accounting differs")
    if (
        sum(status_counts.values()) != len(ids_from_selection)
        or manifest.get("selected_terminal_status_denominator") != len(ids_from_selection)
    ):
        raise GlobalArtistGenreError("selected artist terminal status denominator is not closed")
    if manifest["resolved_artist_count"] != status_counts["resolved_exact_p434_core_name"]:
        raise GlobalArtistGenreError("resolved artist accounting differs")
    if manifest["projected_direct_claim_count"] != sum(len(row["claims"]) for row in projected):
        raise GlobalArtistGenreError("direct claim accounting differs")
    claims_genres = {claim["value_qid"] for row in projected for claim in row["claims"]}
    if manifest["projected_claim_genre_qids_not_hydrated"] != len(claims_genres - hydrated_genres):
        raise GlobalArtistGenreError("unhydrated genre QID accounting differs")
    unknown_status_count = sum(capture.get("http_status") is None for capture in followups)
    if manifest.get("retry_response_http_status_unknown_count") != unknown_status_count:
        raise GlobalArtistGenreError("unknown HTTP status accounting differs")
    if unknown_status_count and "HTTP status is unknown" not in manifest.get("source_response_scope", ""):
        raise GlobalArtistGenreError("unknown HTTP status is omitted from response scope")
    return manifest
