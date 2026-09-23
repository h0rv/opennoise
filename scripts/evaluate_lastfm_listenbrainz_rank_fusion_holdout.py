"""Write a create-only local Last.fm and ListenBrainz rank-fusion report."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.lastfm_listenbrainz_rank_fusion_holdout import (
    evaluate_lastfm_listenbrainz_rank_fusion_holdout,
)


def main() -> int:
    """Evaluate fixed source-rank fusion without creating a serving artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct-database", type=Path, required=True)
    parser.add_argument("--direct-receipt", type=Path, required=True)
    parser.add_argument("--lastfm-artifact", type=Path, required=True)
    parser.add_argument("--lastfm-companion-receipt", type=Path, required=True)
    parser.add_argument("--lastfm-database", type=Path, required=True)
    parser.add_argument("--listenbrainz-database", type=Path, required=True)
    parser.add_argument("--listenbrainz-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(strict=False)
    if (
        not output.is_relative_to(Path(".cache").resolve())
        or output.exists()
        or output.is_symlink()
    ):
        raise ValueError("output must be a new non-symlink file below .cache")
    report = evaluate_lastfm_listenbrainz_rank_fusion_holdout(
        direct_database=args.direct_database,
        direct_receipt_path=args.direct_receipt,
        lastfm_artifact_path=args.lastfm_artifact,
        lastfm_companion_receipt_path=args.lastfm_companion_receipt,
        lastfm_database_path=args.lastfm_database,
        listenbrainz_database_path=args.listenbrainz_database,
        listenbrainz_receipt_path=args.listenbrainz_receipt,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
