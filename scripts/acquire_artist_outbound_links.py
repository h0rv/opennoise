"""Acquire bounded exact MusicBrainz artist URL relationships without following destinations."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

from opennoise.serving.metadata.artist_links import project_artist_links

_MAX_BYTES = 3_000_000
_MAX_ARTISTS = 10


def main() -> int:
    """Retain ten serial metadata responses and their verified link projection."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--artists", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artists = json.loads(args.artists.read_text())["artists"]
    if len(artists) > _MAX_ARTISTS:
        raise ValueError("artist URL acquisition permits at most ten exact identities")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "raw").mkdir()
    total = 0
    captures, projected = [], []
    with httpx.Client(
        timeout=30,
        follow_redirects=False,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded metadata research; https://github.com/h0rv/opennoise)"
        },
    ) as client:
        for index, artist in enumerate(artists):
            if index:
                time.sleep(1.1)
            artist_id = artist["artist_mbid"]
            url = f"https://musicbrainz.org/ws/2/artist/{artist_id}?inc=url-rels&fmt=json"
            with client.stream("GET", url) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise ValueError("artist relationship acquisition byte budget exceeded")
                    body.extend(chunk)
            digest = hashlib.sha256(body).hexdigest()
            payload = json.loads(body)
            projected.append(project_artist_links(payload, artist_id, digest))
            path = f"raw/{index:02d}.json"
            (args.output / path).write_bytes(body)
            captures.append(
                {
                    "artist_mbid": artist_id,
                    "url": url,
                    "sha256": digest,
                    "bytes": len(body),
                    "path": path,
                }
            )
    artifact = {
        "revision": "source-artist-outbound-links-v1",
        "artists": projected,
        "limitations": (
            "Source-declared destinations; availability and listening access "
            "are not guaranteed. No audio or destination requests."
        ),
        "rights": "MusicBrainz core URL relationship metadata CC0.",
    }
    output = json.dumps(artifact, indent=2).encode() + b"\n"
    (args.output / "artist-links.json").write_bytes(output)
    receipt = {
        "license": "MusicBrainz core metadata CC0 1.0",
        "license_url": "https://musicbrainz.org/doc/About/Data_License",
        "captures": captures,
        "total_bytes": total,
        "projection_sha256": hashlib.sha256(output).hexdigest(),
    }
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
