"""Bind recording-specific source listening destinations without acquiring media."""

from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from opennoise.serving.metadata.fma_identity_bridge import capture_file, require_uuid
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack

MAX_RECORDINGS = 50
MAX_RESPONSE_BYTES = 2_000_000

REVISION = "recording-listening-destinations-v1"
PROVIDERS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "soundcloud.com",
    "bandcamp.com",
    "music.apple.com",
    "open.spotify.com",
    "freemusicarchive.org",
    "www.freemusicarchive.org",
}
RELATIONS = {
    "streaming",
    "free streaming",
    "streaming music",
    "download for free",
    "purchase for download",
}


def digest(body: bytes) -> str:
    """Bind original native bytes."""
    return hashlib.sha256(body).hexdigest()


def write(path: Path, value: object) -> None:
    """Never overwrite existing recovery or source artifacts."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def approved_url(value: str) -> bool:
    """Admit literal public provider destinations only; never construct guessed recording URLs."""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    return (
        parsed.scheme in {"http", "https"}
        and not parsed.username
        and not parsed.password
        and (host in PROVIDERS or host.endswith(".bandcamp.com"))
    )


def projection(body: bytes, recording: str, artist: str) -> dict[str, Any]:
    """Require exact native recording identity and explicit artist credit before taking URLs."""
    require_uuid(recording)
    require_uuid(artist)
    payload = json.loads(body)
    if payload.get("id") != recording or artist not in {
        row["artist"]["id"] for row in payload.get("artist-credit", []) if isinstance(row, dict)
    }:
        raise ValueError("recording identity or exact artist credit does not match")
    destinations = []
    for relation in payload.get("relations", []):
        if relation.get("target-type") != "url" or relation.get("type") not in RELATIONS:
            continue
        url = relation["url"]["resource"]
        if approved_url(url):
            destinations.append(
                {
                    "url": url,
                    "relation": relation["type"],
                    "source_url_mbid": require_uuid(relation["url"]["id"]),
                    "availability": "not_checked",
                    "region": None,
                    "permission_scope": (
                        "external provider destination; no embed, preview, "
                        "media download or redistribution grant"
                    ),
                }
            )
    return {
        "recording_mbid": recording,
        "artist_mbid": artist,
        "title": payload["title"],
        "source_sha256": digest(body),
        "destinations": sorted(destinations, key=lambda row: row["url"]),
    }


def replay(output: Path, facts: Path) -> dict[str, Any]:
    """Bind full selected denominator and independently replay every captured byte."""
    if output.is_symlink() or any(p.is_symlink() or not p.is_file() for p in output.iterdir()):
        raise ValueError("native listening destination pack must contain regular files only")
    source = verify_recording_fact_pack(facts)
    selected = sorted(
        {
            (a["artist_mbid"], r["recording_mbid"])
            for a in source["artists"]
            for r in a["recordings"]
        }
    )
    receipt = json.loads((output / "receipt.json").read_bytes())
    if receipt["selection"] != [list(pair) for pair in selected] or receipt["revision"] != REVISION:
        raise ValueError("listening destination frozen selection differs")
    if len(receipt["captures"]) != len(selected):
        raise ValueError("missing capture outcomes")
    if (
        len(selected) > MAX_RECORDINGS
        or sum(c["bytes"] for c in receipt["captures"]) > MAX_RESPONSE_BYTES
    ):
        raise ValueError("listening replay exceeds frozen source budgets")
    expected = {
        "receipt.json",
        "listening-destinations.json",
        *(f"recording-{i:03d}.json" for i in range(len(selected))),
    }
    if {p.name for p in output.iterdir()} not in (
        expected,
        expected - {"listening-destinations.json"},
    ):
        raise ValueError("listening native source pack is not closed")
    recordings = []
    missing = []
    for i, ((artist, recording), capture) in enumerate(
        zip(selected, receipt["captures"], strict=True)
    ):
        if capture["artist"] != artist or capture["recording"] != recording:
            raise ValueError("capture order or identities differ")
        parsed = urlsplit(capture["url"])
        if (
            parsed.scheme != "https"
            or parsed.netloc != "musicbrainz.org"
            or parsed.path != f"/ws/2/recording/{recording}"
            or parse_qs(parsed.query) != {"inc": ["artist-credits url-rels"], "fmt": ["json"]}
        ):
            raise ValueError("native recording listening endpoint or query differs")
        body = capture_file(output, capture, f"recording-{i:03d}.json")
        if capture["status"] == HTTPStatus.OK:
            recordings.append(projection(body, recording, artist))
        else:
            missing.append(
                {"artist_mbid": artist, "recording_mbid": recording, "status": capture["status"]}
            )
    return {
        "revision": REVISION,
        "eligible_recordings": len(selected),
        "recordings": recordings,
        "missing": missing,
        "metadata_license": "MusicBrainz core metadata CC0-1.0",
        "availability_checked": False,
        "audio_downloaded": False,
        "representative_music_judgment": "not_established",
    }


def verify_recording_listening_pack(pack: Path, source: Path) -> dict[str, Any]:
    """Require saved output to equal independently replayed native source assertions."""
    result = replay(pack, source)
    if result != json.loads((pack / "listening-destinations.json").read_bytes()):
        raise ValueError("saved projection differs from independent native source replay")
    return result
