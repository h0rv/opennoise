"""Extract bounded MusicBrainz artist evidence for an H2 seed vocabulary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from musix.ingest.musicbrainz.seed_targets import (
    ReviewedSeedAlias,
    SeedTargetExtractorSettings,
    extract_musicbrainz_seed_targets,
    write_seed_target_artifact,
)
from musix.taxonomy.seeds.universe import load_seed_input


def main() -> int:
    """Parse command-line bounds and write one hash-bound extraction artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--seed-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-archive-sha256")
    parser.add_argument(
        "--reviewed-aliases",
        type=Path,
        help="JSON array of reviewed exact source-label aliases; never inferred from UI aliases",
    )
    parser.add_argument("--max-archive-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--max-member-bytes", type=int, default=64 * 1024**3)
    parser.add_argument("--max-record-bytes", type=int, default=64 * 1024**2)
    parser.add_argument("--max-records", type=int, default=10_000_000)
    parser.add_argument("--max-decompression-ratio", type=int, default=128)
    parser.add_argument("--max-genres-per-artist", type=int, default=128)
    parser.add_argument("--max-tags-per-artist", type=int, default=512)
    parser.add_argument("--max-evidence-rows", type=int, default=2_000_000)
    parser.add_argument("--max-contextual-tag-rows", type=int, default=2_000_000)
    args = parser.parse_args()
    settings = SeedTargetExtractorSettings(
        max_archive_bytes=args.max_archive_bytes,
        max_member_bytes=args.max_member_bytes,
        max_record_bytes=args.max_record_bytes,
        max_records=args.max_records,
        max_decompression_ratio=args.max_decompression_ratio,
        max_genres_per_artist=args.max_genres_per_artist,
        max_tags_per_artist=args.max_tags_per_artist,
        max_evidence_rows=args.max_evidence_rows,
        max_contextual_tag_rows=args.max_contextual_tag_rows,
    )
    aliases = (
        TypeAdapter(tuple[ReviewedSeedAlias, ...]).validate_json(args.reviewed_aliases.read_bytes())
        if args.reviewed_aliases is not None
        else ()
    )
    artifact = extract_musicbrainz_seed_targets(
        args.archive,
        load_seed_input(args.seed_artifact),
        settings,
        reviewed_aliases=aliases,
    )
    if args.expected_archive_sha256 and artifact.archive_sha256 != args.expected_archive_sha256:
        raise SystemExit(
            f"archive sha256 mismatch: expected {args.expected_archive_sha256}, "
            f"got {artifact.archive_sha256}"
        )
    write_seed_target_artifact(args.output, artifact)
    sys.stdout.write(
        json.dumps(
            {
                "output": str(args.output),
                "output_sha256": artifact.output_sha256,
                "archive_sha256": artifact.archive_sha256,
                "seed_count": artifact.seed_count,
                "counters": artifact.counters.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
