"""Build the pinned public artist network without audio or user-level data."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import shutil
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import sparse

if TYPE_CHECKING:
    from pathlib import Path

from opennoise.pipeline.catalog_demo import digest, read, write

CONTRACT = "config/releases/native-artist-network-inputs-v1.json"
CONTRACT_SHA256 = "8f8255ca19f0bce21d2cfbc7e5af74c4791a4c47ab0c0a162d006352b10a91c9"
PROMOTION = "config/releases/native-artist-network-promotion-v1.json"
PROMOTION_SHA256 = "1a710c6e3e4b6f084dab6816bbdb419faac8f6d663b9d80723cdb96fbbd8ba17"
SNAPSHOT = "data/examples/native-artist-network-v1/snapshot.json.gz"
ID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
MAX_SOURCE_BYTES = 40_000_000
MIN_AGGREGATE_SCORE = 10
MIN_CONTEXT = 3
MIN_CONTEXT_SCORE = 1e-8
MAP_WIDTH = 1200
MAP_HEIGHT = 780
MIN_FONT_SIZE = 14
MAX_FONT_SIZE = 24
MIN_HIT_WIDTH = 40


def _pinned(root: Path, relative: str, expected: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError(f"Artist-network source differs: {relative}")
    return path


def inputs(root: Path) -> dict[str, Any]:
    """Verify the closed artist-only input before consuming any snapshot bytes."""
    contract = read(_pinned(root, CONTRACT, CONTRACT_SHA256))
    source = _pinned(root, SNAPSHOT, contract["snapshot_sha256"])
    if source.stat().st_size != contract["snapshot_bytes"]:
        raise ValueError("Artist-network source length differs")
    return contract


def read_snapshot(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Read a bounded identity and relationship projection with an exact field roster."""
    with gzip.open(root / SNAPSHOT, "rb") as stream:
        body = stream.read(MAX_SOURCE_BYTES + 1)
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError("Artist-network expanded source exceeds bounds")
    data = json.loads(body)
    if set(data) != {"revision", "artists", "pairs", "layouts", "source"}:
        raise ValueError("Artist-network contains undeclared source fields")
    artists = data["artists"]
    ids = {row["id"] for row in artists}
    if len(ids) != len(artists) or len(ids) != contract["counts"]["artists"]:
        raise ValueError("Artist-network identity count differs")
    for row in artists:
        if set(row) != {"id", "name"} or not ID.fullmatch(row["id"]) or not row["name"].strip():
            raise ValueError("Invalid native artist identity")
    pairs = set()
    for a, b, score in data["pairs"]:
        if a not in ids or b not in ids or a >= b or (a, b) in pairs:
            raise ValueError("Invalid or repeated artist relationship")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or score <= MIN_AGGREGATE_SCORE
        ):
            raise ValueError("Invalid aggregate relationship score")
        pairs.add((a, b))
    if len(pairs) != contract["counts"]["observed_undirected_pairs"]:
        raise ValueError("Artist relationship count differs")
    return data


def validate_layout(layout: list[dict[str, Any]], valid: set[str]) -> None:
    """Reject undeclared, unbounded or repeated map positions."""
    seen = set()
    for point in layout:
        if (
            set(point) != {"id", "x", "y", "size", "width"}
            or point["id"] not in valid
            or point["id"] in seen
        ):
            raise ValueError("Invalid artist-map member")
        seen.add(point["id"])
        if not all(
            isinstance(point[k], (int, float)) and math.isfinite(point[k])
            for k in ("x", "y", "size", "width")
        ):
            raise ValueError("Non-finite map point")
        if not (
            0 <= point["x"] <= MAP_WIDTH
            and 0 <= point["y"] <= MAP_HEIGHT
            and MIN_FONT_SIZE <= point["size"] <= MAX_FONT_SIZE
            and MIN_HIT_WIDTH <= point["width"] <= MAP_WIDTH
        ):
            raise ValueError("Map point exceeds layout bounds")


def _genre_suggestions(
    site: Path, destination: Path, neighbors: dict[str, dict[str, float]], names: dict[str, str]
) -> int:
    """Extend navigation from observed members without asserting new genre memberships."""
    result = {}
    for genre in read(site / "genres.json"):
        members = {row[0] for row in genre["artists"]}
        seeds = [a for a in members if neighbors[a]]
        scores: dict[str, float] = defaultdict(float)
        support: dict[str, int] = defaultdict(int)
        for artist in seeds:
            maximum = max(neighbors[artist].values())
            for target, score in neighbors[artist].items():
                if target not in members:
                    scores[target] += score / maximum
                    support[target] += 1
        minimum = min(2, len(seeds))
        ranked = sorted(
            (a for a in scores if support[a] >= minimum),
            key=lambda a: (-support[a], -round(scores[a], 8), a),
        )[:12]
        if ranked:
            result[genre["genre_id"]] = [{"id": a, "name": names[a]} for a in ranked]
    write(destination / "genres.json", result)
    return len(result)


def _standalone(destination: Path) -> None:
    """Keep the artist explorer usable when opened locally without an HTTP server."""
    files = {
        p.relative_to(destination).as_posix(): read(p) for p in sorted(destination.rglob("*.json"))
    }
    data = json.dumps(files, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    script = (
        "globalThis.OPENNOISE_ARTIST_FILES=" + data + ";\n" + (destination / "app.mjs").read_text()
    )
    if "</script" in script.lower():
        raise ValueError("Unexpected artist script boundary")
    html = (
        (destination / "index.html").read_text().replace('href="../"', 'href="../OpenNoise.html"')
    )
    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        "<style>" + (destination / "style.css").read_text() + "</style>",
    )
    html = html.replace(
        '<script type="module" src="app.mjs"></script>',
        '<script type="module">' + script + "</script>",
    )
    (destination / "OpenNoiseArtists.html").write_text(html)


def build(root: Path, site: Path) -> dict[str, Any]:
    """Write native relationships and replay shared-context suggestions from the full graph."""
    contract = inputs(root)
    data = read_snapshot(root, contract)
    artists = data["artists"]
    ids = [row["id"] for row in artists]
    index = {a: i for i, a in enumerate(ids)}
    neighbors: dict[str, dict[str, float]] = defaultdict(dict)
    rows, cols, weights = [], [], []
    for a, b, score in data["pairs"]:
        i, j = index[a], index[b]
        neighbors[a][b] = score
        neighbors[b][a] = score
        rows.extend([i, j])
        cols.extend([j, i])
        weights.extend([math.log1p(score)] * 2)
    matrix = sparse.csr_matrix((weights, (rows, cols)), shape=(len(ids), len(ids)))
    lengths = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    inverse = np.zeros_like(lengths)
    np.divide(1, lengths, out=inverse, where=lengths > 0)
    profiles = sparse.diags(inverse) @ matrix
    destination = site / "artist-network"
    destination.mkdir()
    buckets: dict[str, dict[str, Any]] = defaultdict(dict)
    for a in ids:
        q = index[a]
        connections = sorted(neighbors[a], key=lambda b: (-neighbors[a][b], b))
        suggestions = []
        if len(connections) >= MIN_CONTEXT:
            score = (profiles[q] @ profiles.T).toarray().ravel()
            mask = np.ones(len(ids), dtype=bool)
            mask[q] = False
            mask[[index[b] for b in connections]] = False
            candidates = np.flatnonzero(mask & (score > MIN_CONTEXT_SCORE) & (lengths > 0))
            ranked = candidates[np.lexsort((candidates, -np.round(score[candidates], 8)))][:10]
            suggestions = [ids[int(i)] for i in ranked]
        layout = data["layouts"].get(a, [])
        validate_layout(layout, {a, *connections})
        buckets[a[:2]][a] = {"connections": connections, "suggested": suggestions, "map": layout}
    for prefix, bucket in sorted(buckets.items()):
        write(destination / f"details/{prefix}.json", bucket)
    write(
        destination / "catalog.json",
        {
            "revision": "native-artist-network-v1",
            "artists": artists,
            "counts": contract["counts"],
            "method": "common_context",
        },
    )
    for name in ("index.html", "app.mjs", "style.css"):
        shutil.copyfile(root / "src/opennoise/static/artist-network" / name, destination / name)
    populated = _genre_suggestions(
        site, destination, neighbors, {row["id"]: row["name"] for row in artists}
    )
    if populated != contract["genres_with_suggestions"]:
        raise ValueError("Genre navigation coverage differs from pinned source")
    evidence = {
        "revision": "native-artist-network-v1",
        "input_contract_sha256": CONTRACT_SHA256,
        "source": data["source"],
        "rights": "ListenBrainz aggregate listening sessions and MusicBrainz core identities, CC0",
        "audio_lyrics_and_user_histories": False,
        "genre_labels_inferred": False,
        "suggestions": (
            "Cosine of sparse log-weighted artist-neighbor profiles; known connections "
            "and self excluded; uncalibrated; relevance not independently judged"
        ),
        "counts": contract["counts"],
    }
    write(destination / "receipt.json", evidence)
    _standalone(destination)
    return {"input_contract_sha256": CONTRACT_SHA256, "counts": contract["counts"]}


def authorize(root: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> None:
    """Require a distinct fixed promotion while preserving the old catalog's data pins."""
    approval = read(_pinned(root, PROMOTION, PROMOTION_SHA256))
    data = {
        k: v
        for k, v in payload.items()
        if k.startswith("artist-network/")
        and k.endswith(".json")
        and k != "artist-network/receipt.json"
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
        raise ValueError("Artist-network candidate differs from promoted public data")
