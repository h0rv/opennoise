"""Verify, export, serve, and browser-certify one static semantic Pages build."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.error import URLError
from urllib.request import urlopen

from opennoise.common import sha256_file
from opennoise.deployment.semantic_pages import SemanticPagesExportInputs, export_semantic_pages
from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_SEALED_LAYOUT: Final = Path(".cache/semantic-map-layout-v3/artifact.json")
_SEALED_DATABASE: Final = Path("data/public.sqlite")
_SEALED_OUTPUT: Final = Path("dist")
_SEALED_LAYOUT_SHA256: Final = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_SEALED_DATABASE_SHA256: Final = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_SEALED_ENVIRONMENT_OVERRIDES: Final = (
    "OPENNOISE_SEMANTIC_MAP_LAYOUT",
    "OPENNOISE_DISCOVERY_DATABASE",
    "OPENNOISE_PAGES_OUTPUT",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--semantic-layout",
        type=Path,
        default=Path(
            os.environ.get(
                "OPENNOISE_SEMANTIC_MAP_LAYOUT", ".cache/semantic-map-layout-v3/artifact.json"
            )
        ),
    )
    parser.add_argument(
        "--discovery-database",
        type=Path,
        default=Path(os.environ.get("OPENNOISE_DISCOVERY_DATABASE", "data/public.sqlite")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("OPENNOISE_PAGES_OUTPUT", "dist")),
    )
    parser.add_argument("--report", type=Path, default=Path("artifacts/semantic-map/browser.json"))
    parser.add_argument("--captures", type=Path, default=Path("artifacts/semantic-map/captures"))
    parser.add_argument(
        "--sealed-deploy",
        action="store_true",
        help="require the canonical, hash-pinned Pages inputs and output",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OPENNOISE_PAGES_CERTIFY_PORT", "3001")),
    )
    arguments = sys.argv[1:]
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    return parser.parse_args(arguments)


def _sealed_path(label: str, actual: Path, expected: Path) -> None:
    if actual.resolve() != expected.resolve():
        raise RuntimeError(f"sealed deploy requires {label} {expected}, got {actual}")


def _verify_sealed_deploy_inputs(
    arguments: argparse.Namespace,
    *,
    file_hasher: Callable[[Path], tuple[str, int]] = sha256_file,
) -> None:
    """Reject mutable input selection and verify the canonical deploy bytes."""
    overrides = sorted(name for name in _SEALED_ENVIRONMENT_OVERRIDES if name in os.environ)
    if overrides:
        raise RuntimeError(f"sealed deploy rejects environment overrides: {', '.join(overrides)}")
    _sealed_path("semantic layout", arguments.semantic_layout, _SEALED_LAYOUT)
    _sealed_path("discovery database", arguments.discovery_database, _SEALED_DATABASE)
    _sealed_path("output", arguments.output, _SEALED_OUTPUT)
    layout_sha256, _ = file_hasher(arguments.semantic_layout)
    if layout_sha256 != _SEALED_LAYOUT_SHA256:
        raise RuntimeError("sealed deploy semantic layout SHA-256 does not match the release pin")
    database_sha256, _ = file_hasher(arguments.discovery_database)
    if database_sha256 != _SEALED_DATABASE_SHA256:
        raise RuntimeError(
            "sealed deploy discovery database SHA-256 does not match the release pin"
        )


def _wait_for_server(url: str, process: subprocess.Popen[bytes]) -> None:
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError("static loopback server exited before becoming ready")
        try:
            with urlopen(url, timeout=1):  # noqa: S310 - caller supplies loopback host.
                return
        except (OSError, URLError):
            time.sleep(0.1)
    raise RuntimeError("static loopback server did not become ready")


def _atomic_install(staged: Path, output: Path) -> None:
    """Replace an existing export only after the staged browser gate passes."""
    backup: Path | None = None
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise RuntimeError(f"static Pages output is not a directory: {output}")
        backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.previous-", dir=output.parent))
        backup.rmdir()
        output.rename(backup)
    try:
        staged.replace(output)
    except BaseException:
        if backup is not None and not output.exists():
            backup.rename(output)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def main() -> int:
    """Run the sealed layout, static export, loopback, and browser gates."""
    arguments = _arguments()
    if arguments.sealed_deploy:
        _verify_sealed_deploy_inputs(arguments)
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for browser certification")
    artifact = SemanticLayoutArtifact.model_validate_json(arguments.semantic_layout.read_bytes())
    verify_semantic_map_layout(artifact)
    output = arguments.output.resolve()
    report = arguments.report.resolve()
    captures = arguments.captures.resolve()
    if report.is_relative_to(output) or captures.is_relative_to(output):
        raise RuntimeError("browser report and captures must live outside the Pages output")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.certify-", dir=output.parent) as root:
        staged = Path(root) / "dist"
        export_semantic_pages(
            SemanticPagesExportInputs(
                arguments.semantic_layout,
                staged,
                arguments.discovery_database,
            )
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.captures.mkdir(parents=True, exist_ok=True)
        server = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "scripts/run_dev.py",
                "--directory",
                str(staged),
                "--host",
                arguments.host,
                "--port",
                str(arguments.port),
            ],
            stdin=subprocess.DEVNULL,
        )
        base_url = f"http://{arguments.host}:{arguments.port}/"
        try:
            _wait_for_server(base_url, server)
            subprocess.run(  # noqa: S603
                [
                    node,
                    "scripts/capture_semantic_map_browser.mjs",
                    base_url,
                    str(arguments.report),
                    "--captures",
                    str(arguments.captures),
                    "--port",
                    str(arguments.port + 1),
                    "--require-label-point-exit",
                ],
                check=True,
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        _atomic_install(staged, output)
    print(  # noqa: T201
        f"static certification passed: {len(artifact.coordinates)} nodes, "
        f"browser report {arguments.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
