"""Verify an extracted OpenNoise bundle and serve it on loopback using only the stdlib."""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_FILES = 10_000
MAX_BYTES = 250_000_000
MAX_FILE_BYTES = 4_000_000
REVISION = "opennoise-local-listening-bundle-v1"


def inventory(root: Path, *, exclude_manifest: bool = False) -> dict[str, dict[str, int | str]]:
    """Hash a bounded, closed tree without following symbolic links."""
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("bundle path contains a symbolic link")
    result = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("bundle contains a symbolic link")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if exclude_manifest and relative == "MANIFEST.json":
            continue
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
            raise ValueError("bundle file is missing, empty, or oversized")
        body = path.read_bytes()
        total += len(body)
        result[relative] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        if len(result) > MAX_FILES or total > MAX_BYTES:
            raise ValueError("bundle exceeds its file or byte limit")
    return result


def verify(root: Path) -> dict[str, Any]:
    """Check every packaged file, including the launcher, before opening a listener."""
    path = root / "MANIFEST.json"
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("invalid bundle manifest")
    manifest = json.loads(path.read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("revision") != REVISION
        or manifest.get("public_deployment_authorized") is not False
        or manifest.get("files") != inventory(root, exclude_manifest=True)
        or not {"serve.py", "README.txt", "site/index.html"}.issubset(manifest["files"])
    ):
        raise ValueError("bundle inventory or scope differs")
    return manifest


def main() -> None:
    """Serve verified files locally; loading a page never starts playback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:  # noqa: PLR2004 -- TCP port range.
        parser.error("port must be between 0 and 65535")
    root = Path(__file__).resolve().parent
    try:
        manifest = verify(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Bundle verification failed: {error}\n")
    print(f"Verified {len(manifest['files'])} files.", flush=True)  # noqa: T201
    if args.check_only:
        return
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root / "site"))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Open http://127.0.0.1:{server.server_port}/ — Ctrl+C stops it.", flush=True)  # noqa: T201
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()
