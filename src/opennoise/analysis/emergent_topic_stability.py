"""Independent fixed source-cohort subsample refits for inferred topic stability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter

from opennoise.analysis.emergent_community_evaluation import _partition_stability
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.emergent_topics import TopicSettings, fit_topics, load_features

REPLICATES = 3
SAMPLE_SALT = "emergent-source-cohort-stability-v1-fixed-20260930"


def retained_in_subsample(artist: str, replicate: int) -> bool:
    """Choose 80% of exact identities without consulting labels, features, or scores."""
    digest = hashlib.sha256(f"{SAMPLE_SALT}\0{replicate}\0{artist}".encode()).digest()
    return int.from_bytes(digest, "big") % 5 != 0


def evaluate_topic_stability(
    *, features_path: Path, model_directory: Path, output: Path, settings: TopicSettings
) -> dict[str, object]:
    """Recompute features, support, IDF, and topic fits in three frozen 80% cohorts."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace topic subsample evaluations")
    source_hash = sha256_file(features_path)[0]
    model_path = Path(__file__).parents[1] / "ml/emergent_topics.py"
    code_hash = sha256_file(model_path)[0]
    report = json.loads((model_directory / "report.json").read_bytes())
    digest = report.pop("output_sha256")
    if (
        sha256_json(report) != digest
        or report["features_sha256"] != source_hash
        or report["code_sha256"] != code_hash
        or canonical_json(report["settings"]) != canonical_json(asdict(settings))
    ):
        raise ValueError("stability reference differs from frozen source, code, or settings")
    primary_path = model_directory / "primary-assignments.json"
    binding = report["files"]["primary-assignments.json"]
    if sha256_file(primary_path) != (binding["sha256"], binding["bytes"]):
        raise ValueError("stability reference primary assignments are byte-mutated")
    reference = TypeAdapter(dict[str, dict[str, str | None]]).validate_json(
        primary_path.read_bytes()
    )
    output.mkdir(parents=True)
    runs = []
    for replicate in range(REPLICATES):
        sample = output / f"subsample-{replicate}.jsonl"
        selected = 0
        with (
            features_path.open(encoding="utf-8") as source,
            sample.open("x", encoding="utf-8") as target,
        ):
            for line in source:
                row = json.loads(line)
                if retained_in_subsample(row["artist_mbid"], replicate):
                    target.write(line)
                    selected += 1
        data = load_features(sample, settings)
        model, _memberships = fit_topics(data, settings)
        primary = TypeAdapter(dict[str, dict[str, str | None]]).validate_python(
            model["primary_assignments"]
        )
        path = output / f"primary-{replicate}.json"
        path.write_bytes(canonical_json(primary) + b"\n")
        runs.append(
            {
                "replicate": replicate,
                "selected_artist_count": selected,
                "sample_sha256": sha256_file(sample)[0],
                "primary_assignments_sha256": sha256_file(path)[0],
                "coverage": model["coverage"],
                "partitions": {
                    level: _partition_stability(assignments, primary[level])
                    for level, assignments in reference.items()
                },
            }
        )
        if sha256_file(model_path)[0] != code_hash:
            raise ValueError("topic model code changed during the frozen stability run")
    result: dict[str, object] = {
        "revision": "emergent-topic-source-subsample-stability-v1",
        "scope": "local_research_only",
        "source_sha256": source_hash,
        "reference_report_output_sha256": digest,
        "model_code_sha256": code_hash,
        "evaluator_sha256": sha256_file(Path(__file__))[0],
        "settings": asdict(settings),
        "sample_salt": SAMPLE_SALT,
        "sample_rule": "SHA256(revision,NUL,replicate,NUL,artist) mod5 !=0",
        "feature_support_and_idf_refitted": True,
        "replicates": runs,
        "best_run_selection": False,
        "genre_names_validated": False,
        "limitation": (
            "Cohort sensitivity, not independent musical ground truth "
            "or held-out feature prediction."
        ),
    }
    result["output_sha256"] = sha256_json(result)
    (output / "report.json").write_bytes(canonical_json(result) + b"\n")
    return result
