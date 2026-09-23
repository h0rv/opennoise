"""Build and verify the local-only exclusive proper-genre anchor review artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_proper_genre_anchor_projection import (
    build_direct_proper_genre_anchor_projection,
    verify_direct_proper_genre_anchor_projection,
)


def _prepare_output(path: Path, *, cache_root: Path | None = None) -> Path:
    """Keep local review output out of the public tree and refuse replacement."""
    cache_root = (Path.cwd() / ".cache" if cache_root is None else cache_root).resolve()
    target = path.resolve()
    if not target.is_relative_to(cache_root):
        raise ValueError("output must be a new path beneath the local .cache directory")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to replace existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def main() -> int:
    """Build one fresh, local-only anchor review artifact."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-direct-proper-genre-anchor-projection")
    parser.add_argument("--custody-receipt", required=True, type=Path)
    parser.add_argument("--custody-object-store", required=True, type=Path)
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    projection = build_direct_proper_genre_anchor_projection(
        custody_receipt_path=arguments.custody_receipt,
        custody_object_store=arguments.custody_object_store,
        layout_path=arguments.layout,
    )
    verify_direct_proper_genre_anchor_projection(projection)
    output = _prepare_output(arguments.output)
    output.write_bytes(
        json.dumps(projection.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode()
        + b"\n"
    )
    sys.stdout.write(
        json.dumps(
            {"proposals": len(projection.proposals), "abstentions": len(projection.abstentions)}
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
