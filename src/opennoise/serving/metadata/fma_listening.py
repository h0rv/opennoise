"""Capture eight per-track licensed FMA excerpts through bounded native ZIP ranges."""

from __future__ import annotations

import bz2
import hashlib
import html
import json
import os
import shutil
import struct
import zlib
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx

from opennoise.ingest.fma.corpus import source_rows, verify_sources
from opennoise.serving.metadata.fma_identity_bridge import write

URL = "https://os.unil.cloud.switch.ch/fma/fma_small.zip"
ZIP_HEADER_BYTES = 30
ZIP_DIRECTORY_BYTES = 46
ZIP_BZIP2 = 12
ZIP_DEFLATE = 8
ZIP64_SENTINEL = 0xFFFFFFFF

MAX_RANGE = 2_000_000
MAX_AUDIO = 15_000_000
COUNT = 8
LICENSES = {
    f"{scheme}://creativecommons.org/{path}/"
    for scheme in ("http", "https")
    for path in (
        "publicdomain/zero/1.0",
        "licenses/by/3.0",
        "licenses/by/4.0",
        "licenses/by-sa/3.0",
        "licenses/by-sa/4.0",
    )
}


def read_range(  # noqa: PLR0913, PLR0917 — explicit bounded HTTP range custody arguments.
    client: httpx.Client, output: Path, name: str, start: int, end: int, size: int, etag: str
) -> dict[str, Any]:
    """Retain exact native range bytes, ETag, dated response and complete transfer digest."""
    if end - start + 1 > MAX_RANGE:
        raise ValueError("range exceeds bounded listening acquisition")
    with client.stream(
        "GET",
        URL,
        headers={"Range": f"bytes={start}-{end}", "If-Match": etag, "Accept-Encoding": "identity"},
    ) as response:
        if (
            response.status_code != HTTPStatus.PARTIAL_CONTENT
            or response.headers.get("content-range") != f"bytes {start}-{end}/{size}"
            or response.headers.get("etag") != etag
        ):
            raise ValueError("native audio ZIP range or ETag differs")
        count = 0
        digest = hashlib.sha256()
        with (output / name).open("xb") as stream:
            for chunk in response.iter_raw(65536):
                count += len(chunk)
                if count > end - start + 1:
                    raise ValueError("native range exceeds expected bound")
                digest.update(chunk)
                stream.write(chunk)
        if count != end - start + 1:
            raise ValueError("native audio range truncated")
        return {
            "url": URL,
            "path": name,
            "start": start,
            "end": end,
            "archive_bytes": size,
            "etag": etag,
            "status": response.status_code,
            "sha256": digest.hexdigest(),
            "bytes": count,
            "fetched_at": datetime.now(UTC).isoformat(),
        }


def directory_members(body: bytes) -> dict[int, dict[str, Any]]:
    """Read exact ZIP directory members without trusting names as cross-dataset identities."""
    cursor = 0
    members = {}
    while cursor < len(body):
        fields = struct.unpack_from("<4s6H3L5H2L", body, cursor)
        if (
            fields[0] != b"PK\x01\x02"
            or fields[3] & 1
            or fields[4] not in {0, ZIP_DEFLATE, ZIP_BZIP2}
        ):
            raise ValueError("unsupported native audio ZIP member")
        name_size, extra, comment = fields[10:13]
        name = body[cursor + 46 : cursor + 46 + name_size].decode()
        if name.endswith(".mp3"):
            identity = int(Path(name).stem)
            if identity in members:
                raise ValueError("duplicate native FMA track filename")
            offset = fields[16]
            if offset == ZIP64_SENTINEL:
                extra_body = body[cursor + 46 + name_size : cursor + 46 + name_size + extra]
                extra_pos = 0
                found = False
                while extra_pos + 4 <= len(extra_body):
                    tag, length = struct.unpack_from("<HH", extra_body, extra_pos)
                    if tag == 1:
                        offset = struct.unpack_from("<Q", extra_body, extra_pos + 4)[0]
                        found = True
                        break
                    extra_pos += length + 4
                if not found:
                    raise ValueError("missing ZIP64 offset extension")
            members[identity] = {
                "name": name,
                "method": fields[4],
                "flags": fields[3],
                "crc32": fields[7],
                "compressed": fields[8],
                "uncompressed": fields[9],
                "offset": offset,
            }
        cursor += 46 + name_size + extra + comment
    if cursor != len(body):
        raise ValueError("native directory boundary differs")
    return members


def selected_tracks(
    source: Path, members: dict[int, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Freeze a deterministic source-only licensed cohort before requesting any audio."""
    receipt = verify_sources(source)
    rows, checked, handles = source_rows(source, receipt["members"]["fma_metadata/raw_tracks.csv"])
    eligible = []
    total = 0
    try:
        for row in rows:
            total += 1
            identity = int(row["track_id"])
            if (
                row["license_url"] in LICENSES
                and identity in members
                and members[identity]["uncompressed"] <= MAX_RANGE
                and members[identity]["compressed"] <= MAX_RANGE
            ):
                eligible.append(
                    {
                        key: row[key]
                        for key in (
                            "track_id",
                            "artist_id",
                            "artist_name",
                            "track_title",
                            "track_url",
                            "license_url",
                            "license_title",
                            "track_copyright_c",
                            "track_copyright_p",
                            "track_composer",
                            "track_genres",
                        )
                    }
                )
        if not checked.complete:
            raise ValueError("native license source did not reach verified EOF")
        custody = {
            "source_sha256": checked.sha256.hexdigest(),
            "source_bytes": checked.length,
            "native_tracks": total,
            "eligible_license_and_archive_tracks": len(eligible),
            "crc32": f"{checked.crc:08x}",
        }
    finally:
        for handle in handles:
            handle.close()
    eligible.sort(
        key=lambda row: hashlib.sha256(
            f"opennoise-licensed-listening-v1:{row['track_id']}".encode()
        ).hexdigest()
    )
    if len(eligible) < COUNT:
        raise ValueError("insufficient strict licensed source tracks")
    return eligible[:COUNT], custody


def capture_audio(source: Path, probe_directory: Path, output: Path) -> None:  # noqa: C901, PLR0912, PLR0915 — bounded native ZIP custody.
    """Freeze licenses before downloading eight bounded native audio members."""
    output.mkdir(parents=True, exist_ok=False)
    tail = (probe_directory / "central-directory.range").read_bytes()
    probe = json.loads((probe_directory / "tail-receipt.json").read_bytes())
    if hashlib.sha256(tail).hexdigest() != probe["sha256"]:
        raise ValueError("probe native bytes changed")
    with (output / "tail.range").open("xb") as stream:
        stream.write(tail)
    write(output / "tail-receipt.json", probe)
    size = int(probe["headers"]["content-range"].split("/")[1])
    etag = probe["headers"]["etag"]
    end = tail.rfind(b"PK\x05\x06")
    eocd = struct.unpack_from("<4s4H2LH", tail, end)
    if eocd[1] or eocd[2] or eocd[3] != eocd[4] or eocd[5] > MAX_RANGE:
        raise ValueError("unsupported native audio ZIP directory")
    if eocd[6] == ZIP64_SENTINEL:
        record = tail.rfind(b"PK\x06\x06")
        extended = struct.unpack_from("<4sQ2H2L4Q", tail, record)
        directory_size, directory_offset = extended[-2:]
    else:
        directory_size, directory_offset = eocd[5:7]
    captures = []
    tracks = []
    with httpx.Client(timeout=30) as client:
        directory = read_range(
            client,
            output,
            "directory.range",
            directory_offset,
            directory_offset + directory_size - 1,
            size,
            etag,
        )
        captures.append(directory)
        members = directory_members((output / "directory.range").read_bytes())
        selected, custody = selected_tracks(source, members)
        write(
            output / "selection.json",
            {"seed": "opennoise-licensed-listening-v1", "tracks": selected, "source": custody},
        )
        audio_bytes = 0
        for row in selected:
            member = members[int(row["track_id"])]
            start = member["offset"]
            header = read_range(
                client,
                output,
                f"{row['track_id']}-header.range",
                start,
                start + 29,
                size,
                etag,
            )
            captures.append(header)
            fields = struct.unpack("<4s5H3L2H", (output / header["path"]).read_bytes())
            if (
                fields[0] != b"PK\x03\x04"
                or fields[3] != member["method"]
                or (
                    not member["flags"] & 8
                    and fields[6:9]
                    != (member["crc32"], member["compressed"], member["uncompressed"])
                )
            ):
                raise ValueError("native audio local header differs")
            prefix = fields[9] + fields[10]
            payload = read_range(
                client,
                output,
                f"{row['track_id']}-payload.range",
                start + 30,
                start + 29 + prefix + member["compressed"],
                size,
                etag,
            )
            captures.append(payload)
            raw = (output / payload["path"]).read_bytes()
            if raw[: fields[9]] != member["name"].encode():
                raise ValueError("native audio filename differs")
            if member["method"] == 0:
                audio = raw[prefix:]
            elif member["method"] == ZIP_BZIP2:
                decoder = bz2.BZ2Decompressor()
                audio = decoder.decompress(raw[prefix:], max_length=MAX_RANGE + 1)
                if not decoder.eof:
                    raise ValueError("native audio decompression exceeds bound")
            else:
                decoder = zlib.decompressobj(-15)
                audio = decoder.decompress(raw[prefix:], max_length=MAX_RANGE + 1)
                if not decoder.eof:
                    raise ValueError("native audio decompression exceeds bound")
            if len(audio) != member["uncompressed"] or zlib.crc32(audio) != member["crc32"]:
                raise ValueError("native audio CRC or length differs")
            audio_bytes += len(audio)
            if audio_bytes > MAX_AUDIO:
                raise ValueError("permitted listening audio byte budget exceeded")
            audio_path = f"{row['track_id']}.mp3"
            with (output / audio_path).open("xb") as stream:
                stream.write(audio)
            tracks.append(
                {
                    **row,
                    "audio_path": audio_path,
                    "audio_bytes": len(audio),
                    "audio_sha256": hashlib.sha256(audio).hexdigest(),
                    "clip_scope": "FMA small native 30-second excerpt; not a full recording",
                    "attribution": (
                        f"{row['track_title']} — {row['artist_name']}; "
                        "FMA dataset Defferrard et al. ISMIR 2017"
                    ),
                    "source_member": member,
                    "provider_region": "not_recorded",
                    "musical_representativeness": "not_judged",
                }
            )
    write(
        output / "listening.json",
        {
            "revision": "fma-permitted-listening-v1",
            "tracks": tracks,
            "captures": captures,
            "selection_source": custody,
            "probe_sha256": probe["sha256"],
            "audio_bytes": audio_bytes,
        },
    )


def decode_audio(raw: bytes, method: int) -> bytes:
    """Bound decompression before exposing exact licensed MP3 bytes."""
    if method == 0:
        return raw
    if method == ZIP_BZIP2:
        decoder = bz2.BZ2Decompressor()
        audio = decoder.decompress(raw, max_length=MAX_RANGE + 1)
    elif method == ZIP_DEFLATE:
        decoder = zlib.decompressobj(-15)
        audio = decoder.decompress(raw, max_length=MAX_RANGE + 1)
    else:
        raise ValueError("unsupported native audio compression")
    if not decoder.eof or len(audio) > MAX_RANGE:
        raise ValueError("native audio decompression exceeds bound")
    return audio


def bound_file(pack: Path, name: str, expected_sha: str, expected_bytes: int) -> bytes:
    """Read only exact bounded regular pack files with pinned byte hashes."""
    file = pack / name
    if pack.is_symlink() or file.is_symlink() or file.name != name or not file.is_file():
        raise ValueError("native listening path or symlink differs")
    if file.stat().st_size != expected_bytes or expected_bytes > MAX_RANGE:
        raise ValueError("native listening file exceeds bound or differs")
    body = file.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected_sha:
        raise ValueError("native listening byte hash differs")
    return body


def verify_fma_listening_pack(pack: Path, source: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 — complete per-track native range/license replay.
    """Replay full native licenses, frozen cohort, ZIP directory, MP3 CRC and byte custody."""
    if pack.is_symlink() or any(p.is_symlink() or not p.is_file() for p in pack.iterdir()):
        raise ValueError("native listening pack must contain regular files only")
    result = json.loads((pack / "listening.json").read_bytes())
    if result["revision"] != "fma-permitted-listening-v1" or len(result["tracks"]) != COUNT:
        raise ValueError("unexpected native listening scope")
    probe = json.loads((pack / "tail-receipt.json").read_bytes())
    tail = bound_file(pack, "tail.range", probe["sha256"], probe["bytes"])
    if probe["url"] != URL or probe["status"] != HTTPStatus.PARTIAL_CONTENT:
        raise ValueError("native audio provider probe differs")
    size = int(probe["headers"]["content-range"].split("/")[1])
    etag = probe["headers"]["etag"]
    expected_paths = {"listening.json", "selection.json", "tail.range", "tail-receipt.json"}
    ranges = {}
    for capture in result["captures"]:
        name = capture["path"]
        if name in ranges or not name.endswith(".range"):
            raise ValueError("duplicate native listening range")
        if (
            capture["url"] != URL
            or capture["status"] != HTTPStatus.PARTIAL_CONTENT
            or capture["archive_bytes"] != size
            or capture["etag"] != etag
            or capture["end"] - capture["start"] + 1 != capture["bytes"]
        ):
            raise ValueError("native audio range receipt differs")
        datetime.fromisoformat(capture["fetched_at"])
        ranges[name] = bound_file(pack, name, capture["sha256"], capture["bytes"])
        expected_paths.add(name)
    end = tail.rfind(b"PK\x05\x06")
    eocd = struct.unpack_from("<4s4H2LH", tail, end)
    if eocd[6] == ZIP64_SENTINEL:
        extended = struct.unpack_from("<4sQ2H2L4Q", tail, tail.rfind(b"PK\x06\x06"))
        directory_size, directory_offset = extended[-2:]
    else:
        directory_size, directory_offset = eocd[5:7]
    directory_capture = result["captures"][0]
    if (
        directory_capture["path"] != "directory.range"
        or directory_capture["start"] != directory_offset
        or directory_capture["bytes"] != directory_size
    ):
        raise ValueError("native listening directory position differs")
    if result["probe_sha256"] != probe["sha256"]:
        raise ValueError("native listening probe binding differs")
    directory = directory_members(ranges["directory.range"])
    selected, custody = selected_tracks(source, directory)
    selection = json.loads((pack / "selection.json").read_bytes())
    if (
        selection
        != {"seed": "opennoise-licensed-listening-v1", "tracks": selected, "source": custody}
        or result["selection_source"] != custody
    ):
        raise ValueError("native listening frozen license selection differs")
    if len(result["captures"]) != 1 + 2 * COUNT:
        raise ValueError("native listening range cohort differs")
    total = 0
    for i, (original, track) in enumerate(zip(selected, result["tracks"], strict=True)):
        if any(track[key] != value for key, value in original.items()):
            raise ValueError("native source track license or credit changed")
        identity = int(track["track_id"])
        member = directory[identity]
        if member != track["source_member"]:
            raise ValueError("native listening ZIP member changed")
        fields = struct.unpack("<4s5H3L2H", ranges[f"{identity}-header.range"])
        prefix = fields[9] + fields[10]
        header_capture, payload_capture = result["captures"][1 + 2 * i : 3 + 2 * i]
        if (
            header_capture["path"] != f"{identity}-header.range"
            or header_capture["start"] != member["offset"]
            or header_capture["bytes"] != ZIP_HEADER_BYTES
            or payload_capture["path"] != f"{identity}-payload.range"
            or payload_capture["start"] != member["offset"] + ZIP_HEADER_BYTES
            or payload_capture["bytes"] != prefix + member["compressed"]
        ):
            raise ValueError("native audio member range position differs")
        raw = ranges[f"{identity}-payload.range"]
        if (
            fields[0] != b"PK\x03\x04"
            or fields[3] != member["method"]
            or raw[: fields[9]] != member["name"].encode()
        ):
            raise ValueError("native listening local header or filename differs")
        audio = decode_audio(raw[prefix:], member["method"])
        if len(audio) != member["uncompressed"] or zlib.crc32(audio) != member["crc32"]:
            raise ValueError("native listening MP3 CRC or size differs")
        expected_name = f"{identity}.mp3"
        if track["audio_path"] != expected_name:
            raise ValueError("native listening audio path differs")
        exposed = bound_file(pack, expected_name, track["audio_sha256"], track["audio_bytes"])
        if exposed != audio:
            raise ValueError("exposed listening audio differs from native ZIP member")
        total += len(exposed)
        expected_paths.add(expected_name)
    if (
        total > MAX_AUDIO
        or total != result["audio_bytes"]
        or {p.name for p in pack.iterdir()} != expected_paths
    ):
        raise ValueError("native listening byte budget or closed file inventory differs")
    return result


def export_fma_listening(pack: Path, source: Path, output: Path) -> dict[str, Any]:
    """Export only verified excerpts with visible per-track attribution and user controls."""
    result = verify_fma_listening_pack(pack, source)
    output.mkdir(parents=True, exist_ok=False)
    cards = []
    files = {}
    for track in result["tracks"]:
        path = track["audio_path"]
        try:
            os.link(pack / path, output / path)
        except OSError:
            with (pack / path).open("rb") as incoming, (output / path).open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=65536)
        files[path] = {"sha256": track["audio_sha256"], "bytes": track["audio_bytes"]}
        text = html.escape
        cards.append(
            f"<li><h2>{text(track['track_title'])}</h2>"
            f"<p>{text(track['artist_name'])} · FMA track {text(track['track_id'])}</p>"
            f'<audio data-track-id="{text(track["track_id"])}" controls preload="none" '
            f'src="{text(path)}"></audio>'
            f"<p>{text(track['attribution'])}</p><p>"
            f'<a href="{text(track["license_url"], quote=True)}">'
            f"{text(track['license_title'])}</a>"
            f' · <a href="{text(track["track_url"], quote=True)}">Track source</a></p>'
            f"<p>{text(track['track_copyright_c'])} {text(track['track_copyright_p'])}</p></li>"
        )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width">'
        "<title>OpenNoise — permitted listening</title><style>body{font:16px "
        "system-ui;max-width:48rem;margin:2rem auto;padding:0 1rem}li{margin:2rem "
        "0}audio{max-width:100%}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem}a{color:#1259a6}</style>"
        '<a class="skip" href="#main">Skip to listening</a><main id="main" '
        'tabindex="-1"><h1>Permitted listening</h1>'
        "<p>Eight native FMA 30-second excerpts, selected from declared open per-track "
        "licenses. These are source examples; musical representativeness has not been "
        "reviewed. Press play to listen.</p><ol>" + "".join(cards) + "</ol></main></html>"
    )
    body = page.encode()
    with (output / "index.html").open("xb") as stream:
        stream.write(body)
    native_manifest = (pack / "listening.json").read_bytes()
    with (output / "listening.json").open("xb") as stream:
        stream.write(native_manifest)
    files["listening.json"] = {
        "sha256": hashlib.sha256(native_manifest).hexdigest(),
        "bytes": len(native_manifest),
    }
    files["index.html"] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    manifest = {
        "revision": "fma-permitted-listening-static-v1",
        "source_projection_sha256": hashlib.sha256(
            (pack / "listening.json").read_bytes()
        ).hexdigest(),
        "tracks": [t["track_id"] for t in result["tracks"]],
        "files": files,
        "autoplay": False,
        "audio_scope": "8 native per-track licensed 30-second excerpts",
        "metadata_license": "CC-BY-4.0",
    }
    write(output / "manifest.json", manifest)
    return manifest
