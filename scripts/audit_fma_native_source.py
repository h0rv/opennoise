"""Independently replay FMA native CSV custody, projection roles and source quality."""

from __future__ import annotations

import argparse
import ast
import bz2
import csv
import hashlib
import io
import json
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import zstandard
from pydantic import TypeAdapter

from opennoise.common import canonical_json, sha256_file

if TYPE_CHECKING:
    from collections.abc import Iterator

INITIAL_ARTIST_SPLIT_SALT = "opennoise-fma-acoustic-artist-split-v1"


def native_rows(directory: Path, member: dict[str, object]) -> Iterator[dict[str, str]]:
    """Hash every decompressed native byte and compare native ZIP CRC and length."""
    length = 0
    crc = 0
    digest = hashlib.sha256()
    with (directory / str(member["payload_path"])).open("rb") as raw:
        raw.seek(int(str(member["payload_prefix_bytes"])))
        with bz2.BZ2File(raw) as decompressed:

            def lines() -> Iterator[str]:
                nonlocal length, crc
                for line in decompressed:
                    length += len(line)
                    crc = zlib.crc32(line, crc)
                    digest.update(line)
                    yield line.decode("utf-8")

            adapter = TypeAdapter(dict[str, str])
            for row in csv.DictReader(lines()):
                yield adapter.validate_python(row)
    if length != member["uncompressed_bytes"] or crc != member["crc32"]:
        raise ValueError("independent native CSV length or CRC differs")
    member["audited_uncompressed_sha256"] = digest.hexdigest()


def projection_rows(path: Path) -> Iterator[dict[str, object]]:
    """Stream compact projections without importing the acquisition implementation."""
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as stream,
        io.TextIOWrapper(stream, encoding="utf-8") as text,
    ):
        adapter = TypeAdapter(dict[str, object])
        for line in text:
            yield adapter.validate_json(line)


def native_id(value: str) -> int | None:
    """Use native positive ASCII decimal identities; names never bridge entities."""
    return int(value) if value.isascii() and value.isdecimal() and int(value) > 0 else None


def native_genres(value: str) -> list[int] | None:
    """Parse native genre ID observations, preserving missing and invalid lists."""
    try:
        rows = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    values = [native_id(str(row.get("genre_id", ""))) for row in rows]
    if any(value is None for value in values):
        return None
    return sorted({value for value in values if value is not None})


def initial_artist_fold(artist: int) -> int:
    """Replay the rejected initial split solely to demonstrate its album leakage."""
    digest = hashlib.sha256(f"{INITIAL_ARTIST_SPLIT_SALT}\0{artist}".encode()).digest()
    bucket = int.from_bytes(digest, "big") % 1000
    return 0 if bucket < 800 else 1 if bucket < 900 else 2  # noqa: PLR2004 - frozen original split.


def audit(source: Path, projection: Path) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915 - independent streaming audit.
    """Verify every projected native entity and report complete source denominators."""
    csv.field_size_limit(4_000_000)
    receipt = json.loads((source / "source-receipt.json").read_bytes())
    projected_receipt = json.loads((projection / "corpus-receipt.json").read_bytes())
    source_sha = sha256_file(source / "source-receipt.json")[0]
    contract = {
        "metadata_license": "CC-BY-4.0",
        "identity_namespace": "FMA_native_only",
        "musicbrainz_identity_bridge": "absent",
        "track_genre_role": "native_track_genre_metadata_not_artist_membership",
        "audio_downloaded": False,
    }
    if any(projected_receipt.get(key) != value for key, value in contract.items()):
        raise ValueError("native metadata license, identity, or evidence-role contract differs")
    if sha256_file(source / "README.md")[0] != receipt["readme_sha256"]:
        raise ValueError("official licensing README hash differs")
    if projected_receipt["source_receipt_sha256"] != source_sha:
        raise ValueError("projection source receipt differs")
    for row in receipt["ranges"]:
        digest, length = sha256_file(source / row["path"])
        if digest != row["sha256"] or length != row["bytes"]:
            raise ValueError("native captured range hash or length differs")
    artists: set[int] = set()
    genres: set[int] = set()
    albums: dict[int, set[int | None]] = defaultdict(set)
    album_tracks: Counter[int] = Counter()
    names: dict[str, set[int]] = defaultdict(set)
    statistics: Counter[str] = Counter()
    native_counts = {}
    source_hashes = {}
    observed_labels: set[int] = set()
    track_artist_ids: set[int] = set()
    unresolved_artist_ids: set[int] = set()
    for kind in ("artists", "genres", "tracks"):
        path = projection / f"{kind}.jsonl.zst"
        if sha256_file(path)[0] != projected_receipt["files"][kind]["sha256"]:
            raise ValueError("projection file hash differs")
        member = receipt["members"][f"fma_metadata/raw_{kind}.csv"]
        ids: set[int] = set()
        projected = projection_rows(path)
        for row in native_rows(source, member):
            item = next(projected, None)
            if item is None:
                raise ValueError("projection omits a raw native row")
            id_field = {"artists": "artist_id", "genres": "genre_id", "tracks": "track_id"}[kind]
            identity = native_id(row[id_field])
            if identity is None or identity in ids or item[id_field] != identity:
                raise ValueError("native identity duplicate, invalid, or projection drift")
            ids.add(identity)
            if kind == "artists":
                if item["name"] != (row["artist_name"] or None):
                    raise ValueError("artist name projection differs")
                names[row["artist_name"].casefold().strip()].add(identity)
            elif kind == "genres":
                if item["title"] != (row["genre_title"] or None) or item["parent_id"] != (
                    int(row["genre_parent_id"]) if row["genre_parent_id"].isdecimal() else None
                ):
                    raise ValueError("native genre title projection differs")
            else:
                artist = native_id(row["artist_id"])
                album = native_id(row["album_id"])
                labels = native_genres(row["track_genres"])
                expected = {
                    "artist_id": artist,
                    "album_id": album,
                    "album_title": row["album_title"] or None,
                    "genre_ids": labels,
                    "title": row["track_title"] or None,
                    "artist_name": row["artist_name"] or None,
                    "audio_license_title": row["license_title"] or None,
                    "audio_license_url": row["license_url"] or None,
                    "artist_id_status": "source_known"
                    if artist in artists
                    else "source_missing"
                    if artist is None
                    else "source_unresolved",
                }
                if any(item.get(key) != value for key, value in expected.items()):
                    raise ValueError(
                        "track identity, album, genre, or resolution projection differs"
                    )
                observed_labels.update(labels or [])
                if artist is not None:
                    track_artist_ids.add(artist)
                    if artist not in artists:
                        unresolved_artist_ids.add(artist)
                statistics[str(expected["artist_id_status"]) + "_positive_pairs"] += len(
                    labels or []
                )
                statistics[str(expected["artist_id_status"])] += 1
                statistics["positive_track_genre_pairs"] += len(labels or [])
                statistics["tracks_without_positive_genre"] += not labels
                statistics["empty_or_invalid_genre_list"] += labels is None
                statistics["unknown_genre_pairs"] += len(set(labels or []) - genres)
                statistics["missing_or_invalid_album_id"] += album is None
                if album is not None:
                    albums[album].add(artist)
                    album_tracks[album] += 1
        if next(projected, None) is not None:
            raise ValueError("projection adds rows absent from native source")
        if len(ids) != projected_receipt["files"][kind]["rows"]:
            raise ValueError("projection row denominator differs")
        source_hashes[kind] = member["audited_uncompressed_sha256"]
        if source_hashes[kind] != projected_receipt["files"][kind]["uncompressed_source_sha256"]:
            raise ValueError("native decompressed SHA-256 differs")
        native_counts[kind] = len(ids)
        if kind == "artists":
            artists = ids
        elif kind == "genres":
            genres = ids
    multi = {album: values for album, values in albums.items() if len(values) > 1}
    crossing = {
        album
        for album, values in multi.items()
        if len({initial_artist_fold(value) for value in values if value in artists}) > 1
    }
    return {
        "revision": "independent-fma-native-source-audit-v1",
        "source_receipt_sha256": source_sha,
        "projection_receipt_sha256": sha256_file(projection / "corpus-receipt.json")[0],
        "raw_rows": native_counts,
        "quality": statistics,
        "raw_csv_sha256": source_hashes,
        "range_files_verified": len(receipt["ranges"]),
        "projection_native_rows_verified": sum(native_counts.values()),
        "native_duplicate_ids": 0,
        "genre_ids_observed_on_tracks": len(observed_labels),
        "taxonomy_ids_without_track_observations": len(genres - observed_labels),
        "distinct_track_primary_artist_ids": len(track_artist_ids),
        "distinct_unresolved_track_artist_ids": len(unresolved_artist_ids),
        "artist_records_without_track_observations": len(artists - track_artist_ids),
        "native_album_count": len(albums),
        "multi_primary_artist_albums": len(multi),
        "tracks_on_multi_primary_artist_albums": sum(album_tracks[a] for a in multi),
        "albums_crossing_initial_artist_fold": len(crossing),
        "tracks_on_initial_crossfold_albums": sum(album_tracks[a] for a in crossing),
        "normalized_artist_names_shared_by_ids": sum(len(v) > 1 for v in names.values()),
        "native_track_genre_is_artist_fact": False,
        "musicbrainz_identity_bridge": "absent",
        "independent_musical_relevance": "not_measured",
        "model_metrics_read": False,
        "code_sha256": sha256_file(Path(__file__))[0],
    }


def main() -> None:
    """Write fresh independent evidence without modifying source or projection artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--projection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.source, args.projection)
    with args.output.open("xb") as stream:
        stream.write(canonical_json(result) + b"\n")
    print(json.dumps(result, indent=2))  # noqa: T201 - audit receipt.


if __name__ == "__main__":
    main()
