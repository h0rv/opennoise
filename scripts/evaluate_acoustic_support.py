"""Replay train-only acoustic support checks on a small numeric CC0 projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from opennoise.analysis.acoustic_representation import (
    ArtistDescriptors,
    fit_scales,
    sonic_neighbors,
)
from opennoise.analysis.acoustic_support import fit_acoustic_support, supported_sonic_neighbors


def evaluate_projection(projection: Path, receipt: Path) -> dict[str, Any]:
    """Keep each query out of fitting and preserve sparse artist denominators.

    This verifies projected input custody only. Hashes identifying an absent
    native capture do not constitute independent native feature replay.
    """
    body = projection.read_bytes()
    proof = json.loads(receipt.read_bytes())
    artifact = json.loads(body)
    if (
        hashlib.sha256(body).hexdigest() != proof["projection_sha256"]
        or proof["license"] != "CC0-1.0"
        or artifact["scope"]["license"] != "CC0-1.0"
        or proof["source_summary_sha256"] != artifact["source_summary_sha256"]
        or proof["source_receipt_sha256"] != artifact["source_receipt_sha256"]
        or set(artifact)
        != {"artists", "features", "scope", "source_summary_sha256", "source_receipt_sha256"}
    ):
        raise ValueError("numeric acoustic projection custody or license differs")
    if any(
        set(row) != {"artist_id", "recording_count", "values", "observed_counts"}
        for row in artifact["artists"]
    ):
        raise ValueError("unapproved acoustic profile fields")
    artists = tuple(
        sorted(
            (ArtistDescriptors(**row) for row in artifact["artists"]), key=lambda row: row.artist_id
        )
    )
    features = artifact["features"]
    outcomes: list[dict[str, Any]] = []
    for query in artists:
        training = tuple(row for row in artists if row.artist_id != query.artist_id)
        frame = fit_acoustic_support(training, features)
        result = supported_sonic_neighbors(query, training, frame)
        reversed_result = supported_sonic_neighbors(
            query,
            tuple(reversed(training)),
            fit_acoustic_support(tuple(reversed(training)), tuple(reversed(features))),
        )
        if result != reversed_result or query.artist_id in frame.training_artist_ids:
            raise ValueError("acoustic held-out or deterministic ordering contract differs")
        if any(query.artist_id in row.training_artist_ids for row in frame.descriptors):
            raise ValueError("query entered a descriptor training population")
        if any(row["shared_features"] != result["fixed_features"] for row in result["neighbors"]):
            raise ValueError("accepted acoustic distances use different feature dimensions")
        baseline = sonic_neighbors(query, training, fit_scales(training, features))
        outcomes.append(
            {
                "query": query.artist_id,
                "baseline_neighbors": baseline,
                "supported_comparison": result,
                "training_frame": asdict(frame),
            }
        )
    reasons = Counter(
        row["supported_comparison"]["abstention_reason"]
        for row in outcomes
        if row["supported_comparison"]["abstention_reason"] is not None
    )
    return {
        "revision": "acoustic-support-projection-evaluation-v1",
        "input_projection_sha256": hashlib.sha256(body).hexdigest(),
        "input_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "scope": {
            "license": "CC0-1.0",
            "native_feature_custody_verified": False,
            "input_role": "small numeric-only projected artist descriptor summaries",
            "names_or_genres_or_cultural_targets_used": False,
            "thresholds_selected_using_test": False,
            "independent_musical_relevance_evaluated": False,
            "population_out_of_distribution_calibrated": False,
            "audio_requested": False,
            "limitations": (
                "Selected ten-artist sample; repeated recording support and descriptor-range gates "
                "establish comparable metadata distances only. No native raw replay, "
                "music relevance, artist genres or Every Noise axes established."
            ),
        },
        "checks": {
            "query_excluded_from_all_training_populations": True,
            "input_order_replay_equal": True,
            "all_accepted_distances_use_same_features_within_query": True,
        },
        "coverage": {
            "queries": len(outcomes),
            "baseline_ranked_queries": sum(bool(row["baseline_neighbors"]) for row in outcomes),
            "baseline_ranked_pairs": sum(len(row["baseline_neighbors"]) for row in outcomes),
            "supported_queries": sum(
                row["supported_comparison"]["abstention_reason"] is None for row in outcomes
            ),
            "supported_pairs": sum(
                len(row["supported_comparison"]["neighbors"]) for row in outcomes
            ),
            "query_abstentions": dict(sorted(reasons.items())),
        },
        "outcomes": outcomes,
    }


def main() -> int:
    """Write a fresh deterministic report from receipt-bound projected descriptors."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--projection",
        type=Path,
        default=Path("data/examples/acoustic-descriptors/acoustic-descriptors.json"),
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("data/examples/acoustic-descriptors/receipt.json")
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate_projection(args.projection, args.receipt)
    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(body)
    sys.stdout.write(json.dumps(report["coverage"]) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
