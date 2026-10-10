"""Offline export of byte-preserved, verified native FMA listening clips."""

from __future__ import annotations

import hashlib
import json
import math
import re
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from opennoise.serving.metadata import fma_listening64
from opennoise.serving.metadata.fma_listening import LICENSES

REVISION = "fma-local-playback-v1"
DECODE_PROTOCOL = "ffprobe-ffmpeg-mp3-full-decode-v1"
COLLECTION_REVISION = "fma-local-playback-collection-v1"
MAX_MANIFEST_BYTES = 200_000
MAX_DURATION_SECONDS = 31.0
PROCESS_TIMEOUT_SECONDS = 20
PROCESS_MEMORY_BYTES = 512_000_000
PROCESS_LOG_BYTES = 200_000


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked playback input or output")


def _process_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (PROCESS_MEMORY_BYTES, PROCESS_MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (PROCESS_LOG_BYTES, PROCESS_LOG_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _run(command: list[str], directory: Path, name: str) -> bytes:
    """Bound decoder CPU, address space, output files, open files and elapsed time."""
    with (
        (directory / f"{name}.out").open("xb") as output,
        (directory / f"{name}.err").open("xb") as errors,
    ):
        result = subprocess.run(  # noqa: S603 -- local, resolved binaries and fixed argument vectors.
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
            preexec_fn=_process_limits,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "OPENBLAS_NUM_THREADS": "1"},
        )
    if result.returncode:
        raise ValueError(f"local MP3 {name} failed with status {result.returncode}")
    return (directory / f"{name}.out").read_bytes()


def decode_duration(path: Path) -> float:
    """Probe and fully decode MP3 offline; no transcoding artifact is retained."""
    probe_binary, decode_binary = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not probe_binary or not decode_binary:
        raise ValueError("local ffprobe and ffmpeg are required")
    _safe(path)
    if not path.is_file() or not 0 < path.stat().st_size <= fma_listening64.MAX_RANGE_BYTES:
        raise ValueError("local MP3 size exceeds playback bound")
    with tempfile.TemporaryDirectory(prefix="fma-decode-") as name:
        directory = Path(name)
        raw = _run(
            [
                probe_binary,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-f",
                "mp3",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name",
                "-of",
                "json",
                str(path.resolve()),
            ],
            directory,
            "probe",
        )
        result = json.loads(raw)
        streams = result.get("streams", [])
        duration = float(result.get("format", {}).get("duration", "nan"))
        if (
            len(streams) != 1
            or streams[0].get("codec_type") != "audio"
            or streams[0].get("codec_name") != "mp3"
            or not math.isfinite(duration)
            or not 0 < duration <= MAX_DURATION_SECONDS
        ):
            raise ValueError("MP3 codec, stream count or duration exceeds playback contract")
        progress = directory / "progress.txt"
        _run(
            [
                decode_binary,
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-protocol_whitelist",
                "file",
                "-f",
                "mp3",
                "-threads",
                "1",
                "-i",
                str(path.resolve()),
                "-map",
                "0:a:0",
                "-threads",
                "1",
                "-progress",
                str(progress),
                "-f",
                "null",
                "-",
            ],
            directory,
            "decode",
        )
        readings = [
            int(line.split("=", 1)[1]) / 1_000_000
            for line in progress.read_text().splitlines()
            if line.startswith("out_time_us=")
        ]
        if not readings or not 0 < max(readings) <= MAX_DURATION_SECONDS:
            raise ValueError("decoded MP3 duration exceeds playback bound")
    return duration


def export_fma_playback(  # noqa: C901, PLR0915 -- validate all bytes before output.
    pack: Path, metadata_source: Path, output: Path
) -> dict[str, Any]:
    """Replay source custody, validate native MP3s, then export a fresh local-only directory."""
    _safe(pack)
    _safe(metadata_source)
    _safe(output)
    if output.exists():
        raise ValueError("playback output must be a fresh directory")
    verified = fma_listening64.verify(pack, metadata_source)
    receipt_bytes = (pack / "listening.json").read_bytes()
    if json.loads(receipt_bytes) != verified:
        raise ValueError("source pack changed after verification")
    rows = verified["tracks"]
    if not 0 < len(rows) <= fma_listening64.MAX_CLIPS:
        raise ValueError("playback clip count exceeds bound")
    tracks: dict[str, Any] = {}
    audio_blobs: dict[str, bytes] = {}
    total = 0
    with tempfile.TemporaryDirectory(prefix="fma-playback-validated-") as name:
        scratch = Path(name)
        for row in rows:
            identity, artist = row["track_id"], row["artist_id"]
            if (
                type(identity) is not int
                or identity <= 0
                or type(artist) is not int
                or artist <= 0
                or str(identity) in tracks
            ):
                raise ValueError("invalid or duplicate native playback identity")
            filename = f"{identity}.mp3"
            path = pack / filename
            _safe(path)
            if (
                row["audio_path"] != filename
                or not path.is_file()
                or not 0 < path.stat().st_size <= fma_listening64.MAX_RANGE_BYTES
                or path.stat().st_size != row["audio_bytes"]
            ):
                raise ValueError("native playback file size or path differs")
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if digest != row["audio_sha256"]:
                raise ValueError("native playback hash differs")
            total += len(body)
            if total > fma_listening64.MAX_AUDIO_BYTES:
                raise ValueError("aggregate playback audio budget exceeded")
            local = scratch / filename
            local.write_bytes(body)
            duration = decode_duration(local)
            if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION_SECONDS:
                raise ValueError("decoder returned unsupported duration")
            source = row["source"]
            if source["license_url"] not in LICENSES:
                raise ValueError("source audio license outside admitted set")
            title, artist_name = source["track_title"], source["artist_name"]
            tracks[str(identity)] = {
                "track_id": identity,
                "artist_id": artist,
                "title": title,
                "artist_name": artist_name,
                "audio_path": filename,
                "audio_sha256": digest,
                "audio_bytes": len(body),
                "duration_seconds": duration,
                "decode": {
                    "protocol": DECODE_PROTOCOL,
                    "audio_sha256": digest,
                    "full_decode": True,
                },
                "license_title": source["license_title"],
                "license_url": source["license_url"],
                "source_url": source["track_url"],
                "attribution": (
                    f"{title} — {artist_name}; {source['license_title']}; {source['track_url']}"
                ),
                "copyright_c": source["track_copyright_c"],
                "copyright_p": source["track_copyright_p"],
                "composer": source["track_composer"],
            }
            audio_blobs[filename] = body
    manifest = {
        "revision": REVISION,
        "test_only": False,
        "source_pack_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "audio_bytes": total,
        "tracks": tracks,
    }
    encoded = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("playback metadata exceeds 200 KB budget")
    output.mkdir(parents=True, exist_ok=False)
    for filename, body in audio_blobs.items():
        with (output / filename).open("xb") as stream:
            stream.write(body)
    with (output / "manifest.json").open("xb") as stream:
        stream.write(encoded)
    validate_playback_export(output)
    return manifest


def validate_playback_export(directory: Path) -> dict[str, Any]:
    """Replay local output pins and decode receipts; do not rerun decoding or claim signatures."""
    _safe(directory)
    path = directory / "manifest.json"
    _safe(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ValueError("playback manifest missing or oversized")
    manifest = json.loads(path.read_bytes())
    tracks = manifest.get("tracks")
    if (
        manifest.get("revision") not in {REVISION, COLLECTION_REVISION}
        or manifest.get("test_only") is not False
        or manifest.get("public_deployment_authorized") is not False
        or manifest.get("metadata_license") != "CC-BY-4.0"
        or (
            manifest.get("revision") == REVISION
            and (
                not isinstance(manifest.get("source_pack_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", manifest["source_pack_sha256"])
            )
        )
        or not isinstance(tracks, dict)
        or not 0 < len(tracks) <= fma_listening64.MAX_CLIPS
    ):
        raise ValueError("playback manifest scope or identity differs")
    if manifest["revision"] == COLLECTION_REVISION:
        from opennoise.deployment.fma_listening_collection import (  # noqa: PLC0415 -- explicit optional collection protocol.
            validate_collection_metadata,
        )

        validate_collection_metadata(manifest)
    expected = {"manifest.json"}
    total = 0
    string_fields = (
        "title",
        "artist_name",
        "license_title",
        "source_url",
        "attribution",
        "copyright_c",
        "copyright_p",
        "composer",
    )
    for key, track in tracks.items():
        if not isinstance(track, dict):
            raise ValueError("invalid playback track")  # noqa: TRY004 -- malformed external receipt.
        identity, artist = track.get("track_id"), track.get("artist_id")
        duration = track.get("duration_seconds")
        size = track.get("audio_bytes")
        digest = track.get("audio_sha256")
        if (
            type(identity) is not int
            or identity <= 0
            or key != str(identity)
            or type(artist) is not int
            or artist <= 0
            or type(duration) not in (int, float)
            or not math.isfinite(duration)
            or not 0 < duration <= MAX_DURATION_SECONDS
            or type(size) is not int
            or not 0 < size <= fma_listening64.MAX_RANGE_BYTES
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or track.get("license_url") not in LICENSES
            or any(not isinstance(track.get(field), str) for field in string_fields)
        ):
            raise ValueError("playback track metadata or bounds differ")
        evidence = track.get("decode")
        if (
            not isinstance(evidence, dict)
            or evidence.get("protocol") != DECODE_PROTOCOL
            or evidence.get("audio_sha256") != digest
            or evidence.get("full_decode") is not True
        ):
            raise ValueError("playback decode receipt differs")
        filename = f"{identity}.mp3"
        path = directory / filename
        _safe(path)
        if (
            track.get("audio_path") != filename
            or not path.is_file()
            or path.stat().st_size != size
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("playback audio bytes or filename differ")
        expected.add(filename)
        total += size
    if (
        type(manifest.get("audio_bytes")) is not int
        or manifest["audio_bytes"] != total
        or total > fma_listening64.MAX_AUDIO_BYTES
        or {p.name for p in directory.iterdir()} != expected
        or any(p.is_symlink() or not p.is_file() for p in directory.iterdir())
    ):
        raise ValueError("playback inventory or total audio budget differs")
    return manifest
