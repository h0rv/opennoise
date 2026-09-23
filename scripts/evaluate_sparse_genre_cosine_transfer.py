"""Write the fixed local sparse cosine genre-transfer ablation."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ml.sparse_genre_cosine_transfer import evaluate_sparse_genre_cosine_transfer


def _local_cache_output(output: Path) -> Path:
    """Resolve and admit only a new regular path below this checkout's cache."""
    cache_root = Path(__file__).resolve().parents[1] / ".cache"
    resolved_cache = cache_root.resolve()
    resolved_output = output.resolve()
    if not resolved_output.is_relative_to(resolved_cache):
        raise ValueError("local research output must resolve below .cache")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite or follow evaluation output: {output}")
    return resolved_output


def main() -> int:
    """Refuse replacement and evaluate only hash-verified local inputs."""
    parser = argparse.ArgumentParser(prog="evaluate-sparse-genre-cosine-transfer")
    parser.add_argument("--direct-database", required=True, type=Path)
    parser.add_argument("--direct-receipt", required=True, type=Path)
    parser.add_argument("--colisten-database", required=True, type=Path)
    parser.add_argument("--colisten-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = _local_cache_output(args.output)
    report = evaluate_sparse_genre_cosine_transfer(
        direct_database=args.direct_database,
        direct_receipt_path=args.direct_receipt,
        colisten_database=args.colisten_database,
        colisten_receipt_path=args.colisten_receipt,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
