"""Capture bounded arbitrary native recording pages and strict CC0 exact credits separately."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from opennoise.serving.metadata import recording_facts as core
from opennoise.serving.metadata import selected_recording_catalog as catalog
from opennoise.serving.metadata.selected_recording_catalog import canonical_json, sha256_file


def write(path: Path, value: object) -> None:
    """Create new provenance only; never replace existing artifacts."""
    with path.open("xb") as stream:
        stream.write(canonical_json(value))


class Capture:
    """Serialize bounded source custody including failed and excluded response bodies."""

    def __init__(self, output: Path) -> None:
        """Initialize a fresh capture ledger and global source byte accounting."""
        self.output = output
        self.started = time.monotonic()
        self.last = self.started - 1.1
        self.used = 0
        self.ledger: list[dict[str, Any]] = []

    def request(
        self, client: httpx.Client, stage: str, artist: str, recording: str | None = None
    ) -> dict[str, Any]:
        """No retries, redirects, media requests or supplementary inclusion parameters."""
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 >= catalog.MAX_RSS_BYTES:
            raise MemoryError("capture exceeds40 MB RSS guard; partial source custody preserved")
        if stage == "lookup" and recording is None:
            raise ValueError("exact recording identity required before lookup HTTP")
        url = (
            catalog.browse_url(artist)
            if stage == "browse"
            else core.recording_source_url(recording or "")
        )
        time.sleep(max(0, 1.1 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        row = {
            "sequence": len(self.ledger),
            "stage": stage,
            "artist_mbid": artist,
            "url": url,
            "fetched_at": datetime.now(UTC).isoformat(),
            "started_elapsed_seconds": self.last - self.started,
            "status_code": None,
            "outcome": "network_error",
            "bytes": 0,
            "complete_body": False,
        }
        if recording is not None:
            row["recording_mbid"] = recording
        body = bytearray()
        try:
            with client.stream("GET", row["url"]) as response:
                row["status_code"] = response.status_code
                row["headers"] = {
                    key: response.headers[key]
                    for key in ("content-type", "content-length", "date", "etag")
                    if key in response.headers
                }
                remaining = min(catalog.MAX_BODY, catalog.MAX_NATIVE_BYTES - self.used)
                if remaining <= 0:
                    row["outcome"] = "native_byte_budget"
                else:
                    for chunk in response.iter_bytes(chunk_size=1):
                        room = min(
                            catalog.MAX_BODY - len(body), catalog.MAX_NATIVE_BYTES - self.used
                        )
                        if len(chunk) > room:
                            row["outcome"] = "response_or_native_byte_budget"
                            break
                        body.extend(chunk)
                        self.used += len(chunk)
                        if len(body) == catalog.MAX_BODY or self.used == catalog.MAX_NATIVE_BYTES:
                            row["outcome"] = "response_or_native_byte_budget"
                            break
                    else:
                        row["complete_body"] = True
                        row["outcome"] = (
                            "complete_http_200"
                            if response.status_code == httpx.codes.OK
                            else "http_status"
                        )
        except httpx.HTTPError:
            row["outcome"] = "network_error"
        if body:
            path = f"custody/{row['sequence']:03d}.body"
            with (self.output / path).open("xb") as stream:
                stream.write(body)
            row.update(path=path, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        self.ledger.append(row)
        write(self.output / f"ledger/{row['sequence']:03d}.json", row)
        sys.stderr.write(f"{stage} {len(self.ledger)}: {row['outcome']} {len(body)} bytes\n")
        return row


def shard(  # noqa: PLR0913, PLR0917 - exact frozen pair/selection/capture custody roles.
    directory: Path,
    pairs: list[list[str]],
    selected: dict[str, Any],
    captures: list[dict[str, Any]],
    output: Path,
    candidate_sha: str,
) -> None:
    """Reuse the existing strict core-only projection and verifier unchanged."""
    names = {a["artist_mbid"]: a["name"] for a in selected["artists"]}
    artists = {}
    for artist, recording in pairs:
        artists.setdefault(
            artist, {"artist_mbid": artist, "name": names[artist], "recording_mbids": []}
        )["recording_mbids"].append(recording)
    selection = {
        "revision": core.REVISION,
        "selection_method": (
            "Frozen arbitrary native first-page exact credited IDs; no representative claim."
        ),
        "source_projection_sha256": candidate_sha,
        "artists": list(artists.values()),
    }
    directory.mkdir()
    (directory / "raw").mkdir()
    write(directory / "selection.json", selection)
    strict = []
    for native in captures:
        row = {
            key: native[key]
            for key in ("artist_mbid", "recording_mbid", "url", "fetched_at", "status_code")
        }
        row["outcome"] = (
            "unapproved_payload" if native["status_code"] == httpx.codes.OK else "http_status"
        )
        if native["status_code"] is None:
            row["outcome"] = "network_error"
        if native["outcome"] in {"native_byte_budget", "response_or_native_byte_budget"}:
            row["outcome"] = "byte_budget"
        if native["outcome"] == "complete_http_200" and "path" in native:
            body = (output / native["path"]).read_bytes()
            try:
                core.project_recording_fact(body, native["recording_mbid"], native["artist_mbid"])
            except (ValueError, TypeError, KeyError):
                pass
            else:
                target = directory / "raw" / f"{native['recording_mbid']}.json"
                if not target.exists():
                    os.link(output / native["path"], target)
                if target.read_bytes() == body:
                    row.update(
                        outcome="accepted_core",
                        path=f"raw/{native['recording_mbid']}.json",
                        sha256=native["sha256"],
                        bytes=native["bytes"],
                    )
        strict.append(row)
    artifact = core.replay_recording_facts(directory, selection, strict)
    write(directory / "recording-facts.json", artifact)
    receipt = {
        "revision": core.REVISION,
        "license": core.LICENSE,
        "license_url": core.LICENSE_URL,
        "scope": "portable_core_metadata_only",
        "metadata_only": True,
        "tags_or_genres_requested": False,
        "max_requests": core.MAX_REQUESTS,
        "max_response_bytes": core.MAX_BYTES,
        "request_count": len(strict),
        "response_bytes": sum(r["bytes"] for r in captures),
        "selection_sha256": sha256_file(directory / "selection.json")[0],
        "projection_sha256": sha256_file(directory / "recording-facts.json")[0],
        "captures": strict,
    }
    write(directory / "receipt.json", receipt)
    core.verify_recording_fact_pack(directory)


def freeze(output: Path, root: Path) -> dict[str, Any]:
    """Strictly replay the entire selected roster in a fresh process before any HTTP."""
    selected = catalog.roster(root)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "selection.json", selected)
    write(
        output / "freeze.json",
        {
            "revision": catalog.REVISION,
            "selection_sha256": sha256_file(output / "selection.json")[0],
            "roster_verifier_sha256": sha256_file(
                root / "src/opennoise/pipeline/portable_foundation.py"
            )[0],
            "source_files": {
                str(p.relative_to(root)): {"sha256": sha256_file(p)[0], "bytes": p.stat().st_size}
                for pack in catalog.CULTURAL_PACKS
                for p in sorted((root / "data/examples" / pack).rglob("*"))
                if p.is_file()
            },
        },
    )
    return {
        "frozen": True,
        "selected_artists": len(selected["artists"]),
        "roster_sha256": selected["roster_sha256"],
    }


def capture(output: Path, root: Path) -> dict[str, Any]:
    """Freeze the full roster before browsing, then exact lookup pairs before lookup HTTP."""
    selected = catalog.verify_frozen_roster(output, root)
    if {p.name for p in output.iterdir()} != {"selection.json", "freeze.json"}:
        raise ValueError("capture requires a fresh strictly frozen roster directory")
    for name in ("custody", "ledger", "shards"):
        (output / name).mkdir()
    state = Capture(output)
    with httpx.Client(
        timeout=20,
        follow_redirects=False,
        headers={
            "User-Agent": "OpenNoise/0.1 (bounded open core metadata; https://github.com/h0rv/opennoise)"
        },
    ) as client:
        browses = [state.request(client, "browse", a["artist_mbid"]) for a in selected["artists"]]
        projected = catalog.candidates(selected, browses, output)
        write(output / "candidates.json", projected)
        candidate_sha = sha256_file(output / "candidates.json")[0]
        for index, pairs in enumerate(projected["shards"]):
            captures = [
                state.request(client, "lookup", artist, recording) for artist, recording in pairs
            ]
            shard(
                output / "shards" / f"{index:03d}", pairs, selected, captures, output, candidate_sha
            )
    write(output / "captures.json", state.ledger)
    write(
        output / "receipt.json",
        {
            "revision": catalog.REVISION,
            "native_raw_scope": (
                "Unclassified raw custody; only separately verified individual "
                "lookup shards carry MusicBrainz core CC0 facts."
            ),
            "files": {
                p.relative_to(output).as_posix(): {
                    "sha256": sha256_file(p)[0],
                    "bytes": p.stat().st_size,
                }
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
        },
    )
    return {
        "captured": True,
        "independent_replay": "pending; run verify in separate bounded process",
        "actual_requests": len(state.ledger),
        "observed_native_body_bytes": state.used,
    }


def main() -> None:
    """Capture a fresh bounded source pack, or verify its frozen native bytes offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", choices=("freeze", "capture", "verify"))
    args = parser.parse_args()
    action = {"freeze": freeze, "capture": capture, "verify": catalog.verify_catalog}[args.command]
    result = action(args.output, args.root)
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
