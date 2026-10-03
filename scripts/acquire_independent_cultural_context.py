"""Acquire/replay a curated, exact-ID Wikidata CC0 cultural evidence pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast

import httpx

from opennoise.ingest.open_cultural_source import (
    ENDPOINT,
    CulturalArtistEvidence,
    build_query,
    capture_raw_response,
    parse_bindings,
)

# Curated roster (names are provenance/display only); stable QIDs and exact P434
# MusicBrainz IDs came from the retained exact-English-label crosswalk capture.
ROSTER: list[tuple[str, str, str]] = [
    ("Miles Davis", "Q93341", "561d854a-6a28-4aa7-8c99-323e6ce46c2a"),
    ("John Coltrane", "Q7346", "b625448e-bf4a-41c3-a421-72ad46cdb831"),
    ("Nina Simone", "Q174957", "2944824d-4c26-476f-a981-be849081942f"),
    ("Ella Fitzgerald", "Q1768", "54799c0e-eb45-4eea-996d-c4d71a63c499"),
    ("Thelonious Monk", "Q109612", "8e8c7417-c905-46b1-b42a-5260b4274ed4"),
    ("Duke Ellington", "Q4030", "3af06bc4-68ad-4cae-bb7a-7eeeb45e411f"),
    ("Björk", "Q42455", "87c5dedd-371d-4a53-9f7f-80522fb7f3cb"),
    ("Fela Kuti", "Q313868", "6514cffa-fbe0-4965-ad88-e998ead8a82a"),
    ("Ali Farka Touré", "Q334947", "9be2a5ac-8201-489b-b5f6-91f958bf9060"),
    ("Celia Cruz", "Q474045", "7b8e1188-9ca4-4aa5-8393-172de6fa04de"),
    ("Caetano Veloso", "Q309983", "f07dbc2f-317b-470f-bad4-5f1b0eb6faf1"),
    ("Sufjan Stevens", "Q319502", "01d3c51b-9b98-418a-8d8e-37f6fab59d8c"),
    ("Joni Mitchell", "Q205721", "a6de8ef9-b1a1-4756-97aa-481bbb8a4069"),
    ("Joan Baez", "Q131725", "92d37892-6186-4459-9cc1-f0dde57652d0"),
    ("Muddy Waters", "Q220707", "f86f1f07-d182-45ce-ae93-ef610880ca72"),
    ("Son House", "Q352999", "8c87dda0-be58-4e48-a3b5-2626f26364c7"),
    ("Johnny Cash", "Q42775", "d43d12a1-2dc9-4257-a2fd-0a3bb1081b86"),
    ("Wu-Tang Clan", "Q52463", "0febdcf7-4e1f-4661-9493-b40427de2c13"),
    ("A Tribe Called Quest", "Q300602", "9689aa5a-4471-4fb4-9721-07cecda0fa9f"),
    ("Public Enemy", "Q209182", "bf2e15d0-4b77-469e-bfb4-f8414415baca"),
    ("OutKast", "Q472595", "73fdb566-a9b1-494c-9f32-51768ec9fd27"),
    ("Nas", "Q194220", "cfbc0924-0035-4d6c-8197-f024653af823"),
    ("Kraftwerk", "Q44892", "5700dcd4-c139-4f31-aa3e-6382b9af9032"),
    ("Black Sabbath", "Q47670", "5182c1d9-c7d2-4dad-afa0-ccfeada921a8"),
    ("Metallica", "Q15920", "65f4f0c5-ef9e-490c-aee3-909e7ae6b2ab"),
    ("Celtic Frost", "Q324645", "d91b3683-4622-4d72-8a03-80f1ff59e639"),
    ("Sepultura", "Q239074", "1d93c839-22e7-4f76-ad84-d27039efc048"),
    ("Mastodon", "Q548844", "bc5e2ad6-0a4a-4d90-b911-e9a7e6861727"),
    ("Iron Maiden", "Q42482", "ca891d65-d9b0-4258-89f7-e6ba29d83767"),
    ("Johann Sebastian Bach", "Q1339", "24f1766e-9635-4d58-a4d4-9413f9f98a4c"),
    ("Ludwig van Beethoven", "Q255", "1f9df192-a621-4f54-8850-2c5373b7eac9"),
    ("Nina Hagen", "Q159099", "e4d32f51-bc57-42a4-8165-b80f7a86496d"),
    ("Astor Piazzolla", "Q172505", "e280268a-a5ab-4bb0-be4d-ec470ca59131"),
    ("Ravi Shankar", "Q103774", "697f8b9f-0454-40f2-bba2-58f35668cdbe"),
    ("Anoushka Shankar", "Q259379", "40ee8fa3-c6d7-4556-b4e2-9f4114565043"),
    ("Tinariwen", "Q262317", "5c98fc12-be83-4246-ae5b-2184192913b9"),
    ("King Sunny Adé", "Q982678", "3e110caa-e9e8-4c33-98dc-ebbf0c6d2494"),
    ("Miriam Makeba", "Q146256", "bc5c2918-4aba-4ef6-a245-100563a4487f"),
    ("Lata Mangeshkar", "Q156347", "aeb71bd8-447d-4415-8ea1-2b7d664f67e1"),
    ("Manu Chao", "Q207898", "7570a0dd-5a67-401b-b19a-261eee01a284"),
]
BASELINE: list[tuple[str, str, str]] = [
    ("Aphex Twin", "f22942a1-6f70-4f48-866e-238cb2308fbd", "Q223161"),
    ("Four Tet", "3bcff06f-675a-451f-9075-99e8657047e8", "Q959655"),
]
DOCS = {
    "query_service": "https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service",
    "license": "https://www.wikidata.org/wiki/Wikidata:Licensing",
    "identity_property": "https://www.wikidata.org/wiki/Property:P434",
    "properties": {
        "P136": "https://www.wikidata.org/wiki/Property:P136",
        "P495": "https://www.wikidata.org/wiki/Property:P495",
        "P740": "https://www.wikidata.org/wiki/Property:P740",
        "P135": "https://www.wikidata.org/wiki/Property:P135",
    },
}
MAX_RESPONSE_BYTES = 2_000_000
MAX_ARTISTS_PER_BATCH = 50
HTTP_OK = 200


def sha256_file(path: Path) -> str:
    """Hash a source artifact in bounded reads."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_pack_path(directory: Path, relative_path: str) -> Path:
    """Resolve a pack path while rejecting absolute paths, traversal, and symlinks."""
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or "\\" in relative_path
    ):
        raise ValueError("pack paths must be safe relative paths")
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


def _verify_pack_file_hashes(directory: Path) -> None:
    """Verify the CC0 receipt and exact file set before replay."""
    receipt = json.loads(_safe_pack_path(directory, "receipt.json").read_text())
    if receipt["source"] != ENDPOINT or receipt["license"] != "CC0":
        raise ValueError("receipt source or license does not match Wikidata CC0")
    expected = receipt["sha256"]
    actual_paths: set[str] = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("pack paths must not traverse symlinks")
        if path.is_file() and path.name != "receipt.json":
            actual_paths.add(str(path.relative_to(directory)))
    if actual_paths != set(expected):
        raise ValueError("pack file set differs from receipt")
    for relative_path, expected_hash in expected.items():
        path = _safe_pack_path(directory, relative_path)
        if sha256_file(path) != expected_hash:
            raise ValueError(f"pack artifact hash mismatch: {relative_path}")


def _batch_ids(batch: dict[str, object]) -> tuple[str, ...]:
    """Validate and return the exact requested artist IDs for one batch."""
    batch_ids_raw = batch["requested_mbids"]
    if not isinstance(batch_ids_raw, list):
        raise TypeError("batch requested IDs must be strings")
    typed_ids = [value for value in batch_ids_raw if isinstance(value, str)]
    if len(typed_ids) != len(batch_ids_raw):
        raise ValueError("batch requested IDs must be strings")
    batch_ids = tuple(typed_ids)
    if (
        not batch_ids
        or len(batch_ids) > MAX_ARTISTS_PER_BATCH
        or len(set(batch_ids)) != len(batch_ids)
    ):
        raise ValueError("batch must contain 1 to 50 unique artist IDs")
    return batch_ids


def _read_batch_response(
    directory: Path, batch: dict[str, object], batch_ids: tuple[str, ...]
) -> tuple[bytes, dict[str, object]]:
    """Verify exact request and response custody, returning its JSON payload."""
    query = build_query(batch_ids)
    if hashlib.sha256(query.encode()).hexdigest() != batch["query_sha256"]:
        raise ValueError("claim query hash mismatch")
    if batch["http_status"] != HTTP_OK:
        raise ValueError("claim query did not return HTTP 200")
    raw_path = batch["raw_path"]
    if not isinstance(raw_path, str):
        raise TypeError("batch raw path must be a string")
    body = _safe_pack_path(directory, raw_path).read_bytes()
    if len(body) > MAX_RESPONSE_BYTES or len(body) != batch["response_bytes"]:
        raise ValueError("claim response byte count is invalid")
    if hashlib.sha256(body).hexdigest() != batch["response_sha256"]:
        raise ValueError("claim response hash mismatch")
    payload = json.loads(body)
    bindings = payload["results"]["bindings"]
    if len(bindings) != batch["returned_binding_count"]:
        raise ValueError("claim response binding count is invalid")
    return body, cast("dict[str, object]", payload)


def _replay_batch(
    directory: Path, batch: dict[str, object]
) -> tuple[tuple[str, ...], tuple[CulturalArtistEvidence, ...], int]:
    """Verify one exact-ID response and rebuild its raw Wikidata rows."""
    batch_ids = _batch_ids(batch)
    body, payload = _read_batch_response(directory, batch, batch_ids)
    evidence = parse_bindings(payload, set(batch_ids))
    if len(evidence) != batch["matched_artist_count"]:
        raise ValueError("raw MBID match count is invalid")
    unmatched = sorted(set(batch_ids) - {item.musicbrainz_artist_id for item in evidence})
    if batch["unmatched_artist_mbids"] != unmatched:
        raise ValueError("raw unmatched-ID accounting is invalid")
    return batch_ids, evidence, len(body)


def dump(path: Path, value: object) -> None:
    """Write one stable, human-readable JSON artifact."""
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf8",
    )


def _build_discovery_query(names: list[str]) -> str:
    """Query exact English labels and P434 values for a fixed candidate roster."""
    values = " ".join(json.dumps(name, ensure_ascii=False) + "@en" for name in names)
    return (
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT ?label ?mbid ?artist WHERE { "
        f"VALUES ?label {{ {values} }} "
        "?artist rdfs:label ?label; wdt:P434 ?mbid. }"
    )


def _pinned_qids(cohort: list[dict[str, object]], requested_ids: set[str]) -> dict[str, str]:
    """Require exactly one explicit Wikidata identity QID for every requested MBID."""
    qids: dict[str, str] = {}
    for artist in cohort:
        artist_id = artist.get("artist_mbid")
        qid = artist.get("qid")
        if not isinstance(artist_id, str) or not isinstance(qid, str):
            raise TypeError("every cohort artist requires an exact MBID and pinned QID")
        if not qid.startswith("Q") or not qid[1:].isdigit():
            raise ValueError("cohort Wikidata QIDs must be canonical item identifiers")
        if artist_id in qids:
            raise ValueError("cohort contains duplicate exact artist identities")
        qids[artist_id] = qid
    if set(qids) != requested_ids:
        raise ValueError("pinned Wikidata QIDs must exactly cover all requested artist IDs")
    return qids


def acquire(out: Path) -> None:
    """Capture a bounded curated exact-ID Wikidata CC0 pack."""
    out.mkdir(parents=True, exist_ok=False)
    (out / "raw").mkdir()
    # Preserve the exact English-label to P434 discovery response for roster provenance.
    discovery_names = [x[0] for x in ROSTER] + ["Youssou N'Dour", "Kendrick Lamar", "Missy Elliott"]
    discovery_query = _build_discovery_query(discovery_names)
    with httpx.Client(
        timeout=30,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded CC0 music metadata research)",
            "Accept": "application/sparql-results+json",
        },
    ) as client:
        dr = client.get(ENDPOINT, params={"query": discovery_query})
        dr.raise_for_status()
        discovery_body = dr.content
    discovery_payload = json.loads(discovery_body)
    observed = {
        (b["label"]["value"], b["artist"]["value"].rsplit("/", 1)[-1], b["mbid"]["value"])
        for b in discovery_payload["results"]["bindings"]
    }
    if any((name, qid, mbid) not in observed for name, qid, mbid in ROSTER):
        raise ValueError("curated identity missing from retained discovery response")
    for miss in ["Youssou N'Dour", "Kendrick Lamar", "Missy Elliott"]:
        if any(b["label"]["value"] == miss for b in discovery_payload["results"]["bindings"]):
            raise ValueError(
                "omitted artist has an exact discovery match; review before acquisition"
            )
    discovery_raw = out / "raw" / "roster-discovery.json"
    discovery_raw.write_bytes(discovery_body)
    ids = [x[2] for x in ROSTER] + [x[1] for x in BASELINE]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate exact MBID in curated cohort")
    batch = tuple(ids)
    with httpx.Client(
        timeout=30,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded CC0 music metadata research)",
            "Accept": "application/sparql-results+json",
        },
    ) as client:
        query, body, status = capture_raw_response(batch, client=client)
    payload = json.loads(body)
    all_rows = parse_bindings(payload, set(batch))
    expected_qids = {x[2]: x[1] for x in ROSTER}
    expected_qids.update({x[1]: x[2] for x in BASELINE})
    evidence = tuple(
        e for e in all_rows if expected_qids[e.musicbrainz_artist_id] == e.wikidata_artist_id
    )
    if len({e.musicbrainz_artist_id for e in evidence}) != len(evidence):
        raise ValueError("multiple curated QIDs resolved to one exact MBID")
    raw = out / "raw" / "batch-00.json"
    raw.write_bytes(body)
    cohort = [
        {
            "artist_mbid": mbid,
            "name": name,
            "role": "curated_cross_scene",
            "qid": qid,
        }
        for name, qid, mbid in ROSTER
    ]
    cohort += [
        {"artist_mbid": mbid, "name": name, "role": "baseline", "qid": qid}
        for name, mbid, qid in BASELINE
    ]
    manifest = {
        "revision": "independent-cultural-context-wikidata-20261002-v1",
        "acquired_utc": datetime.now(UTC).isoformat(),
        "endpoint": ENDPOINT,
        "license": "CC0",
        "docs": DOCS,
        "properties": ["P135", "P136", "P495", "P740"],
        "identity_rule": (
            "construction joins only by exact MusicBrainz UUID through Wikidata P434; "
            "display names are retained for provenance only"
        ),
        "discovery": {
            "query_sha256": hashlib.sha256(discovery_query.encode()).hexdigest(),
            "response_sha256": hashlib.sha256(discovery_body).hexdigest(),
            "response_bytes": len(discovery_body),
            "http_status": dr.status_code,
            "returned_binding_count": len(discovery_payload["results"]["bindings"]),
            "raw_path": "raw/roster-discovery.json",
            "identity_rule": (
                "exact English label plus exact P434 UUID and manually curated QID; "
                "direct claim acquisition is subsequently exact-MBID based"
            ),
        },
        "selection": {
            "method": (
                "curated cross-scene/country roster fixed before query; no EveryNoise "
                "observations or MusicBrainz genre associations used"
            ),
            "extra_artist_count": len(ROSTER),
            "coverage_note": (
                "The roster was editorially curated for a mix of countries, regions, "
                "historical traditions and ensemble types; this note is not an evidence "
                "label or a model feature."
            ),
            "request_count_including_crosswalk": 2,
            "omitted_discovery_candidates": ["Youssou N'Dour", "Kendrick Lamar", "Missy Elliott"],
            "omission_reason": (
                "No exact English rdfs:label plus P434 crosswalk result in the "
                "retained discovery response."
            ),
        },
        "cohort": cohort,
        "requested_artist_count": len(ids),
        "batch_count": 1,
        "request_count": 2,
        "response_bytes_total": len(body),
        "discovery_response_bytes": len(discovery_body),
        "total_acquired_response_bytes": len(body) + len(discovery_body),
        "matched_artist_count": len(evidence),
        "raw_qid_conflict_row_count": len(all_rows) - len(evidence),
        "unmatched_artist_count": len(ids) - len(evidence),
        "unmatched_artist_mbids": sorted(set(ids) - {e.musicbrainz_artist_id for e in evidence}),
        "direct_claim_count": sum(len(e.claims) for e in evidence),
        "batches": [
            {
                "index": 0,
                "requested_mbids": list(batch),
                "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "response_bytes": len(body),
                "http_status": status,
                "returned_binding_count": len(payload["results"]["bindings"]),
                "matched_artist_count": len(all_rows),
                "unmatched_artist_mbids": sorted(
                    set(ids) - {e.musicbrainz_artist_id for e in all_rows}
                ),
                "raw_qid_conflict_rows": len(all_rows) - len(evidence),
                "raw_path": "raw/batch-00.json",
            }
        ],
    }
    dump(out / "manifest.json", manifest)
    dump(out / "artist-evidence.json", [e.model_dump(mode="json") for e in evidence])
    receipt = {
        "revision": manifest["revision"],
        "source": ENDPOINT,
        "license": "CC0",
        "license_scope": (
            "Wikidata exact P434 identity crosswalk and direct P136/P495/P740/P135 claims only"
        ),
        "sha256": {
            str(p.relative_to(out)): sha256_file(p)
            for p in [out / "manifest.json", out / "artist-evidence.json", raw, discovery_raw]
        },
    }
    dump(out / "receipt.json", receipt)
    sys.stdout.write(
        f"acquired {len(ids)} exact-ID requests; {len(evidence)} matched; "
        f"{manifest['direct_claim_count']} direct claims; {len(body)} response bytes\n"
    )


def _verify_discovery(path: Path) -> None:
    """Replay the curated roster against the exact-label P434 capture."""
    manifest = json.loads((path / "manifest.json").read_text())
    discovery = manifest["discovery"]
    curated = [artist for artist in manifest["cohort"] if artist["role"] == "curated_cross_scene"]
    omitted = manifest["selection"]["omitted_discovery_candidates"]
    names = [artist["name"] for artist in curated] + omitted
    query = _build_discovery_query(names)
    raw = _safe_pack_path(path, discovery["raw_path"]).read_bytes()
    if hashlib.sha256(query.encode()).hexdigest() != discovery["query_sha256"]:
        raise ValueError("discovery query hash mismatch")
    if hashlib.sha256(raw).hexdigest() != discovery["response_sha256"]:
        raise ValueError("discovery response hash mismatch")
    if len(raw) != discovery["response_bytes"]:
        raise ValueError("discovery response byte count mismatch")
    rows = json.loads(raw)["results"]["bindings"]
    observed = {
        (row["label"]["value"], row["artist"]["value"].rsplit("/", 1)[-1], row["mbid"]["value"])
        for row in rows
    }
    if any(
        (artist["name"], artist["qid"], artist["artist_mbid"]) not in observed for artist in curated
    ):
        raise ValueError("curated roster does not replay from exact P434 discovery")
    if any(row["label"]["value"] in omitted for row in rows):
        raise ValueError("an omitted artist has a discovery match")


def replay(path: Path) -> None:
    """Verify pack hashes and replay both P434 discovery and exact-ID claims."""
    _verify_pack_file_hashes(path)
    _verify_discovery(path)
    manifest = json.loads((path / "manifest.json").read_text())
    batch = manifest["batches"][0]
    requested_ids, raw_evidence, response_size = _replay_batch(path, batch)
    qids = _pinned_qids(manifest["cohort"], set(requested_ids))
    evidence = tuple(
        item for item in raw_evidence if qids[item.musicbrainz_artist_id] == item.wikidata_artist_id
    )
    if len({item.musicbrainz_artist_id for item in evidence}) != len(evidence):
        raise ValueError("projection has multiple Wikidata QIDs for one exact MBID")
    projection = json.loads((path / "artist-evidence.json").read_text())
    if [item.model_dump(mode="json") for item in evidence] != projection:
        raise ValueError("projection does not replay")
    if (
        len(requested_ids) != manifest["requested_artist_count"]
        or len(evidence) != manifest["matched_artist_count"]
        or response_size != manifest["response_bytes_total"]
    ):
        raise ValueError("manifest accounting mismatch")
    conflict_count = len(raw_evidence) - len(evidence)
    if manifest.get("raw_qid_conflict_row_count") != conflict_count:
        raise ValueError("raw identity conflict accounting mismatch")
    if batch.get("raw_qid_conflict_rows") != conflict_count:
        raise ValueError("batch identity conflict accounting mismatch")
    unmatched = sorted(set(requested_ids) - {item.musicbrainz_artist_id for item in evidence})
    if manifest.get("unmatched_artist_mbids") != unmatched:
        raise ValueError("unmatched artist IDs are not completely accounted for")
    sys.stdout.write(
        f"verified raw replay: {len(requested_ids)} requested, {len(evidence)} exact matches, "
        f"{sum(len(item.claims) for item in evidence)} claims\n"
    )


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--acquire", type=Path)
    a.add_argument("--verify", type=Path)
    n = a.parse_args()
    if n.acquire:
        acquire(n.acquire)
    elif n.verify:
        replay(n.verify)
