"""Build a local-only H3 coverage report from two sealed Every Noise artifacts."""

import argparse
import asyncio
import json
from pathlib import Path

from musix.adapters.everynoise import (
    NEROYUKI_H3_SOURCE,
    QUINT_SOURCE,
    adapt_historical_genre_artist_map,
    store_verified_bytes,
)
from musix.bootstrap import bootstrap_everynoise
from musix.genre_discovery import import_historical_genre_memberships

RESEARCH_DATE = "2026-09-04"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h2-source", type=Path, required=True)
    parser.add_argument("--h3-source", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    """Build an H2 base map, project H3 evidence, and write a safe report."""
    args = _parser().parse_args()
    bootstrap = asyncio.run(
        bootstrap_everynoise(
            database_path=args.database,
            vault_path=args.vault,
            source_path=args.h2_source,
        )
    )
    raw = args.h3_source.read_bytes()
    adaptation = adapt_historical_genre_artist_map(
        raw,
        NEROYUKI_H3_SOURCE,
        source_revision_date="2024-11-16",
    )
    store_verified_bytes(raw, adaptation.source, args.vault / "raw" / "sha256")
    summary = import_historical_genre_memberships(args.database, adaptation)
    total_source_genres = summary.matched_genres + summary.unmatched_genres
    report = {
        "schema_version": 1,
        "research_date": RESEARCH_DATE,
        "source": {
            "id": adaptation.source.source_id,
            "snapshot": adaptation.source.snapshot,
            "byte_size": adaptation.source.expected_bytes,
            "sha256": adaptation.source.sha256,
            "expected_genre_rows": adaptation.source.expected_records,
        },
        "base_map": {
            "source_id": QUINT_SOURCE.source_id,
            "genre_points": bootstrap.map_points,
            "sha256": bootstrap.source_sha256,
        },
        "coverage": {
            **summary.model_dump(mode="json"),
            "source_genres": total_source_genres,
            "genre_name_match_rate": (
                round(summary.matched_genres / total_source_genres, 6)
                if total_source_genres
                else 0.0
            ),
        },
        "publication": {
            "eligible": False,
            "reason": "The H3 source policy permits local normalization only.",
            "dropped_fields": ["sample_song", "preview_url", "track_id"],
            "audio_or_media_fetched": False,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
