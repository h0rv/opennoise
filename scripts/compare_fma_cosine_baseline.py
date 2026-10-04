"""Compare one frozen cosine arm against the previously inspected native FMA baseline."""

from __future__ import annotations

import argparse
import io
import json
import resource
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import zstandard

from opennoise.common import sha256_file
from opennoise.ml import fma_cosine_baseline
from opennoise.ml.fma_acoustic_baseline import (
    PositiveMetrics,
    artist_group_fold,
    load_features,
    load_metadata,
    native_components,
)
from opennoise.ml.fma_cosine_baseline import PositiveCosine

if TYPE_CHECKING:
    from collections.abc import Iterator

BATCH_ROWS = 512
LIMITS = {"model_run_seconds": 120, "memory_bytes": 1_000_000_000, "new_outputs_bytes": 100_000_000}
PARAMETERS = {
    "minimum_finite_positive_support": 5,
    "minimum_vector_norm": 1e-12,
    "maximum_standardized_absolute_value": 12,
}


def read_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Stream immutable saved ledger/rank records without retaining complete rank arrays."""
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as reader,
        io.TextIOWrapper(reader, encoding="utf-8") as text,
    ):
        for line in text:
            yield json.loads(line)


def compare(args: argparse.Namespace) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - one bounded artifact boundary.
    """Verify native inputs and fixed folds, then evaluate the single declared cosine arm."""
    started = time.monotonic()
    declared = json.loads(args.declaration.read_bytes())
    if declared["parameters"] != PARAMETERS or declared["limits"] != LIMITS:
        raise ValueError("comparison differs from frozen implementation or resource guards")
    if (
        declared["baseline_evaluation_sha256"] != sha256_file(args.baseline / "evaluation.json")[0]
        or declared["native_declaration_sha256"] != sha256_file(args.native_declaration)[0]
        or declared["historical_test_previously_inspected"] is not True
    ):
        raise ValueError("baseline binding or prior-test disclosure differs")
    baseline = json.loads((args.baseline / "evaluation.json").read_bytes())
    for name, binding in baseline["artifacts"].items():
        if sha256_file(args.baseline / name) != (binding["sha256"], binding["bytes"]):
            raise ValueError("baseline artifact differs")
    native_declaration = json.loads(args.native_declaration.read_bytes())
    tracks, labels, _ = load_metadata(args.metadata, native_declaration)
    ids, values, duplicates, _ = load_features(args.features, args.native_declaration)
    for path, key in (
        (args.metadata / "corpus-receipt.json", "metadata_receipt_sha256"),
        (args.features / "projection-receipt.json", "feature_receipt_sha256"),
    ):
        if sha256_file(path)[0] != baseline[key]:
            raise ValueError("comparison inputs differ from baseline")
    components = native_components(tracks, duplicates)
    folds = []
    for row, saved in zip(tracks, read_rows(args.baseline / "native-folds.jsonl.zst"), strict=True):
        group = components.get(row.artist_id)
        fold = artist_group_fold(group) if group is not None else -1
        expected = {
            "track_id": row.track_id,
            "artist_id": row.artist_id,
            "artist_known": row.artist_known,
            "album_id": row.album_id,
            "component_id": group,
            "fold": fold,
        }
        if saved != expected:
            raise ValueError("native component ledger differs")
        folds.append(fold if row.artist_known else -1)
    with np.load(args.baseline / "model.npz", allow_pickle=False) as loaded:
        model = PositiveCosine.from_gaussian(dict(loaded))
    if model.labels.tolist() != list(labels):
        raise ValueError("model label vocabulary differs")
    positions = {int(identity): i for i, identity in enumerate(ids)}
    label_positions = {label: i for i, label in enumerate(labels)}
    support = np.zeros(len(labels), dtype=np.int64)
    for row, fold in zip(tracks, folds, strict=True):
        if fold == 0:
            for label in row.genre_ids:
                support[label_positions[label]] += 1
    args.output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(args.output / "model.npz", **asdict(model))
    # Verify the reusable load contract before recording any metrics.
    with np.load(args.output / "model.npz", allow_pickle=False) as loaded:
        restored = PositiveCosine(**dict(loaded))
    for name, value in asdict(model).items():
        np.testing.assert_array_equal(value, getattr(restored, name))
    evaluation = {}
    for fold, name in ((1, "validation"), (2, "test")):
        selected = [row for row, assigned in zip(tracks, folds, strict=True) if assigned == fold]
        metric = PositiveMetrics(labels, support)
        baseline_ranks = read_rows(args.baseline / f"{name}-acoustic-ranks.jsonl.zst")
        with (
            (args.output / f"{name}-cosine-ranks.jsonl.zst").open("xb") as raw,
            zstandard.ZstdCompressor(level=6).stream_writer(raw) as writer,
        ):
            for start in range(0, len(selected), BATCH_ROWS):
                batch = selected[start : start + BATCH_ROWS]
                x = np.full((len(batch), values.shape[1]), np.nan)
                for i, row in enumerate(batch):
                    if row.track_id in positions:
                        x[i] = values[positions[row.track_id]]
                scores, reasons = restored.score(x)
                ordered = np.argsort(-scores, axis=1, kind="stable")
                for i, row in enumerate(batch):
                    if next(baseline_ranks)["track_id"] != row.track_id:
                        raise ValueError("baseline query denominator differs")
                    reason = reasons[i] if row.track_id in positions else "missing_feature_row"
                    ranking = (
                        [int(index) for index in ordered[i] if restored.active_labels[index]]
                        if reason is None
                        else []
                    )
                    metric.add([label_positions[label] for label in row.genre_ids], ranking, reason)
                    record = {
                        "track_id": row.track_id,
                        "reason": reason,
                        "ranked_genre_ids": [labels[index] for index in ranking],
                    }
                    writer.write((json.dumps(record, sort_keys=True) + "\n").encode())
        if next(baseline_ranks, None) is not None:
            raise ValueError("baseline has surplus queries")
        report = metric.report()
        for key in ("queries", "labeled_queries", "source_positive_count"):
            if report[key] != baseline["evaluation"][name]["acoustic"][key]:
                raise ValueError("evaluation denominator differs")
        evaluation[name] = {"cosine": report, **baseline["evaluation"][name]}
    for path in (args.declaration, Path(__file__), Path(fma_cosine_baseline.__file__)):
        (args.output / path.name).write_bytes(path.read_bytes())
    artifacts: dict[str, dict[str, Any]] = {
        p.name: {"sha256": sha256_file(p)[0], "bytes": p.stat().st_size}
        for p in sorted(args.output.iterdir())
    }
    if sum(row["bytes"] for row in artifacts.values()) > LIMITS["new_outputs_bytes"]:
        raise ValueError("comparison output budget exceeded")
    elapsed = time.monotonic() - started
    if elapsed > LIMITS["model_run_seconds"]:
        raise ValueError("comparison time budget exceeded")
    result = {
        "revision": declared["revision"],
        "declaration_sha256": sha256_file(args.declaration)[0],
        "baseline_evaluation_sha256": declared["baseline_evaluation_sha256"],
        "native_fold_ledger_sha256": sha256_file(args.baseline / "native-folds.jsonl.zst")[0],
        "coverage": baseline["coverage"],
        "partition": baseline["partition"],
        "source_positive_support": dict(zip(map(str, labels), map(int, support), strict=True)),
        "finite_feature_positive_support": model.label_feature_support.tolist(),
        "active_prototypes": int(model.active_labels.sum()),
        "zero_norm_supported_prototypes": int(
            (
                (model.label_feature_support >= PARAMETERS["minimum_finite_positive_support"])
                & ~model.active_labels
            ).sum()
        ),
        "evaluation": evaluation,
        "historical_test_previously_inspected": True,
        "selection_performed": False,
        "limitations": baseline["limitations"],
        "resource": {
            "elapsed_seconds": elapsed,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "limits": LIMITS,
        },
        "artifacts": artifacts,
    }
    encoded = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) + sum(row["bytes"] for row in artifacts.values()) > LIMITS["new_outputs_bytes"]:
        raise ValueError("complete comparison output budget exceeded")
    (args.output / "evaluation.json").write_bytes(encoded)
    return result


def main() -> None:
    """Enforce existing process guards and require explicit immutable input locations."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("metadata", "features", "native-declaration", "baseline", "declaration", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (LIMITS["memory_bytes"], LIMITS["memory_bytes"]))
    resource.setrlimit(
        resource.RLIMIT_CPU, (LIMITS["model_run_seconds"], LIMITS["model_run_seconds"])
    )
    result = compare(args)
    print(  # noqa: T201 - execution receipt.
        json.dumps(
            {"resource": result["resource"], "active_prototypes": result["active_prototypes"]}
        )
    )


if __name__ == "__main__":
    main()
