"""Capture and replay native MusicBrainz FMA URL assertions, never artist names."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

if TYPE_CHECKING:
    from pathlib import Path

import httpx

from opennoise.ingest.fma.corpus import source_rows, verify_sources

QUERY = "url:*freemusicarchive.org* AND (targettype:artist OR targettype:recording)"
LIMIT = 100
MAX_PAGES = 20
MAX_BYTES = 2_000_000
REVISION = "fma-exact-url-identity-bridge-v1"


def digest(body: bytes) -> str:
    """Bind original native bytes."""
    return hashlib.sha256(body).hexdigest()


def write(path: Path, value: object) -> None:
    """Never overwrite existing recovery or source artifacts."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def native_fma(directory: Path) -> tuple[dict[str, Any], dict[str, dict[str, set[int]]]]:
    """Read every native row to verified CRC EOF, retaining literal entity URLs only."""
    receipt = verify_sources(directory)
    index: dict[str, dict[str, set[int]]] = {"artist": {}, "recording": {}}
    facts = {}
    for kind, member_name, id_field, url_field in (
        ("artist", "artists", "artist_id", "artist_url"),
        ("recording", "tracks", "track_id", "track_url"),
    ):
        member = receipt["members"][f"fma_metadata/raw_{member_name}.csv"]
        rows, checked, handles = source_rows(directory, member)
        count = 0
        try:
            for row in rows:
                count += 1
                url = row[url_field]
                if url:
                    index[kind].setdefault(url, set()).add(int(row[id_field]))
            if not checked.complete:
                raise ValueError("native FMA member did not reach verified EOF")
            facts[kind] = {
                "rows": count,
                "source_sha256": checked.sha256.hexdigest(),
                "source_bytes": checked.length,
                "crc32": f"{checked.crc:08x}",
            }
        finally:
            for handle in handles:
                handle.close()
    return facts, index


def require_uuid(value: str) -> str:
    """Require native canonical UUIDs rather than plausible external labels."""
    if str(UUID(value)) != value:
        raise ValueError("noncanonical MusicBrainz UUID")
    return value


def capture_file(directory: Path, capture: dict[str, Any], expected: str) -> bytes:
    """Reject path rewriting, symlinks and oversized native captures before reading."""
    path = directory / expected
    if directory.is_symlink() or capture["path"] != expected or path.is_symlink():
        raise ValueError("native source path or symlink differs")
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("oversized or absent native source capture")
    body = path.read_bytes()
    if digest(body) != capture["sha256"] or len(body) != capture["bytes"]:
        raise ValueError("native source byte binding changed")
    return body


def project(directory: Path, source: Path) -> dict[str, Any]:  # noqa: C901, PLR0912 — complete native census replay and denominator checks.
    """Replay exact source URL/entity-kind relations with conflicts kept unresolved."""
    if directory.is_symlink() or any(
        p.is_symlink() or not p.is_file() for p in directory.iterdir()
    ):
        raise ValueError("native bridge pack must contain regular files only")
    receipt = json.loads((directory / "receipt.json").read_bytes())
    if receipt["revision"] != REVISION or receipt["query"] != QUERY:
        raise ValueError("unexpected bridge source query")
    expected = {
        "receipt.json",
        "bridge.json",
        *(f"page-{i:03d}.json" for i in range(len(receipt["captures"]))),
    }
    if {p.name for p in directory.iterdir()} not in (expected, expected - {"bridge.json"}):
        raise ValueError("native bridge source pack is not closed")
    if sum(c["bytes"] for c in receipt["captures"]) > MAX_BYTES:
        raise ValueError("native bridge replay exceeds byte budget")
    facts, index = native_fma(source)
    candidates: dict[str, dict[int, dict[str, set[str]]]] = {"artist": {}, "recording": {}}
    seen_urls = set()
    total = None
    for offset, capture in enumerate(receipt["captures"]):
        if capture["offset"] != offset * LIMIT or capture["status"] != HTTPStatus.OK:
            raise ValueError("noncontiguous or failed native URL search")
        parsed = urlsplit(capture["url"])
        if (
            parsed.scheme != "https"
            or parsed.netloc != "musicbrainz.org"
            or parsed.path != "/ws/2/url/"
            or parse_qs(parsed.query)
            != {
                "query": [QUERY],
                "limit": [str(LIMIT)],
                "offset": [str(offset * LIMIT)],
                "fmt": ["json"],
            }
        ):
            raise ValueError("native URL search endpoint or query differs")
        body = capture_file(directory, capture, f"page-{offset:03d}.json")
        payload = json.loads(body)
        if payload["offset"] != offset * LIMIT or (total is not None and total != payload["count"]):
            raise ValueError("native search count or offset changed during capture")
        total = payload["count"]
        if len(payload["urls"]) != min(LIMIT, total - offset * LIMIT):
            raise ValueError("native page missing rows")
        for url in payload["urls"]:
            require_uuid(url["id"])
            if url["id"] in seen_urls:
                raise ValueError("duplicate URL entity across pages")
            seen_urls.add(url["id"])
            for relation_list in url.get("relation-list", []):
                for relation in relation_list["relations"]:
                    for kind in ("artist", "recording"):
                        if kind not in relation or relation.get("direction") != "backward":
                            continue
                        entity = relation[kind]
                        for native_id in index[kind].get(url["resource"], set()):
                            by_mbid = candidates[kind].setdefault(native_id, {})
                            by_mbid.setdefault(require_uuid(entity["id"]), set()).add(
                                capture["sha256"]
                            )
    if total != len(seen_urls) or len(receipt["captures"]) > MAX_PAGES:
        raise ValueError("incomplete native search denominator")
    result: dict[str, Any] = {
        "revision": REVISION,
        "native_fma": facts,
        "native_musicbrainz_urls": total,
        "method": (
            "literal source URL equality and matching entity kind; no name joins or URI rewriting"
        ),
        "license": "FMA metadata CC-BY-4.0; MusicBrainz core URL relationship metadata CC0-1.0",
        "attribution": "FMA: A Dataset For Music Analysis, Defferrard et al., ISMIR 2017",
        "audio_downloaded": False,
        "assertion_scope": (
            "native source identity assertions, not independent music "
            "or recording equivalence judgments"
        ),
    }
    for kind in ("artist", "recording"):
        resolved = []
        conflicts = []
        for native_id, matches in sorted(candidates[kind].items()):
            row = {
                "fma_id": native_id,
                "musicbrainz_mbids": sorted(matches),
                "evidence_sha256": sorted({sha for refs in matches.values() for sha in refs}),
            }
            (resolved if len(matches) == 1 else conflicts).append(row)
        result[kind] = {
            "eligible": facts[kind]["rows"],
            "resolved": resolved,
            "conflicts": conflicts,
            "unresolved": facts[kind]["rows"] - len(resolved),
        }
    return result


def capture(output: Path) -> None:
    """Capture a bounded complete provider URL census with original bytes and timestamps."""
    output.mkdir(parents=True, exist_ok=False)
    captures = []
    bytes_used = 0
    with httpx.Client(
        timeout=30, headers={"User-Agent": "OpenNoise/0.1 (https://github.com/h0rv/opennoise)"}
    ) as client:
        for page in range(MAX_PAGES):
            params = {"query": QUERY, "limit": LIMIT, "offset": page * LIMIT, "fmt": "json"}
            for attempt in range(4):
                response = client.get("https://musicbrainz.org/ws/2/url/", params=params)
                if response.status_code == HTTPStatus.OK:
                    break
                error_path = f"page-{page:03d}-attempt-{attempt:02d}.json"
                with (output / error_path).open("xb") as stream:
                    stream.write(response.content)
                write(
                    output / f"page-{page:03d}-attempt-{attempt:02d}-receipt.json",
                    {
                        "url": str(response.url),
                        "status": response.status_code,
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "path": error_path,
                        "sha256": digest(response.content),
                        "bytes": len(response.content),
                    },
                )
                time.sleep(2)
            if response.status_code != HTTPStatus.OK:
                raise ValueError(f"native URL page returned {response.status_code}")
            body = response.content
            bytes_used += len(body)
            if bytes_used > MAX_BYTES:
                raise ValueError("native URL search byte budget exceeded")
            path = f"page-{page:03d}.json"
            with (output / path).open("xb") as stream:
                stream.write(body)
            captures.append(
                {
                    "offset": page * LIMIT,
                    "url": str(response.url),
                    "status": response.status_code,
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "path": path,
                    "sha256": digest(body),
                    "bytes": len(body),
                }
            )
            if (page + 1) * LIMIT >= response.json()["count"]:
                break
            time.sleep(1.1)
        else:
            raise ValueError("native URL search exceeds frozen page bound")
    write(output / "receipt.json", {"revision": REVISION, "query": QUERY, "captures": captures})


def verify_fma_exact_bridge(pack: Path, source: Path) -> dict[str, Any]:
    """Require saved output to equal independently replayed native source assertions."""
    result = project(pack, source)
    if result != json.loads((pack / "bridge.json").read_bytes()):
        raise ValueError("saved projection differs from independent native source replay")
    return result
