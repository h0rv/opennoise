"""Build an independently named, partial CC0 explorer from offline source packs.

This is a new source projection, never a reconstruction of the sealed release.
Native Wikidata claims and recording credits replay from retained responses;
the acoustic example has projection custody only and says so explicitly.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_file
from opennoise.ingest.open_cultural_source import ENDPOINT, build_query, parse_bindings
from opennoise.serving.metadata.artist_links import verify_artist_link_projection
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "open-foundation-portable-v1"
CULTURAL_PACKS = ("cultural-context", "independent-cultural-context")
ASSETS = (
    "portable-foundation.html",
    "portable-foundation.mjs",
    "portable-foundation.css",
    "listening-list.mjs",
)
HTTP_OK = 200
VERIFIER_FILES = (
    "src/opennoise/common/hashing.py",
    "src/opennoise/ingest/open_cultural_source.py",
    "src/opennoise/serving/metadata/recording_facts.py",
    "src/opennoise/serving/metadata/artist_links.py",
)
LEGACY_INPUTS = {
    "data/public.sqlite": "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc",
    ".cache/semantic-map-layout-v3/artifact.json": (
        "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
    ),
}


def _hash(path: Path) -> str:
    return sha256_file(path)[0]


def _path(root: Path, relative: str) -> Path:
    """Keep receipt paths relative and reject symlink traversal."""
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"unsafe portable input path: {relative}")
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"portable input traverses a symlink: {relative}")
    if not current.is_file():
        raise ValueError(f"missing portable input: {relative}")
    return current


def _read(path: Path) -> Any:  # noqa: ANN401 - strict source adapters validate external JSON.
    return json.loads(path.read_bytes())


def _verified_cultural(  # noqa: C901 - request and missingness invariants stay together.
    directory: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rehash every member and replay each exact-MBID query and source claim."""
    receipt = _read(_path(directory, "receipt.json"))
    if receipt["source"] != ENDPOINT or receipt["license"] != "CC0":
        raise ValueError("cultural pack is not the declared CC0 Wikidata source")
    expected = receipt["sha256"]
    actual = {
        str(p.relative_to(directory))
        for p in directory.rglob("*")
        if p.is_file() and p.name != "receipt.json"
    }
    if actual != set(expected):
        raise ValueError("cultural pack member set differs from receipt")
    for relative, digest in expected.items():
        if _hash(_path(directory, relative)) != digest:
            raise ValueError(f"cultural source hash differs: {relative}")
    manifest = _read(_path(directory, "manifest.json"))
    if manifest["endpoint"] != ENDPOINT or manifest["license"] != "CC0":
        raise ValueError("cultural manifest source or license differs")
    cohort = manifest["cohort"]
    ids = [item["artist_mbid"] for item in cohort]
    if len(ids) != len(set(ids)) or len(ids) != manifest["requested_artist_count"]:
        raise ValueError("cultural cohort identity accounting differs")
    requested: set[str] = set()
    replayed = []
    for batch in manifest["batches"]:
        batch_ids = tuple(batch["requested_mbids"])
        if requested.intersection(batch_ids):
            raise ValueError("cultural query repeats requested artist")
        requested.update(batch_ids)
        if hashlib.sha256(build_query(batch_ids).encode()).hexdigest() != batch["query_sha256"]:
            raise ValueError("cultural query does not replay")
        body = _path(directory, batch["raw_path"]).read_bytes()
        if (
            batch["http_status"] != HTTP_OK
            or len(body) != batch["response_bytes"]
            or hashlib.sha256(body).hexdigest() != batch["response_sha256"]
        ):
            raise ValueError("cultural raw response differs")
        evidence = parse_bindings(json.loads(body), set(batch_ids))
        qids = {item["artist_mbid"]: item.get("qid") for item in cohort}
        replayed.extend(
            item.model_dump(mode="json")
            for item in evidence
            if qids.get(item.musicbrainz_artist_id) in (None, item.wikidata_artist_id)
        )
    if requested != set(ids) or replayed != _read(_path(directory, "artist-evidence.json")):
        raise ValueError("cultural claims do not replay from exact requested source identities")
    matched = {item["musicbrainz_artist_id"] for item in replayed}
    if (
        len(matched) != len(replayed)
        or len(replayed) != manifest["matched_artist_count"]
        or sorted(set(ids) - matched) != manifest["unmatched_artist_mbids"]
        or sum(len(item["claims"]) for item in replayed) != manifest["direct_claim_count"]
    ):
        raise ValueError("cultural missingness or claim accounting differs")
    return manifest, replayed


def _acoustic(directory: Path) -> dict[str, Any]:  # noqa: C901 - numeric-only custody checks.
    """Verify projected custody without asserting unavailable native raw replay."""
    receipt = _read(_path(directory, "receipt.json"))
    path = _path(directory, "acoustic-descriptors.json")
    data = _read(path)
    if (
        _hash(path) != receipt["projection_sha256"]
        or receipt["license"] != "CC0-1.0"
        or data["scope"]["license"] != "CC0-1.0"
        or data["source_receipt_sha256"] != receipt["source_receipt_sha256"]
        or data["source_summary_sha256"] != receipt["source_summary_sha256"]
        or set(data)
        != {"artists", "features", "scope", "source_receipt_sha256", "source_summary_sha256"}
    ):
        raise ValueError("acoustic projected custody or license differs")
    features = data["features"]
    seen = set()
    for artist in data["artists"]:
        if set(artist) != {"artist_id", "recording_count", "values", "observed_counts"}:
            raise ValueError("acoustic example contains unapproved artist fields")
        if artist["artist_id"] in seen:
            raise ValueError("acoustic example repeats artist identity")
        seen.add(artist["artist_id"])
        count = artist["recording_count"]
        if type(count) is not int or count < 1:
            raise ValueError("acoustic recording count must be a positive integer")
        if set(artist["values"]) != set(features) or set(artist["observed_counts"]) != set(
            features
        ):
            raise ValueError("acoustic feature missingness differs")
        for feature in features:
            value = artist["values"][feature]
            observed = artist["observed_counts"][feature]
            if type(observed) is not int or not 0 <= observed <= count:
                raise ValueError("acoustic observed count is invalid")
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError("acoustic descriptor must be finite numeric metadata")
            if (value is None) != (observed == 0):
                raise ValueError("acoustic numeric missingness differs from observed counts")
    return data


def _source_pins(root: Path) -> dict[str, str]:
    examples = root / "data/examples"
    packs = (*CULTURAL_PACKS, "recording-facts", "artist-links", "acoustic-descriptors")
    return {
        str(path.relative_to(root)): _hash(_path(root, str(path.relative_to(root))))
        for pack in packs
        for path in sorted((examples / pack).rglob("*"))
        if path.is_file() and path.name != "README.md"
    }


def project_portable_foundation(  # noqa: C901, PLR0912 - explicit independent source boundaries.
    root: Path,
) -> dict[str, Any]:
    """Replay real source inputs into complete cohort records, preserving abstentions."""
    examples = root / "data/examples"
    artists: dict[str, dict[str, Any]] = {}
    for pack in CULTURAL_PACKS:
        directory = examples / pack
        manifest, evidence = _verified_cultural(directory)
        for item in manifest["cohort"]:
            identity = item["artist_mbid"]
            artists.setdefault(
                identity,
                {
                    "artist_mbid": identity,
                    "name": item["name"],
                    "wikidata_ids": [],
                    "claims": [],
                    "direct_genres": [],
                    "recordings": [],
                    "links": [],
                    "acoustic": None,
                    "cohort_sources": [],
                },
            )
            artists[identity]["cohort_sources"].append(pack)
        for item in evidence:
            artist = artists[item["musicbrainz_artist_id"]]
            artist["wikidata_ids"].append(item["wikidata_artist_id"])
            for claim in item["claims"]:
                # Multiple snapshots stay claims, never independent corroborating votes.
                row = dict(claim)
                row.update(
                    {
                        "capture_pack": pack,
                        "observed_at": manifest["acquired_utc"],
                        "verification": "native_raw_replay",
                        "scope": "direct_artist_property",
                    }
                )
                batch = next(
                    b for b in manifest["batches"] if artist["artist_mbid"] in b["requested_mbids"]
                )
                row["source_sha256"] = batch["response_sha256"]
                artist["claims"].append(row)
    recording_receipt = _read(_path(examples / "recording-facts", "receipt.json"))
    recording_captures = {
        (item["artist_mbid"], item["recording_mbid"]): item
        for item in recording_receipt["captures"]
    }
    recordings = verify_recording_fact_pack(examples / "recording-facts")
    for item in recordings["artists"]:
        identity = item["artist_mbid"]
        if identity not in artists:
            raise ValueError("native recording credit artist is outside requested cohort")
        artists[identity]["recordings"] = [
            {
                **row,
                "license": "CC0-1.0",
                "verification": "native_recording_credit_replay",
                "source": "MusicBrainz",
                "source_url": recording_captures[(identity, row["recording_mbid"])]["url"],
                "observed_at": recording_captures[(identity, row["recording_mbid"])]["fetched_at"],
                "scope": "bounded_exact_recording_credits_only",
            }
            for row in item["recordings"]
        ]
        artists[identity]["recording_request_missingness"] = {
            "requested_recordings": item["requested_recordings"],
            "missing_recordings": item["missing_recordings"],
        }
    links = verify_artist_link_projection(
        examples / "artist-links/artist-links.json", examples / "artist-links/receipt.json"
    )
    for item in links["artists"]:
        if item["artist_mbid"] not in artists:
            raise ValueError("outbound link artist is outside requested cohort")
        # Provider links are public core relationships, never private model inputs.
        artists[item["artist_mbid"]]["links"] = [
            {
                **row,
                "license": "CC0-1.0",
                "source": "MusicBrainz",
                "verification": "native_artist_relationship_replay",
                "observed_at": None,
                "observed_at_status": "not_retained_in_source_receipt",
                "scope": "artist_destination_not_recording_playback",
            }
            for row in item["links"]
        ]
    acoustic = _acoustic(examples / "acoustic-descriptors")
    for item in acoustic["artists"]:
        if item["artist_id"] not in artists:
            raise ValueError("acoustic artist is outside requested cohort")
        artists[item["artist_id"]]["acoustic"] = {
            **item,
            "verification": "projection_receipt_only",
            "license": "CC0-1.0",
            "source_receipt_sha256": acoustic["source_receipt_sha256"],
            "source_summary_sha256": acoustic["source_summary_sha256"],
            "raw_replay_available": False,
        }
    genres: dict[str, dict[str, Any]] = {}
    for identity, artist in sorted(artists.items()):
        artist["wikidata_ids"] = sorted(set(artist["wikidata_ids"]))
        for claim in artist["claims"]:
            if claim["property_id"] != "P136":
                continue
            genre = genres.setdefault(
                claim["value_qid"],
                {
                    "genre_id": claim["value_qid"],
                    "name": claim["value_label"] or claim["value_qid"],
                    "artist_mbids": [],
                },
            )
            genre["artist_mbids"].append(identity)
            artist["direct_genres"].append(claim["value_qid"])
        artist["direct_genres"] = sorted(set(artist["direct_genres"]))
        artist["missingness"] = {
            "wikidata_identity": "observed"
            if artist["wikidata_ids"]
            else "unmatched_requested_identity",
            "direct_genres": "observed" if artist["direct_genres"] else "no_observed_direct_genre",
            "recordings": "bounded_exact_credit_examples"
            if artist["recordings"]
            else "not_in_recording_cohort",
            "destinations": "observed_artist_links" if artist["links"] else "not_in_link_cohort",
            "sonic": "projected_numeric_example"
            if artist["acoustic"]
            else "not_in_acoustic_cohort",
            "semantic_position": "unavailable",
            "inferred_memberships": "not_constructed",
        }
    for genre in genres.values():
        genre["artist_mbids"] = sorted(set(genre["artist_mbids"]))
    rows = list(artists.values())
    return {
        "revision": REVISION,
        "license": "CC0-1.0",
        "attribution": "Wikidata, MusicBrainz and AcousticBrainz contributors",
        "scope": {
            "status": "partial_selected_cohort",
            "full_foundation_complete": False,
            "artist_count": len(rows),
            "historical_inputs_used": False,
            "spotify_private_inputs_used": False,
            "noncommercial_packs_used": False,
            "legacy_release_equivalence": False,
            "cohort_selection": (
                "110 previously selected identity-only artists plus 42 independently curated "
                "exact identities; overlap retained once"
            ),
            "limits": (
                "Direct source claims only. Sparse selected coverage; no semantic map, learned "
                "memberships, independent musical validation or complete Every Noise parity."
            ),
        },
        "counts": {
            "artists": len(rows),
            "genres": len(genres),
            "artists_without_genres": sum(not a["direct_genres"] for a in rows),
            "recordings": sum(len(a["recordings"]) for a in rows),
            "artists_without_sonic": sum(a["acoustic"] is None for a in rows),
        },
        "artists": sorted(rows, key=lambda a: a["artist_mbid"]),
        "genres": sorted(genres.values(), key=lambda g: g["genre_id"]),
    }


def browse_layout(data: dict[str, Any]) -> dict[str, Any]:
    """Provide deterministic readable browsing positions, with all semantics abstained."""
    genres = sorted(data["genres"], key=lambda g: (g["name"].casefold(), g["genre_id"]))
    return {
        "revision": "open-foundation-browse-layout-v1",
        "method": "alphabetical_browse_grid",
        "semantic_coordinates_available": False,
        "axes": "presentation only; no musical meaning",
        "positions": [
            {"genre_id": g["genre_id"], "x": i % 4, "y": i // 4} for i, g in enumerate(genres)
        ],
        "semantic_abstentions": [g["genre_id"] for g in genres],
    }


def _database(path: Path, data: dict[str, Any]) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA user_version=1;
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE artist(artist_mbid TEXT PRIMARY KEY,
                name TEXT NOT NULL,record_json TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE genre(genre_id TEXT PRIMARY KEY,name TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE direct_genre(artist_mbid TEXT REFERENCES artist,
                genre_id TEXT REFERENCES genre,PRIMARY KEY(artist_mbid,genre_id)) WITHOUT ROWID;
            CREATE TABLE claim(artist_mbid TEXT REFERENCES artist,ordinal INTEGER,
                record_json TEXT NOT NULL,PRIMARY KEY(artist_mbid,ordinal)) WITHOUT ROWID;
            CREATE TABLE recording(artist_mbid TEXT REFERENCES artist,recording_mbid TEXT,
                record_json TEXT NOT NULL,PRIMARY KEY(artist_mbid,recording_mbid)) WITHOUT ROWID;
        """)
        with connection:
            for key in ("revision", "license", "scope", "counts"):
                connection.execute(
                    "INSERT INTO metadata VALUES (?,?)", (key, canonical_json(data[key]).decode())
                )
            for genre in data["genres"]:
                connection.execute(
                    "INSERT INTO genre VALUES (?,?)", (genre["genre_id"], genre["name"])
                )
            for artist in data["artists"]:
                identity = artist["artist_mbid"]
                connection.execute(
                    "INSERT INTO artist VALUES (?,?,?)",
                    (identity, artist["name"], canonical_json(artist).decode()),
                )
                for genre_id in artist["direct_genres"]:
                    connection.execute(
                        "INSERT INTO direct_genre VALUES (?,?)", (identity, genre_id)
                    )
                for index, claim in enumerate(artist["claims"]):
                    connection.execute(
                        "INSERT INTO claim VALUES (?,?,?)",
                        (identity, index, canonical_json(claim).decode()),
                    )
                for recording in artist["recordings"]:
                    connection.execute(
                        "INSERT INTO recording VALUES (?,?,?)",
                        (identity, recording["recording_mbid"], canonical_json(recording).decode()),
                    )


def _database_rows(path: Path) -> Iterator[list[Any]]:
    with closing(
        sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        if (
            connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or connection.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("portable catalog integrity or foreign keys failed")
        for table, order in (
            ("metadata", "key"),
            ("artist", "artist_mbid"),
            ("genre", "genre_id"),
            ("direct_genre", "artist_mbid,genre_id"),
            ("claim", "artist_mbid,ordinal"),
            ("recording", "artist_mbid,recording_mbid"),
        ):
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):  # noqa: S608 - fixed internal identifiers.
                yield [table, list(row)]


def _logical_database_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for row in _database_rows(path):
        digest.update(canonical_json(row) + b"\n")
    return digest.hexdigest()


def inspect_legacy_inputs(root: Path) -> dict[str, Any]:
    """Report absent legacy artifacts without fabricating their sealed lineage."""
    return {
        "revision": "legacy-input-availability-v1",
        "exact_reconstruction_available": False,
        "reason": (
            "Canonical bytes and layout adapter inputs are unavailable. The retained 3.7 MB "
            "historical vault is not the 62-object 1.54 GB Phase 3 metadata vault; candidate "
            "replays differ in schema, timestamps and provenance. Open portable artifacts "
            "are independently named and never inherit sealed hashes."
        ),
        "inputs": [
            {
                "path": relative,
                "exists": (root / relative).is_file(),
                "expected_sha256": pin,
                "actual_sha256": _hash(root / relative) if (root / relative).is_file() else None,
            }
            for relative, pin in LEGACY_INPUTS.items()
        ],
    }


def build_portable_foundation(root: Path, output: Path) -> dict[str, Any]:
    """Build a fresh static export and separate deterministic SQLite/layout artifacts."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("portable output must be a new directory")
    data = project_portable_foundation(root)
    pins = _source_pins(root)
    output.mkdir(parents=True)
    (output / "data.json").write_bytes(canonical_json(data) + b"\n")
    (output / "layout.json").write_bytes(canonical_json(browse_layout(data)) + b"\n")
    _database(output / "catalog.sqlite", data)
    (output / "legacy-inputs.json").write_bytes(canonical_json(inspect_legacy_inputs(root)) + b"\n")
    assets = root / "src/opennoise/static"
    for asset in ASSETS:
        target = "index.html" if asset.endswith(".html") else asset
        (output / target).write_bytes(_path(assets, asset).read_bytes())
    files = {path.name: _hash(path) for path in sorted(output.iterdir())}
    receipt = {
        "revision": REVISION,
        "scope": data["scope"],
        "license": data["license"],
        "source_files_sha256": pins,
        "builder_sha256": _hash(Path(__file__)),
        "verifier_files_sha256": {name: _hash(_path(root, name)) for name in VERIFIER_FILES},
        "asset_files_sha256": {asset: _hash(_path(assets, asset)) for asset in ASSETS},
        "files_sha256": files,
        "catalog_logical_sha256": _logical_database_hash(output / "catalog.sqlite"),
        "counts": data["counts"],
        "native_raw_replay": [
            "Wikidata direct properties",
            "MusicBrainz exact recording credits",
            "MusicBrainz artist URL relationships",
        ],
        "projected_custody_only": ["AcousticBrainz numeric descriptor example"],
        "legacy_sealed_release": False,
        "full_foundation_acceptance": "incomplete",
    }
    (output / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    validate_portable_foundation(root, output)
    return receipt


def validate_portable_foundation(  # noqa: C901, PLR0912 - one complete source/SQL/static replay.
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Replay current source packs and validate every output byte and catalog record."""
    receipt = _read(_path(output, "receipt.json"))
    if receipt["revision"] != REVISION or receipt["legacy_sealed_release"] is not False:
        raise ValueError("portable receipt revision or release boundary differs")
    if receipt["builder_sha256"] != _hash(Path(__file__)) or receipt[
        "source_files_sha256"
    ] != _source_pins(root):
        raise ValueError("portable builder or source custody differs")
    if receipt["verifier_files_sha256"] != {
        name: _hash(_path(root, name)) for name in VERIFIER_FILES
    }:
        raise ValueError("portable source verifier implementation differs")
    if receipt["license"] != "CC0-1.0" or receipt["full_foundation_acceptance"] != "incomplete":
        raise ValueError("portable receipt license or acceptance scope differs")
    assets = root / "src/opennoise/static"
    if receipt["asset_files_sha256"] != {asset: _hash(_path(assets, asset)) for asset in ASSETS}:
        raise ValueError("portable source assets differ")
    actual = {path.name for path in output.iterdir() if path.name != "receipt.json"}
    if actual != set(receipt["files_sha256"]):
        raise ValueError("portable output member set differs")
    for relative, digest in receipt["files_sha256"].items():
        if _hash(_path(output, relative)) != digest:
            raise ValueError(f"portable output hash differs: {relative}")
    for asset in ASSETS:
        target = "index.html" if asset.endswith(".html") else asset
        if _path(output, target).read_bytes() != _path(assets, asset).read_bytes():
            raise ValueError("portable static asset differs from implementation")
    data = project_portable_foundation(root)
    if _read(output / "data.json") != data or _read(output / "layout.json") != browse_layout(data):
        raise ValueError("portable source projection or layout does not replay")
    if receipt["scope"] != data["scope"] or receipt["counts"] != data["counts"]:
        raise ValueError("portable cohort scope or missingness differs")
    if _logical_database_hash(output / "catalog.sqlite") != receipt["catalog_logical_sha256"]:
        raise ValueError("portable catalog logical hash differs")
    if list(_database_rows(output / "catalog.sqlite")) != list(_projected_database_rows(data)):
        raise ValueError("portable catalog tables differ from native source replay")
    return receipt


def _projected_database_rows(data: dict[str, Any]) -> Iterator[list[Any]]:
    """Reconstruct every SQL row without trusting the generated database or receipt."""
    for key in sorted(("revision", "license", "scope", "counts")):
        yield ["metadata", [key, canonical_json(data[key]).decode()]]
    for artist in data["artists"]:
        yield ["artist", [artist["artist_mbid"], artist["name"], canonical_json(artist).decode()]]
    for genre in data["genres"]:
        yield ["genre", [genre["genre_id"], genre["name"]]]
    for artist in data["artists"]:
        for genre_id in artist["direct_genres"]:
            yield ["direct_genre", [artist["artist_mbid"], genre_id]]
    for artist in data["artists"]:
        for index, claim in enumerate(artist["claims"]):
            yield ["claim", [artist["artist_mbid"], index, canonical_json(claim).decode()]]
    for artist in data["artists"]:
        for recording in sorted(artist["recordings"], key=lambda row: row["recording_mbid"]):
            yield [
                "recording",
                [
                    artist["artist_mbid"],
                    recording["recording_mbid"],
                    canonical_json(recording).decode(),
                ],
            ]
