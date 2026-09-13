"""Build and publish a source-only sparse MusicBrainz tag matrix."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from opennoise.ingest.musicbrainz.seed_targets import load_seed_target_artifact
from opennoise.storage import LocalObjectStore
from opennoise.taxonomy.open.tag_feature_matrix import (
    OpenTagFeatureMatrixSettings,
    build_open_tag_feature_matrix,
    publish_open_tag_feature_matrix,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="build-open-tag-feature-matrix")
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--max-feature-rows", type=int, default=2_000_000)
    parser.add_argument("--max-artist-count", type=int, default=1_000_000)
    parser.add_argument("--max-tag-count", type=int, default=500_000)
    return parser


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build, verify, and publish a source-only matrix plus immutable receipt."""
    arguments = _parser().parse_args()
    artifact = build_open_tag_feature_matrix(
        load_seed_target_artifact(arguments.source_artifact),
        arguments.matrix,
        OpenTagFeatureMatrixSettings(
            max_feature_rows=arguments.max_feature_rows,
            max_artist_count=arguments.max_artist_count,
            max_tag_count=arguments.max_tag_count,
        ),
    )
    receipt = publish_open_tag_feature_matrix(
        artifact,
        artifact_path=arguments.output,
        matrix_path=arguments.matrix,
        store=LocalObjectStore(arguments.object_store),
    )
    rendered = receipt.model_dump_json(indent=2)
    _atomic_text(arguments.receipt, rendered)
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
