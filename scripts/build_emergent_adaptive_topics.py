"""Run the separate adaptive lexical coarse frontier experiment."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import cast

import numpy as np
from scipy import sparse

import opennoise.ml.emergent_adaptive_topics as adaptive_runtime
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.emergent_adaptive_topics import REVISION, fit_adaptive_topics
from opennoise.ml.emergent_topics import FeatureMatrix, TopicSettings, load_features

_EXPANDED_REVISION = "emergent-adaptive-lexical-coarse-topics-expanded-budget-v1"
_EXPANDED_COARSE_BUDGET = 1024


def _fit_variant(
    data: FeatureMatrix, settings: TopicSettings, *, expanded: bool
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    """Change only the selected coarse stopping budget for this local fit."""
    if not expanded:
        return fit_adaptive_topics(data, settings, include_centroids=True)
    default_budget = adaptive_runtime.MAXIMUM_BROAD_COMMUNITIES
    try:
        # The frozen module intentionally declares a literal default; this preset is process-local.
        adaptive_runtime.MAXIMUM_BROAD_COMMUNITIES = _EXPANDED_COARSE_BUDGET  # ty: ignore[invalid-assignment]
        model, assignments = fit_adaptive_topics(data, settings, include_centroids=True)
    finally:
        adaptive_runtime.MAXIMUM_BROAD_COMMUNITIES = default_budget
    model["revision"] = _EXPANDED_REVISION
    model["runtime_overrides"] = {
        "opennoise.ml.emergent_adaptive_topics.MAXIMUM_BROAD_COMMUNITIES": {
            "on_disk_default": default_budget,
            "process_local_value": _EXPANDED_COARSE_BUDGET,
            "role": "coarse_stopping_safety_budget_not_target_count",
        }
    }
    model["predictive_evaluation_for_this_variant"] = "not_run_construction_only_experiment"
    return model, assignments


def main() -> int:
    """Write lexical source assignments and full source centroid artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expanded-coarse-budget",
        action="store_true",
        help="Use the local research 1024 coarse safety budget (default: 128); not a target count.",
    )
    args = parser.parse_args()
    output = args.output
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to overwrite a lexical experiment")
    settings = TopicSettings()
    data = load_features(args.features, settings)
    model, assignments = _fit_variant(data, settings, expanded=args.expanded_coarse_budget)
    primary = model.pop("primary_assignments")
    centers = cast("dict[str, list[float]]", model.pop("centroids"))
    core_groups = model.pop("core_group_ids")
    output.mkdir(parents=True)
    keys = sorted(centers)
    sparse.save_npz(
        output / "topic-centroids.npz", sparse.csr_matrix(np.array([centers[key] for key in keys]))
    )
    records = {
        "communities.json": model,
        "primary-assignments.json": primary,
        "core-profile-groups.json": core_groups,
        "topic-feature-identities.json": {
            "community_ids": keys,
            "features": [
                {"namespace": namespace, "value": value} for namespace, value in data.features
            ],
        },
    }
    for name, record in records.items():
        (output / name).write_bytes(canonical_json(record) + b"\n")
    with (output / "assignments.jsonl").open("wb") as stream:
        for artist, memberships in assignments.items():
            stream.write(
                canonical_json({"artist_mbid": artist, "memberships": memberships}) + b"\n"
            )
    with (output / "musical-profiles.jsonl").open("wb") as stream:
        for artist, profile in zip(data.artists, data.musical_profiles, strict=True):
            stream.write(
                canonical_json({"artist_mbid": artist, "musical_features": profile}) + b"\n"
            )
    report = {
        "revision": model["revision"],
        "algorithm_revision": REVISION,
        "research_builder_sha256": sha256_file(Path(__file__))[0],
        "scope": "local_research_only",
        "settings": asdict(settings),
        "coverage": model["coverage"],
        "lexical_representation": model["lexical_representation"],
        "adaptive_coarse_cut": model["adaptive_coarse_cut"],
        "features_sha256": data.input_sha256,
        "code_sha256": sha256_file(Path("src/opennoise/ml/emergent_adaptive_topics.py"))[0],
        "lexical_code_sha256": sha256_file(Path("src/opennoise/ml/emergent_lexical_topics.py"))[0],
        "graph_code_sha256": sha256_file(Path("src/opennoise/ml/emergent_feature_graph.py"))[0],
        "base_code_sha256": sha256_file(Path("src/opennoise/ml/emergent_topics.py"))[0],
        "native_genre_memberships_added": 0,
        "historical_inputs_used": False,
        "artist_names_used_for_construction": False,
        "public_export_authorized": False,
        "files": {
            path.name: {"sha256": sha256_file(path)[0], "bytes": path.stat().st_size}
            for path in sorted(output.iterdir())
        },
    }
    if args.expanded_coarse_budget:
        report["runtime_overrides"] = model["runtime_overrides"]
        report["predictive_evaluation_for_this_variant"] = model[
            "predictive_evaluation_for_this_variant"
        ]
    feature_receipt = args.features.parent / "receipt.json"
    if feature_receipt.is_file():
        report["feature_receipt_sha256"] = sha256_file(feature_receipt)[0]
    report["output_sha256"] = sha256_json(report)
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    sys.stdout.write(
        json.dumps(
            {"coverage": model["coverage"], "lexical": model["lexical_representation"]}, indent=2
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
