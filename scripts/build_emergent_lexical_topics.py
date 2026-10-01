"""Run the separate native-tag lexical representation experiment."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import cast

import numpy as np
from scipy import sparse

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.emergent_lexical_topics import REVISION, fit_lexical_topics
from opennoise.ml.emergent_topics import TopicSettings, load_features


def main() -> int:
    """Write lexical source assignments and full source centroid artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to overwrite a lexical experiment")
    settings = TopicSettings()
    data = load_features(args.features, settings)
    model, assignments = fit_lexical_topics(data, settings, include_centroids=True)
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
        "revision": REVISION,
        "scope": "local_research_only",
        "settings": asdict(settings),
        "coverage": model["coverage"],
        "lexical_representation": model["lexical_representation"],
        "features_sha256": data.input_sha256,
        "code_sha256": sha256_file(Path("src/opennoise/ml/emergent_lexical_topics.py"))[0],
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
