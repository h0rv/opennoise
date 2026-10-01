"""Fit source-only enrichment or query a frozen model in bounded offline batches."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file
from opennoise.ml.artist_feature_enrichment import (
    MAX_BATCH,
    fit_enrichment,
    load_enrichment,
    read_profiles,
    save_enrichment,
)


def main() -> None:
    """Write only fresh local research artifacts, with no public promotion path."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("fit")
    build.add_argument("--features", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    query = commands.add_parser("predict")
    query.add_argument("--model", type=Path, required=True)
    query.add_argument("--features", type=Path, required=True)
    query.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fit":
        profiles, proper = read_profiles(args.features)
        model = fit_enrichment(profiles, proper, training_sha256=sha256_file(args.features)[0])
        save_enrichment(model, args.output)
        return
    require_local_candidate_destination(args.output.parent)
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("refusing to replace enrichment predictions")
    model = load_enrichment(args.model)
    rows: list[dict[str, object]] = []
    with args.features.open(encoding="utf-8") as stream:
        for line in stream:
            if len(rows) >= MAX_BATCH:
                raise ValueError("offline prediction file exceeds the explicit batch limit")
            rows.append(TypeAdapter(dict[str, object]).validate_json(line))
    predictions = [
        {
            "artist_mbid": row["artist_mbid"],
            "role": "inferred_feature_proposals",
            "proposals": model.proposals(row),
        }
        for row in rows
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        for row in predictions:
            stream.write(canonical_json(row) + b"\n")


if __name__ == "__main__":
    main()
