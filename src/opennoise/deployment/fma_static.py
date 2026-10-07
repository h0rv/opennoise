"""A separate CC BY static catalog of verified native FMA metadata."""

from __future__ import annotations

import io
import json
import os
import shutil
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import zstandard

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.deployment.fma_playback import validate_playback_export
from opennoise.deployment.fma_related import export_related_music
from opennoise.deployment.fma_track_search import export_track_search
from opennoise.deployment.source_genres import export_source_genres
from opennoise.ingest.fma.corpus import project_row, source_rows, verify_sources

PAGE_SIZE = 200
PROFILE_SHARDS = 128
TRACK_ID_SPAN = 500
MAX_SHARD_BYTES = 200_000
MAX_EXPORT_BYTES = 40_000_000
MAX_ARTIST_INDEX_BYTES = 2_000_000
RELATED_GENRES = 6


def _projected_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as stream:
        return [json.loads(line) for line in io.TextIOWrapper(stream)]


def verified_tables(
    source: Path, projected: Path
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Replay every native row and CRC against each bound projected table offline."""
    source_receipt = verify_sources(source)
    receipt = json.loads((projected / "corpus-receipt.json").read_bytes())
    if (
        receipt["source_receipt_sha256"] != sha256_file(source / "source-receipt.json")[0]
        or receipt["metadata_license"] != "CC-BY-4.0"
        or receipt["identity_namespace"] != "FMA_native_only"
    ):
        raise ValueError("FMA corpus custody or namespace mismatch")
    tables = {}
    known = {}
    for kind in ("artists", "genres", "tracks"):
        binding = receipt["files"][kind]
        path = projected / f"{kind}.jsonl.zst"
        if binding["path"] != path.name or sha256_file(path) != (
            binding["sha256"],
            binding["bytes"],
        ):
            raise ValueError("FMA table hash or path mismatch")
        records = _projected_rows(path)
        if len(records) != binding["rows"]:
            raise ValueError("FMA table row count mismatch")
        replayed_sha = _verify_native_rows(source, source_receipt, kind, records, known)
        if replayed_sha != binding["uncompressed_source_sha256"]:
            raise ValueError("FMA native uncompressed source hash mismatch")
        known[kind] = {
            row[{"artists": "artist_id", "genres": "genre_id", "tracks": "track_id"}[kind]]
            for row in records
        }
        if len(known[kind]) != len(records):
            raise ValueError("duplicate FMA entity IDs")
        tables[kind] = records
    return receipt, tables


def _verify_native_rows(
    source: Path,
    source_receipt: dict[str, Any],
    kind: str,
    records: list[dict[str, Any]],
    known: dict[str, set[int]],
) -> str:
    native, checked, handles = source_rows(
        source, source_receipt["members"][f"fma_metadata/raw_{kind}.csv"]
    )
    try:
        for row, actual in zip(native, records, strict=True):
            expected = project_row(kind, row)
            if kind == "tracks":
                expected["artist_id_status"] = (
                    "source_known"
                    if expected["artist_id"] in known["artists"]
                    else "source_missing"
                    if expected["artist_id"] is None
                    else "source_unresolved"
                )
                expected["unresolved_genre_ids"] = [
                    value for value in expected["genre_ids"] or [] if value not in known["genres"]
                ]
            if actual != expected:
                raise ValueError("FMA projected row differs from native source replay")
        if not checked.complete:
            raise ValueError("FMA source stream not completely verified")
    finally:
        for handle in handles:
            handle.close()
    return checked.sha256.hexdigest()


def validated_metadata_url(value: str | None) -> str | None:
    """Keep only declared native FMA metadata destinations; never construct media URLs."""
    if not value:
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme in {"http", "https"}
            and url.hostname in {"freemusicarchive.org", "www.freemusicarchive.org"}
            and not url.username
            and not url.password
            and url.port in {None, 80 if url.scheme == "http" else 443}
        ):
            return value
    except ValueError:
        pass
    return None


def _write(output: Path, relative: str, value: object, files: dict[str, Any]) -> None:
    payload = canonical_json(value) + b"\n"
    if len(payload) > MAX_SHARD_BYTES:
        raise ValueError(f"static shard exceeds 200 KB: {relative}")
    path = output / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
    digest, length = sha256_file(path)
    files[relative] = {"sha256": digest, "bytes": length}


def _cohort(output: Path, key: str, ids: list[int], files: dict[str, Any]) -> None:
    for page, start in enumerate(range(0, len(ids), PAGE_SIZE)):
        _write(
            output,
            f"cohorts/{key}/{page}.json",
            {
                "cohort": key,
                "page": page,
                "total": len(ids),
                "track_ids": ids[start : start + PAGE_SIZE],
            },
            files,
        )


def _track_rows(
    output: Path, tracks: list[dict[str, Any]], files: dict[str, Any]
) -> dict[str, Any]:
    shards = defaultdict(list)
    licenses = []
    license_ids = {}
    unvalidated_urls = 0
    for row in tracks:
        license_key = (row["audio_license_title"], row["audio_license_url"])
        if license_key not in license_ids:
            license_ids[license_key] = len(licenses)
            licenses.append(list(license_key))
        url = validated_metadata_url(row["source_metadata_url"])
        unvalidated_urls += bool(row["source_metadata_url"] and url is None)
        shards[row["track_id"] // TRACK_ID_SPAN].append(
            [
                row["track_id"],
                row["title"],
                row["artist_id"],
                row["genre_ids"],
                license_ids[license_key],
                url,
                row["album_id"],
                row["missing_fields"],
            ]
        )
    for shard, rows in shards.items():
        _write(
            output,
            f"tracks/{shard}.json",
            {
                "shard": shard,
                "columns": [
                    "track_id",
                    "title",
                    "artist_id",
                    "genre_ids",
                    "license_id",
                    "metadata_url",
                    "album_id",
                    "missing_fields",
                ],
                "tracks": rows,
            },
            files,
        )
    return {"licenses": licenses, "unvalidated_source_urls": unvalidated_urls}


def _artist_profiles(
    output: Path,
    artists: dict[int, dict[str, Any]],
    artist_tracks: dict[int | None, list[int]],
    artist_track_genres: dict[int | None, Counter[int]],
    files: dict[str, Any],
) -> None:
    search = []
    profiles: dict[int, dict[str, Any]] = defaultdict(dict)
    for artist_id in sorted(set(artists) | set(artist_tracks), key=lambda value: value or 0):
        artist = artists.get(artist_id)
        name = artist["name"] if artist else f"Missing artist record #{artist_id}"
        ids = artist_tracks.get(artist_id, [])
        status = "source_artist_record" if artist else "missing_source_artist_record"
        search.append([artist_id, name, len(ids), status])
        profiles[(artist_id or 0) % PROFILE_SHARDS][str(artist_id)] = {
            "artist_id": artist_id,
            "name": name,
            "status": status,
            "track_ids": ids,
            "track_genre_counts": [
                {"genre_id": genre, "track_count": count}
                for genre, count in sorted(
                    artist_track_genres[artist_id].items(), key=lambda item: (-item[1], item[0])
                )
            ],
        }
    for shard in range(PROFILE_SHARDS):
        _write(output, f"artists/{shard}.json", {"shard": shard, "artists": profiles[shard]}, files)
    # A single lazy artist index is explicitly bounded below 2 MB, outside shard limits.
    index = (
        canonical_json(
            {"artists": sorted(search, key=lambda row: (row[1].casefold(), row[0] or 0))}
        )
        + b"\n"
    )
    if len(index) >= MAX_ARTIST_INDEX_BYTES:
        raise ValueError("artist search index exceeds 2 MB")
    (output / "artist-index.json").write_bytes(index)
    digest, length = sha256_file(output / "artist-index.json")
    files["artist-index.json"] = {"sha256": digest, "bytes": length}


def _genre_connections(
    tracks: list[dict[str, Any]], genre_tracks: dict[int, list[int]]
) -> dict[int, list[dict[str, Any]]]:
    """Connect direct track annotations by overlap; never infer sonic similarity or parents."""
    shared: Counter[tuple[int, int]] = Counter()
    for track in tracks:
        shared.update(combinations(sorted(set(track["genre_ids"] or [])), 2))
    neighbors: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (left, right), count in shared.items():
        union = len(genre_tracks[left]) + len(genre_tracks[right]) - count
        for source, target in ((left, right), (right, left)):
            neighbors[source].append(
                {"genre_id": target, "shared_tracks": count, "overlap": count / union}
            )
    return {
        genre: sorted(
            rows, key=lambda row: (-row["overlap"], -row["shared_tracks"], row["genre_id"])
        )[:RELATED_GENRES]
        for genre, rows in neighbors.items()
    }


def _playback_binding(source: Path, output: Path, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    if source.name != "audio" or source.parent.resolve() != output.parent.resolve():
        raise ValueError("playback must be the adjacent audio directory")
    attached = validate_playback_export(source)
    native_artists = {row["track_id"]: row["artist_id"] for row in tracks}
    if any(
        native_artists.get(row["track_id"]) != row["artist_id"]
        for row in attached["tracks"].values()
    ):
        raise ValueError("playback track/artist identity differs from native catalog")
    digest, length = sha256_file(source / "manifest.json")
    return {
        "manifest": "../audio/manifest.json",
        "manifest_sha256": digest,
        "manifest_bytes": length,
        "clip_count": len(attached["tracks"]),
        "audio_bytes": attached["audio_bytes"],
        "scope": "separate local audio resource; excluded from metadata export byte total",
    }


def build_fma_static(  # noqa: PLR0913, C901 - explicit independent optional source packs.
    *,
    source: Path,
    projected: Path,
    output: Path,
    source_genres: Path | None = None,
    artist_context_root: Path | None = None,
    related_music: Path | None = None,
    playback: Path | None = None,
) -> dict[str, Any]:
    """Build a fresh independent catalog; source track labels never become artist genres."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace FMA static catalog")
    corpus_receipt, tables = verified_tables(source, projected)
    attached = (
        _playback_binding(playback, output, tables["tracks"]) if playback is not None else None
    )
    output.mkdir(parents=True)
    files: dict[str, Any] = {}
    artist_tracks: dict[int | None, list[int]] = defaultdict(list)
    artist_track_genres: dict[int | None, Counter[int]] = defaultdict(Counter)
    genre_tracks: dict[int, list[int]] = defaultdict(list)
    unannotated = []
    tracks = sorted(tables["tracks"], key=lambda row: row["track_id"])
    for track in tracks:
        artist_tracks[track["artist_id"]].append(track["track_id"])
        artist_track_genres[track["artist_id"]].update(set(track["genre_ids"] or []))
        for genre in sorted(set(track["genre_ids"] or [])):
            genre_tracks[genre].append(track["track_id"])
        if not track["genre_ids"]:
            unannotated.append(track["track_id"])
    artists = {row["artist_id"]: row for row in tables["artists"]}
    unknown = sorted(set(artist_tracks) - set(artists), key=lambda value: value or 0)
    _artist_profiles(output, artists, artist_tracks, artist_track_genres, files)
    connections = _genre_connections(tracks, genre_tracks)
    genre_rows = []
    for genre in sorted(
        tables["genres"], key=lambda row: (row["title"].casefold(), row["genre_id"])
    ):
        ids = genre_tracks.get(genre["genre_id"], [])
        genre_rows.append(
            {
                **genre,
                "track_count": len(ids),
                "connections": connections.get(genre["genre_id"], []),
            }
        )
        _cohort(output, f"genre-{genre['genre_id']}", ids, files)
    _cohort(output, "unannotated", unannotated, files)
    _cohort(output, "all", [row["track_id"] for row in tracks], files)
    track_context = _track_rows(output, tracks, files)
    catalog = {
        "revision": "fma-source-static-v1",
        "metadata_license": "CC-BY-4.0",
        "page_size": PAGE_SIZE,
        "profile_shards": PROFILE_SHARDS,
        "track_id_span": TRACK_ID_SPAN,
        "genres": genre_rows,
        "track_search": export_track_search(output, tracks, files),
        **track_context,
        "counts": {
            "raw_tracks": len(tracks),
            "source_artists": len(artists),
            "missing_artist_records": len(unknown),
            "tracks_with_missing_artist_records": sum(
                len(artist_tracks[artist_id]) for artist_id in unknown
            ),
            "genre_definitions": len(genre_rows),
            "observed_track_genres": len(genre_tracks),
            "unannotated_tracks": len(unannotated),
        },
        "corpus_receipt": "corpus-receipt.json",
    }
    if source_genres is not None:
        catalog["source_genres"] = export_source_genres(
            source_genres, output, files, foundation_root=artist_context_root
        )
    elif artist_context_root is not None:
        raise ValueError("artist context requires a source genre pack")
    if related_music is not None:
        catalog["related_music"] = export_related_music(
            related_music, output, files, {row["track_id"] for row in tracks}
        )
    if attached is not None:
        catalog["playback"] = attached
    _write(output, "catalog.json", catalog, files)
    _write(output, "corpus-receipt.json", corpus_receipt, files)
    static = Path(__file__).resolve().parents[1] / "static"
    for name in (
        "fma-catalog.html",
        "fma-catalog.css",
        "fma-catalog.js",
        "fma-genre-map.js",
        "source-genres.js",
        "fma-related-music.js",
        "fma-playback.js",
        "fma-genre-map.css",
    ):
        relative = "index.html" if name.endswith(".html") else name
        shutil.copyfile(static / name, output / relative)
        digest, length = sha256_file(output / relative)
        files[relative] = {"sha256": digest, "bytes": length}
    return _finish(
        output,
        files,
        catalog["counts"],
        corpus_receipt["source_receipt_sha256"],
        sha256_file(projected / "corpus-receipt.json")[0],
    )


def _finish(
    output: Path, files: dict[str, Any], counts: dict[str, int], source_sha: str, corpus_sha: str
) -> dict[str, Any]:
    manifest = zstandard.ZstdCompressor(level=9).compress(canonical_json(files))
    manifest_path = "files-manifest.json.zst"
    with (output / manifest_path).open("xb") as stream:
        stream.write(manifest)
    result = {
        "revision": "fma-source-static-v1",
        "scope": "optional_separate_CC_BY_native_catalog",
        "deploy_authorized": False,
        "audio_requested": False,
        "model_suggestions": False,
        "counts": counts,
        "source_receipt_sha256": source_sha,
        "corpus_receipt_sha256": corpus_sha,
        "files_manifest": {
            "path": manifest_path,
            "sha256": sha256_hex(manifest),
            "bytes": len(manifest),
            "file_count": len(files),
        },
        "total_bytes": sum(row["bytes"] for row in files.values()) + len(manifest),
        "artist_index_bytes": files["artist-index.json"]["bytes"],
        "largest_json_shard_bytes": max(
            binding["bytes"]
            for path, binding in files.items()
            if path.endswith(".json") and path != "artist-index.json"
        ),
    }
    if result["total_bytes"] + len(canonical_json(result)) + 1 > MAX_EXPORT_BYTES:
        raise ValueError("FMA catalog exceeds 40 MB")
    (output / "static-receipt.json").write_bytes(canonical_json(result) + b"\n")
    return result


def refresh_fma_static_display(*, source: Path, output: Path) -> dict[str, Any]:
    """Preserve a verified snapshot while refreshing its UI using hardlinked data."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace FMA static catalog")
    prior = json.loads((source / "static-receipt.json").read_bytes())
    if (
        prior["revision"] != "fma-source-static-v1"
        or prior["deploy_authorized"] is not False
        or prior["model_suggestions"] is not False
    ):
        raise ValueError("unsupported FMA static source")
    files = prior.get("files")
    if files is None:
        binding = prior["files_manifest"]
        if binding["path"] != "files-manifest.json.zst" or sha256_file(
            source / binding["path"]
        ) != (binding["sha256"], binding["bytes"]):
            raise ValueError("FMA file manifest binding mismatch")
        files = json.loads(
            zstandard.ZstdDecompressor().decompress((source / binding["path"]).read_bytes())
        )
    catalog = json.loads((source / "catalog.json").read_bytes())
    if catalog.get("playback"):
        audio = output.parent / "audio"
        validate_playback_export(audio)
        expected = catalog["playback"]
        if sha256_file(audio / "manifest.json") != (
            expected["manifest_sha256"],
            expected["manifest_bytes"],
        ):
            raise ValueError("refreshed catalog requires the same adjacent audio attachment")
    output.mkdir(parents=True)
    _clone_files(source, output, files)
    static = Path(__file__).resolve().parents[1] / "static"
    for name in (
        "fma-catalog.html",
        "fma-catalog.css",
        "fma-catalog.js",
        "fma-genre-map.js",
        "source-genres.js",
        "fma-related-music.js",
        "fma-playback.js",
        "fma-genre-map.css",
    ):
        relative = "index.html" if name.endswith(".html") else name
        temporary = output / (relative + ".tmp")
        shutil.copyfile(static / name, temporary)
        temporary.replace(output / relative)
        digest, length = sha256_file(output / relative)
        files[relative] = {"sha256": digest, "bytes": length}
    return _finish(
        output,
        files,
        prior["counts"],
        prior["source_receipt_sha256"],
        prior["corpus_receipt_sha256"],
    )


def _clone_files(source: Path, output: Path, files: dict[str, Any]) -> None:
    for relative, binding in files.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("unsafe FMA static manifest path")
        original = source / relative
        if sha256_file(original) != (binding["sha256"], binding["bytes"]):
            raise ValueError("FMA static input binding mismatch")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(original, destination)
        if sha256_file(destination) != (binding["sha256"], binding["bytes"]):
            raise ValueError("FMA static source changed during clone")
