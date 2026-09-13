"""Materialize the single production map from the sealed public graph release."""

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

from opennoise.ml.production_map import build_production_map
from opennoise.ml.repository import PublicInputLoadSettings, PublicModelRepository
from opennoise.models.modeling import PublicModelArtifact
from opennoise.models.production import ProductionMapSettings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument("--source-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
    """Load sealed public data and emit Cytoscape-ready production JSON."""
    arguments = _arguments()
    source_model = PublicModelArtifact.model_validate_json(
        arguments.source_model.read_text(encoding="utf-8")
    )
    with _read_only(arguments.database) as database:
        inputs = PublicModelRepository(database, database).load(PublicInputLoadSettings())
    artifact = build_production_map(inputs, source_model, ProductionMapSettings())
    _write_atomic(arguments.output, artifact.model_dump_json())
    sys.stdout.write(
        artifact.model_dump_json(
            include={"output_sha256", "metrics", "electronic_branch"}, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
