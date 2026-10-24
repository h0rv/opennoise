"""Build, replay, scope-check and browser-certify the promoted public Pages payload."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from opennoise.deployment.public_catalog_release import promotion, release_marker
from opennoise.pipeline.catalog_demo import read, write
from scripts.certify_static_pages import _atomic_install, _wait_for_server


def main() -> int:
    """Install dist only after all source, promotion and browser gates pass."""
    overrides = {
        "OPENNOISE_SEMANTIC_MAP_LAYOUT",
        "OPENNOISE_DISCOVERY_DATABASE",
        "OPENNOISE_PAGES_OUTPUT",
    } & os.environ.keys()
    if overrides:
        raise ValueError("Public release rejects environment input/output overrides")
    root = Path.cwd().resolve()
    approval = promotion(root)
    (root / ".cache").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root / ".cache", prefix="promoted-public-pages-") as temp:
        work = Path(temp)
        output = work / "candidate"
        for command in ("build", "verify"):
            subprocess.run(  # noqa: S603 -- Fixed bounded source-only CLI.
                [
                    sys.executable,
                    "scripts/build_public_catalog_candidate.py",
                    command,
                    "--output",
                    str(output),
                ],
                check=True,
                timeout=310,
            )
        manifest = read(output / "payload-manifest.json")
        commit = (
            os.environ.get("GITHUB_SHA")
            or subprocess.check_output(  # noqa: S603 -- Resolved local Git, fixed read-only arguments.
                [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"], text=True
            ).strip()
        )
        write(output / "site/opennoise-release.json", release_marker(manifest, approval, commit))
        port = int(os.environ.get("OPENNOISE_PAGES_CERTIFY_PORT", "3001"))
        server = subprocess.Popen(  # noqa: S603 -- Loopback only, fixed static server.
            [
                sys.executable,
                "scripts/run_dev.py",
                "--directory",
                str(output / "site"),
                "--port",
                str(port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        try:
            url = f"http://127.0.0.1:{port}"
            _wait_for_server(url, server)
            subprocess.run(  # noqa: S603 -- Fixed local browser acceptance.
                [
                    shutil.which("node") or "/usr/bin/node",
                    "scripts/capture_retained_catalog_demo.mjs",
                    url + "/retained.html",
                    str(work / "browser"),
                ],
                check=True,
                timeout=120,
            )
            subprocess.run(  # noqa: S603 -- Artist-only browser gate on the same loopback export.
                [
                    shutil.which("node") or "/usr/bin/node",
                    "scripts/capture_artist_network.mjs",
                    url + "/retained.html",
                    str(work / "artist-browser"),
                ],
                check=True,
                timeout=120,
            )
            subprocess.run(  # noqa: S603 -- New atlas checked independently beside both prior scopes.
                [
                    shutil.which("node") or "/usr/bin/node",
                    "scripts/capture_genre_atlas.mjs",
                    url,
                    str(work / "atlas-browser"),
                    str(output / "site"),
                ],
                check=True,
                timeout=180,
            )
            subprocess.run(  # noqa: S603 -- Complete offline copy, zero HTTP requests permitted.
                [
                    shutil.which("node") or "/usr/bin/node",
                    "scripts/capture_genre_atlas.mjs",
                    (output / "site/OpenNoise.html").as_uri(),
                    str(work / "atlas-offline-browser"),
                    str(output / "site"),
                ],
                check=True,
                timeout=180,
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        _atomic_install(output / "site", root / "dist")
    print(f"Certified public catalog and artist-network release for {commit}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
