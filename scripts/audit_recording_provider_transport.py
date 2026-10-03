"""Audit HTTP transport for source-bound Spotify recording pages, never playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any, override
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

if TYPE_CHECKING:
    from email.message import Message
    from typing import IO

URL_RE = re.compile(r"https://open\.spotify\.com/track/[A-Za-z0-9]{22}")
TIMEOUT_SECONDS = 12
REVISION = "source-bound-recording-provider-transport-v2"
MAX_PACK_FILES = 52
MAX_CONTROL_BYTES = 2_000_000


def utc_now() -> str:
    """Return the UTC instant of an actual transport request or completion."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def permitted_url(url: str) -> bool:
    """Accept exact HTTPS Spotify track URLs with 22 ASCII base62 characters."""
    return URL_RE.fullmatch(url) is not None


class RestrictedRedirect(HTTPRedirectHandler):
    """Reject redirects so an observation remains bound to the literal source URL."""

    @override
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> Request | None:
        """Reject every redirect before another URL is requested."""
        raise HTTPError(req.full_url, code, "redirect not followed", headers, fp)


def _safe_inputs(pack: Path, facts: Path) -> None:
    """Reject rewritten receipt paths and symlinks before opening source captures."""
    if pack.is_symlink() or not pack.is_dir():
        raise ValueError("listening source pack must be a regular directory")
    _bounded_regular_pack(pack)
    if facts.is_symlink() or not facts.is_dir():
        raise ValueError("recording fact source must be a regular directory")
    for name in ("receipt.json", "selection.json", "recording-facts.json"):
        path = facts / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CONTROL_BYTES:
            raise ValueError("recording fact controls must be regular files")
    _validate_receipt_paths(pack)


def _bounded_regular_pack(pack: Path) -> None:
    """Reject unbounded or nonregular pack members before reading control JSON."""
    for index, path in enumerate(pack.iterdir()):
        if index >= MAX_PACK_FILES:
            raise ValueError("listening source pack exceeds bounded native roster")
        if path.is_symlink() or not path.is_file():
            raise ValueError("listening source pack must contain regular files only")
        if path.stat().st_size > MAX_CONTROL_BYTES:
            raise ValueError("listening source pack member exceeds native byte budget")


def _validate_receipt_paths(pack: Path) -> None:
    """Validate canonical paths and successful captures before native source replay."""
    receipt = json.loads((pack / "receipt.json").read_bytes())
    captures = receipt.get("captures", [])
    selection = receipt.get("selection", [])
    if len({tuple(pair) for pair in selection}) != len(selection):
        raise ValueError("duplicate listening selection")
    if len({capture["recording"] for capture in captures}) != len(captures):
        raise ValueError("duplicate recording capture")
    for index, capture in enumerate(captures):
        if capture.get("path") != f"recording-{index:03d}.json":
            raise ValueError("noncanonical recording capture path")
        if capture.get("status") != HTTPStatus.OK:
            raise ValueError("recording source capture must have HTTP 200 status")


def load_bound_destinations(pack: Path, facts: Path) -> list[dict[str, Any]]:
    """Replay a closed native pack against its verified recording and license roster."""
    # Reuse the native validator rather than trusting counts in the derived listing.
    from opennoise.serving.metadata.listening_destinations import (  # noqa: PLC0415
        verify_recording_listening_pack,
    )

    _safe_inputs(pack, facts)
    listing = verify_recording_listening_pack(pack, facts)
    recordings = listing["recordings"]
    if listing["missing"] or len(recordings) != listing["eligible_recordings"]:
        raise ValueError("listening projection must retain the complete recording roster")
    if len({row["recording_mbid"] for row in recordings}) != len(recordings):
        raise ValueError("duplicate projected recording identity")
    bound: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_relation_ids: set[str] = set()
    for row in recordings:
        for destination in row["destinations"]:
            url = destination["url"]
            if not permitted_url(url) or destination["relation"] != "free streaming":
                raise ValueError(
                    "destination must be a literal source free-streaming Spotify track"
                )
            if url in seen_urls or destination["source_url_mbid"] in seen_relation_ids:
                raise ValueError("duplicate literal destination")
            seen_urls.add(url)
            seen_relation_ids.add(destination["source_url_mbid"])
            bound.append(
                {
                    "recording_mbid": row["recording_mbid"],
                    "artist_mbid": row["artist_mbid"],
                    "title": row["title"],
                    "source_sha256": row["source_sha256"],
                    "source_url_mbid": destination["source_url_mbid"],
                    "relation": destination["relation"],
                    "url": url,
                }
            )
    return bound


def check_transport(url: str) -> dict[str, Any]:
    """Issue a bounded HEAD request and retain transport failures as unknown access."""
    if not permitted_url(url):
        raise ValueError("refusing URL outside literal Spotify track allowlist")
    started = utc_now()
    request = Request(  # noqa: S310 - exact HTTPS host/path allowlist validated above.
        url, method="HEAD", headers={"User-Agent": "OpenNoise-provider-transport/2.0"}
    )
    status: int | None = None
    final_url = url
    error: str | None = None
    try:
        with build_opener(RestrictedRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(response.status)
            final_url = response.geturl()
            if final_url != url:
                error = "response URL differs from literal source destination"
    except HTTPError as exc:
        status = exc.code
        error = f"HTTP {exc.code}; redirects are not followed"
    except (URLError, OSError, TimeoutError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "requested_at_utc": started,
        "completed_at_utc": utc_now(),
        "method": "HEAD",
        "http_status": status,
        "final_redirect_url": final_url,
        "transport_error": error,
        "transport_reachable": status == HTTPStatus.OK and error is None,
        "playback_verified": False,
        "availability": "unverified; regional and account access were not tested",
    }


def audit(pack: Path, facts: Path, out: Path) -> dict[str, Any]:
    """Write a new transport report after verified source replay; never acquire media."""
    if out.exists() or any(out.resolve().is_relative_to(path.resolve()) for path in (pack, facts)):
        raise FileExistsError(
            "transport report output must be a new directory outside source packs"
        )
    items = load_bound_destinations(pack, facts)
    results = [{**item, **check_transport(item["url"])} for item in items]
    report = {
        "revision": REVISION,
        "created_at_utc": utc_now(),
        "source_pack": str(pack),
        "recording_fact_pack": str(facts),
        "source_bindings": {
            f"{label}/{name}": hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for label, directory, names in (
                ("listening", pack, ("receipt.json", "listening-destinations.json")),
                ("facts", facts, ("receipt.json", "selection.json", "recording-facts.json")),
            )
            for name in names
        },
        "method": "HEAD with 12-second timeout; redirects rejected",
        "scope": "HTTP transport of exact source-bound literal Spotify track pages only",
        "limitations": [
            "HTTP 200 does not establish playback or playable content.",
            "Regional availability and account access remain unverified.",
            "No API, authentication, media, preview, embed or download request is made.",
            "Missing destinations and transport errors remain unknown access outcomes.",
        ],
        "destination_count": len(results),
        "results": results,
    }
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (out / "provider-page-status.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def main() -> int:
    """Audit explicit local source packs into a new report directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.pack, args.facts, args.out)
    sys.stdout.write(
        json.dumps({"output": str(args.out), "destinations": result["destination_count"]}) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
