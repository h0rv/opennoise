"""Offline genre-first index over two source-bound, individually bounded collections."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from opennoise.common import canonical_json
from opennoise.deployment.fma_listening_home import build_listening_home

REVISION = "fma-genre-discovery-v1"
MAX_INDEX_BYTES = 200_000
MAX_CONTROL_BYTES = 2_000_000
MAX_AUDIO_FILES = 65
POLICY = (
    "Up to three distinct artists per genre, choosing fewer direct source genre tags then "
    "native track ID; all available excerpts remain listed. This is a browsing heuristic, "
    "not a validated musical-quality ranking. Shared recordings prefer the original collection."
)
ASSETS = (
    "fma-discovery.html",
    "fma-discovery.js",
    "fma-discovery.css",
    "fma-playback.js",
    "fma-catalog.css",
)


def _safe(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlinked discovery path")


def _body(path: Path, limit: int = MAX_CONTROL_BYTES) -> bytes:
    _safe(path)
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("missing or oversized discovery input")
    return path.read_bytes()


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _verified_inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Replay the unchanged home contract on a bounded local hardlink snapshot."""
    retained = json.loads(_body(root / "collections.json"))
    catalogs, audio = {}, {}
    with tempfile.TemporaryDirectory(prefix="fma-discovery-", dir=root.parent) as name:
        snapshot = Path(name)
        for key in ("original", "expanded"):
            for folder in ("audio", "explorer"):
                (snapshot / key / folder).mkdir(parents=True)
            for control in ("catalog.json", "static-receipt.json"):
                body = _body(root / key / "explorer" / control)
                (snapshot / key / "explorer" / control).write_bytes(body)
            audio_root = root / key / "audio"
            _safe(audio_root)
            files = list(audio_root.iterdir())
            if len(files) > MAX_AUDIO_FILES:
                raise ValueError("audio collection inventory exceeds existing bound")
            for path in files:
                _safe(path)
                if not path.is_file() or path.stat().st_size > MAX_CONTROL_BYTES:
                    raise ValueError("audio collection file exceeds existing bound")
                os.link(path, snapshot / key / "audio" / path.name)
            catalogs[key] = json.loads(_body(snapshot / key / "explorer" / "catalog.json"))
            audio[key] = json.loads(
                _body(snapshot / key / "audio" / "manifest.json", MAX_INDEX_BYTES)
            )
        if build_listening_home(snapshot) != retained:
            raise ValueError("retained collection receipt differs from verified inputs")
    return retained, catalogs, audio


def genre_index(root: Path) -> dict[str, Any]:  # noqa: C901 -- exact source joins and transparent bounded ranking.
    """Validate custody and return the complete native-genre listening union without writing."""
    receipt, catalogs, audio = _verified_inputs(root)
    if catalogs["original"]["genres"] != catalogs["expanded"]["genres"]:
        raise ValueError("collection native genre catalogs differ")
    tracks: dict[str, Any] = {}
    collections = {}
    for key in ("original", "expanded"):
        manifest = f"{key}/audio/manifest.json"
        collections[key] = {
            "manifest": manifest,
            "manifest_sha256": _sha(_body(root / manifest, MAX_INDEX_BYTES)),
        }
        for row in catalogs[key]["playback"]["tracks"]:
            identity = str(row["track_id"])
            native = audio[key]["tracks"][identity]
            projected = {
                "track_id": row["track_id"],
                "title": native["title"],
                "artist_id": row["artist_id"],
                "artist_name": native["artist_name"],
                "genre_ids": row["genre_ids"],
            }
            if identity in tracks:
                if any(tracks[identity][field] != value for field, value in projected.items()):
                    raise ValueError("shared native recording association differs")
                tracks[identity]["origins"].append(key)
            else:
                tracks[identity] = {**projected, "collection": key, "origins": [key]}
    genres = []
    for native in catalogs["original"]["genres"]:
        identity = native["genre_id"]
        ids = sorted(row["track_id"] for row in tracks.values() if identity in row["genre_ids"])
        starters, artists = [], set()
        for track_id in sorted(
            ids, key=lambda value: (len(tracks[str(value)]["genre_ids"]), value)
        ):
            artist = tracks[str(track_id)]["artist_id"]
            if artist not in artists:
                starters.append(track_id)
                artists.add(artist)
            if len(starters) == 3:  # noqa: PLR2004 -- frozen browsing limit.
                break
        genres.append(
            {
                **{
                    field: native[field]
                    for field in ("genre_id", "title", "parent_id", "track_count")
                },
                "track_ids": ids,
                "starting_ids": starters,
                "artist_ids": sorted({tracks[str(value)]["artist_id"] for value in ids}),
                "available": bool(ids),
            }
        )
    known = {row["genre_id"] for row in genres}
    if len(known) != len(genres) or any(set(row["genre_ids"]) - known for row in tracks.values()):
        raise ValueError("unknown or duplicate native genre reference")
    result = {
        "revision": REVISION,
        "selection_policy": POLICY,
        "musical_quality_validated": False,
        "public_deployment_authorized": False,
        "counts": {
            "genres": len(genres),
            "playable_genres": sum(1 for row in genres if row["available"]),
            "artists": len({row["artist_id"] for row in tracks.values()}),
            "clips": len(tracks),
        },
        "sources": {
            "collections_sha256": _sha(_body(root / "collections.json")),
            "catalog_sha256": {row["key"]: row["catalog_sha256"] for row in receipt["collections"]},
        },
        "collections": collections,
        "genres": genres,
        "tracks": dict(sorted(tracks.items(), key=lambda item: int(item[0]))),
    }
    if len(canonical_json(result)) + 1 > MAX_INDEX_BYTES:
        raise ValueError("genre discovery index exceeds 200 KB")
    return result


def build_genre_discovery(root: Path) -> dict[str, Any]:
    """Explicitly preserve the existing chooser and install a fresh genre-first entry page."""
    _safe(root)
    names = ("collections.html", "genre-discovery.json", *ASSETS[1:])
    if any((root / name).exists() or (root / name).is_symlink() for name in names):
        raise ValueError("discovery outputs must be fresh")
    chooser = _body(root / "index.html")
    result = genre_index(root)
    source = Path(__file__).parents[1] / "static"
    assets = {name: _body(source / name) for name in ASSETS}
    outputs = {
        "collections.html": chooser,
        "genre-discovery.json": canonical_json(result) + b"\n",
        **{name: assets[name] for name in ASSETS[1:]},
    }
    for name, body in outputs.items():
        with (root / name).open("xb") as stream:
            stream.write(body)
    with tempfile.NamedTemporaryFile(dir=root, prefix=".discovery-index-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(assets["fma-discovery.html"])
    temporary.replace(root / "index.html")
    return result
