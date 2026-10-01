"""Verified source-declared outbound artist destinations, without media requests."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from pathlib import Path

_FIRST_PRINTABLE = 33

_PROVIDERS = {
    "spotify.com": "Spotify",
    "bandcamp.com": "Bandcamp",
    "soundcloud.com": "SoundCloud",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
}


def outbound_provider(url: str, relation_type: str) -> str | None:
    """Accept source URLs for known listening providers or official HTTPS sites."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or "\\" in url
        or any(ord(char) < _FIRST_PRINTABLE for char in url)
        or re.fullmatch(r"[a-z0-9.-]+", host) is None
    ):
        return None
    for domain, provider in _PROVIDERS.items():
        if host == domain or host.endswith("." + domain):
            return provider
    if relation_type != "official homepage" or "." not in host or host.endswith(".local"):
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return "Official website"
    return None


def project_artist_links(
    payload: dict[str, Any], artist_mbid: str, source_sha: str
) -> dict[str, Any]:
    """Project exact-ID artist URL relationships, preserving their source relation type."""
    if payload.get("id") != artist_mbid:
        raise ValueError("artist response does not match requested exact identity")
    links: dict[tuple[str, str], dict[str, str]] = {}
    metadata_links: list[dict[str, str]] = []
    for relation in payload.get("relations", []):
        if relation.get("target-type") != "url":
            continue
        relation_type = relation.get("type", "")
        url = relation.get("url", {}).get("resource", "")
        if relation_type == "discogs" and re.fullmatch(
            r"https://(?:www\.)?discogs\.com/(?:[a-z]{2}/)?artist/[0-9]+(?:-[^?#]*)?", url
        ):
            metadata_links.append(
                {
                    "provider": "Discogs",
                    "url": url,
                    "relation_type": relation_type,
                    "relation_type_id": relation.get("type-id", ""),
                    "source_sha256": source_sha,
                }
            )
        provider = outbound_provider(url, relation_type)
        if provider is None:
            continue
        links[(provider, url)] = {
            "provider": provider,
            "url": url,
            "relation_type": relation_type,
            "relation_type_id": relation.get("type-id", ""),
            "source_sha256": source_sha,
        }
    return {
        "artist_mbid": artist_mbid,
        "name": payload.get("name", artist_mbid),
        "links": [links[key] for key in sorted(links)],
        "metadata_links": sorted(metadata_links, key=lambda row: row["url"]),
    }


def verify_artist_link_projection(projection: Path, receipt: Path) -> dict[str, Any]:  # noqa: C901
    """Verify local CC0 projection bytes and reject unsafe or altered destinations."""
    body = projection.read_bytes()
    proof = json.loads(receipt.read_text())
    if (
        hashlib.sha256(body).hexdigest() != proof.get("projection_sha256")
        or proof.get("license") != "MusicBrainz core metadata CC0 1.0"
        or proof.get("license_url") != "https://musicbrainz.org/doc/About/Data_License"
    ):
        raise ValueError("artist link projection receipt differs")
    artifact = json.loads(body)
    if artifact.get("revision") != "source-artist-outbound-links-v1":
        raise ValueError("unknown artist link projection")
    captures = {row["artist_mbid"]: row["sha256"] for row in proof["captures"]}
    for capture in proof["captures"]:
        artist_id = capture["artist_mbid"]
        if (
            re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", artist_id) is None
            or re.fullmatch(r"[0-9a-f]{64}", capture["sha256"]) is None
            or capture["url"]
            != f"https://musicbrainz.org/ws/2/artist/{artist_id}?inc=url-rels&fmt=json"
        ):
            raise ValueError("artist source URL or exact identity differs")
        source = (receipt.parent / capture["path"]).resolve()
        if not source.is_relative_to(receipt.parent.resolve()):
            raise ValueError("artist link source path escapes receipt directory")
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != capture["sha256"]:
            raise ValueError("artist relationship source checksum differs")
        expected = project_artist_links(json.loads(raw), capture["artist_mbid"], capture["sha256"])
        actual = [
            artist
            for artist in artifact["artists"]
            if artist["artist_mbid"] == capture["artist_mbid"]
        ]
        if actual != [expected]:
            raise ValueError("artist link projection differs from exact source relationships")
    seen: set[str] = set()
    for artist in artifact["artists"]:
        artist_id = artist["artist_mbid"]
        if artist_id in seen or artist_id not in captures:
            raise ValueError("artist link identity lacks unique source capture")
        seen.add(artist_id)
        for link in artist["links"]:
            if (
                outbound_provider(link["url"], link["relation_type"]) != link["provider"]
                or link["source_sha256"] != captures[artist_id]
            ):
                raise ValueError("artist destination provider or source hash differs")
    return artifact
