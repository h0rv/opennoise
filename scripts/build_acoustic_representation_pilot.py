"""Build an authorized local metadata pilot without modifying the immutable capture."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from opennoise.analysis.acoustic_expansion_verification import verify_expansion
from opennoise.analysis.acoustic_representation import (
    RecordingDescriptors,
    aggregate_recordings,
    cultural_neighbors,
    fit_scales,
    sonic_neighbors,
)
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import sha256_file
from opennoise.ingest.acousticbrainz.capture import verify_reprojection
from opennoise.ingest.acousticbrainz.models import BenchmarkSummary
from opennoise.ingest.acousticbrainz.projection import NUMERIC_PATHS

if TYPE_CHECKING:
    from collections.abc import Sequence


class _Membership(BaseModel):
    model_config = ConfigDict(extra="ignore")
    community_id: str
    level: str


class _Artist(BaseModel):
    model_config = ConfigDict(extra="ignore")
    artist_mbid: str
    memberships: tuple[_Membership, ...]


class _Benchmark(BaseModel):
    model_config = ConfigDict(extra="ignore")
    benchmark_artists: tuple[_Artist, ...]


def build(source: Path, destination: Path, expanded: Path | None = None) -> dict[str, object]:
    """Verify source bytes and bind new research scope to excluded raw tags."""
    require_local_candidate_destination(destination)
    verification = verify_reprojection(directory=source)
    summary = BenchmarkSummary.model_validate_json((source / "summary.json").read_bytes())
    benchmark = _Benchmark.model_validate_json((source / "benchmark-source.json").read_bytes())
    recordings = [
        RecordingDescriptors(
            str(row.artist_mbid),
            str(row.recording_mbid),
            {value.path: value.value for value in row.numeric_descriptors},
        )
        for row in summary.outcomes
        if row.level == "low-level"
        and row.state == "available"
        and row.embedded_identity == "matched"
    ]
    expansion = None
    expansion_verification: dict[str, object] = {}
    if expanded is not None:
        expansion, expansion_verification = verify_expansion(expanded, source)
        recordings = [
            RecordingDescriptors(
                row.artist_id,
                row.recording_id,
                {value.path: value.value for value in row.descriptors},
            )
            for row in expansion.outcomes
            if row.state == "available" and row.identity == "matched"
        ]
    artists = aggregate_recordings(recordings, NUMERIC_PATHS)
    memberships = {
        row.artist_mbid: frozenset(
            membership.community_id for membership in row.memberships if membership.level == "micro"
        )
        for row in benchmark.benchmark_artists
    }
    # Each query artist is held out of scale fitting. No cultural label is a fit target.
    neighborhoods = {}
    for query in artists:
        training = tuple(row for row in artists if row.artist_id != query.artist_id)
        scales = fit_scales(training, NUMERIC_PATHS)
        neighborhoods[query.artist_id] = {
            "sonic": sonic_neighbors(query, training, scales),
            "cultural": cultural_neighbors(query.artist_id, memberships),
            "scale_training_artist_ids": [row.artist_id for row in training],
            "scale_values": scales,
        }
    result: dict[str, object] = {
        "revision": "acoustic-representation-research-pilot-v1",
        "source_verification": verification,
        "source_summary_sha256": sha256_file(source / "summary.json")[0],
        "source_receipt_sha256": sha256_file(source / "receipt.json")[0],
        "scope": {
            "authorization": (
                "User instructed implementing open metadata models and filling parity gaps."
            ),
            "new_derived_research_scope": True,
            "original_capture_model_input_allowed": summary.model_input_allowed,
            "source_receipt_unchanged": True,
            "numeric_source_license": "CC0-1.0",
            "source_attribution": summary.source_attribution,
            "raw_tags_consumed": False,
            "high_level_classifiers_consumed": False,
            "audio_requested": False,
            "new_network_requests": 0,
            "product_promotion_allowed": False,
            "representative_sample": False,
            "calibrated": False,
            "everynoise_axes_claimed": False,
        },
        "validation": {
            "method": "leave-one-artist-out scale fitting; exploratory ranking only",
            "cultural_memberships_used_in_sonic_fit": False,
            "quality_evaluated": False,
            "reason": "Tiny selected cohort lacks independent ground truth",
            "recording_level_random_split_used": False,
        },
        "coverage": [row.model_dump(mode="json") for row in summary.artists],
        "features": list(NUMERIC_PATHS),
        "artists": [asdict(row) for row in artists],
        "neighborhoods": neighborhoods,
    }
    if expanded is not None and expansion is not None:
        result["original_pilot_coverage"] = result.pop("coverage")
        result["coverage"] = [
            {
                "artist_id": artist_id,
                "selected_recordings": len(rows),
                "state_counts": {
                    state: sum(row.state == state for row in rows)
                    for state in sorted({row.state for row in rows})
                },
            }
            for artist_id in sorted({row.artist_id for row in expansion.outcomes})
            if (rows := [row for row in expansion.outcomes if row.artist_id == artist_id])
        ]
        result["expansion_verification"] = expansion_verification
        result["expanded_source"] = {
            "receipt_sha256": sha256_file(expanded / "receipt.json")[0],
            "selected_recordings": len(expansion.outcomes),
            "new_requests": expansion.new_requests,
            "new_response_bytes": expansion.new_response_bytes,
            "state_counts": expansion.state_counts,
        }
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "pilot.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return {"artists": len(artists), "recordings": len(recordings), "destination": str(destination)}


def main(argv: Sequence[str] | None = None) -> int:
    """Require explicit source and fresh local destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expanded", type=Path)
    args = parser.parse_args(argv)
    sys.stdout.write(json.dumps(build(args.source, args.output, args.expanded)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
