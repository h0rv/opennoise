"""Build cache-only model and map artifacts without starting a runtime service."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Final

_DEFAULT_RELEASE_DIRECTORY: Final = Path("config/releases/phase3-public-20260831")
_DEFAULT_CACHE_DATABASE: Final = Path("data/phase3-public-qualified.sqlite")
_RETAINED_CACHE_DATABASE: Final = Path(
    ".cache/listenbrainz-qualified-input/sha256/"
    "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite"
)


class ReleaseCertificationError(RuntimeError):
    """Report a missing cache-only release prerequisite."""


def resolve_cache_database(primary: Path, retained: Path) -> Path:
    """Prefer the conventional release input, then the verified retained cache."""
    return primary if primary.is_file() else retained


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-directory", type=Path, default=_DEFAULT_RELEASE_DIRECTORY)
    parser.add_argument(
        "--cache-database",
        type=Path,
        default=resolve_cache_database(_DEFAULT_CACHE_DATABASE, _RETAINED_CACHE_DATABASE),
    )
    parser.add_argument("--serving-database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument(
        "--model-output", type=Path, default=Path("data/model/phase3-public-model.json")
    )
    parser.add_argument(
        "--receipt-output", type=Path, default=Path("data/release/phase3-public-receipt.json")
    )
    parser.add_argument(
        "--map-output", type=Path, default=Path("data/model/production-map-v1.json")
    )
    parser.add_argument(
        "--acceptance-output",
        type=Path,
        default=Path("data/model/production-map-v1.acceptance.json"),
    )
    parser.add_argument(
        "--report-output", type=Path, default=Path("data/model/production-map-v1.seed-report.json")
    )
    arguments = sys.argv[1:]
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


def _run(*command: str) -> None:
    subprocess.run(command, check=True)  # noqa: S603


def main() -> int:
    """Verify the sealed cache and build model/map evidence entirely offline."""
    arguments = _arguments()
    manifest = _require_file(
        arguments.release_directory / "release-manifest.json", "release manifest"
    )
    cache = _require_file(arguments.cache_database, "sealed cache database")
    for path in (
        arguments.serving_database,
        arguments.model_output,
        arguments.receipt_output,
        arguments.map_output,
        arguments.acceptance_output,
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
        str(arguments.report_output),
    )
    sys.stdout.write(
        f"cache-only certification passed; model={arguments.model_output} "
        f"map={arguments.map_output}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
