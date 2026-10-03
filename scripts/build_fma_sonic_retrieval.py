"""Freeze and replay cross-component acoustic retrieval on native FMA identities."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import (
    _json_rows,
    artist_group_fold,
    load_features,
    load_metadata,
    native_components,
)
from opennoise.ml.sonic_retrieval import fit_index, freeze_queries, nearest, source_overlap

SEED = "opennoise-native-fma-sonic-retrieval-v1"
QUERY_LIMIT = 240
NEIGHBOR_LIMIT = 10
IMPLEMENTATION_PATHS = (
    "scripts/build_fma_sonic_retrieval.py",
    "src/opennoise/ml/sonic_retrieval.py",
    "src/opennoise/ml/fma_acoustic_baseline.py",
    "src/opennoise/ingest/fma_features.py",
)


def binding(path: Path) -> dict[str, object]:
    """Bind observed bytes without modifying their original source."""
    digest, length = sha256_file(path)
    return {"sha256": digest, "bytes": length}


def declared_policy(
    metadata: Path, model: Path, queries: list[int], raw_track_count: int
) -> dict[str, Any]:
    """Reconstruct the entire frozen contract without creating or replacing files."""
    return {
        "revision": SEED,
        "seed": SEED,
        "query_limit": QUERY_LIMIT,
        "queries": freeze_queries(queries, SEED, QUERY_LIMIT),
        "eligible_query_tracks": len(queries),
        "raw_track_denominator": raw_track_count,
        "query_selection_before_descriptor_or_score_inspection": True,
        "metadata_receipt": binding(metadata / "corpus-receipt.json"),
        "model_declaration": binding(model / "declaration.json"),
        "native_folds": binding(model / "native-folds.jsonl.zst"),
        "arms": ["standardized_euclidean", "training_annotation_frequency", "fixed_hash_order"],
        "neighbors": NEIGHBOR_LIMIT,
        "normalization": "finite whole-training rows only; omit constant dimensions",
        "support_gate": "abstain if any standardized active descriptor absolute value exceeds 12",
        "isolation": "native artist/known album/full-native-feature-duplicate connected components",
        "validation_reuse": (
            "previously reported validation; descriptive new frozen arm, not untouched confirmation"
        ),
        "source_absences_are_negatives": False,
        "musical_relevance_established": False,
        "license": "CC-BY-4.0",
    }


def freeze(metadata: Path, model: Path, output: Path) -> dict[str, Any]:
    """Declare the query roster before reading acoustic values or comparison scores."""
    original = json.loads((model / "declaration.json").read_bytes())
    tracks, _, _ = load_metadata(metadata, original)
    ledger = {row["track_id"]: row for row in _json_rows(model / "native-folds.jsonl.zst")}
    report = json.loads((model / "evaluation.json").read_bytes())
    if binding(model / "native-folds.jsonl.zst") != report["artifacts"]["native-folds.jsonl.zst"]:
        raise ValueError("saved native-fold binding differs")
    if {row.track_id for row in tracks} != set(ledger):
        raise ValueError("saved fold roster omits raw native track IDs")
    queries = [
        row.track_id for row in tracks if row.artist_known and ledger[row.track_id]["fold"] == 1
    ]
    declaration = declared_policy(metadata, model, queries, len(tracks))
    output.mkdir(parents=True, exist_ok=False)
    (output / "declaration.json").write_text(
        json.dumps(declaration, indent=2, sort_keys=True) + "\n"
    )
    return declaration


def run(  # noqa: C901 - replay native components and every frozen query in one boundary.
    metadata: Path, features: Path, model: Path, declaration_path: Path, output: Path
) -> dict[str, Any]:
    """Replay sources/components, fit once and preserve all frozen queries including failures."""
    declaration = json.loads(declaration_path.read_bytes())
    if declaration["revision"] != SEED or declaration["neighbors"] != NEIGHBOR_LIMIT:
        raise ValueError("retrieval declaration revision or neighbor limit differs")
    for name, path in (
        ("metadata_receipt", metadata / "corpus-receipt.json"),
        ("model_declaration", model / "declaration.json"),
        ("native_folds", model / "native-folds.jsonl.zst"),
    ):
        if binding(path) != declaration[name]:
            raise ValueError("frozen retrieval source binding differs")
    original = json.loads((model / "declaration.json").read_bytes())
    tracks, _, _ = load_metadata(metadata, original)
    ledger = {row["track_id"]: row for row in _json_rows(model / "native-folds.jsonl.zst")}
    if {row.track_id for row in tracks} != set(ledger):
        raise ValueError("saved fold roster omits raw native track IDs")
    eligible = [
        row.track_id for row in tracks if row.artist_known and ledger[row.track_id]["fold"] == 1
    ]
    if declared_policy(metadata, model, eligible, len(tracks)) != declaration:
        raise ValueError("frozen retrieval policy, denominators or query selection differ")
    identities, values, duplicates, feature_receipt = load_features(
        features, features.parent / "declaration.json"
    )
    components = native_components(tracks, duplicates)
    for row in tracks:
        component = components.get(row.artist_id)
        fold = artist_group_fold(component) if component is not None else -1
        if (
            ledger[row.track_id]["component_id"] != component
            or ledger[row.track_id]["fold"] != fold
        ):
            raise ValueError("saved fold differs from native component replay")
    by_identity = {row.track_id: row for row in tracks}
    feature_positions = {int(identity): i for i, identity in enumerate(identities)}
    feature_components = np.array(
        [ledger[int(identity)]["component_id"] or 0 for identity in identities]
    )
    training = np.array(
        [
            by_identity[int(identity)].artist_known and ledger[int(identity)]["fold"] == 0
            for identity in identities
        ]
    )
    index = fit_index(identities, feature_components, values, training)
    support = Counter(
        label
        for row in tracks
        if row.artist_known and ledger[row.track_id]["fold"] == 0
        for label in row.genre_ids
    )
    frequency = sorted(
        index.identities.astype(int).tolist(),
        key=lambda identity: (
            -sum(support[label] for label in by_identity[identity].genre_ids),
            identity,
        ),
    )
    fixed_hash = freeze_queries(
        index.identities.astype(int).tolist(), SEED + "-baseline", len(index.identities)
    )
    rows: list[dict[str, Any]] = []
    for identity in declaration["queries"]:
        track = by_identity[identity]
        component = components.get(track.artist_id)
        if component is None:
            raise ValueError("frozen resolved query component disappeared")
        position = feature_positions.get(identity)
        if position is None:
            neighbors, distances, reason = [], [], "missing_feature_row"
        else:
            neighbors, distances, reason = nearest(
                index, values[position], component, limit=NEIGHBOR_LIMIT
            )
        arms = {
            "standardized_euclidean": neighbors,
            "training_annotation_frequency": [
                i for i in frequency if components.get(by_identity[i].artist_id) != component
            ][:NEIGHBOR_LIMIT],
            "fixed_hash_order": [
                i for i in fixed_hash if components.get(by_identity[i].artist_id) != component
            ][:NEIGHBOR_LIMIT],
        }
        rows.append(
            {
                "track_id": identity,
                "artist_id": track.artist_id,
                "component_id": component,
                "genre_ids": list(track.genre_ids),
                "targets_missing": track.targets_missing,
                "reason": reason,
                "distances": distances,
                "arms": {
                    arm: {
                        "track_ids": selected,
                        **source_overlap(
                            track.genre_ids, [by_identity[i].genre_ids for i in selected]
                        ),
                    }
                    for arm, selected in arms.items()
                },
            }
        )
    results = {}
    for arm in declaration["arms"]:
        positives = sum(row["arms"][arm]["observed_positives"] for row in rows)
        recovered = sum(row["arms"][arm]["recovered_positives"] for row in rows)
        labelled = sum(bool(row["genre_ids"]) for row in rows)
        results[arm] = {
            "source_positive_count": positives,
            "recovered_positives_in_neighbor_annotation_union": recovered,
            "union_source_recall": recovered / max(1, positives),
            "queries_with_any_observed_overlap": sum(
                row["arms"][arm]["any_observed_overlap"] for row in rows
            ),
            "labelled_queries": labelled,
            "unknown_annotation_queries": len(rows) - labelled,
            "musical_precision_available": False,
        }
    output.mkdir(parents=True, exist_ok=False)
    (output / "queries.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    np.savez_compressed(
        output / "normalization.npz", center=index.center, scale=index.scale, active=index.active
    )
    report = {
        "revision": SEED,
        "implementation": {
            name: binding(Path(__file__).resolve().parents[1] / name)
            for name in IMPLEMENTATION_PATHS
        },
        "declaration": binding(declaration_path),
        "feature_receipt": binding(features / "projection-receipt.json"),
        "native_feature_member_sha256": feature_receipt["native_observed_sha256"],
        "training_index_rows": len(index.identities),
        "training_components": len(set(index.components.tolist())),
        "frozen_queries": len(rows),
        "query_components": len({row["component_id"] for row in rows}),
        "abstentions": dict(Counter(row["reason"] for row in rows if row["reason"])),
        "evaluation": results,
        "files": {path.name: binding(path) for path in sorted(output.iterdir())},
        "license": "CC-BY-4.0",
        "namespace": "native-fma-track",
        "musical_relevance_established": False,
        "recording_identity_or_musicbrainz_bridge_claimed": False,
        "validation_reuse": declaration["validation_reuse"],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    """Require explicit sources and fresh outputs for freezing or one-arm replay."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--declaration", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        report = freeze(args.metadata, args.model, args.output)
    else:
        if args.features is None or args.declaration is None:
            parser.error("run requires --features and --declaration")
        report = run(args.metadata, args.features, args.model, args.declaration, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))  # noqa: T201 - CLI JSON report.


if __name__ == "__main__":
    main()
