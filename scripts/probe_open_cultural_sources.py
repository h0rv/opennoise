"""Probe Wikidata and optionally acquire a small exact-MBID cultural-context pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NotRequired, TypedDict, cast

import httpx

from opennoise.ingest.open_cultural_source import (
    ENDPOINT,
    PROPERTY_IDS,
    CulturalArtistEvidence,
    build_query,
    capture_raw_response,
    parse_bindings,
)

BENCHMARK_MANIFEST = Path(
    ".cache/acousticbrainz-benchmark-metadata-20260930-v1/query-manifest.json"
)
ARTIST_SEARCH = Path(".cache/named-style-atlas-20260930-v2/artist-search.json")
ARTIST_FEATURES = Path(".cache/microgenre-features-rich-v2/artist-features.jsonl")
DEFAULT_PACK = Path(".cache/open-cultural-context-wikidata-20261001-v2")
ARTISTS = (
    "0b0c25f4-f31c-46a5-a4fb-ccbf53d663bd",
    "3bcff06f-675a-451f-9075-99e8657047e8",
    "410c9baf-5469-44f6-9852-826524b80c61",
    "4d86ad4e-28d8-4e9f-8cf4-735c57060fdc",
    "69158f97-4c07-4c4e-baf8-4e4ab1ed666e",
    "69d9c5ba-7bba-4cb7-ab32-8ccc48ad4f97",
    "735e3514-a8ae-401f-af3b-6300df1b8d2c",
    "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6",
    "f22942a1-6f70-4f48-866e-238cb2308fbd",
    "ff95eb47-41c4-4f7f-a104-cdc30f02e872",
)
STRATA = (
    "hip hop",
    "jazz",
    "rock",
    "pop",
    "punk",
    "metal",
    "classical",
    "folk",
    "ambient",
    "house",
    "techno",
    "reggae",
    "soul",
    "country",
    "blues",
    "disco",
    "industrial",
    "noise",
)
MAX_BYTES = 2_000_000
MAX_PACK_BYTES = 10_000_000
SOURCE_SAMPLE_SIZE = 100
MAX_PER_STRATUM = 6
MAX_ARTISTS_PER_BATCH = 50
HTTP_OK = 200
PORTABLE_EXPECTED_ARTISTS = 110
PORTABLE_EXPECTED_MATCHES = 48
PORTABLE_EXPECTED_CLAIMS = 130


class CohortArtist(TypedDict):
    """Exact-ID artist included in the frozen cultural-context sample."""

    artist_mbid: str
    name: str
    role: str
    selection_stratum: NotRequired[str]
    source_genres: NotRequired[list[str]]


DOCS = {
    "query_service": "https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service",
    "musicbrainz_artist_id_property": "https://www.wikidata.org/wiki/Property:P434",
    "genre_property": "https://www.wikidata.org/wiki/Property:P136",
    "country_of_origin_property": "https://www.wikidata.org/wiki/Property:P495",
    "location_formed_property": "https://www.wikidata.org/wiki/Property:P740",
    "movement_property": "https://www.wikidata.org/wiki/Property:P135",
    "license": "https://www.wikidata.org/wiki/Wikidata:Licensing",
}


def sha256_file(path: Path) -> str:
    """Hash one local source artifact in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_source_genres(
    names: dict[str, str], benchmark_ids: set[str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Read direct-genre strata by exact MBID from the local feature cache."""
    genres_by_artist: dict[str, set[str]] = defaultdict(set)
    artists_by_genre: dict[str, set[str]] = defaultdict(set)
    with ARTIST_FEATURES.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            artist_id = item.get("artist_mbid")
            if artist_id not in names or artist_id in benchmark_ids:
                continue
            for feature in item.get("features", []):
                if feature.get("namespace") == "artist_genre":
                    genre = feature["value"]
                    genres_by_artist[artist_id].add(genre)
                    artists_by_genre[genre].add(artist_id)
    return genres_by_artist, artists_by_genre


def _select_source_ids(
    artists_by_genre: dict[str, set[str]], names: dict[str, str], benchmark_ids: set[str]
) -> dict[str, str]:
    """Select a stable broad sample with deterministic fill for sparse strata."""
    chosen: dict[str, str] = {}
    for genre in STRATA:
        ordered = sorted(
            artists_by_genre[genre],
            key=lambda artist_id: hashlib.sha256(
                f"open-cultural-context-v1:{genre}:{artist_id}".encode()
            ).hexdigest(),
        )
        for artist_id in ordered:
            if len(chosen) >= SOURCE_SAMPLE_SIZE:
                break
            chosen.setdefault(artist_id, genre)
            if sum(value == genre for value in chosen.values()) >= MAX_PER_STRATUM:
                break
    leftovers = set(names) - benchmark_ids - set(chosen)
    for artist_id in sorted(
        leftovers,
        key=lambda value: hashlib.sha256(f"open-cultural-context-v1:{value}".encode()).hexdigest(),
    ):
        if len(chosen) >= SOURCE_SAMPLE_SIZE:
            break
        chosen[artist_id] = "deterministic_fill"
    if len(chosen) != SOURCE_SAMPLE_SIZE:
        raise ValueError("source catalog did not provide 100 unique non-benchmark IDs")
    return chosen


def choose_pack_cohort() -> tuple[list[CohortArtist], dict[str, Any]]:
    """Select ten frozen benchmarks and 100 stable, genre-stratified exact IDs."""
    benchmark_data = json.loads(BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    benchmarks = benchmark_data["artists"]
    benchmark_ids = {item["artist_mbid"] for item in benchmarks}
    search_data = json.loads(ARTIST_SEARCH.read_text(encoding="utf-8"))
    names = {item[0]: item[1] for item in search_data["artists"]}
    genres_by_artist, artists_by_genre = _read_source_genres(names, benchmark_ids)
    chosen = _select_source_ids(artists_by_genre, names, benchmark_ids)
    cohort: list[CohortArtist] = [
        {"artist_mbid": item["artist_mbid"], "name": item["name"], "role": "benchmark"}
        for item in benchmarks
    ] + [
        {
            "artist_mbid": artist_id,
            "name": names[artist_id],
            "role": "stratified_source_artist",
            "selection_stratum": stratum,
            "source_genres": sorted(genres_by_artist.get(artist_id, set())),
        }
        for artist_id, stratum in sorted(chosen.items())
    ]
    selection = {
        "benchmark_manifest_path": str(BENCHMARK_MANIFEST),
        "benchmark_manifest_sha256": sha256_file(BENCHMARK_MANIFEST),
        "artist_search_path": str(ARTIST_SEARCH),
        "artist_search_sha256": sha256_file(ARTIST_SEARCH),
        "artist_features_path": str(ARTIST_FEATURES),
        "artist_features_sha256": sha256_file(ARTIST_FEATURES),
        "artist_search_name_count": len(names),
        "benchmark_count": len(benchmarks),
        "stratified_source_artist_count": len(chosen),
        "selection_strata": list(STRATA),
        "selection": (
            "SHA256-ranked exact MBID within each listed local artist_genre stratum, "
            "six max per stratum, then SHA256 fill"
        ),
        "identity_rule": (
            "artist names are retained for display and provenance only; "
            "identity joins use exact MBID"
        ),
    }
    return cohort, selection


def acquire_pack(output: Path) -> None:
    """Acquire three immutable response batches and derive property-specific neighbors."""
    cohort, selection = choose_pack_cohort()
    artist_ids: tuple[str, ...] = tuple(item["artist_mbid"] for item in cohort)
    batches = [artist_ids[index : index + 50] for index in range(0, len(artist_ids), 50)]
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    manifest: dict[str, object] = {
        "revision": "open-cultural-context-wikidata-v2",
        "acquired_utc": datetime.now(UTC).isoformat(),
        "endpoint": ENDPOINT,
        "license": "CC0",
        "docs": DOCS,
        "properties": sorted(PROPERTY_IDS),
        "selection": selection,
        "cohort": cohort,
        "requested_artist_count": len(artist_ids),
        "batch_count": len(batches),
        "batches": [],
        "response_bytes_total": 0,
        "request_count": 0,
        "raw_capture_mode": "exact response bytes",
    }
    all_evidence: list[CulturalArtistEvidence] = []
    total_bytes = 0
    with httpx.Client(
        timeout=30,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded CC0 metadata research)",
            "Accept": "application/sparql-results+json",
        },
    ) as client:
        for index, batch in enumerate(batches):
            if index:
                time.sleep(1.1)
            query, body, status = capture_raw_response(batch, client=client)
            total_bytes += len(body)
            if total_bytes > MAX_PACK_BYTES:
                raise ValueError("total response bytes exceeded the 10 MB pack cap")
            payload = json.loads(body)
            evidence = parse_bindings(payload, set(batch))
            rows = payload["results"]["bindings"]
            raw_path = output / "raw" / f"batch-{index:02d}.json"
            raw_path.write_bytes(body)
            matched_ids = {item.musicbrainz_artist_id for item in evidence}
            manifest["batches"].append(
                {
                    "index": index,
                    "requested_mbids": list(batch),
                    "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                    "response_sha256": hashlib.sha256(body).hexdigest(),
                    "response_bytes": len(body),
                    "http_status": status,
                    "returned_binding_count": len(rows),
                    "matched_artist_count": len(evidence),
                    "unmatched_artist_mbids": sorted(set(batch) - matched_ids),
                    "raw_path": str(raw_path.relative_to(output)),
                }
            )
            all_evidence.extend(evidence)
    if len({item.musicbrainz_artist_id for item in all_evidence}) != len(all_evidence):
        raise ValueError("multiple Wikidata artists resolved to the same requested MBID")
    manifest["request_count"] = len(batches)
    manifest["response_bytes_total"] = total_bytes
    matched_ids = {item.musicbrainz_artist_id for item in all_evidence}
    manifest["matched_artist_count"] = len(all_evidence)
    manifest["unmatched_artist_count"] = len(artist_ids) - len(all_evidence)
    manifest["unmatched_artist_mbids"] = sorted(set(artist_ids) - matched_ids)
    manifest["direct_claim_count"] = sum(len(item.claims) for item in all_evidence)
    manifest["artist_match_rate"] = len(all_evidence) / len(artist_ids)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    evidence_path = output / "artist-evidence.json"
    evidence_path.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in all_evidence], sort_keys=True, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    neighbors_path = output / "benchmark-neighbors.json"
    neighbor_rows = make_benchmark_neighbors(cohort, all_evidence)
    neighbors_path.write_text(
        json.dumps(neighbor_rows, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    hashes = {
        str(path.relative_to(output)): sha256_file(path)
        for path in (
            manifest_path,
            evidence_path,
            neighbors_path,
            *sorted((output / "raw").glob("*.json")),
        )
    }
    receipt = {
        "revision": "open-cultural-context-wikidata-v2",
        "source": ENDPOINT,
        "license": "CC0",
        "license_scope": "Wikidata raw responses and direct projections only",
        "selection_claim_license": "MusicBrainz supplementary associations CC-BY-NC-SA-3.0",
        "sha256": hashes,
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        json.dumps(
            {"output": str(output), "receipt": receipt, "neighbors": len(neighbor_rows)}, indent=2
        )
        + "\n"
    )


def make_benchmark_neighbors(
    cohort: list[CohortArtist], evidence: list[CulturalArtistEvidence]
) -> list[dict[str, Any]]:
    """Score benchmark-to-candidate overlap separately for each direct property."""
    by_id = {item.musicbrainz_artist_id: item for item in evidence}
    benchmarks = [item for item in cohort if item["role"] == "benchmark"]
    candidates = [item for item in cohort if item["role"] == "stratified_source_artist"]
    rows: list[dict[str, Any]] = []
    for anchor in benchmarks:
        anchor_evidence = by_id.get(anchor["artist_mbid"])
        if anchor_evidence is None:
            continue
        anchor_claims: dict[str, set[str]] = defaultdict(set)
        for claim in anchor_evidence.claims:
            anchor_claims[claim.property_id].add(claim.value_qid)
        for candidate in candidates:
            candidate_evidence = by_id.get(candidate["artist_mbid"])
            if candidate_evidence is None:
                continue
            candidate_claims: dict[str, set[str]] = defaultdict(set)
            for claim in candidate_evidence.claims:
                candidate_claims[claim.property_id].add(claim.value_qid)
            for property_id in sorted(set(anchor_claims) & set(candidate_claims)):
                left = anchor_claims[property_id]
                right = candidate_claims[property_id]
                shared = sorted(left & right)
                if not shared:
                    continue
                rows.append(
                    {
                        "anchor_artist_mbid": anchor["artist_mbid"],
                        "anchor_label": anchor_evidence.label,
                        "candidate_artist_mbid": candidate["artist_mbid"],
                        "candidate_label": candidate_evidence.label,
                        "property_id": property_id,
                        "score": len(shared) / len(left | right),
                        "shared_value_qids": shared,
                        "anchor_value_count": len(left),
                        "candidate_value_count": len(right),
                        "score_method": "Jaccard overlap within one direct Wikidata property only",
                        "source": ENDPOINT,
                        "license": "CC0",
                    }
                )
    rows.sort(
        key=lambda row: (
            row["anchor_artist_mbid"],
            row["property_id"],
            -float(row["score"]),
            row["candidate_artist_mbid"],
        )
    )
    return rows


def _safe_pack_path(directory: Path, relative_path: str) -> Path:
    """Resolve a receipt or response path while rejecting escapes and symlinks."""
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("pack paths must be safe relative paths")
    if "\\" in relative_path:
        raise ValueError("pack paths must use portable forward slashes")
    root = directory.resolve()
    candidate = directory.joinpath(*relative.parts)
    current = directory
    if current.is_symlink():
        raise ValueError("pack root must not be a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("pack paths must not traverse symlinks")
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("pack path escapes its root")
    return candidate


def _verify_pack_file_hashes(directory: Path) -> dict[str, Any]:
    """Check receipt source/license, exact files, and all artifact hashes."""
    receipt_path = _safe_pack_path(directory, "receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["source"] != ENDPOINT or receipt["license"] != "CC0":
        raise ValueError("receipt source or license does not match this adapter")
    expected = receipt["sha256"]
    if not isinstance(expected, dict):
        raise TypeError("receipt hashes must be an object")
    expected_paths = set(expected)
    for relative_path in expected_paths:
        _safe_pack_path(directory, relative_path)
    actual_paths: set[str] = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("pack paths must not traverse symlinks")
        if path.is_file() and path.name != "receipt.json":
            actual_paths.add(str(path.relative_to(directory)))
    if actual_paths != expected_paths:
        raise ValueError("pack file set differs from receipt")
    for relative_path, expected_hash in expected.items():
        path = _safe_pack_path(directory, relative_path)
        if sha256_file(path) != expected_hash:
            raise ValueError(f"pack artifact hash mismatch: {relative_path}")
    return receipt


def _replay_batch(
    directory: Path, batch: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[CulturalArtistEvidence, ...], int]:
    """Validate one exact-ID request record and replay its raw response."""
    batch_ids = cast("tuple[str, ...]", tuple(batch["requested_mbids"]))
    if not batch_ids or len(batch_ids) > MAX_ARTISTS_PER_BATCH:
        raise ValueError("batch must contain 1 to 50 artist IDs")
    if len(set(batch_ids)) != len(batch_ids):
        raise ValueError("batch contains duplicate requested artist IDs")
    query = build_query(batch_ids)
    if hashlib.sha256(query.encode()).hexdigest() != batch["query_sha256"]:
        raise ValueError(f"query hash mismatch in batch {batch['index']}")
    if batch["http_status"] != HTTP_OK:
        raise ValueError(f"batch {batch['index']} did not return HTTP 200")
    body = _safe_pack_path(directory, batch["raw_path"]).read_bytes()
    body_size = len(body)
    if body_size != batch["response_bytes"] or body_size > MAX_BYTES:
        raise ValueError(f"batch {batch['index']} response byte count is invalid")
    if hashlib.sha256(body).hexdigest() != batch["response_sha256"]:
        raise ValueError(f"response hash mismatch in batch {batch['index']}")
    payload = json.loads(body)
    results = payload.get("results")
    bindings = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(bindings, list) or len(bindings) != batch["returned_binding_count"]:
        raise ValueError(f"batch {batch['index']} binding count is invalid")
    evidence = parse_bindings(payload, set(batch_ids))
    matched_ids = {item.musicbrainz_artist_id for item in evidence}
    unmatched_ids = sorted(set(batch_ids) - matched_ids)
    if len(evidence) != batch["matched_artist_count"]:
        raise ValueError(f"batch {batch['index']} match count is invalid")
    if batch.get("unmatched_artist_mbids", unmatched_ids) != unmatched_ids:
        raise ValueError(f"batch {batch['index']} unmatched IDs are incomplete")
    return batch_ids, evidence, body_size


def _validate_replay_accounting(
    manifest: dict[str, Any],
    cohort_ids: list[str],
    requested_ids: list[str],
    replayed: list[CulturalArtistEvidence],
    response_bytes: int,
) -> None:
    """Ensure all requested, matched, unmatched, and returned bytes are accounted for."""
    if len(set(cohort_ids)) != len(cohort_ids):
        raise ValueError("cohort contains duplicate MusicBrainz artist IDs")
    if len(cohort_ids) != manifest["requested_artist_count"]:
        raise ValueError("cohort size differs from requested artist count")
    if set(requested_ids) != set(cohort_ids):
        raise ValueError("batch requests do not cover the exact cohort")
    if response_bytes != manifest["response_bytes_total"] or response_bytes > MAX_PACK_BYTES:
        raise ValueError("response byte total is invalid")
    matched_ids = {item.musicbrainz_artist_id for item in replayed}
    unmatched = sorted(set(cohort_ids) - matched_ids)
    if len(replayed) != manifest["matched_artist_count"]:
        raise ValueError("matched artist count is invalid")
    if manifest.get("unmatched_artist_mbids", unmatched) != unmatched:
        raise ValueError("manifest unmatched artist IDs are incomplete")
    if manifest.get("unmatched_artist_count", len(unmatched)) != len(unmatched):
        raise ValueError("manifest unmatched artist count is invalid")
    claim_count = sum(len(item.claims) for item in replayed)
    if manifest.get("direct_claim_count", claim_count) != claim_count:
        raise ValueError("manifest direct claim count is invalid")


def _replay_responses(
    directory: Path, manifest: dict[str, Any], receipt_paths: set[str]
) -> list[CulturalArtistEvidence]:
    """Rebuild exact-ID claim records and enforce complete request/response accounting."""
    cohort = cast("list[CohortArtist]", manifest["cohort"])
    cohort_ids = [item["artist_mbid"] for item in cohort]
    batches = manifest["batches"]
    if len(batches) != manifest["batch_count"] or len(batches) != manifest["request_count"]:
        raise ValueError("batch and request counts do not match manifest")
    replayed: list[CulturalArtistEvidence] = []
    requested_ids: list[str] = []
    response_bytes = 0
    for batch in batches:
        raw_path = batch["raw_path"]
        if raw_path not in receipt_paths:
            raise ValueError("batch raw response is missing from receipt hashes")
        batch_ids, evidence, body_size = _replay_batch(directory, batch)
        if set(requested_ids) & set(batch_ids):
            raise ValueError("requested artist IDs repeat across batches")
        requested_ids.extend(batch_ids)
        replayed.extend(evidence)
        response_bytes += body_size
    _validate_replay_accounting(manifest, cohort_ids, requested_ids, replayed, response_bytes)
    return replayed


def verify_pack(directory: Path) -> None:
    """Verify receipt hashes and replay raw responses into both projections."""
    receipt = _verify_pack_file_hashes(directory)
    receipt_paths = set(receipt["sha256"])
    manifest = json.loads(_safe_pack_path(directory, "manifest.json").read_text(encoding="utf-8"))
    cohort = cast("list[CohortArtist]", manifest["cohort"])
    requested = {item["artist_mbid"] for item in cohort}
    portable_lineage = manifest.get("portable_derivation")
    if portable_lineage:
        if (
            receipt.get("derived_from_manifest_sha256")
            != portable_lineage["source_manifest_sha256"]
        ):
            raise ValueError("portable receipt lineage differs from its manifest")
        if len(cohort) != PORTABLE_EXPECTED_ARTISTS or any(
            "source_genres" in item or "selection_stratum" in item for item in cohort
        ):
            raise ValueError("portable cohort must have 110 identity-only artist records")
        if (
            manifest.get("matched_artist_count") != PORTABLE_EXPECTED_MATCHES
            or manifest.get("direct_claim_count") != PORTABLE_EXPECTED_CLAIMS
        ):
            raise ValueError("portable pack does not match reviewed 110/48/130 counts")
    replayed = _replay_responses(directory, manifest, receipt_paths)
    artist_rows = json.loads(
        _safe_pack_path(directory, "artist-evidence.json").read_text(encoding="utf-8")
    )
    expected_evidence = [item.model_dump(mode="json") for item in replayed]
    if expected_evidence != artist_rows:
        raise ValueError("claim projection does not replay from raw responses")
    returned = {item.musicbrainz_artist_id for item in replayed}
    if len(returned) != len(replayed) or not returned <= requested:
        raise ValueError("projection has duplicate or unrequested artist MBIDs")
    neighbors = json.loads(
        _safe_pack_path(directory, "benchmark-neighbors.json").read_text(encoding="utf-8")
    )
    if make_benchmark_neighbors(cohort, replayed) != neighbors:
        raise ValueError("neighbor projection does not replay from direct claims")
    sys.stdout.write(
        f"verified receipt, raw replay, and projections; "
        f"{len(returned)} exact artist matches; "
        f"{sum(len(item.claims) for item in replayed)} claims; "
        f"{len(neighbors)} scored neighbors\n"
    )


def make_portable_manifest(
    source_manifest: dict[str, Any],
    source_manifest_sha256: str,
    evidence: list[CulturalArtistEvidence],
) -> dict[str, Any]:
    """Remove nonportable cohort genre values while retaining identity and source hashes."""
    portable = json.loads(json.dumps(source_manifest))
    portable["cohort"] = [
        {key: artist[key] for key in ("artist_mbid", "name", "role")}
        for artist in source_manifest["cohort"]
    ]
    portable_selection = dict(source_manifest["selection"])
    strata = portable_selection.pop("selection_strata", [])
    portable_selection["selection_strata_count"] = len(strata)
    portable["selection"] = portable_selection
    cohort_ids = {item["artist_mbid"] for item in portable["cohort"]}
    matched_ids = {item.musicbrainz_artist_id for item in evidence}
    unmatched = sorted(cohort_ids - matched_ids)
    for batch in portable["batches"]:
        batch_ids = set(batch["requested_mbids"])
        batch["unmatched_artist_mbids"] = sorted(batch_ids - matched_ids)
    portable["unmatched_artist_mbids"] = unmatched
    portable["unmatched_artist_count"] = len(unmatched)
    portable["direct_claim_count"] = sum(len(item.claims) for item in evidence)
    portable["portable_derivation"] = {
        "source_manifest_sha256": source_manifest_sha256,
        "removed_fields": [
            "cohort.source_genres",
            "cohort.selection_stratum",
            "selection.selection_strata",
        ],
        "reason": (
            "cohort genre selection values come from supplementary "
            "noncommercial artist associations"
        ),
    }
    return portable


def write_portable_pack(source_directory: Path, output_directory: Path) -> None:
    """Create a create-once CC0 pack with source-claim selection values removed."""
    verify_pack(source_directory)
    source_manifest_path = _safe_pack_path(source_directory, "manifest.json")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_receipt = _verify_pack_file_hashes(source_directory)
    source_manifest_sha256 = source_receipt["sha256"]["manifest.json"]
    if source_manifest_sha256 != sha256_file(source_manifest_path):
        raise ValueError("local v2 manifest hash changed since its receipt")
    evidence = [
        CulturalArtistEvidence.model_validate(item)
        for item in json.loads(
            _safe_pack_path(source_directory, "artist-evidence.json").read_text(encoding="utf-8")
        )
    ]
    output_directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source_directory / "raw", output_directory / "raw")
    for name in ("artist-evidence.json", "benchmark-neighbors.json"):
        shutil.copy2(source_directory / name, output_directory / name)
    portable = make_portable_manifest(source_manifest, source_manifest_sha256, evidence)
    manifest_path = output_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(portable, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    hashes = {
        str(path.relative_to(output_directory)): sha256_file(path)
        for path in (
            manifest_path,
            output_directory / "artist-evidence.json",
            output_directory / "benchmark-neighbors.json",
            *sorted((output_directory / "raw").glob("*.json")),
        )
    }
    receipt = {
        "revision": "open-cultural-context-wikidata-portable-v1",
        "source": ENDPOINT,
        "license": "CC0",
        "derived_from_manifest_sha256": source_manifest_sha256,
        "sha256": hashes,
    }
    (output_directory / "receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    verify_pack(output_directory)


def run_demo(directory: Path) -> None:
    """Print the highest scored source-backed benchmark cultural overlaps."""
    rows = json.loads((directory / "benchmark-neighbors.json").read_text(encoding="utf-8"))
    rows.sort(
        key=lambda row: (-row["score"], row["anchor_artist_mbid"], row["candidate_artist_mbid"])
    )
    sys.stdout.write(
        json.dumps({"source": ENDPOINT, "license": "CC0", "neighbors": rows[:5]}, indent=2) + "\n"
    )


def run_probe(output: Path | None) -> None:
    """Run the fixed ten-ID exact benchmark endpoint probe."""
    query = build_query(ARTISTS)
    with httpx.Client(
        timeout=20,
        headers={
            "User-Agent": "OpenNoise/0.1 (open cultural metadata research)",
            "Accept": "application/sparql-results+json",
        },
    ) as client:
        _, body, status_code = capture_raw_response(ARTISTS, client=client)
    payload = json.loads(body)
    evidence = parse_bindings(payload, set(ARTISTS))
    artifact = {
        "checked_utc_date": datetime.now(UTC).date().isoformat(),
        "endpoint": ENDPOINT,
        "request_count": 1,
        "request_body_bytes": 0,
        "response_bytes": len(body),
        "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "status_code": status_code,
        "requested_mbids": sorted(ARTISTS),
        "returned_artists": [item.model_dump(mode="json") for item in evidence],
        "returned_artist_count": len(evidence),
        "docs": DOCS,
        "license": "Wikidata structured data is dedicated to the public domain under CC0",
        "identity_note": "IDs are the exact ten-artist frozen benchmark manifest cohort",
    }
    serialized = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)


def main() -> None:
    """Probe the source or acquire the bounded cultural-context pack."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--acquire-pack", action="store_true")
    parser.add_argument("--verify-pack", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--write-portable-pack", action="store_true")
    parser.add_argument(
        "--portable-output", type=Path, default=Path("data/examples/cultural-context")
    )
    parser.add_argument("--pack-output", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()
    if args.verify_pack:
        verify_pack(args.pack_output)
    elif args.write_portable_pack:
        write_portable_pack(args.pack_output, args.portable_output)
    elif args.demo:
        run_demo(args.pack_output)
    elif args.acquire_pack:
        acquire_pack(args.pack_output)
    else:
        run_probe(args.output)


if __name__ == "__main__":
    main()
