"""Reconstruct all retained open identities with separately licensed direct evidence.

This profile uses every row of the pinned core projection. Identity presence is
not musical coverage. No historical reference, names-as-genres, or private data
enters construction. Static indexes enumerate all identities without a server.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any
from uuid import UUID

import ijson
import zstandard

from opennoise.common import canonical_json, sha256_file
from opennoise.ingest.acousticbrainz.native_sonic import verify_native_sonic
from opennoise.ingest.wikidata.entity_evidence import verify as verify_entity_evidence
from opennoise.ingest.wikidata.global_artist_genres import verify_global_artist_genres
from opennoise.pipeline.full_input_assembly import (
    TOP_ASSETS,
    addon_directories,
    construction_manifest,
    copy_native_facts,
    export_addons,
    public_genres,
    research_profile,
    supplemental_contexts,
    validate_addons,
)
from opennoise.pipeline.full_input_context import (
    FullInputSources,
    add_fma_context,
    add_recording_destinations,
    export_fma_context,
    verify_genre_context,
)
from opennoise.pipeline.full_input_indexes import (
    export_compact_search,
    normalize_name,
    validate_compact_search,
)
from opennoise.pipeline.portable_foundation import project_portable_foundation

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

REVISION = "open-foundation-full-input-v3"
CORE_SHA = "fd8d5d9cc36f1b90a200bf79c6316b5d2410045b31d2559a0d19c3f2ac2b8bbd"
CORE_COUNT = 2_999_670
PAGE_SIZE = 500
CORE_RELATIVE = ".cache/musicbrainz-core-artist-identities-20261002-v1"
GLOBAL_RELATIVE = ".cache/wikidata-global-musical-artists-20261002-v1"


def _read(path: Path) -> Any:  # noqa: ANN401 - external source adapters validate JSON.
    return json.loads(path.read_bytes())


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = canonical_json(value)
    if path.exists():
        if path.read_bytes() == body:
            return
        raise ValueError("refusing to overwrite existing or hardlinked output")
    with path.open("xb") as stream:
        stream.write(body)


def _digest(path: Path) -> str:
    return sha256_file(path)[0]


def _core_rows(directory: Path) -> Iterator[tuple[str, str]]:
    receipt = _read(directory / "receipt.json")
    source = directory / "artist-identities.jsonl.zst"
    if source.is_symlink() or directory.is_symlink():
        raise ValueError("full-input source cannot be symlinked")
    if (
        receipt["output_sha256"] != CORE_SHA
        or _digest(source) != CORE_SHA
        or receipt["license"] != "CC0-1.0"
        or receipt["artist_count"] != CORE_COUNT
        or receipt["fields"] != ["artist_mbid", "name"]
        or receipt["verified_complete"] is not True
    ):
        raise ValueError("full-input core source differs from pinned identity-only snapshot")
    count = 0
    with (
        source.open("rb") as compressed,
        zstandard.ZstdDecompressor().stream_reader(compressed) as reader,
    ):
        for line in io.TextIOWrapper(reader, encoding="utf-8"):
            row = json.loads(line)
            identity, name = row["artist_mbid"], row["name"]
            if (
                not isinstance(identity, str)
                or str(UUID(identity)) != identity
                or not isinstance(name, str)
                or not name
            ):
                raise ValueError("invalid exact core artist identity or native name")
            if set(row) != {"artist_mbid", "name"}:
                raise ValueError("core source contains fields beyond identities")
            count += 1
            yield identity, name
    if count != CORE_COUNT:
        raise ValueError("core stream denominator differs from pinned complete member")


def _empty_artist(identity: str, name: str) -> dict[str, Any]:
    return {
        "artist_mbid": identity,
        "name": name,
        "claims": [],
        "direct_genres": [],
        "recordings": [],
        "links": [],
        "native_sonic": [],
        "inferred_memberships": [],
        "semantic_position": None,
    }


def _entity_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Stream already byte-verified native projections instead of duplicating 48MB JSON."""
    with path.open("rb") as stream:
        yield from ijson.items(stream, "artists.item", use_float=True)


def _add_entities(
    root: Path, artists: dict[str, dict[str, Any]], pack: Path, *, compact_native: bool = False
) -> None:
    """Admit literal statements only after exact native identifier replay."""
    verify_entity_evidence(pack, root / CORE_RELATIVE)
    projection_path = pack / "projection.json"
    with projection_path.open("rb") as stream:
        license_name = next(ijson.items(stream, "license", use_float=True))
    if license_name != "CC0-1.0":
        raise ValueError("entity pack is outside the CC0 source profile")
    with projection_path.open("rb") as stream:
        context_entities = dict(ijson.kvitems(stream, "context_entities", use_float=True))
    receipt_sha = _digest(pack / "receipt.json")
    for row in _entity_rows(projection_path):
        if row["status"] != "exact_identity":
            continue
        artist = artists.setdefault(
            row["artist_mbid"], _empty_artist(row["artist_mbid"], row["name"])
        )
        evidence = {**row, "source_receipt_sha256": receipt_sha}
        if compact_native:
            artist["_native_entity_evidence_sha256"] = hashlib.sha256(
                canonical_json(evidence)
            ).hexdigest()
        else:
            artist["native_entity_evidence"] = evidence
        artist["wikidata_ids"] = sorted(set(artist.get("wikidata_ids", [])) | {row["wikidata_qid"]})
        for claim in row["claims"].get("P136", []):
            value = claim["datavalue"].get("value")
            if not isinstance(value, dict) or "id" not in value:
                continue
            qid = value["id"]
            labels = context_entities.get(qid, {}).get("labels", {})
            artist["claims"].append(
                {
                    "property_id": "P136",
                    "value_qid": qid,
                    "value_label": labels.get("en", {}).get("value", qid),
                    "native_statement": claim,
                    "capture_pack": "wikidata-entity-evidence-v1",
                    "source_receipt_sha256": receipt_sha,
                    "license": "CC0-1.0",
                    "verification": "native_entity_replay_exact_p434",
                    "scope": "direct_artist_property",
                    "source": "https://www.wikidata.org/w/api.php",
                    "wikidata_artist_qid": row["wikidata_qid"],
                }
            )


def _evidence(  # noqa: C901, PLR0912 - distinct native source scopes remain visible.
    root: Path,
    inputs: FullInputSources,
    *,
    compact_native: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    portable = project_portable_foundation(root)
    artists = {a["artist_mbid"]: dict(a) for a in portable["artists"]}
    global_directory = root / GLOBAL_RELATIVE
    verify_global_artist_genres(global_directory, root / CORE_RELATIVE)
    global_receipt_sha = _digest(global_directory / "receipt.json")
    for row in _read(global_directory / "projection.json")["artists"]:
        if row["identity_status"] != "resolved_exact_p434_core_name":
            continue
        artist = artists.setdefault(
            row["artist_mbid"], _empty_artist(row["artist_mbid"], row["core_name"])
        )
        artist["wikidata_ids"] = sorted(
            set(artist.get("wikidata_ids", [])) | {row["wikidata_artist_qid"]}
        )
        for claim in row["claims"]:
            artist["claims"].append(
                {
                    **claim,
                    "capture_pack": GLOBAL_RELATIVE,
                    "source_receipt_sha256": global_receipt_sha,
                    "verification": "native_query_body_replay_exact_p434",
                    "transport_ledger_limit": "recovered retry status/date unknown",
                    "scope": "direct_artist_property",
                }
            )
    sonic = verify_native_sonic(root / "data/examples/native-sonic")
    for row in sonic["records"]:
        if not row["artist_join_allowed"]:
            continue
        fact = row["exact_credit"]["fact"]
        for identity in fact["credited_artist_mbids"]:
            artist = artists.setdefault(identity, _empty_artist(identity, ""))
            artist.setdefault("native_sonic", []).append(row)
            if not any(r["recording_mbid"] == fact["recording_mbid"] for r in artist["recordings"]):
                artist["recordings"].append(
                    {**fact, "license": "CC0-1.0", "verification": "native_exact_credit_replay"}
                )
    fma_artists: dict[str, dict[str, Any]] = {}
    add_fma_context(fma_artists, inputs)
    if inputs.entity_pack is not None:
        _add_entities(root, artists, inputs.entity_pack, compact_native=compact_native)
    if inputs.listening_pack is not None:
        add_recording_destinations(root, artists, inputs.listening_pack)
    for identity, fma_artist in fma_artists.items():
        existing = artists.setdefault(identity, fma_artist)
        if existing is not fma_artist:
            existing.setdefault("fma_track_context", []).extend(fma_artist["fma_track_context"])
    genres: dict[str, dict[str, Any]] = {}
    for identity, artist in artists.items():
        artist.setdefault("native_sonic", [])
        artist["inferred_memberships"] = []
        artist["semantic_position"] = None
        artist["direct_genres"] = sorted(
            {c["value_qid"] for c in artist["claims"] if c["property_id"] == "P136"}
        )
        artist["missingness"] = {
            "wikidata_identity": "observed_exact_source_identifier"
            if artist.get("wikidata_ids")
            else "no_observed_identity_claim",
            "direct_genres": "observed" if artist["direct_genres"] else "no_observed_direct_genre",
            "recordings": "bounded_exact_credit_examples"
            if artist["recordings"]
            else "no_observed_recording_example",
            "destinations": "source_recording_destination_assertions_availability_unchecked"
            if any(r.get("destinations") for r in artist["recordings"])
            else "no_observed_recording_destination",
            "sonic": "native_recording_numeric_examples"
            if artist["native_sonic"]
            else "no_observed_native_sonic_example",
            "semantic_position": "unavailable",
            "inferred_memberships": "not_constructed",
        }
        for claim in artist["claims"]:
            if claim["property_id"] != "P136":
                continue
            genre = genres.setdefault(
                claim["value_qid"],
                {
                    "genre_id": claim["value_qid"],
                    "name": claim["value_label"] or claim["value_qid"],
                    "artist_mbids": set(),
                },
            )
            genre["artist_mbids"].add(identity)
    return artists, [
        {**g, "artist_mbids": sorted(g["artist_mbids"])} for _, g in sorted(genres.items())
    ]


def create_identity_database(path: Path, rows: Iterable[tuple[str, str]]) -> int:
    """Stream identities to a fresh SQLite file; duplicate IDs fail, names may repeat."""
    if path.exists():
        raise ValueError("identity database output must be fresh")
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE artist(artist_mbid TEXT PRIMARY KEY,name TEXT NOT NULL,
                search_name TEXT NOT NULL,bucket TEXT NOT NULL) WITHOUT ROWID;
        """)
        count = 0
        with connection:
            for identity, name in rows:
                normalized = normalize_name(name)
                connection.execute(
                    "INSERT INTO artist VALUES(?,?,?,?)",
                    (identity, name, normalized, normalized[:2].encode().hex() or "empty"),
                )
                count += 1
            connection.execute("CREATE INDEX artist_search ON artist(search_name,artist_mbid)")
            connection.execute(
                "CREATE INDEX artist_bucket ON artist(bucket,search_name,artist_mbid)"
            )
    return count


def _pages(output: Path, stem: str, cursor: sqlite3.Cursor) -> list[str]:
    paths = []
    while rows := cursor.fetchmany(PAGE_SIZE):
        relative = f"{stem}/{len(paths):06d}.json"
        _write(output / relative, rows)
        paths.append(relative)
    return paths


def export_identity_indexes(
    database: Path, output: Path, *, compact: bool = False
) -> dict[str, Any]:
    """Export complete deterministic browse, exact-ID and bounded name-prefix indexes."""
    with closing(sqlite3.connect(database)) as connection:
        count = connection.execute("SELECT COUNT(*) FROM artist").fetchone()[0]
        browse = _pages(
            output,
            "browse",
            connection.execute(
                "SELECT artist_mbid,name FROM artist ORDER BY search_name,artist_mbid"
            ),
        )
        _write(
            output / "browse/index.json", {"count": count, "page_size": PAGE_SIZE, "pages": browse}
        )
        for number in range(256):
            prefix = f"{number:02x}"
            rows = connection.execute(
                "SELECT artist_mbid,name FROM artist WHERE artist_mbid>=? AND artist_mbid<? "
                "ORDER BY artist_mbid",
                (prefix, prefix + "z"),
            ).fetchall()
            _write(output / f"artists/identity-{prefix}.json", rows)
        if compact:
            bucket_count = export_compact_search(output)
            return {
                "artists": count,
                "browse_pages": len(browse),
                "search_pages": bucket_count,
                "search_buckets": 0,
            }
        buckets = []
        for key, prefix, size in connection.execute(
            "SELECT bucket,substr(search_name,1,2),COUNT(*) FROM artist "
            "GROUP BY bucket ORDER BY bucket"
        ):
            pages = _pages(
                output,
                f"search/{key}",
                connection.execute(
                    "SELECT search_name,artist_mbid,name FROM artist WHERE bucket=? "
                    "ORDER BY search_name,artist_mbid",
                    (key,),
                ),
            )
            metadata = []
            for page in pages:
                values = _read(output / page)
                metadata.append(
                    {
                        "path": page,
                        "first": values[0][0],
                        "last": values[-1][0],
                        "count": len(values),
                    }
                )
            buckets.append({"key": key, "prefix": prefix, "count": size, "pages": metadata})
        search = {"normalization": "NFKC casefold", "buckets": buckets, "count": count}
        _write(output / "search/index.json", search)
    return {"artists": count, "browse_pages": len(browse), "search_buckets": len(buckets)}


def _bind_evidence(database: Path, artists: dict[str, dict[str, Any]]) -> None:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        for identity, artist in artists.items():
            row = connection.execute(
                "SELECT name FROM artist WHERE artist_mbid=?", (identity,)
            ).fetchone()
            if row is None:
                raise ValueError("exact evidence artist absent from full core snapshot")
            if artist["name"] != row[0]:
                artist["source_cohort_name"] = artist["name"]
            artist["name"] = row[0]


def _profile_source_links(profile: dict[str, Any], inputs: FullInputSources) -> None:
    """Expose independently named source contexts with their own license scopes."""
    if inputs.fma_source is not None:
        profile["fma_catalog"] = {"path": "fma/", "license": "CC-BY-4.0"}
    if inputs.fma_listening_pack is not None:
        profile["permitted_listening"] = {
            "path": "fma-listening/",
            "license": "per-track declarations",
        }
    if inputs.genre_context_pack is not None:
        profile["genre_context"] = {
            "path": "genre-context.json",
            "scope": "literal P31 types and one-hop P279 source parents; no musical distances",
        }


def build_full_input_foundation(
    root: Path,
    output: Path,
    inputs: FullInputSources | None = None,
    identity_base: Path | None = None,
) -> dict[str, Any]:
    """Reconstruct a fresh all-input profile independently of sealed legacy paths."""
    if output.exists():
        raise ValueError("full-input output must be fresh; existing work is never overwritten")
    inputs = inputs or FullInputSources()
    artists, genres = _evidence(root, inputs)
    output.mkdir(parents=True)
    database = output / "full-input.sqlite"
    if identity_base is None:
        create_identity_database(database, _core_rows(root / CORE_RELATIVE))
        counts = export_identity_indexes(database, output, compact=True)
    else:
        validate_identity_base(root, identity_base)
        browse_index = _read(identity_base / "browse/index.json")
        paths = [
            "full-input.sqlite",
            "browse/index.json",
            *browse_index["pages"],
            *[f"artists/identity-{number:02x}.json" for number in range(256)],
        ]
        for relative in paths:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(identity_base / relative, target)
        counts = {
            "artists": browse_index["count"],
            "browse_pages": len(browse_index["pages"]),
            "search_buckets": 0,
        }
    _bind_evidence(database, artists)
    if identity_base is not None:
        counts["search_pages"] = export_compact_search(output)
        counts["search_buckets"] = 0
    counts.update(
        {
            "artists_with_details": len(artists),
            "artists_with_direct_genres": sum(bool(a["direct_genres"]) for a in artists.values()),
            "genres": len(genres),
            "native_sonic_recordings": len(
                {r["recording_mbid"] for a in artists.values() for r in a["native_sonic"]}
            ),
            "artists_without_observed_genres": counts["artists"]
            - sum(bool(a["direct_genres"]) for a in artists.values()),
        }
    )
    if inputs.fma_projection is not None and inputs.fma_bridge is not None:
        fma_corpus = _read(inputs.fma_projection / "corpus-receipt.json")
        fma_bridge = _read(inputs.fma_bridge / "bridge.json")
        counts.update(
            {
                "fma_native_artists": fma_corpus["files"]["artists"]["rows"],
                "fma_native_tracks": fma_corpus["files"]["tracks"]["rows"],
                "fma_native_genres": fma_corpus["files"]["genres"]["rows"],
                "fma_exact_artist_bridges": len(fma_bridge["artist"]["resolved"]),
            }
        )
    for identity, artist in sorted(artists.items()):
        _write(output / f"details/{identity}.json", artist)
    export_fma_context(inputs, output)
    genre_context = verify_genre_context(inputs, root / CORE_RELATIVE)
    if genre_context is not None:
        _write(output / "genre-context.json", genre_context)
    _write(output / "genres.json", genres)
    with closing(sqlite3.connect(database)) as connection:
        for genre in genres:
            _write(
                output / f"genres/{genre['genre_id']}.json",
                [
                    [
                        identity,
                        connection.execute(
                            "SELECT name FROM artist WHERE artist_mbid=?", (identity,)
                        ).fetchone()[0],
                    ]
                    for identity in genre["artist_mbids"]
                ],
            )
    assets = root / "src/opennoise/static"
    for name in (
        "full-foundation.html",
        "full-foundation.css",
        "full-foundation.mjs",
        "full-foundation-normalization.mjs",
        "listening-list.mjs",
    ):
        shutil.copyfile(assets / name, output / ("index.html" if name.endswith(".html") else name))
    profile = {
        "revision": REVISION,
        "counts": counts,
        "license": "CC0-1.0 core; CC-BY-4.0 FMA context" if inputs.fma_source else "CC0-1.0",
        "licenses": {
            "core": "CC0-1.0",
            "fma_metadata": "CC-BY-4.0" if inputs.fma_source else None,
            "audio": "per-track declarations only" if inputs.fma_listening_pack else None,
        },
        "search_format": "browse-page-bounds-v1",
        "normalization": "NFKC casefold",
        "scope": {
            "status": "full_retained_identity_input_reconstruction",
            "full_foundation_complete": False,
            "legacy_release_equivalence": False,
            "historical_inputs_used": False,
            "spotify_private_inputs_used": False,
            "inferred_memberships": "unavailable",
            "semantic_coordinates": "unavailable",
            "identity_coverage_is_not_musical_coverage": True,
            "recordings": "bounded exact-credit examples; not representative music certification",
        },
        "featured_artists": [
            {"artist_mbid": a["artist_mbid"], "name": a["name"]}
            for a in sorted(
                (a for a in artists.values() if a.get("cohort_sources")),
                key=lambda a: (normalize_name(a["name"]), a["artist_mbid"]),
            )
        ],
        "identity_shards": {
            "directory": "artists",
            "prefix_length": 2,
            "file_prefix": "identity-",
            "file_suffix": ".json",
        },
    }
    _profile_source_links(profile, inputs)
    _write(output / "profile.json", profile)
    return _seal_export(root, output, inputs, counts)


def assemble_full_input_foundation(  # noqa: PLR0913, PLR0917 - explicit immutable source/proof/reuse roles.
    root: Path,
    output: Path,
    inputs: FullInputSources,
    source_base: Path,
    source_proof: Path,
    research_base: Path | None = None,
) -> dict[str, Any]:
    """Extend a replayed native export immutably, then require fresh whole-export replay."""
    receipt = _read(source_base / "receipt.json")
    proof = _read(source_proof)
    if (
        proof.get("valid") is not True
        or proof.get("native_identity_rows_replayed") != CORE_COUNT
        or proof.get("receipt_sha256") != _digest(source_base / "receipt.json")
        or proof.get("counts") != receipt["counts"]
        or proof.get("full_foundation_complete") is not False
    ):
        raise ValueError("native base requires its exact successful independent source replay")
    _validate_file_bindings(root, source_base, receipt)
    supplied = inputs.bindings()
    native_roles = set(supplied) - set(addon_directories(inputs))
    bound = {**FullInputSources().bindings(), **receipt["additional_source_bindings"]}
    if any(bound[role] != supplied[role] for role in native_roles):
        raise ValueError("assembly cannot change replayed native input roles")
    contexts, summary = supplemental_contexts(source_base, inputs)
    copy_native_facts(source_base, output, receipt)
    for asset in TOP_ASSETS:
        destination = "index.html" if asset == "full-foundation.html" else asset
        shutil.copyfile(root / "src/opennoise/static" / asset, output / destination)
    _write(output / "genres.json", public_genres(_read(source_base / "genres.json")))
    profile = _read(source_base / "profile.json")
    profile["genre_index_format"] = "lazy-complete-cohorts-v1"
    profile["native_base"] = {
        "receipt_sha256": _digest(source_base / "receipt.json"),
        "replay_report_sha256": _digest(source_proof),
    }
    research_profile(profile, inputs, summary, contexts)
    _write(output / "profile.json", profile)
    export_addons(output, inputs, contexts, research_base)
    _write(output / "construction.json", construction_manifest(root, inputs))
    return _seal_export(root, output, inputs, profile["counts"])


def _seal_export(
    root: Path, output: Path, inputs: FullInputSources, counts: dict[str, Any]
) -> dict[str, Any]:
    """Write a missing byte inventory; source replay remains a separate mandatory step."""
    receipt = {
        "revision": REVISION,
        "counts": counts,
        "core_projection_sha256": CORE_SHA,
        "core_receipt_sha256": _digest(root / CORE_RELATIVE / "receipt.json"),
        "global_receipt_sha256": _digest(root / GLOBAL_RELATIVE / "receipt.json"),
        "native_sonic_receipt_sha256": _digest(root / "data/examples/native-sonic/receipt.json"),
        "additional_source_bindings": inputs.bindings(),
        "implementation_files": {
            str(p.relative_to(root)): _digest(p)
            for p in sorted((root / "src/opennoise/pipeline").glob("full_input*.py"))
        },
        "files": {
            p.relative_to(output).as_posix(): {"sha256": _digest(p), "size_bytes": p.stat().st_size}
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    _write(output / "receipt.json", receipt)
    return {
        "revision": REVISION,
        "output": str(output),
        "counts": counts,
        "receipt_sha256": _digest(output / "receipt.json"),
    }


def seal_full_input_foundation(
    root: Path, output: Path, inputs: FullInputSources
) -> dict[str, Any]:
    """Preserve a completed export after a final-bookkeeping failure, without file replacement."""
    if (output / "receipt.json").exists():
        raise ValueError("refusing to replace an existing full-input receipt")
    profile = _read(output / "profile.json")
    if profile["revision"] != REVISION:
        raise ValueError("unsealed export belongs to a different reconstruction profile")
    result = _seal_export(root, output, inputs, profile["counts"])
    return {**result, "independent_replay": "pending; run validate before acceptance"}


def _compare_pages(output: Path, paths: list[str], cursor: sqlite3.Cursor) -> None:
    for path in paths:
        expected = [list(row) for row in cursor.fetchmany(PAGE_SIZE)]
        if not expected or _read(output / path) != expected:
            raise ValueError(f"static ordered coverage differs: {path}")
    if cursor.fetchone() is not None:
        raise ValueError("static ordered coverage omitted source identities")


def validate_identity_indexes(  # noqa: C901 - complete indexes and explicit identity-only reuse.
    database: Path,
    output: Path,
    *,
    identity_only: bool = False,
) -> None:
    """Independently enumerate every source row for each complete static index."""
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        count = connection.execute("SELECT COUNT(*) FROM artist").fetchone()[0]
        browse = _read(output / "browse/index.json")
        if browse["count"] != count or browse["page_size"] != PAGE_SIZE:
            raise ValueError("browse denominator or page-size declaration differs")
        _compare_pages(
            output,
            browse["pages"],
            connection.execute(
                "SELECT artist_mbid,name FROM artist ORDER BY search_name,artist_mbid"
            ),
        )
        for number in range(256):
            prefix = f"{number:02x}"
            rows = [
                list(r)
                for r in connection.execute(
                    "SELECT artist_mbid,name FROM artist WHERE artist_mbid>=? AND artist_mbid<? "
                    "ORDER BY artist_mbid",
                    (prefix, prefix + "z"),
                )
            ]
            if _read(output / f"artists/identity-{prefix}.json") != rows:
                raise ValueError("exact-ID static shard differs from all-input database")
        if identity_only:
            return
        search = _read(output / "search/index.json")
        if search.get("format") == "browse-page-bounds-v1":
            validate_compact_search(output)
            return
        expected_buckets = connection.execute(
            "SELECT bucket,substr(search_name,1,2),COUNT(*) FROM artist "
            "GROUP BY bucket ORDER BY bucket"
        ).fetchall()
        actual_buckets = [(b["key"], b["prefix"], b["count"]) for b in search["buckets"]]
        if actual_buckets != expected_buckets or search["count"] != count:
            raise ValueError("search bucket universe or denominator differs")
        if search["normalization"] != "NFKC casefold":
            raise ValueError("search normalization declaration differs")
        for bucket in search["buckets"]:
            for page in bucket["pages"]:
                values = _read(output / page["path"])
                if not values or (page["first"], page["last"], page["count"]) != (
                    values[0][0],
                    values[-1][0],
                    len(values),
                ):
                    raise ValueError("search lexical page bounds or counts differ")
            _compare_pages(
                output,
                [page["path"] for page in bucket["pages"]],
                connection.execute(
                    "SELECT search_name,artist_mbid,name FROM artist WHERE bucket=? "
                    "ORDER BY search_name,artist_mbid",
                    (bucket["key"],),
                ),
            )


def _validate_profile(  # noqa: C901, PLR0912 - literal profile contracts and licensed source roles.
    output: Path,
    database: Path,
    artists: dict[str, dict[str, Any]],
    genres: list[dict[str, Any]],
    count: int,
    # Receipt is read directly to keep the verification boundary small.
) -> None:
    """Reject forged musical coverage, promotion, and genre-cohort claims."""
    receipt = _read(output / "receipt.json")
    profile = _read(output / "profile.json")
    if profile["revision"] != REVISION or profile["counts"] != receipt["counts"]:
        raise ValueError("full-input profile version or counts disagree with receipt")
    counts = profile["counts"]
    direct = sum(bool(a["direct_genres"]) for a in artists.values())
    sonic_count = len({r["recording_mbid"] for a in artists.values() for r in a["native_sonic"]})
    if (
        counts["artists"],
        counts["artists_with_details"],
        counts["artists_with_direct_genres"],
        counts["artists_without_observed_genres"],
        counts["genres"],
        counts["native_sonic_recordings"],
    ) != (count, len(artists), direct, count - direct, len(genres), sonic_count):
        raise ValueError("full-input musical missingness denominators differ from source replay")
    browse = _read(output / "browse/index.json")
    search = _read(output / "search/index.json")
    if counts["browse_pages"] != len(browse["pages"]):
        raise ValueError("profile browse page count differs from complete index")
    if search.get("format") == "browse-page-bounds-v1":
        if counts.get("search_pages") != len(search["pages"]) or counts["search_buckets"] != 0:
            raise ValueError("profile compact search counts differ from index")
        if profile.get("search_format") != search["format"]:
            raise ValueError("profile search format differs from static source index")
    bound = receipt["additional_source_bindings"]
    expected_license = "CC0-1.0 core; CC-BY-4.0 FMA context" if bound["fma_source"] else "CC0-1.0"
    if profile["license"] != expected_license:
        raise ValueError("profile license roles differ from verified source namespaces")
    expected_featured = [
        {"artist_mbid": a["artist_mbid"], "name": a["name"]}
        for a in sorted(
            (a for a in artists.values() if a.get("cohort_sources")),
            key=lambda a: (normalize_name(a["name"]), a["artist_mbid"]),
        )
    ]
    if profile["featured_artists"] != expected_featured:
        raise ValueError("featured cohort differs from source-selected exact identities")
    if profile["identity_shards"] != {
        "directory": "artists",
        "prefix_length": 2,
        "file_prefix": "identity-",
        "file_suffix": ".json",
    }:
        raise ValueError("profile exact identity shard routing differs")
    scope = profile["scope"]
    if scope["identity_coverage_is_not_musical_coverage"] is not True:
        raise ValueError("profile falsely equates identity and musical coverage")
    if any(
        scope[key] is not False
        for key in (
            "full_foundation_complete",
            "legacy_release_equivalence",
            "historical_inputs_used",
            "spotify_private_inputs_used",
        )
    ):
        raise ValueError("full-input profile makes unsupported provenance or completion claims")
    if (
        scope["inferred_memberships"] != "unavailable"
        or scope["semantic_coordinates"] != "unavailable"
    ):
        raise ValueError("full-input profile makes unsupported musical inference claims")
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        for genre in genres:
            expected_cohort = [
                [
                    identity,
                    connection.execute(
                        "SELECT name FROM artist WHERE artist_mbid=?", (identity,)
                    ).fetchone()[0],
                ]
                for identity in genre["artist_mbids"]
            ]
            if _read(output / f"genres/{genre['genre_id']}.json") != expected_cohort:
                raise ValueError("native direct genre cohort does not replay")


def _validate_file_bindings(root: Path, output: Path, receipt: dict[str, Any]) -> None:
    """Rehash the closed file set and bind source receipts to current replay inputs."""
    for relative, key in (
        (CORE_RELATIVE + "/receipt.json", "core_receipt_sha256"),
        (GLOBAL_RELATIVE + "/receipt.json", "global_receipt_sha256"),
        ("data/examples/native-sonic/receipt.json", "native_sonic_receipt_sha256"),
    ):
        if receipt[key] != _digest(root / relative):
            raise ValueError("full-input source receipt binding differs")
    if (
        receipt["revision"] not in {REVISION, "open-foundation-full-input-v1"}
        or receipt["core_projection_sha256"] != CORE_SHA
    ):
        raise ValueError("full-input source version or core pin differs")
    if any(p.is_symlink() for p in output.rglob("*")):
        raise ValueError("full-input export cannot contain symlinks")
    expected = set(receipt["files"])
    actual = {
        p.relative_to(output).as_posix()
        for p in output.rglob("*")
        if p.is_file() and p.relative_to(output).as_posix() != "receipt.json"
    }
    if expected != actual:
        raise ValueError("full-input export closed file set differs")
    for path, binding in receipt["files"].items():
        member = output / path
        if (
            member.is_symlink()
            or _digest(member) != binding["sha256"]
            or member.stat().st_size != binding["size_bytes"]
        ):
            raise ValueError(f"full-input output bytes differ: {path}")


def _validate_identity_database(root: Path, database: Path) -> int:
    """Compare every immutable database identity against the pinned complete source stream."""
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("full-input database integrity failed")
        count = 0
        for identity, name in _core_rows(root / CORE_RELATIVE):
            actual_row = connection.execute(
                "SELECT name,search_name,bucket FROM artist WHERE artist_mbid=?", (identity,)
            ).fetchone()
            normalized = normalize_name(name)
            if actual_row != (name, normalized, normalized[:2].encode().hex() or "empty"):
                raise ValueError("full-input database differs from exact native identity stream")
            count += 1
        if count != connection.execute("SELECT COUNT(*) FROM artist").fetchone()[0]:
            raise ValueError("full-input database identity denominator differs")
    return count


def validate_identity_base(root: Path, output: Path) -> None:
    """Replay only the copied source-bound identity substrate, never old musical data."""
    database = output / "full-input.sqlite"
    browse = _read(output / "browse/index.json")
    paths = [
        database,
        output / "browse/index.json",
        *[output / path for path in browse["pages"]],
        *[output / f"artists/identity-{number:02x}.json" for number in range(256)],
    ]
    if output.is_symlink() or any(path.is_symlink() for path in paths):
        raise ValueError("identity substrate cannot be symlinked")
    if browse["pages"] != [f"browse/{number:06d}.json" for number in range(len(browse["pages"]))]:
        raise ValueError("identity substrate browse paths must be canonical")
    _validate_identity_database(root, database)
    validate_identity_indexes(database, output, identity_only=True)


def _compare_artist_detail(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    """Compare all native entity fields one row at a time using their canonical source hash."""
    expected = dict(expected)
    evidence_digest = expected.pop("_native_entity_evidence_sha256", None)
    if evidence_digest is not None:
        actual = dict(actual)
        evidence = actual.pop("native_entity_evidence", None)
        if (
            evidence is None
            or hashlib.sha256(canonical_json(evidence)).hexdigest() != evidence_digest
        ):
            raise ValueError(
                "native entity fields differ from independently reconstructed source row"
            )
    if actual != expected:
        raise ValueError("full-input detail does not replay from exact source claims")


def validate_full_input_foundation(
    root: Path,
    output: Path,
    inputs: FullInputSources | None = None,
) -> dict[str, Any]:
    """Replay sources, then independently compare every database and exported identity."""
    receipt = _read(output / "receipt.json")
    _validate_file_bindings(root, output, receipt)
    inputs = inputs or FullInputSources()
    expected_bindings = inputs.bindings()
    if {
        **FullInputSources().bindings(),
        **receipt.get("additional_source_bindings", {}),
    } != expected_bindings:
        raise ValueError("additional replay input roles differ from export bindings")
    del receipt
    genre_context = verify_genre_context(inputs, root / CORE_RELATIVE)
    if genre_context is not None and _read(output / "genre-context.json") != genre_context:
        raise ValueError("typed genre source context differs from native replay")
    del genre_context
    artists, genres = _evidence(root, inputs, compact_native=True)
    database = output / "full-input.sqlite"
    _bind_evidence(database, artists)
    profile = _read(output / "profile.json")
    expected_genres = (
        public_genres(genres)
        if profile.get("genre_index_format") == "lazy-complete-cohorts-v1"
        else genres
    )
    if _read(output / "genres.json") != expected_genres:
        raise ValueError("full-input direct genre claims differ from native replay")
    for identity, artist in artists.items():
        _compare_artist_detail(_read(output / f"details/{identity}.json"), artist)
    count = _validate_identity_database(root, database)
    _validate_profile(output, database, artists, genres, count)
    validate_identity_indexes(database, output)
    del artists, genres
    validate_addons(output, inputs)
    return {
        "revision": REVISION,
        "valid": True,
        "native_identity_rows_replayed": count,
        "validator_files": {
            str(p.relative_to(root)): _digest(p)
            for p in sorted((root / "src/opennoise/pipeline").glob("full_input*.py"))
        },
        "counts": _read(output / "profile.json")["counts"],
        "receipt_sha256": _digest(output / "receipt.json"),
        "full_foundation_complete": False,
    }
