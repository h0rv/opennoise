"""Serve a pre-exported static OpenNoise directory on loopback."""

from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    """Run the sole local delivery path without constructing an application backend."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("dist"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3001)
    raw_arguments = sys.argv[1:]
    if raw_arguments[:1] == ["--"]:
        raw_arguments = raw_arguments[1:]
    arguments = parser.parse_args(raw_arguments)
    if not (arguments.directory / "index.html").is_file():
        parser.error(
            f"{arguments.directory} has no static export; "
            "run `uv run poe export-semantic-pages` first"
        )
    handler = partial(SimpleHTTPRequestHandler, directory=str(arguments.directory))
    with ThreadingHTTPServer((arguments.host, arguments.port), handler) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
