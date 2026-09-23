"""Write one create-only local Last.fm 1K feasibility receipt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.lastfm_1k_feasibility import run_lastfm_1k_feasibility_scan


def main() -> int:
    """Scan an explicitly supplied local archive without extracting it."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        output = _local_cache_output_path(arguments.output)
        if output.exists() or output.is_symlink():
            raise FileExistsError("receipt output already exists")
        receipt = run_lastfm_1k_feasibility_scan(
            archive_path=arguments.archive,
            supplied_archive_sha256=arguments.archive_sha256,
            catalog_path=arguments.catalog,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(receipt.model_dump_json(indent=2) + "\n")
    except (OSError, ValueError) as error:
        sys.stderr.write(f"Last.fm 1K feasibility scan failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only Last.fm 1K feasibility receipt: {output}\n")
    return 0


def _local_cache_output_path(path: Path) -> Path:
    """Permit a non-symlink receipt output only below the local cache directory."""
    if path.is_symlink():
        raise ValueError("receipt output cannot be a symbolic link")
    output = path.resolve(strict=False)
    if not output.is_relative_to((Path.cwd() / ".cache").resolve()):
        raise ValueError("receipt output must be inside this repository's .cache directory")
    return output


if __name__ == "__main__":
    raise SystemExit(main())
