"""Launch the local app only with a validated production map pair."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from musix.models.production import ProductionMapArtifact


@dataclass(frozen=True, slots=True)
class ProductionLaunchPaths:
    """One compatible serving database and semantic map artifact."""

    database: Path
    map_artifact: Path


def resolve_production_paths(root: Path) -> ProductionLaunchPaths | None:
    """Prefer explicit environment paths, then cacheable release outputs."""
    configured_database = os.environ.get("MUSIX_DATABASE_PATH")
    configured_map = os.environ.get("MUSIX_PRODUCTION_MAP_PATH")
    candidates = (
        ProductionLaunchPaths(
            database=Path(configured_database),
            map_artifact=Path(configured_map),
        )
        if configured_database and configured_map
        else None,
        ProductionLaunchPaths(
            database=root / "data/public.sqlite",
            map_artifact=root / "data/model/production-map-v1.json",
        ),
        ProductionLaunchPaths(
            database=root / ".cache/release-certify/public.sqlite",
            map_artifact=root / ".cache/release-certify/production-map-v1.json",
        ),
    )
    for candidate in candidates:
        if (
            candidate is None
            or not candidate.database.is_file()
            or not candidate.map_artifact.is_file()
        ):
            continue
        try:
            ProductionMapArtifact.model_validate_json(
                candidate.map_artifact.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        return candidate
    return None


def main() -> int:
    """Start the production-first local app or explain the cacheable prerequisite."""
    root = Path.cwd()
    paths = resolve_production_paths(root)
    if paths is None:
        sys.stderr.write(
            "Production map unavailable. Run `uv run poe release-certify` first "
            "(requires the sealed cache; see docs/PUBLIC_RELEASE_PIPELINE.md).\n"
        )
        return 2
    environment = os.environ | {
        "MUSIX_DATABASE_PATH": str(paths.database),
        "MUSIX_DATABASE_READ_ONLY": "true",
        "MUSIX_PRODUCTION_MAP_PATH": str(paths.map_artifact),
    }
    return subprocess.run(
        [sys.executable, "-m", "musix.cli", "serve"], check=False, env=environment
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
