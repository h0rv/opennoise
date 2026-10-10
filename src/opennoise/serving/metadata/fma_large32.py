"""Separately bounded fma_large directory probe and licensed 32-clip capture.

Only explicit probe/capture calls access the network. Existing small-archive
constants and custody rules are unchanged. Each attempted request leaves evidence.
"""

# ruff: noqa: PLR2004 -- explicit ZIP/HTTP wire-format fields.
# ruff: noqa: TRY300, TRY301 -- persist request evidence for each boundary rejection.
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from opennoise.ingest.fma.corpus import project_row, source_rows, verify_sources
from opennoise.serving.metadata import fma_listening64
from opennoise.serving.metadata.fma_listening import LICENSES

REVISION = "fma-large32-native-listening-v1"
URL = "https://os.unil.cloud.switch.ch/fma/fma_large.zip"
TAIL_BYTES = 65_557
RANGE_BYTES = 2_000_000
DIRECTORY_BYTES = 16_000_000
DIRECTORY_REQUESTS = 8
AUDIO_BYTES = 32_000_000
AUDIO_REQUESTS = 64
MAX_CLIPS = 32
LIMITS = {
    "directory_requests": DIRECTORY_REQUESTS,
    "directory_response_bytes": DIRECTORY_BYTES,
    "audio_requests": AUDIO_REQUESTS,
    "audio_response_bytes": AUDIO_BYTES,
    "decoded_audio_bytes": AUDIO_BYTES,
    "total_requests": 72,
    "total_response_bytes": 48_000_000,
    "range_bytes": RANGE_BYTES,
    "clips": MAX_CLIPS,
}


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked large32 path")


def _json(path: Path) -> dict[str, Any]:
    _safe(path)
    if not path.is_file() or path.stat().st_size > RANGE_BYTES:
        raise ValueError("large32 control missing or oversized")
    return json.loads(path.read_bytes())


def _write(path: Path, value: object, *, exclusive: bool = True) -> None:
    _safe(path)
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _strong(etag: str) -> bool:
    return re.fullmatch(r'"[\x21\x23-\x7e]+"', etag) is not None


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=False)


def _request(  # noqa: PLR0913, PLR0917, C901, PLR0915 -- one explicit range-attempt custody boundary.
    client: httpx.Client,
    output: Path,
    name: str,
    start: int | None,
    end: int | None,
    captures: list[dict[str, Any]],
    *,
    phase: str,
    total: int | None = None,
    etag: str | None = None,
) -> dict[str, Any]:
    suffix = start is None and end is None
    if not suffix and (type(start) is not int or type(end) is not int):
        raise ValueError("both exact range endpoints required")
    start_value = start if isinstance(start, int) else -1
    end_value = end if isinstance(end, int) else -1
    size = TAIL_BYTES if suffix else end_value - start_value + 1
    maximum, request_limit = (
        (DIRECTORY_BYTES, DIRECTORY_REQUESTS)
        if phase == "directory"
        else (AUDIO_BYTES, AUDIO_REQUESTS)
    )
    phase_rows = [row for row in captures if row["phase"] == phase]
    if (
        phase not in {"directory", "audio"}
        or not 0 < size <= RANGE_BYTES
        or len(phase_rows) >= request_limit
        or len(captures) >= LIMITS["total_requests"]
        or sum(row["bytes"] for row in phase_rows) + size > maximum
        or sum(row["bytes"] for row in captures) + size > LIMITS["total_response_bytes"]
        or (suffix and (captures or phase != "directory"))
        or (not suffix and (total is None or not 0 <= start_value <= end_value < total))
        or Path(name).name != name
        or client.follow_redirects
    ):
        raise ValueError("large32 range/request budget or path differs")
    _safe(output / name)
    if (output / name).exists():
        raise ValueError("range artifact already exists")
    request_range = f"bytes=-{TAIL_BYTES}" if suffix else f"bytes={start}-{end}"
    attempt_path = output / f"attempt-{len(captures) + 1:03}.json"
    attempt: dict[str, Any] = {
        "url": URL,
        "phase": phase,
        "range": request_range,
        "observed_at": datetime.now(UTC).isoformat(),
        "status": None,
        "state": "started",
        "received_bytes": 0,
    }
    _write(attempt_path, attempt)
    headers = {"Range": request_range, "Accept-Encoding": "identity"}
    if etag is not None:
        headers["If-Match"] = etag
    count, digest = 0, hashlib.sha256()
    try:
        with client.stream("GET", URL, headers=headers) as response:
            observed_etag = response.headers.get("etag", "")
            content_range = response.headers.get("content-range", "")
            attempt.update(
                status=response.status_code, content_range=content_range, etag=observed_etag
            )
            match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", content_range)
            if response.status_code != 206 or match is None:
                raise ValueError(
                    f"large32 request stopped: HTTP {response.status_code}; exact206 required"
                )
            actual_start, actual_end, actual_total = map(int, match.groups())
            expected_start = actual_total - TAIL_BYTES if suffix else start
            expected_end = actual_total - 1 if suffix else end
            if (
                actual_total <= TAIL_BYTES
                or actual_start != expected_start
                or actual_end != expected_end
                or (total is not None and actual_total != total)
                or response.headers.get("content-length") != str(size)
                or response.headers.get("content-encoding", "identity") != "identity"
                or not _strong(observed_etag)
                or (etag is not None and observed_etag != etag)
            ):
                raise ValueError("large32 response length, range, total or strong ETag differs")
            with (output / name).open("xb") as stream:
                for chunk in response.iter_raw(65_536):
                    count += len(chunk)
                    if count > size:
                        raise ValueError("large32 response exceeds requested range")
                    digest.update(chunk)
                    stream.write(chunk)
            if count != size:
                raise ValueError("large32 response truncated")
        record = {
            "path": name,
            "phase": phase,
            "url": URL,
            "start": actual_start,
            "end": actual_end,
            "archive_bytes": actual_total,
            "etag": observed_etag,
            "bytes": count,
            "sha256": digest.hexdigest(),
            "status": 206,
            "observed_at": attempt["observed_at"],
            "attempt": attempt_path.name,
        }
        attempt.update(state="complete", received_bytes=count, sha256=digest.hexdigest())
        captures.append(record)
        return record
    except Exception as exc:
        attempt.update(state="failed", received_bytes=count, error_type=type(exc).__name__)
        if isinstance(exc, ValueError):
            attempt["error"] = str(exc)
        raise
    finally:
        _write(attempt_path, attempt, exclusive=False)


def directory_location(tail: bytes, total: int) -> tuple[int, int, int]:
    """Validate single-disk EOCD/ZIP64 locator and exact terminal byte boundaries."""
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        raise ValueError("missing ZIP end record")
    end = struct.unpack_from("<4s4H2LH", tail, position)
    if end[1] or end[2] or end[3] != end[4] or position + 22 + end[7] != len(tail):
        raise ValueError("invalid/multi-disk ZIP end record")
    entries, length, offset = end[4:7]
    boundary = total - len(tail) + position
    if entries == 0xFFFF or offset == 0xFFFFFFFF or length == 0xFFFFFFFF:
        if position < 20:
            raise ValueError("missing ZIP64 locator")
        locator = struct.unpack_from("<4sLQL", tail, position - 20)
        if locator[0] != b"PK\x06\x07" or locator[1] != 0 or locator[3] != 1:
            raise ValueError("invalid/multi-disk ZIP64 locator")
        extended = locator[2] - (total - len(tail))
        if extended < 0 or extended + 56 > position - 20:
            raise ValueError("ZIP64 end record outside retained suffix")
        fields = struct.unpack_from("<4sQ2H2L4Q", tail, extended)
        if (
            fields[0] != b"PK\x06\x06"
            or fields[1] < 44
            or extended + 12 + fields[1] != position - 20
            or fields[4]
            or fields[5]
            or fields[6] != fields[7]
        ):
            raise ValueError("invalid/multi-disk ZIP64 end record")
        entries, length, offset = fields[7:10]
        boundary = locator[2]
    if (
        not 0 < entries <= 200_000
        or not 0 < length <= DIRECTORY_BYTES
        or not 0 <= offset < offset + length <= boundary
    ):
        raise ValueError("ZIP directory size or source boundary exceeds plan")
    return int(offset), int(length), int(entries)


def directory_plan(offset: int, length: int) -> list[tuple[int, int]]:
    """Preflight the entire directory before fetching its first chunk."""
    plan = [
        (start, min(start + RANGE_BYTES, offset + length) - 1)
        for start in range(offset, offset + length, RANGE_BYTES)
    ]
    if len(plan) + 1 > DIRECTORY_REQUESTS or length + TAIL_BYTES > DIRECTORY_BYTES:
        raise ValueError("entire directory exceeds remaining request/byte budget")
    return plan


def directory_members(body: bytes, directory_start: int, entries: int) -> dict[int, dict[str, Any]]:  # noqa: C901, PLR0912, PLR0915 -- complete central/ZIP64 parsing.
    """Validate every member path/mode/disk and conditional ZIP64 sizes/offsets."""
    cursor, count = 0, 0
    names: set[str] = set()
    members = {}
    while cursor < len(body):
        if cursor + 46 > len(body):
            raise ValueError("truncated directory record")
        fields = struct.unpack_from("<4s6H3L5H2L", body, cursor)
        name_size, extra_size, comment = fields[10:13]
        next_cursor = cursor + 46 + name_size + extra_size + comment
        if (
            fields[0] != b"PK\x01\x02"
            or next_cursor > len(body)
            or fields[3] & 1
            or fields[4] not in {0, 8, 12}
            or (fields[15] >> 16) & 0o170000 not in {0, 0o100000, 0o040000}
        ):
            raise ValueError("invalid/encrypted/symlink ZIP member")
        name = body[cursor + 46 : cursor + 46 + name_size].decode("utf-8")
        path = PurePosixPath(name)
        if (
            not name
            or any(ord(character) < 32 or ord(character) == 127 for character in name)
            or name in names
            or path.is_absolute()
            or "\\" in name
            or ":" in name
            or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
        ):
            raise ValueError("unsafe or duplicate ZIP member path")
        names.add(name)
        extra = body[cursor + 46 + name_size : cursor + 46 + name_size + extra_size]
        extensions = {}
        index = 0
        while index < len(extra):
            if index + 4 > len(extra):
                raise ValueError("truncated ZIP extra tag")
            tag, size = struct.unpack_from("<HH", extra, index)
            index += 4
            if index + size > len(extra) or tag in extensions:
                raise ValueError("truncated or duplicate ZIP extra")
            extensions[tag] = extra[index : index + size]
            index += size
        uncompressed, compressed, offset, disk = fields[9], fields[8], fields[16], fields[13]
        values = [uncompressed, compressed, offset, disk]
        zip64 = extensions.get(1, b"")
        index = 0
        for slot, (value, sentinel, width) in enumerate(
            zip(values, (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF), (8, 8, 8, 4), strict=True)
        ):
            if value == sentinel:
                if index + width > len(zip64):
                    raise ValueError("missing conditional ZIP64 extension")
                values[slot] = int.from_bytes(zip64[index : index + width], "little")
                index += width
        uncompressed, compressed, offset, disk = values
        if disk != 0 or not 0 <= offset < directory_start:
            raise ValueError("multi-disk member or invalid local offset")
        if name.endswith(".mp3"):
            if ((fields[15] >> 16) & 0o170000) == 0o040000 or fields[15] & 0x10:
                raise ValueError("MP3 entry has directory attributes")
            match = re.fullmatch(r"fma_large/(\d{3})/(\d{6})\.mp3", name)
            if not match or int(match[1]) != int(match[2]) // 1000:
                raise ValueError("invalid native large-archive MP3 identity")
            identity = int(match[2])
            if (
                identity <= 0
                or identity in members
                or compressed <= 0
                or uncompressed <= 0
                or offset + 30 + name_size + compressed > directory_start
            ):
                raise ValueError("duplicate native identity or unsafe MP3 size/offset")
            members[identity] = {
                "name": name,
                "method": fields[4],
                "flags": fields[3],
                "crc32": fields[7],
                "compressed": compressed,
                "uncompressed": uncompressed,
                "offset": offset,
            }
        cursor, count = next_cursor, count + 1
    if count != entries:
        raise ValueError("directory entry count differs from end record")
    return members


def probe(output: Path) -> dict[str, Any]:
    """NETWORK: exact suffix and bounded directory only; caller owns acquisition approval."""
    _safe(output)
    output.mkdir(parents=True, exist_ok=False)
    captures: list[dict[str, Any]] = []
    with _client() as client:
        first = _request(client, output, "tail.range", None, None, captures, phase="directory")
        offset, length, entries = directory_location(
            (output / "tail.range").read_bytes(), first["archive_bytes"]
        )
        plan = directory_plan(offset, length)
        for index, (start, end) in enumerate(plan):
            _request(
                client,
                output,
                f"directory-{index:02}.range",
                start,
                end,
                captures,
                phase="directory",
                total=first["archive_bytes"],
                etag=first["etag"],
            )
    result = {
        "revision": REVISION,
        "limits": LIMITS,
        "archive_bytes": first["archive_bytes"],
        "etag": first["etag"],
        "directory": {"start": offset, "bytes": length, "entries": entries},
        "captures": captures,
    }
    _write(output / "probe.json", result)
    verify_probe(output)
    return result


def _read_record(
    directory: Path, record: dict[str, Any], total: int, etag: str, number: int
) -> bytes:
    name = str(record["path"])
    if (
        Path(name).name != name
        or record["url"] != URL
        or record["status"] != 206
        or record["archive_bytes"] != total
        or record["etag"] != etag
        or not _strong(etag)
        or not 0 <= record["start"] <= record["end"] < total
        or record["bytes"] != record["end"] - record["start"] + 1
        or not 0 < record["bytes"] <= RANGE_BYTES
        or record["attempt"] != f"attempt-{number:03}.json"
    ):
        raise ValueError("range receipt identity differs")
    path: Path = directory / name
    _safe(path)
    if not path.is_file() or path.stat().st_size != record["bytes"]:
        raise ValueError("range file size differs")
    body = path.read_bytes()
    attempt = _json(directory / record["attempt"])
    if (
        _sha(body) != record["sha256"]
        or attempt["state"] != "complete"
        or attempt["url"] != URL
        or attempt["status"] != 206
        or attempt["phase"] != record["phase"]
        or attempt["received_bytes"] != len(body)
        or attempt["sha256"] != record["sha256"]
        or attempt["etag"] != etag
        or attempt["observed_at"] != record["observed_at"]
        or attempt["range"]
        != (f"bytes=-{TAIL_BYTES}" if number == 1 else f"bytes={record['start']}-{record['end']}")
        or attempt["content_range"] != f"bytes {record['start']}-{record['end']}/{total}"
    ):
        raise ValueError("range bytes or attempt custody differs")
    datetime.fromisoformat(record["observed_at"])
    return body


def verify_probe(output: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """OFFLINE: replay every directory byte and exact preflight plan."""
    result = _json(output / "probe.json")
    captures, total, etag = result["captures"], result["archive_bytes"], result["etag"]
    if (
        result["revision"] != REVISION
        or result["limits"] != LIMITS
        or not 2 <= len(captures) <= DIRECTORY_REQUESTS
        or captures[0]["path"] != "tail.range"
        or any(row["phase"] != "directory" for row in captures)
    ):
        raise ValueError("directory protocol differs")
    bodies = [
        _read_record(output, row, total, etag, index + 1) for index, row in enumerate(captures)
    ]
    offset, length, entries = directory_location(bodies[0], total)
    plan = directory_plan(offset, length)
    if (
        (captures[0]["start"], captures[0]["end"]) != (total - TAIL_BYTES, total - 1)
        or result["directory"] != {"start": offset, "bytes": length, "entries": entries}
        or len(captures) != len(plan) + 1
    ):
        raise ValueError("directory source bounds differ")
    for index, ((start, end), row) in enumerate(zip(plan, captures[1:], strict=True)):
        if row["path"] != f"directory-{index:02}.range" or (row["start"], row["end"]) != (
            start,
            end,
        ):
            raise ValueError("directory chunk plan differs")
    return result, directory_members(b"".join(bodies[1:]), offset, entries)


def selection(source: Path, baseline: Path, probe_directory: Path) -> dict[str, Any]:
    """Exclude old tracks; greedily cover new direct genres, preferring novel artists on ties."""
    _probed, members = verify_probe(probe_directory)
    previous = fma_listening64.verify(baseline, source)
    old_ids = {row["track_id"] for row in previous["tracks"]}
    old_artists = {row["artist_id"] for row in previous["tracks"]}
    old_genres = {genre for row in previous["tracks"] for genre in row["genre_ids"]}
    receipt = verify_sources(source)
    rows, checked, handles = source_rows(source, receipt["members"]["fma_metadata/raw_artists.csv"])
    try:
        known = {int(row["artist_id"]) for row in rows}
        if not checked.complete:
            raise ValueError("native artist stream incomplete")
    finally:
        for handle in handles:
            handle.close()
    rows, checked, handles = source_rows(source, receipt["members"]["fma_metadata/raw_tracks.csv"])
    candidates: list[dict[str, Any]] = []
    try:
        for row in rows:
            projected = project_row("tracks", row)
            identity, artist = projected["track_id"], projected["artist_id"]
            member = members.get(identity)
            if (
                identity in old_ids
                or artist not in known
                or row["license_url"] not in LICENSES
                or member is None
                or member["uncompressed"] > RANGE_BYTES
                or member["compressed"] + len(member["name"].encode()) + 65_535 > RANGE_BYTES
            ):
                continue
            candidates.append(
                {
                    "track_id": identity,
                    "artist_id": artist,
                    "genre_ids": projected["genre_ids"] or [],
                    "member": member,
                    "source": {
                        key: row.get(key, "")
                        for key in (
                            "artist_name",
                            "track_title",
                            "track_url",
                            "license_url",
                            "license_title",
                            "track_copyright_c",
                            "track_copyright_p",
                            "track_composer",
                        )
                    },
                }
            )
        if not checked.complete:
            raise ValueError("native license stream incomplete")
        track_sha = checked.sha256.hexdigest()
    finally:
        for handle in handles:
            handle.close()
    chosen: list[dict[str, Any]] = []
    artists: set[int] = set()
    covered = set(old_genres)
    network = decoded = 0
    while len(chosen) < MAX_CLIPS:
        available = [
            row
            for row in candidates
            if row["artist_id"] not in artists
            and network
            + 30
            + len(row["member"]["name"].encode())
            + 65_535
            + row["member"]["compressed"]
            <= AUDIO_BYTES
            and decoded + row["member"]["uncompressed"] <= AUDIO_BYTES
        ]
        if not available:
            break
        row = min(
            available,
            key=lambda item: (
                -len(set(item["genre_ids"]) - covered),
                item["artist_id"] in old_artists,
                _sha(f"{REVISION}:{item['track_id']}".encode()),
            ),
        )
        chosen.append(row)
        artists.add(row["artist_id"])
        covered.update(row["genre_ids"])
        network += 30 + len(row["member"]["name"].encode()) + 65_535 + row["member"]["compressed"]
        decoded += row["member"]["uncompressed"]
    return {
        "revision": REVISION,
        "limits": LIMITS,
        "baseline_sha256": _sha((baseline / "listening.json").read_bytes()),
        "probe_sha256": _sha((probe_directory / "probe.json").read_bytes()),
        "metadata_receipt_sha256": _sha((source / "source-receipt.json").read_bytes()),
        "native_track_csv_sha256": track_sha,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "selection_rule": (
            "greedy new direct genres; prefer artists absent from baseline on ties; "
            "SHA256 revision:track_id tie; one artist per batch; no old tracks; "
            "no replacement after freeze"
        ),
        "baseline_track_ids": sorted(old_ids),
        "baseline_artist_ids": sorted(old_artists),
        "baseline_genres": sorted(old_genres),
        "eligible_tracks": len(candidates),
        "new_genres": sorted(covered - old_genres),
        "tracks": chosen,
        "planned_audio_requests": 2 * len(chosen),
        "planned_audio_response_bytes_upper_bound": network,
        "planned_decoded_audio_bytes": decoded,
    }


def freeze(source: Path, baseline: Path, probe_directory: Path) -> dict[str, Any]:
    """OFFLINE: retain exact reviewed selection before any member payload requests."""
    result = selection(source, baseline, probe_directory)
    _write(probe_directory / "selection.json", result)
    return result


CLAIMS = {
    "audio_scope": "native FMA large excerpts; no transcoding or full tracks",
    "metadata_license": "CC-BY-4.0",
    "musical_representativeness": "not_judged",
    "full_archive_hash_verified": False,
    "public_deployment_authorized": False,
}


def capture(source: Path, baseline: Path, probe_directory: Path, output: Path) -> dict[str, Any]:
    """NETWORK: acquire only frozen native members under both phase and combined budgets."""
    frozen = _json(probe_directory / "selection.json")
    if frozen != selection(source, baseline, probe_directory) or not frozen["tracks"]:
        raise ValueError("frozen large32 cohort differs or is empty")
    probed, _ = verify_probe(probe_directory)
    _safe(output)
    output.mkdir(parents=True, exist_ok=False)
    names = {"probe.json", "selection.json"}
    for record in probed["captures"]:
        names.update((record["path"], record["attempt"]))
    for name in names:
        shutil.copyfile(probe_directory / name, output / name)
    captures = list(probed["captures"])
    tracks = []
    decoded_total = 0
    with _client() as client:
        for item in frozen["tracks"]:
            identity, member = item["track_id"], item["member"]
            header = _request(
                client,
                output,
                f"{identity}-header.range",
                member["offset"],
                member["offset"] + 29,
                captures,
                phase="audio",
                total=probed["archive_bytes"],
                etag=probed["etag"],
            )
            start, end, prefix = fma_listening64._payload_bounds(  # noqa: SLF001 -- unchanged pure 2MB local header checks.
                (output / header["path"]).read_bytes(), item, probed["directory"]["start"]
            )
            payload = _request(
                client,
                output,
                f"{identity}-payload.range",
                start,
                end,
                captures,
                phase="audio",
                total=probed["archive_bytes"],
                etag=probed["etag"],
            )
            audio = fma_listening64._audio((output / payload["path"]).read_bytes(), prefix, member)  # noqa: SLF001 -- unchanged bounded native decoder/CRC.
            decoded_total += len(audio)
            if decoded_total > AUDIO_BYTES:
                raise ValueError("decoded large32 audio budget exceeded")
            with (output / f"{identity}.mp3").open("xb") as stream:
                stream.write(audio)
            tracks.append(
                {
                    **item,
                    "audio_path": f"{identity}.mp3",
                    "audio_bytes": len(audio),
                    "audio_sha256": _sha(audio),
                }
            )
    result = {
        "revision": REVISION,
        "limits": LIMITS,
        **CLAIMS,
        "baseline_sha256": frozen["baseline_sha256"],
        "selection_sha256": _sha((output / "selection.json").read_bytes()),
        "new_genres": frozen["new_genres"],
        "captures": captures,
        "tracks": tracks,
        "audio_bytes": decoded_total,
        "response_bytes": sum(row["bytes"] for row in captures),
    }
    _write(output / "listening.json", result)
    verify(output, source, baseline)
    return result


def verify(pack: Path, source: Path, baseline: Path) -> dict[str, Any]:  # noqa: C901 -- independent complete custody domains.
    """OFFLINE: validate baseline, native licenses, frozen selection and every acquired byte."""
    result, frozen = _json(pack / "listening.json"), _json(pack / "selection.json")
    probed, _ = verify_probe(pack)
    if (
        result["revision"] != REVISION
        or result["limits"] != LIMITS
        or any(
            result.get(key) != value or type(result.get(key)) is not type(value)
            for key, value in CLAIMS.items()
        )
        or frozen != selection(source, baseline, pack)
        or result["baseline_sha256"] != frozen["baseline_sha256"]
        or result["selection_sha256"] != _sha((pack / "selection.json").read_bytes())
        or result["new_genres"] != frozen["new_genres"]
        or not 0 < len(result["tracks"]) <= MAX_CLIPS
        or len(result["tracks"]) != len(frozen["tracks"])
    ):
        raise ValueError("large32 frozen protocol or source role differs")
    captures = result["captures"]
    initial = len(probed["captures"])
    if captures[:initial] != probed["captures"] or len(captures) != initial + 2 * len(
        result["tracks"]
    ):
        raise ValueError("large32 request inventory differs")
    expected = {"probe.json", "selection.json", "listening.json"}
    for record in captures:
        expected.update((record["path"], record["attempt"]))
    decoded = 0
    for index, (item, track) in enumerate(zip(frozen["tracks"], result["tracks"], strict=True)):
        if {key: track[key] for key in item} != item:
            raise ValueError("large32 track differs from frozen source")
        identity, member = item["track_id"], item["member"]
        header, payload = captures[initial + 2 * index : initial + 2 * index + 2]
        if (
            header["path"] != f"{identity}-header.range"
            or payload["path"] != f"{identity}-payload.range"
            or header["phase"] != "audio"
            or payload["phase"] != "audio"
            or (header["start"], header["end"]) != (member["offset"], member["offset"] + 29)
        ):
            raise ValueError("large32 header/payload identity differs")
        header_body = _read_record(
            pack, header, probed["archive_bytes"], probed["etag"], initial + 2 * index + 1
        )
        start, end, prefix = fma_listening64._payload_bounds(  # noqa: SLF001 -- reuse unchanged pure header checks.
            header_body, item, probed["directory"]["start"]
        )
        if (payload["start"], payload["end"]) != (start, end):
            raise ValueError("large32 payload bounds differ")
        payload_body = _read_record(
            pack, payload, probed["archive_bytes"], probed["etag"], initial + 2 * index + 2
        )
        audio = fma_listening64._audio(payload_body, prefix, member)  # noqa: SLF001
        path = pack / f"{identity}.mp3"
        _safe(path)
        if (
            track["audio_path"] != path.name
            or track["audio_bytes"] != len(audio)
            or track["audio_sha256"] != _sha(audio)
            or not path.is_file()
            or path.stat().st_size != len(audio)
            or path.read_bytes() != audio
        ):
            raise ValueError("large32 exposed audio differs from native member")
        expected.add(path.name)
        decoded += len(audio)
    for phase, max_requests, maximum in (
        ("directory", DIRECTORY_REQUESTS, DIRECTORY_BYTES),
        ("audio", AUDIO_REQUESTS, AUDIO_BYTES),
    ):
        phase_rows = [row for row in captures if row["phase"] == phase]
        if len(phase_rows) > max_requests or sum(row["bytes"] for row in phase_rows) > maximum:
            raise ValueError("large32 phase budget differs")
    if (
        decoded != result["audio_bytes"]
        or decoded > AUDIO_BYTES
        or result["response_bytes"] != sum(row["bytes"] for row in captures)
        or result["response_bytes"] > LIMITS["total_response_bytes"]
        or len(captures) > LIMITS["total_requests"]
        or {path.name for path in pack.iterdir()} != expected
        or any(path.is_symlink() or not path.is_file() for path in pack.iterdir())
    ):
        raise ValueError("large32 closed inventory or combined budget differs")
    return result
