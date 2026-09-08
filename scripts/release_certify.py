"""Build and certify one cache-only public production release."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Final
from urllib.error import URLError
from urllib.request import urlopen

_DEFAULT_RELEASE_DIRECTORY: Final = Path("config/releases/phase3-public-20260831")
_DEFAULT_CACHE_DATABASE: Final = Path("data/phase3-public-qualified.sqlite")
_DEFAULT_SERVING_DATABASE: Final = Path("data/public.sqlite")
_DEFAULT_MODEL: Final = Path("data/model/phase3-public-model.json")
_DEFAULT_RECEIPT: Final = Path("data/release/phase3-public-receipt.json")
_DEFAULT_MAP: Final = Path("data/model/production-map-v1.json")
_DEFAULT_ACCEPTANCE: Final = Path("data/model/production-map-v1.acceptance.json")
_DEFAULT_EVIDENCE_REPORT: Final = Path("data/model/production-map-v1.seed-report.json")
_DEFAULT_BROWSER_EVIDENCE: Final = Path("data/model/production-map-v1.browser.json")
_DEFAULT_REPORT: Final = Path("data/model/production-map-v1.report.json")
_DEFAULT_CAPTURES: Final = Path("data/model/production-map-captures")
_SERVER_START_TIMEOUT_SECONDS: Final = 20.0
_HTTP_OK: Final = 200


class ReleaseCertificationError(RuntimeError):
    """Report a missing prerequisite or failed release-certification boundary."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build only from the sealed cache, then certify the rendered production map."
    )
    parser.add_argument("--release-directory", type=Path, default=_DEFAULT_RELEASE_DIRECTORY)
    parser.add_argument("--cache-database", type=Path, default=_DEFAULT_CACHE_DATABASE)
    parser.add_argument("--serving-database", type=Path, default=_DEFAULT_SERVING_DATABASE)
    parser.add_argument("--model-output", type=Path, default=_DEFAULT_MODEL)
    parser.add_argument("--receipt-output", type=Path, default=_DEFAULT_RECEIPT)
    parser.add_argument("--map-output", type=Path, default=_DEFAULT_MAP)
    parser.add_argument("--acceptance-output", type=Path, default=_DEFAULT_ACCEPTANCE)
    parser.add_argument("--seed-report-output", type=Path, default=_DEFAULT_EVIDENCE_REPORT)
    parser.add_argument("--browser-evidence-output", type=Path, default=_DEFAULT_BROWSER_EVIDENCE)
    parser.add_argument("--report-output", type=Path, default=_DEFAULT_REPORT)
    parser.add_argument("--captures-directory", type=Path, default=_DEFAULT_CAPTURES)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3012)
    arguments = sys.argv[1:]
    # Poe forwards free task arguments after a literal separator. Accept that
    # separator here so `uv run poe release-certify -- --cache-database …` is exact.
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    return parser.parse_args(arguments)


def _require_file(path: Path, description: str) -> Path:
    absolute = path.resolve()
    if not absolute.is_file():
        raise ReleaseCertificationError(
            f"cache-only prerequisite missing: {description}: {absolute}"
        )
    return absolute


def _require_browser() -> tuple[Path, str]:
    chromium = Path("/usr/bin/chromium")
    node = shutil.which("node")
    if not chromium.is_file() or node is None:
        raise ReleaseCertificationError(
            "browser certification requires /usr/bin/chromium and node; no browser QA was skipped"
        )
    return chromium, node


def _run(*command: str) -> None:
    subprocess.run(command, check=True)  # noqa: S603


def _musix_command() -> str:
    candidate = Path(sys.executable).with_name("musix")
    if candidate.is_file():
        return str(candidate)
    command = shutil.which("musix")
    if command is None:
        raise ReleaseCertificationError("cache-only prerequisite missing: musix command")
    return command


def _wait_for_server(host: str, port: int, process: subprocess.Popen[bytes]) -> None:
    endpoint = f"http://{host}:{port}/api/health"
    deadline = time.monotonic() + _SERVER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ReleaseCertificationError(
                "local certification server exited before becoming healthy"
            )
        try:
            with urlopen(endpoint, timeout=0.5) as response:
                if response.status == _HTTP_OK:
                    return
        except URLError:
            time.sleep(0.1)
    raise ReleaseCertificationError("local certification server did not become healthy")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    """Run the sealed release build, data acceptance, and required browser acceptance."""
    arguments = _arguments()
    manifest = _require_file(
        arguments.release_directory / "release-manifest.json", "release manifest"
    )
    cache = _require_file(arguments.cache_database, "sealed cache database")
    _require_browser()
    for path in (
        arguments.serving_database,
        arguments.model_output,
        arguments.receipt_output,
        arguments.map_output,
        arguments.acceptance_output,
        arguments.seed_report_output,
        arguments.browser_evidence_output,
        arguments.report_output,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    _run(
        sys.executable,
        "scripts/build_public_release.py",
        "--release-directory",
        str(manifest.parent),
        "--cache-database",
        str(cache),
        "--serving-database",
        str(arguments.serving_database),
        "--model-output",
        str(arguments.model_output),
        "--receipt-output",
        str(arguments.receipt_output),
    )
    _run(
        sys.executable,
        "scripts/build_production_map.py",
        "--database",
        str(arguments.serving_database),
        "--source-model",
        str(arguments.model_output),
        "--output",
        str(arguments.map_output),
    )
    _run(
        sys.executable,
        "scripts/build_production_map_evidence.py",
        "--artifact",
        str(arguments.map_output),
        "--source-model",
        str(arguments.model_output),
        "--output",
        str(arguments.acceptance_output),
        "--report",
        str(arguments.seed_report_output),
    )
    environment = os.environ.copy()
    environment["MUSIX_PRODUCTION_MAP_PATH"] = str(arguments.map_output.resolve())
    server = subprocess.Popen(  # noqa: S603
        [
            _musix_command(),
            "serve",
            "--database",
            str(arguments.serving_database),
            "--host",
            arguments.host,
            "--port",
            str(arguments.port),
        ],
        env=environment,
    )
    try:
        _wait_for_server(arguments.host, arguments.port, server)
        _run(
            shutil.which("node") or "node",
            "scripts/capture_production_map_browser.mjs",
            f"http://{arguments.host}:{arguments.port}",
            str(arguments.browser_evidence_output),
            "--acceptance",
            str(arguments.acceptance_output),
            "--captures",
            str(arguments.captures_directory),
        )
        _run(
            sys.executable,
            "scripts/evaluate_production_map.py",
            str(arguments.acceptance_output),
            "--report",
            str(arguments.report_output),
        )
    finally:
        _terminate(server)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseCertificationError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"release certification failed: {error}") from error
