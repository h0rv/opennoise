"""Independently replay FMA source grouping, training statistics and saved positive ranks."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import TypeAdapter

from opennoise.common import canonical_json, sha256_file
from scripts.audit_fma_native_source import projection_rows

MIN_LABEL_SUPPORT = 5
RARE_TRAINING_SUPPORT = 100
MAX_STANDARDIZED_OFFSET = 12

if TYPE_CHECKING:
    from collections.abc import Mapping


def independent_components(  # noqa: C901 - independent bipartite traversal.
    rows: Mapping[int, dict[str, object]], duplicates: list[list[int]]
) -> dict[int, int]:
    """Traverse a bipartite graph, independently of the model's union-find implementation."""
    graph: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    for row in rows.values():
        artist = row["artist_id"]
        if artist is None:
            continue
        a = ("artist", int(str(artist)))
        graph[a]
        if row["album_id"] is not None:
            b = ("album", int(str(row["album_id"])))
            graph[a].add(b)
            graph[b].add(a)
    for index, duplicate in enumerate(duplicates):
        b = ("duplicate", index)
        for identity in duplicate:
            if identity in rows and rows[identity]["artist_id"] is not None:
                a = ("artist", int(str(rows[identity]["artist_id"])))
                graph[a].add(b)
                graph[b].add(a)
    seen: set[tuple[str, int]] = set()
    result = {}
    for node in graph:
        if node in seen:
            continue
        todo = [node]
        artists = []
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            if current[0] == "artist":
                artists.append(current[1])
            todo.extend(graph[current] - seen)
        for artist in artists:
            result[artist] = min(artists)
    return result


def fold_for(identity: int, revision: str) -> int:
    """Reproduce the sealed native-component bucket from its complete digest."""
    bucket = int(hashlib.sha256(f"{revision}\0{identity}".encode()).hexdigest(), 16) % 1000
    return 0 if bucket < 800 else 1 if bucket < 900 else 2  # noqa: PLR2004 - sealed split.


def replay_metrics(
    rows: list[dict[str, object]],
    rankings: list[list[int]],
    reasons: list[str | None],
    labels: list[int],
    support: Counter[int],
) -> dict[str, object]:
    """Compute positive-only query and label measures using plain counters."""
    label_adapter = TypeAdapter(list[int])
    positives: Counter[int] = Counter()
    hits = {5: Counter(), 10: Counter()}
    reciprocal = 0.0
    unlabeled = 0
    for row, ranking in zip(rows, rankings, strict=True):
        target = set(label_adapter.validate_python(row["genre_ids"] or []))
        positives.update(target)
        unlabeled += not target
        reciprocal += next((1 / i for i, value in enumerate(ranking, 1) if value in target), 0)
        for k, counter in hits.items():
            counter.update(target & set(ranking[:k]))
    total = sum(positives.values())
    result: dict[str, object] = {
        "queries": len(rows),
        "unlabeled_queries": unlabeled,
        "labeled_queries": len(rows) - unlabeled,
        "source_positive_count": total,
        "mean_reciprocal_rank": reciprocal / max(1, len(rows) - unlabeled),
        "abstentions": dict(Counter(reason for reason in reasons if reason is not None)),
        "rare_positive_count": sum(
            n for label, n in positives.items() if support[label] <= RARE_TRAINING_SUPPORT
        ),
        "cold_positive_count": sum(
            n for label, n in positives.items() if support[label] < MIN_LABEL_SUPPORT
        ),
        "training_unseen_positive_count": sum(
            n for label, n in positives.items() if not support[label]
        ),
        "below_five_seen_positive_count": sum(
            n for label, n in positives.items() if 0 < support[label] < MIN_LABEL_SUPPORT
        ),
        "precision_available": False,
        "per_label": [
            {
                "genre_id": label,
                "training_positive_count": support[label],
                "held_out_positive_count": positives[label],
                "hits_at_5": hits[5][label],
                "hits_at_10": hits[10][label],
            }
            for label in labels
        ],
    }
    for k, counts in hits.items():
        result[f"recall_at_{k}"] = sum(counts.values()) / max(1, total)
        result[f"macro_recall_at_{k}"] = sum(
            counts[label] / n for label, n in positives.items()
        ) / max(1, len(positives))
        for name, predicate in (
            ("rare", lambda n: n <= RARE_TRAINING_SUPPORT),
            ("cold", lambda n: n < MIN_LABEL_SUPPORT),
            ("training_unseen", lambda n: n == 0),
        ):
            denominator = sum(n for label, n in positives.items() if predicate(support[label]))
            numerator = sum(n for label, n in counts.items() if predicate(support[label]))
            result[f"{name}_recall_at_{k}"] = numerator / max(1, denominator)
    return result


def audit(  # noqa: C901, PLR0912, PLR0915 - independent artifact/statistical boundary.
    metadata: Path, features: Path, model_directory: Path, saved_pack: Path | None = None
) -> dict[str, object]:
    """Verify all artifacts and recompute grouping, fit parameters and every saved metric."""
    report = json.loads((model_directory / "evaluation.json").read_bytes())
    declaration = json.loads((model_directory / "declaration.json").read_bytes())
    for name, facts in report["artifacts"].items():
        if sha256_file(model_directory / name) != (facts["sha256"], facts["bytes"]):
            raise ValueError("FMA model artifact hash or length differs")
    if sha256_file(metadata / "corpus-receipt.json")[0] != report["metadata_receipt_sha256"]:
        raise ValueError("audited source metadata receipt differs")
    metadata_receipt = json.loads((metadata / "corpus-receipt.json").read_bytes())
    for facts in metadata_receipt["files"].values():
        if sha256_file(metadata / facts["path"]) != (facts["sha256"], facts["bytes"]):
            raise ValueError("audited native metadata projection differs")
    feature_receipt = json.loads((features / "projection-receipt.json").read_bytes())
    if sha256_file(features / "projection-receipt.json")[0] != report["feature_receipt_sha256"]:
        raise ValueError("audited feature receipt differs")
    for name, facts in feature_receipt["files"].items():
        if sha256_file(features / name) != (facts["sha256"], facts["bytes"]):
            raise ValueError("audited feature artifact differs")
    rows = {
        int(str(row["track_id"])): row for row in projection_rows(metadata / "tracks.jsonl.zst")
    }
    duplicate = json.loads((features / "duplicate-native-feature-cells.json").read_bytes())
    component = independent_components(rows, duplicate)
    folds = {
        int(str(row["track_id"])): row
        for row in projection_rows(model_directory / "native-folds.jsonl.zst")
    }
    if rows.keys() != folds.keys():
        raise ValueError("native fold track identities differ")
    for identity, row in rows.items():
        saved = folds[identity]
        artist = row["artist_id"]
        group = component[int(str(artist))] if artist is not None else None
        expected = {
            "artist_id": artist,
            "album_id": row["album_id"],
            "artist_known": row["artist_id_status"] == "source_known",
            "component_id": group,
            "fold": fold_for(group, declaration["partition"]["revision"]) if group else -1,
        }
        if any(saved[key] != value for key, value in expected.items()):
            raise ValueError("independent native grouping or fold differs")
    train = [
        identity
        for identity in sorted(rows)
        if folds[identity]["artist_known"] and folds[identity]["fold"] == 0
    ]
    label_adapter = TypeAdapter(list[int])
    genre_lists = {
        identity: tuple(label_adapter.validate_python(row["genre_ids"] or []))
        for identity, row in rows.items()
    }
    support: Counter[int] = Counter(label for identity in train for label in genre_lists[identity])
    identity_array = np.memmap(features / "track_ids.uint32", dtype="<u4", mode="r")
    dimension = len(feature_receipt["columns"])
    values = np.memmap(
        features / "features.float32", dtype="<f4", mode="r", shape=(len(identity_array), dimension)
    )
    positions = {int(identity): i for i, identity in enumerate(identity_array)}
    finite_train = [
        identity
        for identity in train
        if identity in positions and np.isfinite(values[positions[identity]]).all()
    ]
    x = np.array([values[positions[identity]] for identity in finite_train], dtype=np.float64)
    center, scale = np.mean(x, axis=0), np.std(x, axis=0)
    active = scale > 0
    normalized = (x[:, active] - center[active]) / scale[active]
    model = dict(np.load(model_directory / "model.npz", allow_pickle=False))
    for key, expected in (("center", center), ("scale", scale), ("active_columns", active)):
        np.testing.assert_allclose(model[key], expected, rtol=1e-11, atol=1e-11)
    labels = [int(value) for value in model["labels"]]
    native_labels = sorted(
        int(str(row["genre_id"])) for row in projection_rows(metadata / "genres.jsonl.zst")
    )
    if labels != native_labels:
        raise ValueError("model label vocabulary differs from native taxonomy")
    feature_support = []
    for i, label in enumerate(labels):
        selected = np.array([label in genre_lists[identity] for identity in finite_train])
        count = int(selected.sum())
        feature_support.append(count)
        mean = normalized[selected].mean(axis=0) if count else np.zeros(int(active.sum()))
        variance = normalized[selected].var(axis=0) if count else np.zeros(int(active.sum()))
        variance = np.maximum(0.5 * variance + 0.5, 0.1)
        intercept = (
            -0.5 * np.sum(mean * mean / variance + np.log(variance))
            + np.log((support[label] + 0.5) / (len(train) + 1))
            if count >= MIN_LABEL_SUPPORT
            else -np.inf
        )
        for key, expected in (("quadratic", -0.5 / variance), ("linear", mean / variance)):
            np.testing.assert_allclose(model[key][i], expected, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(model["intercept"][i], intercept, rtol=1e-10, atol=1e-10)
    np.testing.assert_array_equal(model["label_feature_support"], feature_support)
    np.testing.assert_array_equal(
        model["active_labels"], np.array(feature_support) >= MIN_LABEL_SUPPORT
    )
    popularity = sorted(
        (label for label in labels if support[label]), key=lambda label: (-support[label], label)
    )
    constant = [label for label in labels if support[label]]
    verified_queries = 0
    for fold, name in ((1, "validation"), (2, "test")):
        selected = [
            rows[identity]
            for identity in sorted(rows)
            if folds[identity]["artist_known"] and folds[identity]["fold"] == fold
        ]
        saved = list(projection_rows(model_directory / f"{name}-acoustic-ranks.jsonl.zst"))
        if [row["track_id"] for row in selected] != [row["track_id"] for row in saved]:
            raise ValueError("held-out query identities or missing-query denominators differ")
        acoustic = [label_adapter.validate_python(row["ranked_genre_ids"]) for row in saved]
        reasons = TypeAdapter(list[str | None]).validate_python([row["reason"] for row in saved])
        for start in range(0, len(saved), 512):
            batch = saved[start : start + 512]
            query = np.full((len(batch), dimension), np.nan)
            exists = np.zeros(len(batch), dtype=bool)
            for i, query_row in enumerate(batch):
                identity = int(str(query_row["track_id"]))
                if identity in positions:
                    exists[i] = True
                    query[i] = values[positions[identity]]
            z = (query[:, active] - center[active]) / scale[active]
            complete = np.isfinite(z).all(axis=1)
            accepted = complete & (np.abs(z) <= MAX_STANDARDIZED_OFFSET).all(axis=1)
            score = np.einsum("ij,kj->ik", z[accepted] ** 2, model["quadratic"])
            score += np.einsum("ij,kj->ik", z[accepted], model["linear"])
            score += model["intercept"]
            valid_index = 0
            for i, query_row in enumerate(batch):
                expected_reason = (
                    "missing_feature_row"
                    if not exists[i]
                    else "missing_descriptors"
                    if not complete[i]
                    else "outside_training_support"
                    if not accepted[i]
                    else None
                )
                ranking = []
                if accepted[i]:
                    order = np.argsort(-score[valid_index], kind="stable")
                    ranking = [labels[j] for j in order if model["active_labels"][j]]
                    valid_index += 1
                if (
                    query_row["reason"] != expected_reason
                    or query_row["ranked_genre_ids"] != ranking
                ):
                    raise ValueError("independent query score ranking or abstention differs")
        for arm, rankings, arm_reasons in (
            ("acoustic", acoustic, reasons),
            ("popularity", [popularity] * len(saved), [None] * len(saved)),
            ("constant", [constant] * len(saved), [None] * len(saved)),
        ):
            replay = replay_metrics(selected, rankings, arm_reasons, labels, support)
            actual = report["evaluation"][name][arm]
            for key, expected in replay.items():
                if isinstance(expected, float):
                    if not np.isclose(actual[key], expected, rtol=1e-12, atol=1e-12):
                        raise ValueError(f"independent positive metric differs: {name}/{arm}/{key}")
                elif actual[key] != expected:
                    raise ValueError(f"independent positive metric differs: {name}/{arm}/{key}")
        verified_queries += len(saved)
    pack_targets = 0
    if saved_pack is not None:
        pack_receipt = json.loads((saved_pack / "pack-receipt.json").read_bytes())
        for name, facts in pack_receipt["files"].items():
            if sha256_file(saved_pack / name) != (facts["sha256"], facts["bytes"]):
                raise ValueError("saved FMA replay pack file differs")
        target_rows = list(projection_rows(saved_pack / "held-out-native-targets.jsonl.zst"))
        expected_targets = [
            {
                "track_id": identity,
                "fold": folds[identity]["fold"],
                "genre_ids": rows[identity]["genre_ids"],
            }
            for identity in sorted(rows)
            if folds[identity]["artist_known"] and folds[identity]["fold"] in (1, 2)
        ]
        if target_rows != expected_targets:
            raise ValueError("saved target pack differs from original native metadata")
        pack_targets = len(target_rows)
    return {
        "revision": "independent-fma-model-audit-v1",
        "model_report_sha256": sha256_file(model_directory / "evaluation.json")[0],
        "model_artifact_files_verified": len(report["artifacts"]),
        "native_track_folds_verified": len(rows),
        "independently_traversed_native_components": len(set(component.values())),
        "finite_training_rows_verified": len(finite_train),
        "gaussian_label_parameters_verified": len(labels),
        "validation_test_acoustic_queries_verified": verified_queries,
        "metric_arms_verified": 6,
        "tracked_pack_target_rows_verified_against_native_metadata": pack_targets,
        "heldout_missing_features_retained": True,
        "ranking_formula_recomputed": True,
        "independent_musical_relevance": "not_measured",
        "code_sha256": sha256_file(Path(__file__))[0],
    }


def main() -> None:
    """Write fresh evidence without fitting a second model or changing the frozen one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--saved-pack", type=Path)
    args = parser.parse_args()
    result = audit(args.metadata, args.features, args.model, args.saved_pack)
    with args.output.open("xb") as stream:
        stream.write(canonical_json(result) + b"\n")
    print(json.dumps(result, indent=2))  # noqa: T201 - independent audit receipt.


if __name__ == "__main__":
    main()
