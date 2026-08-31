"""Build one bounded public graph artifact from policy-safe SQLite evidence."""

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

from musix.ml.public_graph import build_public_model
from musix.ml.repository import PublicInputLoadSettings, PublicModelRepository
from musix.models.modeling import PublicModelSettings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-db", type=Path, default=Path("data/musix.sqlite"))
    parser.add_argument("--listenbrainz-db", type=Path, default=Path("data/musix.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("data/model/public-model-v1.json"))
    parser.add_argument("--max-direct-memberships", type=int, default=100_000)
    parser.add_argument("--max-artist-pairs", type=int, default=250_000)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    parser.add_argument("--neighbors-per-genre", type=int, default=25)
    return parser.parse_args()


def _read_only(path: Path) -> sqlite3.Connection:
    absolute = path.resolve(strict=True)
    return sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro", uri=True)


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    """Load, build, and atomically publish one content-addressed artifact."""
    arguments = _arguments()
    load_settings = PublicInputLoadSettings(
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=arguments.max_artist_pairs,
        max_metadata_candidates=arguments.max_metadata_candidates,
    )
    model_settings = PublicModelSettings(
        neighbors_per_genre=arguments.neighbors_per_genre,
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=arguments.max_artist_pairs,
    )
    with (
        _read_only(arguments.catalog_db) as catalog,
        _read_only(arguments.listenbrainz_db) as listenbrainz,
    ):
        inputs = PublicModelRepository(catalog, listenbrainz).load(load_settings)
    artifact = build_public_model(inputs, model_settings)
    _write_atomic(arguments.output, artifact.model_dump_json())
    summary = artifact.model_dump_json(include={"output_sha256", "coverage", "resources"}, indent=2)
    sys.stdout.write(f"{summary}\n")


if __name__ == "__main__":
    main()
