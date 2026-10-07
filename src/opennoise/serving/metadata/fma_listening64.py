"""Separately approved, staged capture of at most 64 native licensed FMA excerpts.

Probe and capture perform network I/O only when explicitly called. Freeze and
verification replay retained bytes offline. This does not modify the eight-clip recipe.
"""

# ruff: noqa: PLR2004 -- ZIP wire-format fields and fixed HTTP protocol values.
from __future__ import annotations

import bz2
import hashlib
import json
import re
import shutil
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from opennoise.ingest.fma.corpus import project_row, source_rows, verify_sources
from opennoise.serving.metadata.fma_listening import LICENSES, directory_members

REVISION = "fma-permitted-listening64-v1"
URL = "https://os.unil.cloud.switch.ch/fma/fma_small.zip"
ARCHIVE_BYTES = 7_679_594_875
MAX_CLIPS = 64
MAX_REQUESTS = 130
MAX_RESPONSE_BYTES = 64_000_000
MAX_AUDIO_BYTES = 64_000_000
MAX_RANGE_BYTES = 2_000_000
TAIL_BYTES = 65_557
MAX_EXTRA_BYTES = 65_535
LIMITS = {
    "clips": MAX_CLIPS,
    "requests": MAX_REQUESTS,
    "response_bytes": MAX_RESPONSE_BYTES,
    "audio_bytes": MAX_AUDIO_BYTES,
    "range_bytes": MAX_RANGE_BYTES,
}


RECEIPT_CLAIMS = {
    "audio_scope": "native FMA small excerpts; no transcoding or full tracks",
    "metadata_license": "CC-BY-4.0",
    "musical_representativeness": "not_judged",
    "full_archive_hash_verified": False,
    "public_deployment_authorized": False,
}


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked listening path")


def _write(path: Path, value: object) -> None:
    _safe(path)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def _json(path: Path) -> dict[str, Any]:
    _safe(path)
    if not path.is_file() or path.stat().st_size > MAX_RANGE_BYTES:
        raise ValueError("missing or oversized listening control")
    return json.loads(path.read_bytes())


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _read(path: Path, binding: dict[str, Any]) -> bytes:
    _safe(path)
    if (
        not path.is_file()
        or path.stat().st_size != binding["bytes"]
        or not 0 < binding["bytes"] <= MAX_RANGE_BYTES
    ):
        raise ValueError("listening artifact size differs")
    body = path.read_bytes()
    if _sha(body) != binding["sha256"]:
        raise ValueError("listening artifact hash differs")
    return body


def _get(  # noqa: PLR0913, PLR0917 -- explicit range custody arguments.
    client: httpx.Client,
    output: Path,
    name: str,
    start: int,
    end: int,
    captures: list[dict[str, Any]],
    etag: str | None = None,
) -> dict[str, Any]:
    """Stream a single exact range; invalid status/headers stop before consuming the body."""
    size = end - start + 1
    if not 0 <= start <= end < ARCHIVE_BYTES or size > MAX_RANGE_BYTES:
        raise ValueError("invalid or oversized requested range")
    if (
        len(captures) >= MAX_REQUESTS
        or sum(c["bytes"] for c in captures) + size > MAX_RESPONSE_BYTES
    ):
        raise ValueError("request or aggregate response budget exceeded")
    if Path(name).name != name or client.follow_redirects:
        raise ValueError("unsafe range path or redirect-enabled client")
    headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
    if etag is not None:
        headers["If-Match"] = etag
    _safe(output / name)
    # No retry loop. Standard HTTPX transport defaults to zero retries and preserves proxies.
    with client.stream("GET", URL, headers=headers) as response:
        actual_etag = response.headers.get("etag", "")
        if (
            response.status_code != 206
            or response.headers.get("content-range") != f"bytes {start}-{end}/{ARCHIVE_BYTES}"
            or response.headers.get("content-length") != str(size)
            or response.headers.get("content-encoding", "identity") != "identity"
            or not actual_etag
            or actual_etag.startswith("W/")
            or (etag is not None and actual_etag != etag)
        ):
            raise ValueError(
                f"audio range rejected: HTTP {response.status_code}; range/ETag headers must match"
            )
        count = 0
        digest = hashlib.sha256()
        with (output / name).open("xb") as stream:
            for chunk in response.iter_raw(65_536):
                if count + len(chunk) > size:
                    raise ValueError("audio response exceeds declared range")
                count += len(chunk)
                digest.update(chunk)
                stream.write(chunk)
        if count != size:
            raise ValueError("truncated audio range")
    record = {
        "path": name,
        "url": URL,
        "start": start,
        "end": end,
        "bytes": count,
        "sha256": digest.hexdigest(),
        "etag": actual_etag,
        "status": 206,
        "archive_bytes": ARCHIVE_BYTES,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    captures.append(record)
    return record


def _directory_location(tail: bytes) -> tuple[int, int]:
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        raise ValueError("missing ZIP end record")
    eocd = struct.unpack_from("<4s4H2LH", tail, position)
    if eocd[1] or eocd[2] or eocd[3] != eocd[4] or position + 22 + eocd[7] != len(tail):
        raise ValueError("unsupported ZIP end boundary")
    length, offset = eocd[5:7]
    if offset == 0xFFFFFFFF or length == 0xFFFFFFFF:
        extended = tail.rfind(b"PK\x06\x06", 0, position)
        if extended < 0 or extended + 56 > position:
            raise ValueError("missing ZIP64 end record")
        fields = struct.unpack_from("<4sQ2H2L4Q", tail, extended)
        if fields[4] or fields[5] or fields[6] != fields[7]:
            raise ValueError("unsupported multi-disk ZIP64")
        length, offset = fields[-2:]
    if not 0 < length <= MAX_RANGE_BYTES or not 0 <= offset < offset + length <= ARCHIVE_BYTES - 22:
        raise ValueError("ZIP directory exceeds source bounds")
    return int(offset), int(length)


def _members(body: bytes, directory_start: int) -> dict[int, dict[str, Any]]:
    cursor = 0
    while cursor < len(body):
        if cursor + 46 > len(body):
            raise ValueError("truncated central directory")
        fields = struct.unpack_from("<4s6H3L5H2L", body, cursor)
        mode = fields[15] >> 16
        if fields[0] != b"PK\x01\x02" or mode & 0o170000 == 0o120000:
            raise ValueError("invalid or symlink ZIP member")
        cursor += 46 + sum(fields[10:13])
        if cursor > len(body):
            raise ValueError("truncated central member")
    members = directory_members(body)
    for identity, member in members.items():
        match = re.fullmatch(r"fma_small/(\d{3})/(\d{6})\.mp3", member["name"])
        if (
            not match
            or int(match[2]) != identity
            or int(match[1]) != identity // 1000
            or identity <= 0
            or member["flags"] & 1
            or not 0 <= member["offset"] < directory_start
            or member["compressed"] <= 0
            or member["uncompressed"] <= 0
            or member["offset"] + 30 + len(member["name"].encode()) + member["compressed"]
            > directory_start
        ):
            raise ValueError("unsafe native MP3 member or archive offset")
    return members


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=False)


def probe(output: Path) -> dict[str, Any]:
    """NETWORK: acquire only tail and directory; requires explicit prior audio-source approval."""
    _safe(output)
    output.mkdir(parents=True, exist_ok=False)
    captures: list[dict[str, Any]] = []
    with _client() as client:
        tail = _get(
            client, output, "tail.range", ARCHIVE_BYTES - TAIL_BYTES, ARCHIVE_BYTES - 1, captures
        )
        offset, size = _directory_location((output / "tail.range").read_bytes())
        _get(client, output, "directory.range", offset, offset + size - 1, captures, tail["etag"])
    result = {"revision": REVISION, "limits": LIMITS, "captures": captures}
    _write(output / "probe.json", result)
    verify_probe(output)
    return result


def verify_probe(directory: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Offline exact two-request receipt and ZIP directory replay."""
    result = _json(directory / "probe.json")
    if result["revision"] != REVISION or result["limits"] != LIMITS or len(result["captures"]) != 2:
        raise ValueError("probe protocol differs")
    bodies = []
    for expected_name, record in zip(
        ("tail.range", "directory.range"), result["captures"], strict=True
    ):
        if (
            record["path"] != expected_name
            or record["url"] != URL
            or record["status"] != 206
            or record["archive_bytes"] != ARCHIVE_BYTES
            or record["end"] - record["start"] + 1 != record["bytes"]
            or not record["etag"]
            or record["etag"].startswith("W/")
        ):
            raise ValueError("probe range custody differs")
        datetime.fromisoformat(record["observed_at"])
        bodies.append(_read(directory / expected_name, record))
    tail, central = result["captures"]
    offset, length = _directory_location(bodies[0])
    if (
        (tail["start"], tail["end"]) != (ARCHIVE_BYTES - TAIL_BYTES, ARCHIVE_BYTES - 1)
        or (central["start"], central["bytes"]) != (offset, length)
        or central["etag"] != tail["etag"]
    ):
        raise ValueError("probe tail/directory offsets differ")
    return result, _members(bodies[1], offset)


def selection(source: Path, probe_directory: Path) -> dict[str, Any]:
    """Offline deterministic genre coverage, one known native artist each, before any audio."""
    probed, members = verify_probe(probe_directory)
    receipt = verify_sources(source)
    artists, checked, handles = source_rows(
        source, receipt["members"]["fma_metadata/raw_artists.csv"]
    )
    try:
        known = {int(row["artist_id"]) for row in artists}
        if not checked.complete:
            raise ValueError("artist source incomplete")
    finally:
        for handle in handles:
            handle.close()
    rows, checked, handles = source_rows(source, receipt["members"]["fma_metadata/raw_tracks.csv"])
    candidates: list[dict[str, Any]] = []
    try:
        for row in rows:
            projected = project_row("tracks", row)
            identity = projected["track_id"]
            member = members.get(identity)
            if (
                row["license_url"] not in LICENSES
                or projected["artist_id"] not in known
                or member is None
                or member["uncompressed"] > MAX_RANGE_BYTES
                or member["compressed"] + len(member["name"].encode()) + MAX_EXTRA_BYTES
                > MAX_RANGE_BYTES
            ):
                continue
            candidates.append(
                {
                    "track_id": identity,
                    "artist_id": projected["artist_id"],
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
            raise ValueError("track license source incomplete")
        source_sha = checked.sha256.hexdigest()
    finally:
        for handle in handles:
            handle.close()
    eligible = len(candidates)
    used_artists: set[int] = set()
    covered: set[int] = set()
    chosen = []
    network = sum(row["bytes"] for row in probed["captures"])
    audio = 0
    while len(chosen) < MAX_CLIPS:
        possible = [
            r
            for r in candidates
            if r["artist_id"] not in used_artists
            and network
            + 30
            + len(r["member"]["name"].encode())
            + MAX_EXTRA_BYTES
            + r["member"]["compressed"]
            <= MAX_RESPONSE_BYTES
            and audio + r["member"]["uncompressed"] <= MAX_AUDIO_BYTES
        ]
        if not possible:
            break
        item = min(
            possible,
            key=lambda r: (
                -len(set(r["genre_ids"]) - covered),
                _sha(f"{REVISION}:{r['track_id']}".encode()),
            ),
        )
        chosen.append(item)
        used_artists.add(item["artist_id"])
        covered.update(item["genre_ids"])
        network += (
            30
            + len(item["member"]["name"].encode())
            + MAX_EXTRA_BYTES
            + item["member"]["compressed"]
        )
        audio += item["member"]["uncompressed"]
    if not chosen:
        raise ValueError("no bounded licensed native clips eligible")
    return {
        "revision": REVISION,
        "limits": LIMITS,
        "selection_rule": (
            "greedy new direct-track genre coverage; SHA256 revision:track_id "
            "tie break; one known native artist; budget constrained"
        ),
        "probe_sha256": _sha((probe_directory / "probe.json").read_bytes()),
        "metadata_receipt_sha256": _sha((source / "source-receipt.json").read_bytes()),
        "native_track_csv_sha256": source_sha,
        "eligible_tracks": eligible,
        "planned_requests": 2 + 2 * len(chosen),
        "planned_response_bytes_upper_bound": network,
        "planned_audio_bytes": audio,
        "direct_genres_covered": sorted(covered),
        "tracks": chosen,
    }


def freeze(source: Path, probe_directory: Path) -> dict[str, Any]:
    """OFFLINE: write immutable chosen IDs and license metadata for review before capture."""
    result = selection(source, probe_directory)
    _write(probe_directory / "selection.json", result)
    return result


def _payload_bounds(
    header: bytes, item: dict[str, Any], directory_start: int
) -> tuple[int, int, int]:
    member = item["member"]
    if len(header) != 30:
        raise ValueError("native local header length differs")
    fields = struct.unpack("<4s5H3L2H", header)
    if (
        fields[0] != b"PK\x03\x04"
        or fields[2] != member["flags"]
        or fields[3] != member["method"]
        or fields[9] != len(member["name"].encode())
        or (
            not fields[2] & 8
            and fields[6:9] != (member["crc32"], member["compressed"], member["uncompressed"])
        )
    ):
        raise ValueError("native local header differs from frozen directory")
    prefix = fields[9] + fields[10]
    start = member["offset"] + 30
    end = start + prefix + member["compressed"] - 1
    if end >= directory_start or end - start + 1 > MAX_RANGE_BYTES:
        raise ValueError("payload exceeds directory or range bounds")
    return int(start), int(end), int(prefix)


def _audio(payload: bytes, prefix: int, member: dict[str, Any]) -> bytes:
    if payload[: len(member["name"].encode())] != member["name"].encode():
        raise ValueError("native member filename differs")
    compressed = payload[prefix:]
    if len(compressed) != member["compressed"]:
        raise ValueError("compressed member length differs")
    method = member["method"]
    if method == 0:
        audio = compressed
    else:
        decoder = (
            bz2.BZ2Decompressor()
            if method == 12
            else zlib.decompressobj(-15)
            if method == 8
            else None
        )
        if decoder is None:
            raise ValueError("unsupported native compression")
        audio = decoder.decompress(compressed, MAX_RANGE_BYTES + 1)
        if not decoder.eof or decoder.unused_data:
            raise ValueError("native decompression boundary differs")
    if (
        len(audio) > MAX_RANGE_BYTES
        or len(audio) != member["uncompressed"]
        or zlib.crc32(audio) != member["crc32"]
    ):
        raise ValueError("native MP3 size or CRC differs")
    return audio


def capture(source: Path, probe_directory: Path, output: Path) -> dict[str, Any]:
    """NETWORK: acquire only the frozen selection; no retry, replacement, fallback or tuning."""
    frozen = _json(probe_directory / "selection.json")
    if frozen != selection(source, probe_directory):
        raise ValueError("frozen selection differs from offline replay")
    probed, _ = verify_probe(probe_directory)
    _safe(output)
    output.mkdir(parents=True, exist_ok=False)
    for name in ("probe.json", "selection.json", "tail.range", "directory.range"):
        shutil.copyfile(probe_directory / name, output / name)
    captures = list(probed["captures"])
    tracks: list[dict[str, Any]] = []
    with _client() as client:
        for item in frozen["tracks"]:
            identity = item["track_id"]
            member = item["member"]
            header = _get(
                client,
                output,
                f"{identity}-header.range",
                member["offset"],
                member["offset"] + 29,
                captures,
                captures[0]["etag"],
            )
            start, end, prefix = _payload_bounds(
                _read(output / header["path"], header), item, captures[1]["start"]
            )
            payload = _get(
                client,
                output,
                f"{identity}-payload.range",
                start,
                end,
                captures,
                captures[0]["etag"],
            )
            audio = _audio(_read(output / payload["path"], payload), prefix, member)
            if sum(t["audio_bytes"] for t in tracks) + len(audio) > MAX_AUDIO_BYTES:
                raise ValueError("aggregate audio budget exceeded")
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
        "selection_sha256": _sha((output / "selection.json").read_bytes()),
        "captures": captures,
        "tracks": tracks,
        "response_bytes": sum(r["bytes"] for r in captures),
        "audio_bytes": sum(t["audio_bytes"] for t in tracks),
        **RECEIPT_CLAIMS,
    }
    _write(output / "listening.json", result)
    verify(output, source)
    return result


def verify(pack: Path, source: Path) -> dict[str, Any]:  # noqa: C901 -- full custody replay.
    """OFFLINE: reselect from native licenses and authenticate every range and exposed MP3."""
    _safe(pack)
    result = _json(pack / "listening.json")
    if any(
        result.get(key) != value or type(result.get(key)) is not type(value)
        for key, value in RECEIPT_CLAIMS.items()
    ):
        raise ValueError("listening receipt claims differ from fixed protocol")
    frozen = _json(pack / "selection.json")
    probed, _ = verify_probe(pack)
    if (
        result["revision"] != REVISION
        or result["limits"] != LIMITS
        or frozen != selection(source, pack)
        or result["selection_sha256"] != _sha((pack / "selection.json").read_bytes())
        or result["captures"][:2] != probed["captures"]
        or len(result["tracks"]) != len(frozen["tracks"])
        or len(result["captures"]) != 2 + 2 * len(result["tracks"])
        or len(result["captures"]) > MAX_REQUESTS
    ):
        raise ValueError("listening pack protocol or selection differs")
    expected = {"probe.json", "selection.json", "listening.json", "tail.range", "directory.range"}
    total = 0
    for i, item in enumerate(frozen["tracks"]):
        track = result["tracks"][i]
        if {k: track[k] for k in item} != item:
            raise ValueError("track differs from frozen native metadata")
        identity = item["track_id"]
        header, payload = result["captures"][2 + i * 2 : 4 + i * 2]
        for record, name in (
            (header, f"{identity}-header.range"),
            (payload, f"{identity}-payload.range"),
        ):
            if (
                record["path"] != name
                or record["url"] != URL
                or record["etag"] != probed["captures"][0]["etag"]
                or record["status"] != 206
                or record["archive_bytes"] != ARCHIVE_BYTES
                or record["end"] - record["start"] + 1 != record["bytes"]
            ):
                raise ValueError("native range identity differs")
            datetime.fromisoformat(record["observed_at"])
            expected.add(name)
        if (header["start"], header["end"]) != (
            item["member"]["offset"],
            item["member"]["offset"] + 29,
        ):
            raise ValueError("native header offsets differ")
        start, end, prefix = _payload_bounds(
            _read(pack / header["path"], header), item, probed["captures"][1]["start"]
        )
        if (payload["start"], payload["end"]) != (start, end):
            raise ValueError("native payload offsets differ")
        audio = _audio(_read(pack / payload["path"], payload), prefix, item["member"])
        name = f"{identity}.mp3"
        if (
            track["audio_path"] != name
            or _read(pack / name, {"bytes": track["audio_bytes"], "sha256": track["audio_sha256"]})
            != audio
        ):
            raise ValueError("exposed audio differs from native MP3")
        total += len(audio)
        expected.add(name)
    actual = {p.name for p in pack.iterdir()}
    if any(p.is_symlink() or not p.is_file() for p in pack.iterdir()) or actual != expected:
        raise ValueError("listening closed inventory differs")
    if (
        total != result["audio_bytes"]
        or total > MAX_AUDIO_BYTES
        or result["response_bytes"] != sum(r["bytes"] for r in result["captures"])
        or result["response_bytes"] > MAX_RESPONSE_BYTES
    ):
        raise ValueError("aggregate response/audio budget differs")
    return result
