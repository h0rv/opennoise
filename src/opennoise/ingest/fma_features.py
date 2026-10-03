"""Stream native FMA Librosa features with bounded ZIP custody and partial projection."""

from __future__ import annotations

import bz2
import csv
import hashlib
import io
import json
import math
import shutil
import struct
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from opennoise.common import canonical_json, sha256_file
from opennoise.ingest.fma.corpus import (
    ARCHIVE_BYTES,
    ARCHIVE_URL,
    ETAG,
    README_SHA256,
    CheckedCSV,
    check_range,
    local_header,
    verify_sources,
)

if TYPE_CHECKING:
    from pathlib import Path

REVISION = "fma-native-librosa-feature-projection-v1"
MEMBER_NAME = "fma_metadata/features.csv"
MAX_SOURCE_BYTES = 310_000_000
MAX_PROJECTION_BYTES = 20_000_000
MAX_ROWS = 110_000
CHANNELS = {
    "mfcc": 20,
    "chroma_cens": 12,
    "spectral_contrast": 7,
    "rmse": 1,
    "spectral_centroid": 1,
    "spectral_bandwidth": 1,
    "spectral_rolloff": 1,
    "zero_crossing_rate": 1,
}
SELECTED_COLUMNS = tuple(
    ("zcr" if name == "zero_crossing_rate" else name, "mean", number)
    for name, count in sorted(CHANNELS.items())
    for number in range(1, count + 1)
)
_FLOAT_ROW = struct.Struct("<" + "f" * len(SELECTED_COLUMNS))
_TRACK_ID = struct.Struct("<I")
_HEADER_LEVELS = 3


def selected_feature_positions(
    headers: list[list[str]],
) -> tuple[list[tuple[str, str, int]], list[int]]:
    """Map declared mean channels to native positions, including the explicit zcr alias."""
    if (
        len(headers) != _HEADER_LEVELS
        or [row[0] for row in headers] != ["feature", "statistics", "number"]
        or len({len(row) for row in headers}) != 1
    ):
        raise ValueError("native feature CSV multilevel headers differ")
    columns = [
        (headers[0][i], headers[1][i], int(headers[2][i])) for i in range(1, len(headers[0]))
    ]
    if len(set(columns)) != len(columns) or not set(SELECTED_COLUMNS).issubset(columns):
        raise ValueError("required native Librosa columns missing or duplicated")
    return columns, [columns.index(column) + 1 for column in SELECTED_COLUMNS]


def feature_member(tail: bytes) -> dict[str, Any]:
    """Locate exactly the permitted feature member in the preserved native directory."""
    end = tail.rfind(b"PK\x05\x06")
    if end < 0 or end + 22 != len(tail):
        raise ValueError("feature ZIP end directory missing or unsupported")
    _, disk, directory_disk, disk_count, total, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, end
    )
    cursor = offset - (ARCHIVE_BYTES - len(tail))
    if (
        disk
        or directory_disk
        or disk_count != total
        or comment
        or cursor < 0
        or cursor + size != end
    ):
        raise ValueError("feature ZIP central directory bounds differ")
    selected = []
    for _ in range(total):
        fields = struct.unpack_from("<4s6H3L5H2L", tail, cursor)
        name_size, extra_size, comment_size, disk_start = fields[10:14]
        if fields[0] != b"PK\x01\x02" or disk_start:
            raise ValueError("unsupported feature ZIP central entry")
        name = tail[cursor + 46 : cursor + 46 + name_size].decode("utf-8")
        if name == MEMBER_NAME:
            selected.append(
                {
                    "name": name,
                    "flags": fields[3],
                    "compression": fields[4],
                    "crc32": fields[7],
                    "compressed_bytes": fields[8],
                    "uncompressed_bytes": fields[9],
                    "header_offset": fields[16],
                }
            )
        cursor += 46 + name_size + extra_size + comment_size
        if cursor > end:
            raise ValueError("feature ZIP directory truncated")
    if cursor != end or len(selected) != 1:
        raise ValueError("permitted feature ZIP member not unique")
    member = selected[0]
    if (
        member["flags"],
        member["compression"],
        member["compressed_bytes"],
        member["uncompressed_bytes"],
        member["crc32"],
    ) != (0, 12, 293323100, 951117185, 0xE8EB7A19):
        raise ValueError("native feature member facts differ from frozen archive")
    return member


def _capture_range(
    client: httpx.Client, directory: Path, filename: str, start: int, end: int
) -> dict[str, Any]:
    if not 0 <= start <= end < ARCHIVE_BYTES or end - start + 1 > MAX_SOURCE_BYTES:
        raise ValueError("feature HTTP range exceeds declared budget")
    digest, length = hashlib.sha256(), 0
    with client.stream(
        "GET",
        ARCHIVE_URL,
        headers={"Range": f"bytes={start}-{end}", "If-Match": ETAG, "Accept-Encoding": "identity"},
    ) as response:
        check_range(response.status_code, response.headers, start, end)
        with (directory / filename).open("xb") as stream:
            for block in response.iter_raw(chunk_size=1_000_000):
                length += len(block)
                if length > end - start + 1:
                    raise ValueError("feature HTTP body exceeds native range")
                stream.write(block)
                digest.update(block)
                if length % 16_000_000 == 0:
                    sys.stderr.write(f"Retained native FMA feature range: {length} bytes\n")
        if length != end - start + 1:
            raise ValueError("feature HTTP body truncated")
        return {
            "path": filename,
            "url": ARCHIVE_URL,
            "start": start,
            "end": end,
            "status": response.status_code,
            "headers": {
                key: response.headers[key] for key in ("content-range", "content-length", "etag")
            },
            "bytes": length,
            "sha256": digest.hexdigest(),
        }


def capture_features(metadata_source: Path, output: Path, declaration: Path) -> dict[str, Any]:
    """Reuse verified metadata license/directory custody and capture no audio or EchoNest."""
    metadata = verify_sources(metadata_source)
    declaration_body = declaration.read_bytes()
    declared = json.loads(declaration_body)
    if (
        declared["projection"]["channels"] != CHANNELS
        or declared["source"]["readme_sha256"] != README_SHA256
        or metadata["readme_sha256"] != README_SHA256
        or sha256_file(metadata_source / "source-receipt.json")[0]
        != declared["source"]["metadata_source_receipt_sha256"]
    ):
        raise ValueError("feature acquisition differs from sealed declaration")
    tail = (metadata_source / "central-directory.range").read_bytes()
    member = feature_member(tail)
    if (
        shutil.disk_usage(output.parent).free
        < MAX_SOURCE_BYTES + MAX_PROJECTION_BYTES + 100_000_000
    ):
        raise ValueError("insufficient free space for bounded immutable feature custody")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("README.md", "central-directory.range"):
        with (output / name).open("xb") as stream:
            stream.write((metadata_source / name).read_bytes())
    with (output / "declaration.json").open("xb") as stream:
        stream.write(declaration_body)
    with httpx.Client(
        timeout=120,
        follow_redirects=False,
        headers={"User-Agent": "OpenNoise-FMA-Librosa-metadata/1.0"},
    ) as client:
        offset = member["header_offset"]
        header = _capture_range(client, output, "feature-local-header.range", offset, offset + 29)
        name_size, extra_size = local_header((output / header["path"]).read_bytes(), member)
        payload = _capture_range(
            client,
            output,
            "feature-compressed.range",
            offset + 30,
            offset + 29 + name_size + extra_size + member["compressed_bytes"],
        )
    member.update(
        header_path=header["path"],
        payload_path=payload["path"],
        payload_prefix_bytes=name_size + extra_size,
    )
    receipt = {
        "revision": REVISION,
        "captured_at": datetime.now(UTC).isoformat(),
        "archive_url": ARCHIVE_URL,
        "archive_etag": ETAG,
        "archive_bytes": ARCHIVE_BYTES,
        "full_archive_sha1_verified": False,
        "license": "CC-BY-4.0",
        "attribution": (
            "Defferrard, Benzi, Vandergheynst and Bresson, "
            "FMA: A Dataset For Music Analysis, ISMIR 2017, https://github.com/mdeff/fma"
        ),
        "readme_sha256": README_SHA256,
        "central_directory_sha256": hashlib.sha256(tail).hexdigest(),
        "metadata_source_receipt_sha256": sha256_file(metadata_source / "source-receipt.json")[0],
        "declaration_sha256": hashlib.sha256(declaration_body).hexdigest(),
        "metadata_features_license_basis": (
            "Official README distributes all metadata/features together, lists features.csv as "
            "common Librosa features, and declares metadata CC BY 4.0; "
            "EchoNest is separately named and excluded."
        ),
        "audio_downloaded": False,
        "excluded": ["EchoNest", "pickle", "audio"],
        "native_http_bytes": header["bytes"] + payload["bytes"],
        "ranges": [header, payload],
        "member": member,
    }
    (output / "source-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def verify_feature_source(directory: Path) -> dict[str, Any]:
    """Verify every retained range and native member binding before streaming projection."""
    receipt = json.loads((directory / "source-receipt.json").read_bytes())
    tail = (directory / "central-directory.range").read_bytes()
    central = feature_member(tail)
    if (
        receipt["revision"] != REVISION
        or receipt["license"] != "CC-BY-4.0"
        or receipt["archive_etag"] != ETAG
        or receipt["archive_url"] != ARCHIVE_URL
        or receipt["archive_bytes"] != ARCHIVE_BYTES
        or receipt["audio_downloaded"] is not False
        or receipt["full_archive_sha1_verified"] is not False
        or sha256_file(directory / "README.md")[0] != README_SHA256
        or hashlib.sha256(tail).hexdigest() != receipt["central_directory_sha256"]
        or sha256_file(directory / "declaration.json")[0] != receipt["declaration_sha256"]
    ):
        raise ValueError("feature source licensing or custody boundary differs")
    member = receipt["member"]
    if any(member[key] != value for key, value in central.items()) or {
        row["path"] for row in receipt["ranges"]
    } != {"feature-local-header.range", "feature-compressed.range"}:
        raise ValueError("feature member or range inventory differs")
    for row in receipt["ranges"]:
        path = directory / row["path"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("feature source must be an immutable regular file")
        check_range(row["status"], row["headers"], row["start"], row["end"])
        digest, length = sha256_file(path)
        if (
            row["url"] != ARCHIVE_URL
            or digest != row["sha256"]
            or length != row["bytes"]
            or length != row["end"] - row["start"] + 1
        ):
            raise ValueError("feature native range byte binding differs")
    ranges = {row["path"]: row for row in receipt["ranges"]}
    header, payload = ranges["feature-local-header.range"], ranges["feature-compressed.range"]
    prefix = sum(local_header((directory / header["path"]).read_bytes(), member))
    offset = member["header_offset"]
    if (
        (
            header["start"],
            header["end"],
            payload["start"],
            payload["end"],
            member["payload_prefix_bytes"],
        )
        != (
            offset,
            offset + 29,
            offset + 30,
            offset + 29 + prefix + member["compressed_bytes"],
            prefix,
        )
        or header["bytes"] + payload["bytes"] != receipt["native_http_bytes"]
        or receipt["native_http_bytes"] > MAX_SOURCE_BYTES
    ):
        raise ValueError("feature native offsets or budget differ")
    return receipt


def project_feature_stream(directory: Path, output: Path) -> dict[str, Any]:  # noqa: C901, PLR0915 - one bounded streaming pass binds native cells and artifacts.
    """Verify CRC/full native SHA while retaining 44 float columns and duplicate diagnostics."""
    source = verify_feature_source(directory)
    member = source["member"]
    output.mkdir(parents=True, exist_ok=False)
    rows = 0
    missing_cells = dict.fromkeys((str(column) for column in SELECTED_COLUMNS), 0)
    seen_ids: set[int] = set()
    native_signatures: dict[bytes, list[int]] = {}
    with (directory / member["payload_path"]).open("rb") as raw:
        if raw.read(len(MEMBER_NAME)) != MEMBER_NAME.encode():
            raise ValueError("native feature local filename differs")
        raw.seek(member["payload_prefix_bytes"])
        checked = CheckedCSV(bz2.BZ2File(raw), member)
        with io.TextIOWrapper(io.BufferedReader(checked), encoding="utf-8", newline="") as text:
            reader = csv.reader(text)
            headers = [next(reader) for _ in range(3)]
            columns, positions = selected_feature_positions(headers)
            index_header = next(reader)
            if index_header[0] != "track_id" or any(index_header[1:]):
                raise ValueError("native track index header differs")
            with (
                (output / "features.float32").open("xb") as vectors,
                (output / "track_ids.uint32").open("xb") as identities,
            ):
                for row in reader:
                    if (
                        len(row) != len(columns) + 1
                        or not row[0].isascii()
                        or not row[0].isdecimal()
                    ):
                        raise ValueError("native acoustic row or track identity differs")
                    identity = int(row[0])
                    if identity <= 0 or identity >= 2**32 or identity in seen_ids:
                        raise ValueError("invalid or repeated native feature track identity")
                    seen_ids.add(identity)
                    values = []
                    for column, position in zip(SELECTED_COLUMNS, positions, strict=True):
                        value = float(row[position]) if row[position] else math.nan
                        if not math.isfinite(value):
                            value = math.nan
                            missing_cells[str(column)] += 1
                        values.append(value)
                    vectors.write(_FLOAT_ROW.pack(*values))
                    identities.write(_TRACK_ID.pack(identity))
                    signature = hashlib.sha256(canonical_json(row[1:])).digest()
                    native_signatures.setdefault(signature, []).append(identity)
                    rows += 1
                    if (
                        rows > MAX_ROWS
                        or rows * (_FLOAT_ROW.size + _TRACK_ID.size) > MAX_PROJECTION_BYTES
                    ):
                        raise ValueError("native feature projection exceeds row or byte budget")
                    if rows % 20000 == 0:
                        sys.stderr.write(f"Projected native FMA acoustic rows: {rows}\n")
            if not checked.complete:
                raise ValueError("native acoustic source stream did not reach verified EOF")
    duplicates = [sorted(ids) for ids in native_signatures.values() if len(ids) > 1]
    duplicates.sort()
    (output / "duplicate-native-feature-cells.json").write_bytes(canonical_json(duplicates) + b"\n")
    files: dict[str, dict[str, Any]] = {
        name: {"sha256": sha256_file(output / name)[0], "bytes": (output / name).stat().st_size}
        for name in ("features.float32", "track_ids.uint32", "duplicate-native-feature-cells.json")
    }
    receipt = {
        "revision": REVISION,
        "source_receipt_sha256": sha256_file(directory / "source-receipt.json")[0],
        "declaration_sha256": source["declaration_sha256"],
        "license": "CC-BY-4.0",
        "attribution": source["attribution"],
        "rows": rows,
        "columns": SELECTED_COLUMNS,
        "conceptual_channels": CHANNELS,
        "explicit_native_channel_aliases": {"zero_crossing_rate": "zcr"},
        "native_column_count": len(columns),
        "dtype": "little-endian float32 with explicit NaN missingness",
        "track_id_dtype": "little-endian uint32",
        "native_uncompressed_bytes": checked.length,
        "native_zip_crc32_verified": f"{checked.crc:08x}",
        "native_observed_sha256": checked.sha256.hexdigest(),
        "full_archive_sha1_verified": False,
        "missing_cells": missing_cells,
        "duplicate_group_count": len(duplicates),
        "duplicate_signature_basis": (
            "Exact original full native CSV feature-cell string arrays, excluding track ID; "
            "not a recording or artist identity bridge"
        ),
        "files": files,
        "audio_downloaded": False,
        "echo_nest_consumed": False,
    }
    if sum(file["bytes"] for file in files.values()) > MAX_PROJECTION_BYTES:
        raise ValueError("complete acoustic projection artifact budget exceeded")
    (output / "projection-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt
