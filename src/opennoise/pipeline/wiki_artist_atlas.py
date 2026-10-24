"""Build a separately pinned Wikipedia artist atlas beside the existing CC0 catalog."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import re
import shutil
import unicodedata
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import sparse

from opennoise.pipeline.catalog_demo import digest, read, write

if TYPE_CHECKING:
    from pathlib import Path

CONTRACT = "config/releases/wiki-artist-atlas-inputs-v1.json"
CONTRACT_SHA256 = "673cc05bd0402541787d2b2ca7056afa7056d0cd97a63092fd73b81986039640"
PROMOTION = "config/releases/wiki-artist-atlas-promotion-v2.json"
PROMOTION_SHA256 = "e75b82f00bc7ab6a589036b2e19b59497498f66819887435d0bf0ac94536e513"
SNAPSHOT = "data/examples/wiki-artist-atlas-v1/snapshot.json.gz"
RESOURCE = "http://dbpedia.org/resource/"
DBO = "http://dbpedia.org/ontology/"
MAX_SOURCE_BYTES = 120_000_000
COORDINATE_DIMENSIONS = 2
MIN_CONTEXT_SCORE = 1e-8
WELL_CONNECTED_MINIMUM = 5
INCOMPATIBLE_ARTIST_TYPES = {
    "MusicalWork",
    "Work",
    "Genre",
    "MusicGenre",
    "Instrument",
    "Place",
    "Language",
}
INCOMPATIBLE_GENRE_TYPES = {
    "Agent",
    "Person",
    "MusicalArtist",
    "Band",
    "Organisation",
    "Company",
    "RecordLabel",
    "EthnicGroup",
    "Place",
    "Instrument",
    "Language",
    "Work",
    "Event",
    "TimePeriod",
}
IDENTITY_EVIDENCE = {
    "source_type",
    "source_person_and_instrument",
}
RELATIONSHIPS = {
    DBO + v for v in ("associatedMusicalArtist", "associatedBand", "bandMember", "formerBandMember")
}


def _pinned(root: Path, relative: str, expected: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError(f"Wiki artist source differs: {relative}")
    return path


def inputs(root: Path) -> dict[str, Any]:
    """Verify the new source without changing either prior public input contract."""
    contract = read(_pinned(root, CONTRACT, CONTRACT_SHA256))
    source = _pinned(root, SNAPSHOT, contract["snapshot_sha256"])
    if source.stat().st_size != contract["snapshot_bytes"]:
        raise ValueError("Wiki artist source length differs")
    parent = source.parent
    for name, expected in contract["metadata_manifests"].items():
        _pinned(root, (parent / name).relative_to(root).as_posix(), expected)
    _pinned(
        root, (parent / "dbpedia-logo.png").relative_to(root).as_posix(), contract["logo_sha256"]
    )
    _pinned(
        root,
        (parent / "genres.txt").relative_to(root).as_posix(),
        contract["genre_vocabulary_sha256"],
    )
    return contract


def identity_valid(row: dict[str, Any]) -> bool:
    """Require positive musical identity evidence; relationship roles cannot supply it."""
    kinds = set(row.get("source_types", ()))
    evidence = set(row.get("identity_evidence", ()))
    if not evidence or not evidence <= IDENTITY_EVIDENCE or kinds & INCOMPATIBLE_ARTIST_TYPES:
        return False
    direct = bool(kinds & {"MusicalArtist", "Band"}) and "source_type" in evidence
    person = "Person" in kinds and "source_person_and_instrument" in evidence
    return direct or person


def _artist(row: dict[str, Any], valid_genres: set[str]) -> None:
    """Validate the identity proof and every allowed feature block."""
    expected_artist = {
        "uri",
        "name",
        "genres",
        "features",
        "identity_evidence",
        "source_types",
        "position",
    }
    if set(row) != expected_artist or not identity_valid(row):
        raise ValueError("Wiki atlas identity lacks positive artist evidence")
    if not set(row["genres"]) <= valid_genres:
        raise ValueError("Unknown source genre membership")
    if not set(row["features"]) <= {DBO + "instrument", DBO + "recordLabel"}:
        raise ValueError("Unexpected artist feature source")


def _vocabulary_match(name: str, vocabulary: set[str]) -> str | None:
    """Validate labels against core genre definitions without reading artist genre tags."""
    term = unicodedata.normalize("NFKC", name).casefold().strip()
    variants = [term]
    if term.endswith(" music"):
        variants.append(term[:-6].strip())
    if term.endswith(" (music)"):
        variants.append(term[:-8].strip())
    return next((v for v in variants if v in vocabulary), None)


def _genre(row: dict[str, Any], vocabulary: set[str]) -> None:
    """Reject known non-genre concepts while preserving unknown source types."""
    expected = {
        "uri",
        "name",
        "music_genre_type_observed",
        "source_types",
        "position",
        "shared_member_neighbors",
        "genre_evidence",
        "vocabulary_term",
    }
    types = set(row["source_types"])
    if set(row) != expected or (
        not types & {"Genre", "MusicGenre"} and types & INCOMPATIBLE_GENRE_TYPES
    ):
        raise ValueError("Incompatible source genre concept")
    if row["genre_evidence"] == "dbpedia_genre_type" and types & {"Genre", "MusicGenre"}:
        return
    if (
        row["genre_evidence"] != "musicbrainz_core_vocabulary"
        or _vocabulary_match(row["name"], vocabulary) != row["vocabulary_term"]
        or row["vocabulary_term"] is None
    ):
        raise ValueError("Unvalidated source genre label")


def _named_position(row: dict[str, Any]) -> None:
    """Require a named source URI and bounded navigation coordinates."""
    if (
        not row["uri"].startswith(RESOURCE)
        or not isinstance(row["name"], str)
        or not row["name"].strip()
    ):
        raise ValueError("Invalid named source entity")
    position = row["position"]
    if len(position) != COORDINATE_DIMENSIONS or not all(
        not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1
        for v in position
    ):
        raise ValueError("Invalid source navigation coordinate")


def _relations(data: dict[str, Any], valid_artists: set[str]) -> None:
    """Keep source relationship kinds and both endpoints inside the reviewed artist cohort."""
    seen = set()
    for a, relation, b in data["relations"]:
        if (
            a not in valid_artists
            or b not in valid_artists
            or a == b
            or relation not in RELATIONSHIPS
            or (a, relation, b) in seen
        ):
            raise ValueError("Invalid source artist relationship")
        seen.add((a, relation, b))


def read_snapshot(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Reject unreviewed fields, unsupported identities and incompatible genre concepts."""
    with gzip.open(root / SNAPSHOT, "rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES or len(raw) != contract["expanded_bytes"]:
        raise ValueError("Wiki artist expanded source differs")
    data = json.loads(raw)
    if set(data) != {
        "revision",
        "source_version",
        "artists",
        "genres",
        "relations",
        "feature_labels",
        "source",
    }:
        raise ValueError("Wiki artist source field roster differs")
    artist_ids = [r["uri"] for r in data["artists"]]
    genre_ids = [r["uri"] for r in data["genres"]]
    if artist_ids != sorted(set(artist_ids)) or genre_ids != sorted(set(genre_ids)):
        raise ValueError("Repeated or unordered source identities")
    valid_genres = set(genre_ids)
    vocabulary_path = (root / SNAPSHOT).parent / "genres.txt"
    vocabulary_raw = vocabulary_path.read_bytes()
    if hashlib.sha256(vocabulary_raw).hexdigest() != contract["genre_vocabulary_sha256"]:
        raise ValueError("Core genre vocabulary differs")
    vocabulary = {
        unicodedata.normalize("NFKC", n).casefold().strip()
        for n in vocabulary_raw.decode().splitlines()
    }
    for row in data["artists"]:
        _artist(row, valid_genres)
        _named_position(row)
    for row in data["genres"]:
        _genre(row, vocabulary)
        _named_position(row)
    _relations(data, set(artist_ids))
    return data


def _id(uri: str) -> str:
    return hashlib.sha256(uri.encode()).hexdigest()[:32]


def _genre_groups(data: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Group only validated genre-name aliases; artist identities remain separate."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for genre in data["genres"]:
        key = (
            "core:" + genre["vocabulary_term"]
            if genre["vocabulary_term"]
            else "typed:" + unicodedata.normalize("NFKC", genre["name"]).casefold().strip()
        )
        groups[key].append(genre)
    canonical, source_ids = {}, {}
    for key, values in sorted(groups.items()):
        primary = min(values, key=lambda g: (not g["music_genre_type_observed"], g["uri"]))
        gid = _id("genre-name:" + key)
        canonical[gid] = {**primary, "source_uris": sorted(g["uri"] for g in values)}
        for genre in values:
            source_ids[genre["uri"]] = gid
    return canonical, source_ids


def _map(ids: list[str], names: dict[str, dict[str, Any]], degrees: dict[str, int]) -> list[str]:
    return sorted(set(ids), key=lambda a: (-degrees[a], names[a]["uri"]))[:60]


def _standalone(site: Path) -> None:
    """Compress the complete atlas into one offline HTML without a public file over25MiB."""
    files = {
        p.relative_to(site).as_posix(): read(p) for p in sorted((site / "atlas").rglob("*.json"))
    }
    files["artist-network/catalog.json"] = read(site / "artist-network/catalog.json")
    # Public IDs repeat across complete member/neighbor lists. Intern them only in
    # the offline transport; restore exact IDs before the normal app reads data.
    ids = [r["id"] for r in files["atlas/artists.json"]]
    ids.extend(r["id"] for r in files["atlas/genres.json"])
    tokens = {v: "~" + format(i, "x") for i, v in enumerate(ids)}

    def compact(value: object) -> object:
        if isinstance(value, str):
            return tokens.get(value, "~" + value if value.startswith("~") else value)
        if isinstance(value, list):
            return [compact(v) for v in value]
        if isinstance(value, dict):
            return {compact(k): compact(v) for k, v in value.items()}
        return value

    if len(ids) != len(set(ids)) or not all(re.fullmatch("[a-f0-9]{32}", v) for v in ids):
        raise ValueError("Offline atlas identifier roster differs")
    raw = json.dumps(
        {"ids": ids, "files": compact(files)},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    compressed = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    normalization = (
        (site / "full-foundation-normalization.mjs")
        .read_text()
        .replace("export const normalizeName", "const normalizeName")
    )
    script = (
        (site / "atlas.mjs")
        .read_text()
        .replace(
            "import {normalizeName} from './full-foundation-normalization.mjs';", normalization
        )
    )
    script = "globalThis.OPENNOISE_ATLAS_GZIP=" + json.dumps(compressed) + ";\n" + script
    if "</script" in script.lower():
        raise ValueError("Unexpected offline atlas script boundary")
    html = (site / "index.html").read_text()
    html = html.replace(
        '<link rel="stylesheet" href="atlas.css">',
        "<style>" + (site / "atlas.css").read_text() + "</style>",
    )
    html = html.replace(
        '<script type="module" src="atlas.mjs"></script>',
        '<script type="module">' + script + "</script>",
    )
    if len(html.encode()) >= 25 * 1024 * 1024:
        raise ValueError(f"Offline atlas exceeds Pages file limit: {len(html.encode())} bytes")
    (site / "OpenNoise.html").write_text(html)


def _profiles(data: dict[str, Any]) -> tuple[dict[str, set[str]], Any]:
    """Fit binary source-neighbor profiles from the complete public graph."""
    artists = data["artists"]
    index = {a["uri"]: i for i, a in enumerate(artists)}
    neighbors: dict[str, set[str]] = defaultdict(set)
    for a, _, b in data["relations"]:
        neighbors[a].add(b)
        neighbors[b].add(a)
    rows, cols = [], []
    for a, values in sorted(neighbors.items()):
        rows.extend([index[a]] * len(values))
        cols.extend(index[b] for b in sorted(values))
    graph = sparse.csr_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(len(artists), len(artists))
    )
    lengths = np.sqrt(np.asarray(graph.sum(axis=1)).ravel())
    inverse = np.zeros_like(lengths)
    np.divide(1, lengths, out=inverse, where=lengths > 0)
    profiles = (sparse.diags(inverse) @ graph).tocsr()
    return neighbors, profiles


def _metadata_profiles(data: dict[str, Any]) -> sparse.csr_matrix:
    """Use fixed TFIDF and separately normalized genre, instrument and label blocks."""
    artists = data["artists"]
    _, genre_ids = _genre_groups(data)
    blocks = []
    for kind in ("genre", "instrument", "recordLabel"):
        values = [
            sorted({genre_ids[g] for g in a["genres"]})
            if kind == "genre"
            else sorted(set(a["features"].get(DBO + kind, ())))
            for a in artists
        ]
        vocabulary = {v: i for i, v in enumerate(sorted({v for row in values for v in row}))}
        rows, columns = [], []
        for i, row in enumerate(values):
            rows.extend([i] * len(row))
            columns.extend(vocabulary[v] for v in row)
        matrix = sparse.csr_matrix(
            (np.ones(len(rows)), (rows, columns)), shape=(len(artists), len(vocabulary))
        )
        frequency = np.asarray((matrix > 0).sum(axis=0)).ravel()
        matrix = matrix @ sparse.diags(1 + np.log((len(artists) + 1) / (frequency + 1)))
        length = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
        inverse = np.zeros_like(length)
        np.divide(1, length, out=inverse, where=length > 0)
        blocks.append(sparse.diags(inverse) @ matrix)
    combined = sparse.hstack(blocks, format="csr")
    length = np.sqrt(np.asarray(combined.multiply(combined).sum(axis=1)).ravel())
    inverse = np.zeros_like(length)
    np.divide(1, length, out=inverse, where=length > 0)
    result = (sparse.diags(inverse) @ combined).tocsr()
    if not isinstance(result, sparse.csr_matrix):
        raise TypeError("Metadata profiles must be a CSR matrix")
    return result


def _metadata_neighbors(
    profiles: sparse.csr_matrix, transpose: sparse.csr_matrix, query: int
) -> list[int]:
    """Return exact positive cosine neighbors, with bounded selection and stable ties."""
    score = (profiles[query] @ transpose).tocsr()
    mask = (score.data > MIN_CONTEXT_SCORE) & (score.indices != query)
    indices, values = score.indices[mask], np.round(score.data[mask], 8)
    limit = 10
    if len(indices) > limit:
        boundary = np.partition(values, -limit)[-limit]
        keep = values >= boundary
        indices, values = indices[keep], values[keep]
    return [int(v) for v in indices[np.lexsort((indices, -values))][:limit]]


def _artist_pages(
    data: dict[str, Any],
    destination: Path,
    contract: dict[str, Any],
    public_ids: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, set[str]], dict[str, int], dict[str, int]]:
    """Write complete artist details and their model suggestions in bounded shards."""
    artists = data["artists"]
    uri_ids = {a["uri"]: _id(a["uri"]) for a in artists}
    _, genre_ids = _genre_groups(data)
    neighbors, profiles = _profiles(data)
    transpose = profiles.T.tocsr()
    metadata = _metadata_profiles(data)
    metadata_transpose = metadata.T.tocsr()
    degree = {uri_ids[a["uri"]]: len(neighbors.get(a["uri"], ())) for a in artists}
    buckets: dict[str, dict[str, Any]] = defaultdict(dict)
    members: dict[str, list[str]] = defaultdict(list)
    suggested_counts = {"graph_suggested_artists": 0, "metadata_suggested_artists": 0}
    for q, row in enumerate(artists):
        uri, aid = row["uri"], uri_ids[row["uri"]]
        known = neighbors.get(uri, set())
        suggested = []
        if len(known) >= contract["minimum_context_neighbors"]:
            score = (profiles[q] @ transpose).tocsr()
            candidates = [
                int(i)
                for i, v in zip(score.indices, score.data, strict=True)
                if v > MIN_CONTEXT_SCORE and int(i) != q and artists[int(i)]["uri"] not in known
            ]
            values = dict(zip(score.indices.tolist(), score.data.tolist(), strict=True))
            ranked = sorted(candidates, key=lambda i: (-round(values[i], 8), i))[:10]
            suggested = [uri_ids[artists[i]["uri"]] for i in ranked]
            suggested_counts["graph_suggested_artists"] += bool(suggested)
        elif not known:
            suggested = [
                uri_ids[artists[i]["uri"]]
                for i in _metadata_neighbors(metadata, metadata_transpose, q)
            ]
            suggested_counts["metadata_suggested_artists"] += bool(suggested)
        related = [uri_ids[b] for b in sorted(known)]
        gids = sorted({genre_ids[g] for g in row["genres"]})
        for gid in gids:
            members[gid].append(aid)
        buckets[aid[:2]][aid] = {
            "name": row["name"],
            "uri": uri,
            "genres": gids,
            "related": related,
            "suggested": suggested,
            "map": _map(related, public_ids, degree),
        }
        if suggested and not known:
            buckets[aid[:2]][aid]["suggestion_basis"] = "artist_metadata"
    for prefix, bucket in sorted(buckets.items()):
        write(destination / f"artists/{prefix}.json", bucket)
    write(
        destination / "artists.json",
        [
            {
                "id": uri_ids[a["uri"]],
                "name": a["name"],
                "x": a["position"][0],
                "y": a["position"][1],
            }
            for a in artists
        ],
    )
    return members, neighbors, suggested_counts, degree


def _genre_pages(
    data: dict[str, Any],
    destination: Path,
    members: dict[str, list[str]],
    public_ids: dict[str, dict[str, Any]],
    degree: dict[str, int],
) -> list[dict[str, Any]]:
    """Keep every supported genre and its complete member list reachable."""
    canonical, _ = _genre_groups(data)
    genre_rows = []
    for gid, g in canonical.items():
        if not members[gid]:
            raise ValueError("Empty source genre would create an empty browsing page")
        genre_rows.append(
            {
                "id": gid,
                "name": g["name"],
                "uri": g["uri"],
                "source_uris": g["source_uris"],
                "artists": len(members[gid]),
                "x": g["position"][0],
                "y": g["position"][1],
            }
        )
        write(
            destination / f"genres/{gid}.json",
            {"artists": members[gid], "map": _map(members[gid], public_ids, degree)},
        )
    write(destination / "genres.json", genre_rows)
    return genre_rows


def build(root: Path, site: Path) -> dict[str, Any]:
    """Serve source memberships,source relationships and exact shared-context suggestions."""
    contract = inputs(root)
    data = read_snapshot(root, contract)
    artists = data["artists"]
    public_ids = {_id(a["uri"]): a for a in artists}
    if len(public_ids) != len(artists):
        raise ValueError("Public artist identifier collision")
    genre_ids = {g["uri"]: _id(g["uri"]) for g in data["genres"]}
    if len(set(genre_ids.values())) != len(genre_ids):
        raise ValueError("Public genre identifier collision")
    destination = site / "atlas"
    destination.mkdir()
    members, neighbors, suggested_counts, degree = _artist_pages(
        data, destination, contract, public_ids
    )
    genre_rows = _genre_pages(data, destination, members, public_ids, degree)
    observed_counts = {
        "artists": len(artists),
        "genre_artists": sum(bool(a["genres"]) for a in artists),
        "connected_artists": sum(bool(v) for v in neighbors.values()),
        "at_least5_connections": sum(len(v) >= WELL_CONNECTED_MINIMUM for v in neighbors.values()),
        "genres": len(data["genres"]),
        "genre_claims": sum(len(a["genres"]) for a in artists),
        "source_relationship_statements": len(data["relations"]),
        "source_relationship_pairs": sum(map(len, neighbors.values())) // 2,
    }
    if observed_counts != contract["counts"]:
        raise ValueError("Wiki artist source counts differ")
    counts = {
        **observed_counts,
        "source_genre_labels": observed_counts["genres"],
        "genres": len(genre_rows),
        "source_genre_claims": observed_counts["genre_claims"],
        "genre_claims": sum(len(v) for v in members.values()),
        "artists_with_suggestions": sum(suggested_counts.values()),
        **suggested_counts,
    }
    logo = (root / SNAPSHOT).parent / "dbpedia-logo.png"
    write(
        destination / "receipt.json",
        {
            "revision": "wiki-artist-atlas-v1",
            "input_contract_sha256": CONTRACT_SHA256,
            "source_version": data["source_version"],
            "counts": counts,
            "source": data["source"],
            "logo_data": "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode(),
            "audio_lyrics_or_user_histories": False,
            "musical_relevance_validated": False,
            "suggestions": (
                "Exact normalized binary neighbor-profile cosine on the complete source graph. "
                "For artists with no source relationships, exact TFIDF cosine of genre, "
                "instrument and record-label metadata, each block separately normalized. "
                "Known relationships and self excluded. Suggested is inference, "
                "not a source credit or genre claim."
            ),
        },
    )
    shutil.copyfile(site / "index.html", site / "retained.html")
    shutil.copyfile(site / "OpenNoise.html", site / "OpenNoiseRetained.html")
    assets = root / "src/opennoise/static/genre-atlas"
    for name in ("index.html", "atlas.css", "atlas.mjs"):
        shutil.copyfile(assets / name, site / name)
    _standalone(site)
    return {"input_contract_sha256": CONTRACT_SHA256, "counts": counts}


def authorize(root: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> None:
    """Require a distinct fixed approval for the new licensed source and its full data output."""
    approval = read(_pinned(root, PROMOTION, PROMOTION_SHA256))
    data = {
        k: v
        for k, v in payload.items()
        if k.startswith("atlas/") and k.endswith(".json") and k != "atlas/receipt.json"
    }
    encoded = (
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if (
        manifest.get("input_contract_sha256") != CONTRACT_SHA256
        or manifest.get("counts") != approval["counts"]
        or len(data) != approval["data_files"]
        or hashlib.sha256(encoded).hexdigest() != approval["data_inventory_sha256"]
    ):
        raise ValueError("Wiki artist atlas differs from its public promotion")
