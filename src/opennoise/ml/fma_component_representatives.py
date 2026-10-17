"""One fixed extra training representative per historically retained component."""

from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, BinaryIO, cast

import numpy as np
import zstandard

from opennoise.ml.fma_component_balanced import Corpus, load_corpus
from opennoise.ml.fma_component_representatives_custody import (
    MAX_OUTPUT_BYTES,
    BoundedWriter,
    digest,
    encoded,
    inventory,
    no_symlink,
    output_bytes,
    receipt,
    verify_seal,
    verify_stage,
    write_json,
)
from opennoise.ml.fma_component_representatives_stats import (
    ARMS,
    BUCKETS,
    METRICS,
    accumulate,
    empty_component,
    label_histogram,
    summarize,
)
from opennoise.ml.fma_retrieval_loss import analyze_fold, candidate_pool, vote_ranking

BATCH = 256
NEIGHBORS = 10
MAX_COMPONENTS = 2048
SUPPORT_LIMIT = 12
GEOMETRY_ATOL = 1e-12
GIANT_COMPONENT = 2


def raw_geometry(
    features: np.ndarray, center: np.ndarray, scale: np.ndarray, active: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply saved normalization only; complete descriptors and exact positive norm."""
    width = features.shape[1]
    if (
        center.shape != (width,)
        or scale.shape != (width,)
        or active.shape != (width,)
        or active.dtype != np.bool_
        or not np.isfinite(center).all()
        or not np.isfinite(scale).all()
        or np.any(scale[active] <= 0)
    ):
        raise ValueError("Invalid saved raw normalization")
    z = (np.asarray(features[:, active], dtype=np.float64) - center[active]) / scale[active]
    supported = np.isfinite(features).all(axis=1) & (np.abs(z) <= SUPPORT_LIMIT).all(axis=1)
    z = np.where(supported[:, None], z, 0)
    norms = np.linalg.norm(z, axis=1)
    usable = supported & (norms > 0)
    units = np.divide(z, norms[:, None], out=np.zeros_like(z), where=norms[:, None] > 0)
    return units, supported, usable


def choose_representatives(  # noqa: PLR0913, PLR0917 - explicit label-free geometry inputs.
    ids: np.ndarray,
    groups: np.ndarray,
    folds: np.ndarray,
    units: np.ndarray,
    usable: np.ndarray,
    original_ids: list[int],
    fold: int,
) -> list[dict[str, Any]]:
    """Choose farthest different eligible recordings without receiving source labels."""
    if len(original_ids) > MAX_COMPONENTS or original_ids != sorted(set(original_ids)):
        raise ValueError("Original representative roster differs")
    lookup = {int(track): index for index, track in enumerate(ids)}
    if len(lookup) != len(ids) or any(track not in lookup for track in original_ids):
        raise ValueError("Unknown or duplicate native recording")
    original_rows = [lookup[track] for track in original_ids]
    selected_groups = {int(groups[row]) for row in original_rows}
    if len(selected_groups) != len(original_rows) or any(
        folds[row] == fold or not usable[row] for row in original_rows
    ):
        raise ValueError("Original representative is unsupported or leaks a component")
    members: dict[int, list[int]] = defaultdict(list)
    total_members: Counter[int] = Counter()
    for row in np.flatnonzero(folds != fold):
        group = int(groups[row])
        if group in selected_groups:
            total_members[group] += 1
            if usable[row]:
                members[group].append(int(row))
    result = []
    for original in original_rows:
        group = int(groups[original])
        others = [row for row in members[group] if row != original]
        second = None
        distance = None
        identical = False
        if others:
            similarities = units[others] @ units[original]
            order = np.lexsort((ids[others], similarities))
            second = others[int(order[0])]
            distance = float(1 - similarities[order[0]])
            identical = bool(np.array_equal(units[original], units[second]))
        result.append(
            {
                "component_id": group,
                "original_track_id": int(ids[original]),
                "second_track_id": int(ids[second]) if second is not None else None,
                "eligible_records": len(members[group]),
                "training_records": total_members[group],
                "second_cosine_distance": distance,
                "identical_unit_vector": identical,
            }
        )
    return result


def component_neighbors(
    scores: np.ndarray, originals: np.ndarray, extra_scores: np.ndarray, extras: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Choose max-scoring representatives, then distinct components, with native-ID ties."""
    if (
        scores.shape != extra_scores.shape
        or scores.shape[1] != len(originals)
        or len(extras) != len(originals)
    ):
        raise ValueError("Component score shape differs")
    has_extra = extras > 0
    use_extra = has_extra[None, :] & (
        (extra_scores > scores)
        | ((extra_scores == scores) & (extras[None, :] < originals[None, :]))
    )
    winners = np.where(use_extra, extras[None, :], originals[None, :])
    best = np.where(use_extra, extra_scores, scores)
    order = np.lexsort((winners, -best), axis=1)[:, :NEIGHBORS]
    return np.take_along_axis(winners, order, axis=1), np.take_along_axis(best, order, axis=1)


def _roster(data: Corpus) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]]]:
    roster: dict[int, dict[str, Any]] = {}
    for index, track in enumerate(data.ids.tolist()):
        columns = data.targets.indices[data.targets.indptr[index] : data.targets.indptr[index + 1]]
        roster[track] = {
            "component_id": int(data.groups[index]),
            "inner_fold": int(data.inner_folds[index]),
            "targets": {data.labels[col] for col in columns},
        }
    return roster, {track: row["targets"] for track, row in roster.items()}


def _raw_reason(complete: bool, supported: bool, usable: bool, pool: int) -> str | None:  # noqa: FBT001
    if not complete:
        return "missing_descriptors"
    if not supported:
        return "outside_training_support"
    if not usable:
        return "raw_zero_norm"
    return None if pool else "no_joint_candidates"


def _prediction(
    ids: list[int],
    scores: list[float],
    labels: dict[int, set[int]],
    reason: str | None,
    usable: bool,  # noqa: FBT001 - saved descriptor availability.
) -> dict[str, Any]:
    return {
        "neighbor_ids": ids,
        "cosine_scores": scores,
        "ranking": vote_ranking(ids, labels),
        "reason": reason,
        "descriptor_available": usable,
    }


def _check_raw(saved: dict[str, Any], actual: dict[str, Any]) -> None:
    if (
        saved["neighbor_ids"] != actual["neighbor_ids"]
        or saved["ranking"] != actual["ranking"]
        or saved["reason"] != actual["reason"]
        or saved["descriptor_available"] != actual["descriptor_available"]
        or not np.allclose(
            saved["cosine_distances"],
            1 - np.asarray(actual["cosine_scores"]),
            rtol=0,
            atol=GEOMETRY_ATOL,
        )
    ):
        raise ValueError("Frozen original raw geometry or votes did not replay")


def _candidate_report(
    data: Corpus,
    fold: int,
    usable: np.ndarray,
    roster: list[dict[str, Any]],
    labels: dict[int, set[int]],
) -> dict[str, Any]:
    original = [row["original_track_id"] for row in roster]
    expanded = sorted(
        [
            *original,
            *(row["second_track_id"] for row in roster if row["second_track_id"] is not None),
        ]
    )
    fit = data.inner_folds != fold
    return {
        "revision": "fma-component-representatives-candidates-v1",
        "fold": fold,
        "components": roster,
        "fit_records": int(fit.sum()),
        "finite_fit_records": int((fit & np.isfinite(data.features).all(axis=1)).sum()),
        "raw_eligible_fit_records": int((fit & usable).sum()),
        "candidate_components": len(roster),
        "second_representatives": len(expanded) - len(original),
        "identical_unit_vector_seconds": sum(row["identical_unit_vector"] for row in roster),
        "giant_component_2_present": any(row["component_id"] == GIANT_COMPONENT for row in roster),
        "arms": {
            name: {
                "record_count": len(ids),
                "label_count_histogram": label_histogram(ids, labels),
                "source_label_union": sorted(set[int]().union(*(labels[track] for track in ids))),
            }
            for name, ids in zip(ARMS[:2], [original, expanded], strict=True)
        },
    }


def _public_candidates(report: dict[str, Any]) -> dict[str, Any]:
    """Keep aggregate reports free of recording, component and source-label rosters."""
    result = {key: value for key, value in report.items() if key not in {"components", "arms"}}
    result["arms"] = {
        arm: {key: value for key, value in values.items() if key != "source_label_union"}
        | {"source_label_count": len(values["source_label_union"])}
        for arm, values in report["arms"].items()
    }
    distances = [
        row["second_cosine_distance"]
        for row in report["components"]
        if row["second_track_id"] is not None
    ]
    result["second_cosine_distance"] = (
        {
            "minimum": min(distances),
            "median": float(np.median(distances)),
            "maximum": max(distances),
        }
        if distances
        else None
    )
    for field in ("eligible_records", "training_records"):
        result[field + "_histogram"] = sorted(
            Counter(row[field] for row in report["components"]).items()
        )
    return result


def _original_statistics(folder: Path, components: list[dict[str, Any]]) -> None:
    with np.load(folder / "statistics.npz", allow_pickle=False) as saved:
        ids, values = saved["components"], saved["values"]
    if ids.tolist() != [row["component_id"] for row in components]:
        raise ValueError("Original component roster differs")
    for index, row in enumerate(components):
        for current, old in [(0, 0), (2, 4)]:
            if not np.allclose(
                row["statistics"][current],
                values[index, old, [0, 1, 2, 3, 4, 11, 12, 6]],
                rtol=0,
                atol=1e-10,
            ):
                raise ValueError("Original raw or popularity sufficient statistics differ")


def run_fold(seal: Path, output: Path, fold: int) -> None:  # noqa: PLR0915 - one bounded streamed fold.
    """Compute one reviewed fold using frozen normalization, without fitting anything."""
    if fold not in range(5):
        raise ValueError("Invalid held-out fold")
    no_symlink(output)
    directory = output / f"fold-{fold}"
    if directory.exists():
        raise FileExistsError("Fresh fold output required")
    output_bytes(output)
    if output.exists() and not {path.name for path in output.iterdir()}.issubset(
        {f"fold-{number}" for number in range(5)}
    ):
        raise ValueError("Fold output root contains unexpected entries")
    spec = verify_seal(seal)
    data = load_corpus({"source": spec["source"]})
    roster, labels = _roster(data)
    original_folder = Path(spec["original_run"]) / f"fold-{fold}"
    # Verify original targets, complete query roster, votes, reasons and all five controls first.
    analyze_fold(original_folder, fold, roster, set(data.labels))
    candidates = json.loads((original_folder / "candidates.json").read_bytes())
    original_pool, old_union = candidate_pool(candidates, fold, roster)
    with np.load(original_folder / "embedding.npz", allow_pickle=False) as saved:
        units, supported, usable = raw_geometry(
            data.features, saved["center"], saved["scale"], saved["active_columns"]
        )
    representatives = choose_representatives(
        data.ids, data.groups, data.inner_folds, units, usable, sorted(original_pool), fold
    )
    report = _candidate_report(data, fold, usable, representatives, labels)
    original_ids = np.array([row["original_track_id"] for row in representatives], dtype=np.int64)
    extra_ids = np.array([row["second_track_id"] or 0 for row in representatives], dtype=np.int64)
    index = {int(track): row for row, track in enumerate(data.ids)}
    original_vectors = units[[index[int(track)] for track in original_ids]]
    extra_vectors = np.array(
        [units[index[int(track)]] if track else np.zeros(units.shape[1]) for track in extra_ids]
    ).reshape(len(extra_ids), units.shape[1])
    new_union = set(report["arms"][ARMS[1]]["source_label_union"])
    groups = {track: row["component_id"] for track, row in roster.items()}
    query = np.flatnonzero(data.inner_folds == fold)
    components: dict[int, dict[str, Any]] = {}
    directory.mkdir(parents=True)
    write_json(output, directory / "candidates.json", report)
    remaining = MAX_OUTPUT_BYTES - output_bytes(output)
    with (
        (directory / "predictions.jsonl.zst").open("xb") as raw_file,
        zstandard.open(original_folder / "ranks.jsonl.zst", "rt") as previous,
    ):
        bounded = BoundedWriter(raw_file, remaining)
        with zstandard.ZstdCompressor(level=3).stream_writer(
            cast("BinaryIO", bounded), closefd=False
        ) as stream:
            for start in range(0, len(query), BATCH):
                batch = query[start : start + BATCH]
                original_scores = units[batch] @ original_vectors.T
                nearest = np.argsort(-original_scores, axis=1, kind="stable")[:, :NEIGHBORS]
                # Replay the complete original batch before computing its new neighborhoods.
                originals, saved_rows = [], []
                for offset, row in enumerate(batch):
                    saved_row = json.loads(next(previous))
                    if saved_row["track_id"] != int(data.ids[row]):
                        raise ValueError("Saved query order differs")
                    reason = _raw_reason(
                        bool(np.isfinite(data.features[row]).all()),
                        bool(supported[row]),
                        bool(usable[row]),
                        len(original_ids),
                    )
                    selected = nearest[offset] if reason is None else []
                    actual = _prediction(
                        [int(original_ids[col]) for col in selected],
                        [float(original_scores[offset, col]) for col in selected],
                        labels,
                        reason,
                        bool(usable[row]),
                    )
                    _check_raw(saved_row["arms"]["raw44_neighbors"], actual)
                    originals.append(actual)
                    saved_rows.append(saved_row)
                extra_scores = units[batch] @ extra_vectors.T
                winning_ids, winning_scores = component_neighbors(
                    original_scores, original_ids, extra_scores, extra_ids
                )
                for offset, row in enumerate(batch):
                    track = int(data.ids[row])
                    old = originals[offset]
                    selected_ids = winning_ids[offset].tolist() if old["reason"] is None else []
                    scores = winning_scores[offset].tolist() if selected_ids else []
                    if len({groups[track_id] for track_id in selected_ids}) != len(
                        selected_ids
                    ) or any(
                        groups[track_id] == groups[track] or roster[track_id]["inner_fold"] == fold
                        for track_id in selected_ids
                    ):
                        raise ValueError("New neighborhood leaks or repeats components")
                    new = _prediction(
                        selected_ids, scores, labels, old["reason"], old["descriptor_available"]
                    )
                    popularity = saved_rows[offset]["arms"]["recording_popularity"]
                    predictions = [old, new, popularity]
                    component = groups[track]
                    stats = components.setdefault(component, empty_component(component, fold))
                    accumulate(
                        stats, labels[track], predictions, [old_union, new_union], labels, groups
                    )
                    record = {
                        "track_id": track,
                        "component_id": component,
                        "inner_fold": fold,
                        "targets": sorted(labels[track]),
                        "arms": dict(zip(ARMS, predictions, strict=True)),
                    }
                    stream.write(encoded(record))
            if previous.read(1):
                raise ValueError("Unexpected trailing original query")
    ordered = [components[key] for key in sorted(components)]
    _original_statistics(original_folder, ordered)
    summarize(ordered)
    write_json(
        output,
        directory / "components.json",
        {
            "arms": ARMS,
            "statistics_columns": METRICS,
            "bucket_columns": BUCKETS,
            "components": ordered,
        },
    )
    receipt(output, directory, seal, f"fold-{fold}")


def summarize_run(seal: Path, output: Path) -> None:
    """Close all five folds with paired scopes and descriptive mechanism counts."""
    spec = verify_seal(seal)
    output_bytes(output)
    if {path.name for path in output.iterdir()} != {f"fold-{fold}" for fold in range(5)}:
        raise ValueError("Summary requires exactly five fresh completed fold stages")
    components, candidate_reports, fold_receipts = [], {}, {}
    data = load_corpus({"source": spec["source"]})
    for fold in range(5):
        folder = output / f"fold-{fold}"
        verify_stage(folder, seal, f"fold-{fold}")
        result = json.loads((folder / "components.json").read_bytes())
        if (
            result["arms"] != list(ARMS)
            or result["statistics_columns"] != list(METRICS)
            or result["bucket_columns"] != list(BUCKETS)
        ):
            raise ValueError("Fold sufficient-statistic schema differs")
        rows = result["components"]
        expected, counts = np.unique(data.groups[data.inner_folds == fold], return_counts=True)
        if [row["component_id"] for row in rows] != expected.tolist() or any(
            row["fold"] != fold or row["statistics"][0][0] != count
            for row, count in zip(rows, counts, strict=True)
        ):
            raise ValueError("Fold component or query roster differs")
        components.extend(rows)
        candidate_reports[str(fold)] = _public_candidates(
            json.loads((folder / "candidates.json").read_bytes())
        )
        fold_receipts[str(fold)] = digest(folder / "receipt.json")
    components.sort(key=lambda row: row["component_id"])
    if len({row["component_id"] for row in components}) != len(components):
        raise ValueError("Component crosses held-out folds")
    result = {
        "revision": "fma-component-representatives-results-v1",
        "pooled": summarize(components),
        "per_fold": {
            str(fold): summarize([row for row in components if row["fold"] == fold])
            for fold in range(5)
        },
        "giant_component_2": summarize(
            [row for row in components if row["component_id"] == GIANT_COMPONENT]
        ),
        "all_other_components": summarize(
            [row for row in components if row["component_id"] != GIANT_COMPONENT]
        ),
        "candidate_reports": candidate_reports,
        "fold_receipts": fold_receipts,
        "interpretation": spec["protocol"]["decision"],
        "uncertainty": spec["protocol"]["uncertainty"],
    }
    directory = output / "summary"
    directory.mkdir()
    write_json(output, directory / "results.json", result)
    receipt(output, directory, seal, "summary")


def replay_fold(seal: Path, output: Path, fold: int) -> None:
    """Recompute one fold in fresh temporary space and require identical bytes."""
    output_bytes(output)
    if not {path.name for path in output.iterdir()}.issubset(
        {"summary", *(f"fold-{number}" for number in range(5))}
    ):
        raise ValueError("Replay output root contains unexpected entries")
    verify_stage(output / f"fold-{fold}", seal, f"fold-{fold}")
    with tempfile.TemporaryDirectory(prefix="opennoise-representative-replay-") as temporary:
        root = Path(temporary)
        run_fold(seal, root, fold)
        if inventory(root / f"fold-{fold}") != inventory(output / f"fold-{fold}"):
            raise ValueError("Fold numerical replay differs")


def replay_summary(seal: Path, output: Path) -> None:
    """Recompute summary from verified fold bytes without modifying original outputs."""
    import shutil  # noqa: PLC0415 - local immutable copy for replay only.

    output_bytes(output)
    if {path.name for path in output.iterdir()} != {
        "summary",
        *(f"fold-{fold}" for fold in range(5)),
    }:
        raise ValueError("Replay requires exactly five folds and their summary")
    verify_stage(output / "summary", seal, "summary")
    with tempfile.TemporaryDirectory(prefix="opennoise-representative-summary-") as temporary:
        root = Path(temporary)
        for fold in range(5):
            verify_stage(output / f"fold-{fold}", seal, f"fold-{fold}")
            shutil.copytree(output / f"fold-{fold}", root / f"fold-{fold}")
        summarize_run(seal, root)
        if inventory(root / "summary") != inventory(output / "summary"):
            raise ValueError("Summary numerical replay differs")
