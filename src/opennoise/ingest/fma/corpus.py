"""Bounded ranged FMA ZIP custody and streaming native metadata projection."""

from __future__ import annotations

import ast
import bz2
import csv
import hashlib
import io
import json
import struct
import zlib
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from _typeshed import WriteableBuffer

import httpx
import zstandard

from opennoise.common import canonical_json, sha256_file

ARCHIVE_URL = "https://os.unil.cloud.switch.ch/fma/fma_metadata.zip"
README_URL = "https://raw.githubusercontent.com/mdeff/fma/master/README.md"
README_SHA256 = "54148723ff06c19374c368499f1e97afb3d10f58646d20a221e4d9c7ab63fac9"
ARCHIVE_BYTES = 358412441
ETAG = '"64dd28f582705ace094de08c63643be6-69"'
TAIL_BYTES = 65557
ZIP_BZIP2 = 12
ZIP64_SENTINEL = 0xFFFFFFFF
LOCAL_HEADER_BYTES = 30
MAX_EXTRA_BYTES = 4096
MAX_UNCOMPRESSED_BYTES = 150_000_000
MAX_README_BYTES = 100_000
EXPECTED_RANGES = 7
MAX_GENRE_LITERAL_BYTES = 50_000
MAX_PROJECTION_BYTES = 30_000_000
MAX_NATIVE_BYTES = 15_000_000
MEMBERS = tuple(f"fma_metadata/raw_{kind}.csv" for kind in ("genres", "artists", "tracks"))


def central_members(tail: bytes) -> dict[str, dict[str, Any]]:
    """Read the ZIP directory without fetching or trusting excluded payloads."""
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or end + 22 > len(tail):
        raise ValueError("missing ZIP end directory")
    signature, disk, directory_disk, disk_count, total, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, end
    )
    if (
        signature != b"PK\x05\x06"
        or disk
        or directory_disk
        or disk_count != total
        or end + 22 + comment != len(tail)
    ):
        raise ValueError("unsupported ZIP directory")
    start = offset - (ARCHIVE_BYTES - len(tail))
    if start < 0 or start + size != end:
        raise ValueError("ZIP directory range mismatch")
    cursor = start
    members: dict[str, dict[str, Any]] = {}
    for _ in range(total):
        if cursor + 46 > end:
            raise ValueError("truncated ZIP directory")
        fields = struct.unpack_from("<4s6H3L5H2L", tail, cursor)
        if fields[0] != b"PK\x01\x02":
            raise ValueError("invalid ZIP directory signature")
        flags, method, crc, compressed, uncompressed = (
            fields[3],
            fields[4],
            fields[7],
            fields[8],
            fields[9],
        )
        name_size, extra_size, comment_size, disk_start = fields[10:14]
        name = tail[cursor + 46 : cursor + 46 + name_size].decode("utf-8")
        if (
            name in members
            or disk_start
            or flags & 9
            or ZIP64_SENTINEL in (compressed, uncompressed)
        ):
            raise ValueError("unsupported ZIP member")
        members[name] = {
            "name": name,
            "flags": flags,
            "compression": method,
            "crc32": crc,
            "compressed_bytes": compressed,
            "uncompressed_bytes": uncompressed,
            "header_offset": fields[16],
        }
        cursor += 46 + name_size + extra_size + comment_size
    if cursor != end or not set(MEMBERS).issubset(members):
        raise ValueError("ZIP directory membership mismatch")
    selected = {name: members[name] for name in MEMBERS}
    if any(
        row["compression"] != ZIP_BZIP2 or row["uncompressed_bytes"] > MAX_UNCOMPRESSED_BYTES
        for row in selected.values()
    ) or sum(
        row["compressed_bytes"] for row in selected.values()
    ) > MAX_NATIVE_BYTES - TAIL_BYTES - MAX_README_BYTES - len(MEMBERS) * (
        LOCAL_HEADER_BYTES + MAX_EXTRA_BYTES + 100
    ):
        raise ValueError("unsupported or oversized source members")
    return selected


def local_header(header: bytes, member: dict[str, Any]) -> tuple[int, int]:
    """Require the local header to agree with directory facts before reading data."""
    if len(header) != LOCAL_HEADER_BYTES:
        raise ValueError("truncated local ZIP header")
    fields = struct.unpack("<4s5H3L2H", header)
    if fields[0] != b"PK\x03\x04" or (fields[2], fields[3], fields[6], fields[7], fields[8]) != (
        member["flags"],
        12,
        member["crc32"],
        member["compressed_bytes"],
        member["uncompressed_bytes"],
    ):
        raise ValueError("local ZIP facts differ from directory")
    name_size, extra_size = fields[9:11]
    if name_size != len(member["name"].encode()) or extra_size > MAX_EXTRA_BYTES:
        raise ValueError("unsupported local ZIP name or extra")
    return name_size, extra_size


def check_range(status: int, headers: Mapping[str, str], start: int, end: int) -> None:
    """Reject silent full downloads, changed objects, encoding, and truncated ranges."""
    expected = f"bytes {start}-{end}/{ARCHIVE_BYTES}"
    if (
        status != HTTPStatus.PARTIAL_CONTENT
        or headers.get("content-range") != expected
        or headers.get("etag") != ETAG
        or headers.get("content-length") != str(end - start + 1)
        or headers.get("content-encoding", "identity") != "identity"
    ):
        raise ValueError("HTTP range, length, encoding, or ETag mismatch")


def capture_range(
    client: httpx.Client, directory: Path, name: str, start: int, end: int
) -> dict[str, Any]:
    """Capture one exact bounded native archive range into an exclusive file."""
    if not 0 <= start <= end < ARCHIVE_BYTES or end - start + 1 > MAX_NATIVE_BYTES:
        raise ValueError("range exceeds bounds")
    with client.stream(
        "GET",
        ARCHIVE_URL,
        headers={"Range": f"bytes={start}-{end}", "If-Match": ETAG, "Accept-Encoding": "identity"},
    ) as response:
        check_range(response.status_code, response.headers, start, end)
        length = 0
        with (directory / name).open("xb") as stream:
            for block in response.iter_raw():
                length += len(block)
                if length > end - start + 1:
                    raise ValueError("oversized HTTP range")
                stream.write(block)
        if length != end - start + 1:
            raise ValueError("truncated HTTP range")
        return {
            "url": ARCHIVE_URL,
            "path": name,
            "start": start,
            "end": end,
            "status": response.status_code,
            "headers": {
                key: response.headers[key] for key in ("content-range", "content-length", "etag")
            },
            "sha256": sha256_file(directory / name)[0],
            "bytes": length,
        }


def _capture_readme(client: httpx.Client, directory: Path) -> dict[str, Any]:
    with client.stream("GET", README_URL, headers={"Accept-Encoding": "identity"}) as response:
        if (
            response.status_code != HTTPStatus.OK
            or response.headers.get("content-encoding", "identity") != "identity"
        ):
            raise ValueError("invalid official README HTTP response")
        length = 0
        with (directory / "README.md").open("xb") as stream:
            for block in response.iter_raw():
                length += len(block)
                if length > MAX_README_BYTES:
                    raise ValueError("official README exceeds bounded capture")
                stream.write(block)
        if sha256_file(directory / "README.md")[0] != README_SHA256:
            raise ValueError("official FMA license README hash mismatch")
        return {
            "url": README_URL,
            "status": response.status_code,
            "bytes": length,
            "sha256": README_SHA256,
            "headers": dict(response.headers),
        }


def capture_sources(directory: Path) -> dict[str, Any]:
    """Capture only three permitted compressed CSV payloads and licensing custody."""
    directory.mkdir(parents=True, exist_ok=False)
    with httpx.Client(
        timeout=60, follow_redirects=False, headers={"User-Agent": "OpenNoise-FMA-metadata/1.0"}
    ) as client:
        readme = _capture_readme(client, directory)
        ranges = [
            capture_range(
                client,
                directory,
                "central-directory.range",
                ARCHIVE_BYTES - TAIL_BYTES,
                ARCHIVE_BYTES - 1,
            )
        ]
        members = central_members((directory / "central-directory.range").read_bytes())
        for index, member in enumerate(members.values()):
            offset = member["header_offset"]
            ranges.append(
                capture_range(client, directory, f"{index}-local-header.range", offset, offset + 29)
            )
            name_size, extra_size = local_header(
                (directory / ranges[-1]["path"]).read_bytes(), member
            )
            ranges.append(
                capture_range(
                    client,
                    directory,
                    f"{index}-compressed.range",
                    offset + 30,
                    offset + 29 + name_size + extra_size + member["compressed_bytes"],
                )
            )
            member.update(
                header_path=ranges[-2]["path"],
                payload_path=ranges[-1]["path"],
                payload_prefix_bytes=name_size + extra_size,
            )
        receipt = {
            "revision": "fma-ranged-native-metadata-v1",
            "captured_at": datetime.now(UTC).isoformat(),
            "archive_url": ARCHIVE_URL,
            "archive_bytes": ARCHIVE_BYTES,
            "archive_etag": ETAG,
            "full_archive_sha1_verified": False,
            "readme_url": README_URL,
            "readme_http": readme,
            "readme_sha256": README_SHA256,
            "metadata_license": "CC-BY-4.0",
            "audio_downloaded": False,
            "excluded": ["EchoNest", "pickle", "audio", "features.csv"],
            "native_http_bytes": sum(row["bytes"] for row in ranges) + readme["bytes"],
            "ranges": ranges,
            "members": members,
        }
        if receipt["native_http_bytes"] > MAX_NATIVE_BYTES:
            raise ValueError("native transfer budget exceeded")
        (directory / "source-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
        return receipt


class CheckedCSV(io.RawIOBase):
    """Verify every decompressed byte without materializing the raw CSV."""

    def __init__(self, source: bz2.BZ2File, member: dict[str, Any]) -> None:
        """Attach decompressor and immutable expected native ZIP facts."""
        self.source = source
        self.member = member
        self.length = 0
        self.crc = 0
        self.sha256 = hashlib.sha256()
        self.complete = False

    @override
    def close(self) -> None:
        """Close the decompressor when the text reader is closed."""
        self.source.close()
        super().close()

    @override
    def readable(self) -> bool:
        """Permit buffered text decoding."""
        return True

    @override
    def readinto(self, buffer: WriteableBuffer) -> int:
        """Bound decompression and verify CRC at EOF."""
        view = memoryview(buffer)
        block = self.source.read(len(view))
        self.length += len(block)
        self.crc = zlib.crc32(block, self.crc)
        self.sha256.update(block)
        if self.length > self.member["uncompressed_bytes"]:
            raise ValueError("uncompressed size exceeds native ZIP bound")
        if not block:
            if self.length != self.member["uncompressed_bytes"] or self.crc != self.member["crc32"]:
                raise ValueError("native ZIP CRC or byte count mismatch")
            self.complete = True
        view[: len(block)] = block
        return len(block)


def source_rows(
    directory: Path, member: dict[str, Any]
) -> tuple[csv.DictReader[str], CheckedCSV, tuple[io.TextIOWrapper, io.BufferedReader]]:
    """Open a bounded source member with local filename validation and CRC checking."""
    raw = (directory / member["payload_path"]).open("rb")
    name_size, extra_size = local_header((directory / member["header_path"]).read_bytes(), member)
    if (
        raw.read(name_size) != member["name"].encode()
        or member["payload_prefix_bytes"] != name_size + extra_size
    ):
        raw.close()
        raise ValueError("local filename or payload offset mismatch")
    raw.seek(name_size + extra_size)
    checked = CheckedCSV(bz2.BZ2File(raw), member)
    text = io.TextIOWrapper(io.BufferedReader(checked), encoding="utf-8", newline="")
    csv.field_size_limit(4_000_000)
    return csv.DictReader(text), checked, (text, raw)


def verify_sources(directory: Path) -> dict[str, Any]:
    """Replay native range receipts and central facts before any projection."""
    receipt = json.loads((directory / "source-receipt.json").read_bytes())
    if (
        receipt["archive_url"] != ARCHIVE_URL
        or receipt["archive_bytes"] != ARCHIVE_BYTES
        or receipt["archive_etag"] != ETAG
        or receipt["readme_sha256"] != README_SHA256
        or sha256_file(directory / "README.md")[0] != README_SHA256
    ):
        raise ValueError("source or licensing custody mismatch")
    if len(receipt["ranges"]) != EXPECTED_RANGES or set(receipt["members"]) != set(MEMBERS):
        raise ValueError("unexpected source capture inventory")
    expected_paths = {
        "central-directory.range",
        *(f"{index}-{kind}.range" for index in range(3) for kind in ("local-header", "compressed")),
    }
    if {row["path"] for row in receipt["ranges"]} != expected_paths:
        raise ValueError("unexpected range paths")
    for row in receipt["ranges"]:
        check_range(row["status"], row["headers"], row["start"], row["end"])
        digest, length = sha256_file(directory / row["path"])
        if (
            row["url"] != ARCHIVE_URL
            or digest != row["sha256"]
            or length != row["bytes"]
            or length != row["end"] - row["start"] + 1
        ):
            raise ValueError("range digest or captured bytes mismatch")
    _verify_member_ranges(directory, receipt)
    if (
        sum(row["bytes"] for row in receipt["ranges"]) + (directory / "README.md").stat().st_size
        != receipt["native_http_bytes"]
        or receipt["native_http_bytes"] > MAX_NATIVE_BYTES
    ):
        raise ValueError("native transfer budget mismatch")
    return receipt


def _verify_member_ranges(directory: Path, receipt: dict[str, Any]) -> None:
    selected = central_members((directory / "central-directory.range").read_bytes())
    ranges = {row["path"]: row for row in receipt["ranges"]}
    tail = ranges["central-directory.range"]
    if (tail["start"], tail["end"]) != (ARCHIVE_BYTES - TAIL_BYTES, ARCHIVE_BYTES - 1):
        raise ValueError("central range differs from archive tail")
    for index, (name, central) in enumerate(selected.items()):
        member = receipt["members"][name]
        if (
            any(member[key] != value for key, value in central.items())
            or member["header_path"] != f"{index}-local-header.range"
            or member["payload_path"] != f"{index}-compressed.range"
        ):
            raise ValueError("member receipt differs from ZIP central directory")
        sizes = local_header((directory / member["header_path"]).read_bytes(), member)
        header, payload = ranges[member["header_path"]], ranges[member["payload_path"]]
        offset, prefix = member["header_offset"], sum(sizes)
        if (
            header["start"],
            header["end"],
            payload["start"],
            payload["end"],
            member["payload_prefix_bytes"],
        ) != (
            offset,
            offset + 29,
            offset + 30,
            offset + 29 + prefix + member["compressed_bytes"],
            prefix,
        ):
            raise ValueError("captured member range differs from native ZIP offsets")


def _native_id(value: str | None, *, allow_zero: bool = False) -> int | None:
    if value and value.isascii() and value.isdecimal():
        number = int(value)
        if number > 0 or (allow_zero and number == 0):
            return number
    return None


def _genre_ids(value: str) -> list[int] | None:
    if not value or len(value) > MAX_GENRE_LITERAL_BYTES:
        return None
    try:
        rows = ast.literal_eval(value)
    except (ValueError, SyntaxError, RecursionError):
        return None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    values = [_native_id(str(row.get("genre_id", ""))) for row in rows]
    if any(value is None for value in values):
        return None
    return sorted({value for value in values if value is not None})


def project_row(kind: str, row: dict[str, str]) -> dict[str, Any]:
    """Project source IDs without entity bridging, artist genre inference, or media URLs."""
    fields = {
        "genres": {"genre_id": "genre_id", "title": "genre_title", "parent_id": "genre_parent_id"},
        "artists": {"artist_id": "artist_id", "name": "artist_name"},
        "tracks": {
            "track_id": "track_id",
            "title": "track_title",
            "artist_id": "artist_id",
            "artist_name": "artist_name",
            "album_id": "album_id",
            "album_title": "album_title",
            "audio_license_title": "license_title",
            "audio_license_url": "license_url",
            "source_metadata_url": "track_url",
        },
    }[kind]
    result = {}
    missing = {}
    for target, source in fields.items():
        value = row.get(source, "")
        result[target] = (
            _native_id(value, allow_zero=target == "parent_id")
            if target.endswith("_id")
            else value or None
        )
        if result[target] is None:
            missing[target] = "source_empty" if not value else "source_invalid_native_id"
    if kind == "tracks":
        result["genre_ids"] = _genre_ids(row.get("track_genres", ""))
        if result["genre_ids"] is None:
            missing["genre_ids"] = (
                "source_empty" if not row.get("track_genres") else "source_unparseable_genre_list"
            )
    if result[f"{kind[:-1] if kind != 'genres' else 'genre'}_id"] is None:
        raise ValueError("source entity lacks valid native ID")
    result["missing_fields"] = missing
    return result


def _project_member(
    directory: Path, output: Path, member: dict[str, Any], kind: str, known: dict[str, set[int]]
) -> dict[str, Any]:
    rows, checked, handles = source_rows(directory, member)
    ids: set[int] = set()
    missing_counts: dict[str, int] = {}
    unmapped = 0
    path = output / f"{kind}.jsonl.zst"
    required = {
        "genres": {"genre_id", "genre_parent_id", "genre_title"},
        "artists": {"artist_id", "artist_name"},
        "tracks": {
            "track_id",
            "artist_id",
            "track_title",
            "track_genres",
            "license_title",
            "license_url",
        },
    }[kind]
    if not required.issubset(rows.fieldnames or []):
        raise ValueError("source CSV required columns missing")
    try:
        with (
            path.open("xb") as raw,
            zstandard.ZstdCompressor(level=9).stream_writer(raw) as compressed,
        ):
            for row in rows:
                projected = project_row(kind, row)
                native_id = projected[
                    {"genres": "genre_id", "artists": "artist_id", "tracks": "track_id"}[kind]
                ]
                if native_id in ids:
                    raise ValueError("duplicate native source identity")
                ids.add(native_id)
                if kind == "tracks":
                    projected["artist_id_status"] = (
                        "source_known"
                        if projected["artist_id"] in known["artists"]
                        else "source_missing"
                        if projected["artist_id"] is None
                        else "source_unresolved"
                    )
                    projected["unresolved_genre_ids"] = [
                        value
                        for value in projected["genre_ids"] or []
                        if value not in known["genres"]
                    ]
                    unmapped += projected["artist_id_status"] != "source_known"
                for field in projected["missing_fields"]:
                    missing_counts[field] = missing_counts.get(field, 0) + 1
                compressed.write(canonical_json(projected) + b"\n")
        if not checked.complete:
            raise ValueError("source stream did not reach verified EOF")
    finally:
        for handle in handles:
            handle.close()
    known[kind] = ids
    return {
        "path": path.name,
        "rows": len(ids),
        "sha256": sha256_file(path)[0],
        "bytes": path.stat().st_size,
        "uncompressed_source_bytes": checked.length,
        "uncompressed_source_sha256": checked.sha256.hexdigest(),
        "native_zip_crc32_verified": f"{checked.crc:08x}",
        "missing_fields": missing_counts,
        "unresolved_track_artists": unmapped,
    }


def project_corpus(directory: Path, output: Path) -> dict[str, Any]:
    """Build fresh compact CC BY metadata from verified compressed captures offline."""
    receipt = verify_sources(directory)
    output.mkdir(parents=True, exist_ok=False)
    known: dict[str, set[int]] = {}
    projections = {}
    for name, member in receipt["members"].items():
        kind = name.removeprefix("fma_metadata/raw_").removesuffix(".csv")
        projections[kind] = _project_member(directory, output, member, kind, known)
    result = {
        "revision": "fma-native-corpus-v1",
        "source_receipt_sha256": sha256_file(directory / "source-receipt.json")[0],
        "metadata_license": "CC-BY-4.0",
        "attribution": (
            "Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst, Xavier Bresson: "
            "FMA: A Dataset For Music Analysis, ISMIR 2017, https://github.com/mdeff/fma"
        ),
        "cohort_scope": "raw_API_snapshot_not_cleaned_audio_subset",
        "readme_sha256": README_SHA256,
        "audio_license_scope": "per_track_source_declaration_only_not_metadata_license",
        "audio_downloaded": False,
        "playback_availability": "not_verified",
        "identity_namespace": "FMA_native_only",
        "musicbrainz_identity_bridge": "absent",
        "track_genre_role": "native_track_genre_metadata_not_artist_membership",
        "genre_parent_role": "native_source_taxonomy",
        "source_era": "FMA_2017_snapshot",
        "excluded": receipt["excluded"],
        "files": projections,
    }
    if sum(row["bytes"] for row in projections.values()) > MAX_PROJECTION_BYTES:
        raise ValueError("projected corpus exceeds storage budget")
    (output / "corpus-receipt.json").write_bytes(canonical_json(result) + b"\n")
    return result
