"""Run the bounded public multi-snapshot graph validation experiment."""

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

from musix.ml.repository import PublicInputLoadSettings, PublicModelRepository
from musix.ml.validation import build_graph_validation
from musix.ml.validation_repository import GraphValidationRepository, ValidationLoadSettings
from musix.models.modeling import PublicModelSettings
from musix.models.validation import GraphValidationInput, GraphValidationSettings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-db", type=Path, default=Path("data/musix.sqlite"))
    parser.add_argument(
        "--listenbrainz-db", type=Path, default=Path("data/listenbrainz-holdout.sqlite")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/model/public-graph-validation-v1.json")
    )
    parser.add_argument("--max-direct-memberships", type=int, default=100_000)
    parser.add_argument("--max-pairs-per-snapshot", type=int, default=250_000)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    parser.add_argument("--neighbors-per-genre", type=int, default=10)
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
    """Load, validate, and atomically publish one experiment report."""
    arguments = _arguments()
    load_settings = PublicInputLoadSettings(
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=1,
        max_metadata_candidates=arguments.max_metadata_candidates,
    )
    validation_load_settings = ValidationLoadSettings(
        maximum_pairs_per_snapshot=arguments.max_pairs_per_snapshot
    )
    model_settings = PublicModelSettings(
        neighbors_per_genre=max(arguments.neighbors_per_genre, 25),
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=arguments.max_pairs_per_snapshot * 14,
    )
    validation_settings = GraphValidationSettings(neighbors_per_genre=arguments.neighbors_per_genre)
    with (
        _read_only(arguments.catalog_db) as catalog,
        _read_only(arguments.listenbrainz_db) as listenbrainz,
    ):
        repository = PublicModelRepository(catalog, listenbrainz)
        base_inputs = repository.load_catalog_only(load_settings)
        validation_repository = GraphValidationRepository(catalog, listenbrainz)
        snapshots = validation_repository.temporal_snapshots(validation_load_settings)
        hierarchy = validation_repository.hierarchy_edges(validation_load_settings)
    artifact = build_graph_validation(
        GraphValidationInput(
            base_inputs=base_inputs,
            snapshots=snapshots,
            hierarchy=hierarchy,
            input_database_bytes=(
                arguments.catalog_db.stat().st_size + arguments.listenbrainz_db.stat().st_size
            ),
        ),
        model_settings,
        validation_settings,
    )
    _write_atomic(arguments.output, artifact.model_dump_json(indent=2))
    summary = artifact.model_dump_json(
        include={
            "output_sha256",
            "export_allowed",
            "hierarchy_edges",
            "community_stability",
            "neighborhood",
            "temporal",
            "source_holdout",
            "deterministic_rerun",
            "resources",
        },
        indent=2,
    )
    sys.stdout.write(f"{summary}\n")


if __name__ == "__main__":
    main()
