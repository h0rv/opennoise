"""Replay a small checked-in CC0 artist-work projection without network access."""

import argparse
import json
from pathlib import Path

from opennoise.serving.metadata.artist_works import (
    CreditedMusicCandidate,
    rank_artist_works,
    verify_projected_artist_work_examples,
)


def main() -> int:
    """Verify the source receipt and replay explainable bounded ranking."""
    parser = argparse.ArgumentParser()
    parser.add_argument("projection", type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("representative output already exists")
    artifact = verify_projected_artist_work_examples(args.projection, args.receipt)
    fields = set(CreditedMusicCandidate.model_fields)
    for artist in artifact["artists"]:
        for kind in ("recordings", "release_groups"):
            candidates = tuple(
                CreditedMusicCandidate.model_validate_json(
                    json.dumps({key: value for key, value in row.items() if key in fields})
                )
                for row in artist[kind]
            )
            rows = []
            for ranked in rank_artist_works(artist["artist_mbid"], candidates):
                row = ranked.candidate.model_dump(mode="json")
                row.update(ranked.model_dump(mode="json", exclude={"candidate"}))
                rows.append(row)
            artist[kind] = rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(artifact, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
