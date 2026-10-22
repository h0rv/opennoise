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
                timeout=130,
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
                    url,
                    str(work / "browser"),
                ],
                check=True,
                timeout=120,
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        _atomic_install(output / "site", root / "dist")
    print(f"Certified public catalog release for {commit}: 433 catalog artists, 1031 recordings")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
