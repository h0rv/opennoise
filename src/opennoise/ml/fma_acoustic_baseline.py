"""Artist/album-isolated source-positive acoustic genre reconstruction on native FMA IDs."""

from __future__ import annotations

import hashlib
import io
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import zstandard
from scipy import sparse

from opennoise.common import sha256_file
from opennoise.ingest import fma_features
from opennoise.ingest.fma_features import CHANNELS, SELECTED_COLUMNS, verify_feature_source
from opennoise.ml import fma_split_audit

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

SPLIT_REVISION = "opennoise-fma-acoustic-native-component-split-v2"
MIN_LABEL_SUPPORT = 5
RARE_TRAINING_SUPPORT = 100
VARIANCE_SHRINKAGE = 0.5
MIN_VARIANCE = 0.1
MAX_STANDARDIZED_OFFSET = 12.0
_TRAIN_BUCKET_END = 800
_VALIDATION_BUCKET_END = 900
_BUCKET_COUNT = 1000
_BATCH_ROWS = 2048
_MATRIX_DIMENSIONS = 2


@dataclass(frozen=True, slots=True)
class NativeTrack:
    """Native source IDs and observed track labels; no factual artist genre assignments."""

    track_id: int
    artist_id: int | None
    artist_known: bool
    album_id: int | None
    genre_ids: tuple[int, ...]
    targets_missing: bool


def artist_group_fold(group_id: int) -> int:
    """Prespecified 80/10/10 hash buckets, never adjusted using labels or realized sizes."""
    if type(group_id) is not int or group_id <= 0:
        raise ValueError("native artist component requires a positive source ID")
    digest = hashlib.sha256(f"{SPLIT_REVISION}\0{group_id}".encode()).digest()
    bucket = int.from_bytes(digest, "big") % _BUCKET_COUNT
    return 0 if bucket < _TRAIN_BUCKET_END else 1 if bucket < _VALIDATION_BUCKET_END else 2


def native_components(
    tracks: Sequence[NativeTrack], duplicate_groups: Sequence[Sequence[int]]
) -> dict[int, int]:
    """Keep native artists, known albums and exact full-feature duplicate groups together."""
    parents = {row.artist_id: row.artist_id for row in tracks if row.artist_id is not None}
    owners: dict[int, int] = {}
    by_track = {row.track_id: row for row in tracks}

    def root(identity: int) -> int:
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    def union(left: int, right: int) -> None:
        a, b = root(left), root(right)
        parents[max(a, b)] = min(a, b)

    for row in tracks:
        if row.artist_id is not None and row.album_id is not None:
            union(row.artist_id, owners.setdefault(row.album_id, row.artist_id))
    for group in duplicate_groups:
        artists = sorted(
            {
                row.artist_id
                for identity in group
                if (row := by_track.get(identity)) is not None and row.artist_id is not None
            }
        )
        for artist in artists[1:]:
            union(artists[0], artist)
    components = {identity: root(identity) for identity in sorted(parents)}
    fma_split_audit.audit_native_components(tracks, duplicate_groups, components)
    return components


def _json_rows(path: Path) -> Iterator[dict[str, Any]]:
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as reader,
        io.TextIOWrapper(reader, encoding="utf-8") as text,
    ):
        for line in text:
            yield json.loads(line)


def load_metadata(
    directory: Path, declaration: dict[str, Any]
) -> tuple[tuple[NativeTrack, ...], tuple[int, ...], dict[str, Any]]:
    """Verify projected native metadata custody and read only IDs and source track labels."""
    receipt = json.loads((directory / "corpus-receipt.json").read_bytes())
    if (
        receipt["metadata_license"] != "CC-BY-4.0"
        or receipt["source_receipt_sha256"]
        != declaration["source"]["metadata_source_receipt_sha256"]
        or receipt["files"]["tracks"]["sha256"] != declaration["source"]["metadata_tracks_sha256"]
    ):
        raise ValueError("FMA native metadata differs from frozen source declaration")
    for binding in receipt["files"].values():
        digest, length = sha256_file(directory / binding["path"])
        if digest != binding["sha256"] or length != binding["bytes"]:
            raise ValueError("FMA native metadata projection bytes differ")
    genres = {
        int(row["genre_id"]) for row in _json_rows(directory / receipt["files"]["genres"]["path"])
    }
    rows = []
    seen = set()
    for row in _json_rows(directory / receipt["files"]["tracks"]["path"]):
        identity = row["track_id"]
        if type(identity) is not int or identity <= 0 or identity in seen:
            raise ValueError("FMA source tracks require distinct positive native IDs")
        seen.add(identity)
        labels = tuple(sorted(set(row["genre_ids"] or [])))
        genres.update(labels)
        rows.append(
            NativeTrack(
                identity,
                row["artist_id"],
                row["artist_id_status"] == "source_known",
                row["album_id"],
                labels,
                row["genre_ids"] is None,
            )
        )
    return tuple(sorted(rows, key=lambda row: row.track_id)), tuple(sorted(genres)), receipt


def load_features(
    directory: Path, declaration_path: Path
) -> tuple[np.ndarray, np.ndarray, list[list[int]], dict[str, Any]]:
    """Load a bounded numeric projection after native range and artifact verification."""
    source = verify_feature_source(directory.parent)
    receipt = json.loads((directory / "projection-receipt.json").read_bytes())
    if (
        receipt["source_receipt_sha256"] != sha256_file(directory.parent / "source-receipt.json")[0]
        or receipt["declaration_sha256"] != sha256_file(declaration_path)[0]
        or source["declaration_sha256"] != receipt["declaration_sha256"]
        or receipt["license"] != "CC-BY-4.0"
        or receipt["conceptual_channels"] != CHANNELS
        or receipt["columns"] != [list(row) for row in SELECTED_COLUMNS]
        or receipt["audio_downloaded"] is not False
        or receipt["echo_nest_consumed"] is not False
    ):
        raise ValueError("FMA acoustic projection boundary differs")
    for filename, binding in receipt["files"].items():
        path = directory / filename
        if (
            filename
            not in {"features.float32", "track_ids.uint32", "duplicate-native-feature-cells.json"}
            or path.is_symlink()
        ):
            raise ValueError("unexpected acoustic projection artifact")
        if sha256_file(path) != (binding["sha256"], binding["bytes"]):
            raise ValueError("acoustic projection byte binding differs")
    n = receipt["rows"]
    if (
        receipt["files"]["features.float32"]["bytes"] != n * len(SELECTED_COLUMNS) * 4
        or receipt["files"]["track_ids.uint32"]["bytes"] != n * 4
    ):
        raise ValueError("acoustic native array shape differs")
    identities = np.memmap(directory / "track_ids.uint32", mode="r", dtype="<u4", shape=(n,))
    features = np.memmap(
        directory / "features.float32", mode="r", dtype="<f4", shape=(n, len(SELECTED_COLUMNS))
    )
    duplicates = json.loads((directory / "duplicate-native-feature-cells.json").read_bytes())
    return identities, features, duplicates, receipt


@dataclass(frozen=True)
class PositiveGaussian:
    """Source-positive label density, not calibrated genre probabilities or verified negatives."""

    center: np.ndarray
    scale: np.ndarray
    active_columns: np.ndarray
    quadratic: np.ndarray
    linear: np.ndarray
    intercept: np.ndarray
    active_labels: np.ndarray
    label_feature_support: np.ndarray
    training_rows: int


def fit_positive_gaussian(
    features: np.ndarray, targets: sparse.csr_matrix, training: np.ndarray
) -> PositiveGaussian:
    """Fit normalization and label-conditioned densities entirely inside declared training rows."""
    if (
        training.dtype != np.bool_
        or training.ndim != 1
        or features.ndim != _MATRIX_DIMENSIONS
        or targets.ndim != _MATRIX_DIMENSIONS
        or training.shape != (features.shape[0],)
        or targets.shape[0] != features.shape[0]
    ):
        raise ValueError("training requires a boolean row mask and aligned feature/target matrices")
    eligible = training & np.isfinite(features).all(axis=1)
    x = np.asarray(features[eligible], dtype=np.float64)
    if len(x) < MIN_LABEL_SUPPORT:
        raise ValueError("insufficient finite training feature rows")
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    active = np.isfinite(scale) & (scale > 0)
    if not active.any():
        raise ValueError("training has no varying acoustic features")
    normalized = (x[:, active] - center[active]) / scale[active]
    y = targets[eligible]
    support = np.asarray(y.sum(axis=0)).ravel()
    totals = np.asarray(y.T @ normalized)
    squares = np.asarray(y.T @ (normalized * normalized))
    safe_support = np.maximum(support, 1.0)
    means = totals / safe_support[:, None]
    variances = np.maximum(squares / safe_support[:, None] - means * means, 0.0)
    variances = np.maximum(
        (1.0 - VARIANCE_SHRINKAGE) * variances + VARIANCE_SHRINKAGE, MIN_VARIANCE
    )
    source_support = np.asarray(targets[training].sum(axis=0)).ravel()
    prevalence = (source_support + 0.5) / (int(training.sum()) + 1)
    active_labels = support >= MIN_LABEL_SUPPORT
    intercept = -0.5 * np.sum(means * means / variances + np.log(variances), axis=1) + np.log(
        prevalence
    )
    intercept[~active_labels] = -np.inf
    return PositiveGaussian(
        center,
        scale,
        active,
        -0.5 / variances,
        means / variances,
        intercept,
        active_labels,
        support,
        int(eligible.sum()),
    )


def score_positive_gaussian(
    model: PositiveGaussian, features: np.ndarray
) -> tuple[np.ndarray, list[str | None]]:
    """Abstain on missing or numerically unsupported descriptors; never impute source evidence."""
    selected = features[:, model.active_columns]
    complete = np.asarray(np.isfinite(selected).all(axis=1), dtype=bool)
    normalized = (
        np.asarray(selected, dtype=np.float64) - model.center[model.active_columns]
    ) / model.scale[model.active_columns]
    supported = complete & (np.abs(normalized) <= MAX_STANDARDIZED_OFFSET).all(axis=1)
    scores = np.full((len(features), len(model.active_labels)), -np.inf, dtype=np.float64)
    valid = normalized[supported]
    scores[supported] = (
        (valid * valid) @ model.quadratic.T + valid @ model.linear.T + model.intercept
    )
    reasons = [
        None
        if supported[i]
        else "missing_descriptors"
        if not complete[i]
        else "outside_training_support"
        for i in range(len(features))
    ]
    return scores, reasons


class PositiveMetrics:
    """Positive-only recall with cold/rare labels and abstentions retained in denominators."""

    def __init__(self, labels: Sequence[int], training_support: np.ndarray) -> None:
        """Initialize source-positive counters for the entire declared native label vocabulary."""
        self.labels = tuple(labels)
        self.training_support = training_support
        self.positives = np.zeros(len(labels), dtype=np.int64)
        self.hits = {k: np.zeros(len(labels), dtype=np.int64) for k in (5, 10)}
        self.queries = 0
        self.unlabeled_queries = 0
        self.reciprocal_rank = 0.0
        self.abstentions: Counter[str] = Counter()

    def add(
        self, positive_columns: Sequence[int], ranking: Sequence[int], reason: str | None = None
    ) -> None:
        """Count all declared targets, including zero-hit queries without feature support."""
        self.queries += 1
        if reason is not None:
            self.abstentions[reason] += 1
        if not positive_columns:
            self.unlabeled_queries += 1
            return
        self.positives[list(positive_columns)] += 1
        positives = set(positive_columns)
        self.reciprocal_rank += next(
            (1.0 / rank for rank, label in enumerate(ranking, 1) if label in positives), 0.0
        )
        for k, hits in self.hits.items():
            matched = positives & set(ranking[:k])
            if matched:
                hits[list(matched)] += 1

    def report(self) -> dict[str, Any]:
        """Separate observed recovery, musical relevance unknowns and source label support."""
        present = self.positives > 0
        rare = self.training_support <= RARE_TRAINING_SUPPORT
        cold = self.training_support < MIN_LABEL_SUPPORT
        unseen = self.training_support == 0
        result: dict[str, Any] = {
            "queries": self.queries,
            "labeled_queries": self.queries - self.unlabeled_queries,
            "unlabeled_queries": self.unlabeled_queries,
            "source_positive_count": int(self.positives.sum()),
            "abstentions": dict(sorted(self.abstentions.items())),
            "mean_reciprocal_rank": self.reciprocal_rank
            / max(1, self.queries - self.unlabeled_queries),
            "rare_positive_count": int(self.positives[rare].sum()),
            "cold_positive_count": int(self.positives[cold].sum()),
            "training_unseen_positive_count": int(self.positives[unseen].sum()),
            "below_five_seen_positive_count": int(self.positives[cold & ~unseen].sum()),
            "precision_available": False,
        }
        for k, hits in self.hits.items():
            result[f"recall_at_{k}"] = int(hits.sum()) / max(1, int(self.positives.sum()))
            result[f"macro_recall_at_{k}"] = (
                float(np.mean(hits[present] / self.positives[present])) if present.any() else 0.0
            )
            result[f"rare_recall_at_{k}"] = int(hits[rare].sum()) / max(
                1, int(self.positives[rare].sum())
            )
            result[f"cold_recall_at_{k}"] = int(hits[cold].sum()) / max(
                1, int(self.positives[cold].sum())
            )
            result[f"training_unseen_recall_at_{k}"] = int(hits[unseen].sum()) / max(
                1, int(self.positives[unseen].sum())
            )
        result["per_label"] = [
            {
                "genre_id": label,
                "training_positive_count": int(self.training_support[i]),
                "held_out_positive_count": int(self.positives[i]),
                "hits_at_5": int(self.hits[5][i]),
                "hits_at_10": int(self.hits[10][i]),
            }
            for i, label in enumerate(self.labels)
        ]
        return result


def training_baseline_rankings(support: np.ndarray) -> tuple[list[int], list[int]]:
    """Rank source-training-observed labels only; unseen taxonomy IDs receive no credit."""
    return (
        [int(i) for i in np.argsort(-support, kind="stable") if support[i] > 0],
        [i for i in range(len(support)) if support[i] > 0],
    )


def _freeze_implementation(output: Path, declaration_path: Path) -> None:
    for module in (__file__, fma_features.__file__, fma_split_audit.__file__):
        if module is None:
            raise ValueError("model implementation source is unavailable")
        path = Path(module)
        (output / path.name).write_bytes(path.read_bytes())
    (output / "declaration.json").write_bytes(declaration_path.read_bytes())


def _evaluate_folds(  # noqa: PLR0913 - explicit independent evidence dimensions.
    features: np.ndarray,
    *,
    targets: sparse.csr_matrix,
    folds: np.ndarray,
    present: np.ndarray,
    labels: Sequence[int],
    support: np.ndarray,
    model: PositiveGaussian,
    output: Path,
    tracks: Sequence[NativeTrack],
) -> dict[str, Any]:
    """Preserve every eligible native query and rank only supported model labels."""
    popularity, constant = training_baseline_rankings(support)
    results = {}
    for fold, name in ((1, "validation"), (2, "test")):
        indices = np.flatnonzero(folds == fold)
        metrics = {
            arm: PositiveMetrics(labels, support) for arm in ("acoustic", "popularity", "constant")
        }
        with (
            (output / f"{name}-acoustic-ranks.jsonl.zst").open("xb") as raw,
            zstandard.ZstdCompressor(level=6).stream_writer(raw) as writer,
        ):
            for start in range(0, len(indices), _BATCH_ROWS):
                batch = indices[start : start + _BATCH_ROWS]
                scores, reasons = score_positive_gaussian(model, features[batch])
                rankings = np.argsort(-scores, axis=1, kind="stable")
                for offset, index in enumerate(batch):
                    positive = targets.indices[
                        targets.indptr[index] : targets.indptr[index + 1]
                    ].tolist()
                    reason = "missing_feature_row" if not present[index] else reasons[offset]
                    ranking = (
                        [int(label) for label in rankings[offset] if model.active_labels[label]]
                        if reason is None
                        else []
                    )
                    metrics["acoustic"].add(positive, ranking, reason)
                    metrics["popularity"].add(positive, popularity)
                    metrics["constant"].add(positive, constant)
                    record = {
                        "track_id": tracks[index].track_id,
                        "reason": reason,
                        "ranked_genre_ids": [labels[label] for label in ranking],
                    }
                    writer.write((json.dumps(record, sort_keys=True) + "\n").encode())
        results[name] = {arm: metric.report() for arm, metric in metrics.items()}
    return results


def evaluate_native_corpus(
    metadata: Path, features_directory: Path, declaration_path: Path, output: Path
) -> dict[str, Any]:
    """Replay a sealed single model arm and positive-only baselines on all native queries."""
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    declaration = json.loads(declaration_path.read_bytes())
    tracks, labels, metadata_receipt = load_metadata(metadata, declaration)
    identities, values, duplicates, feature_receipt = load_features(
        features_directory, declaration_path
    )
    components = native_components(tracks, duplicates)
    positions = {row.track_id: i for i, row in enumerate(tracks)}
    label_positions = {identity: i for i, identity in enumerate(labels)}
    features = np.full((len(tracks), values.shape[1]), np.nan, dtype=np.float32)
    present = np.zeros(len(tracks), dtype=bool)
    for source_index, identity in enumerate(identities):
        target_index = positions.get(int(identity))
        if target_index is None or present[target_index]:
            raise ValueError("feature IDs must match distinct native metadata tracks")
        features[target_index] = values[source_index]
        present[target_index] = True
    known = np.array([row.artist_known for row in tracks], dtype=bool)
    folds = np.array(
        [artist_group_fold(components[row.artist_id]) if row.artist_id else -1 for row in tracks],
        dtype=np.int8,
    )
    target_rows, target_columns = [], []
    for i, row in enumerate(tracks):
        for label in row.genre_ids:
            target_rows.append(i)
            target_columns.append(label_positions[label])
    targets = sparse.csr_matrix(
        (np.ones(len(target_rows), dtype=np.float64), (target_rows, target_columns)),
        shape=(len(tracks), len(labels)),
    )
    training = known & (folds == 0)
    support = np.asarray(targets[training].sum(axis=0)).ravel()
    model = fit_positive_gaussian(features, targets, training)
    results = _evaluate_folds(
        features,
        targets=targets,
        folds=np.where(known, folds, -1),
        present=present,
        labels=labels,
        support=support,
        model=model,
        output=output,
        tracks=tracks,
    )
    component_sizes = Counter(components[row.artist_id] for row in tracks if row.artist_id)

    def coverage(mask: np.ndarray) -> dict[str, int]:
        return {"tracks": int(mask.sum()), "source_positives": int(targets[mask].sum())}

    report: dict[str, Any] = {
        "revision": declaration["revision"],
        "declaration_sha256": sha256_file(declaration_path)[0],
        "metadata_receipt_sha256": sha256_file(metadata / "corpus-receipt.json")[0],
        "feature_receipt_sha256": sha256_file(features_directory / "projection-receipt.json")[0],
        "source": {
            "license": "CC-BY-4.0",
            "metadata": metadata_receipt["source_receipt_sha256"],
            "features": feature_receipt["source_receipt_sha256"],
            "whole_archive_hash_verified": False,
            "native_feature_sha256": feature_receipt["native_observed_sha256"],
        },
        "coverage": {
            "raw": coverage(np.ones(len(tracks), dtype=bool)),
            "features": coverage(present),
            "missing_features": coverage(~present),
            "unresolved_artist": coverage(~known),
            "known_missing_features": coverage(known & ~present),
            "unresolved_missing_features": coverage(~known & ~present),
            "raw_genre_vocabulary": len(labels),
            "observed_genre_ids": int((np.asarray(targets.sum(axis=0)).ravel() > 0).sum()),
            "missing_target_rows": sum(row.targets_missing for row in tracks),
            "empty_observed_label_rows": sum(
                not row.targets_missing and not row.genre_ids for row in tracks
            ),
        },
        "partition": {
            "revision": SPLIT_REVISION,
            "components": len(component_sizes),
            "largest_components_tracks": sorted(component_sizes.values(), reverse=True)[:20],
            "folds": {
                name: coverage(known & (folds == fold))
                for fold, name in enumerate(("train", "validation", "test"))
            },
            "duplicate_groups": len(duplicates),
            "unresolved_positive_artist_ids_retained_as_graph_nodes": True,
        },
        "model": {
            "finite_training_rows": model.training_rows,
            "active_features": int(model.active_columns.sum()),
            "active_labels": int(model.active_labels.sum()),
            "feature_positive_support": {
                str(label): int(model.label_feature_support[i]) for i, label in enumerate(labels)
            },
            "scores_calibrated": False,
            "target_role": "native_track_source_recovery",
            "artist_facts": False,
            "public_product_promotion_authorized": False,
            "comparators_restricted_to_training_observed_labels": True,
        },
        "evaluation": results,
        "limitations": [
            "Native-ID isolation does not resolve nonexact recording or performer aliases.",
            "Observed track labels are incomplete; source absences are unknown.",
            (
                "No artist genre assignments, MBID bridge, audio, independent musical relevance, "
                "or EveryNoise parity."
            ),
            "No validation tuning; train-only normalization and support gates are prespecified.",
        ],
    }
    _freeze_implementation(output, declaration_path)
    np.savez_compressed(
        output / "model.npz",
        center=model.center,
        scale=model.scale,
        active_columns=model.active_columns,
        quadratic=model.quadratic,
        linear=model.linear,
        intercept=model.intercept,
        active_labels=model.active_labels,
        label_feature_support=model.label_feature_support,
        labels=np.array(labels, dtype=np.int64),
    )
    with (
        (output / "native-folds.jsonl.zst").open("wb") as raw,
        zstandard.ZstdCompressor(level=6).stream_writer(raw) as writer,
    ):
        for row, fold in zip(tracks, folds, strict=True):
            record = {
                "track_id": row.track_id,
                "artist_id": row.artist_id,
                "artist_known": row.artist_known,
                "album_id": row.album_id,
                "component_id": components.get(row.artist_id),
                "fold": int(fold),
            }
            writer.write((json.dumps(record, sort_keys=True) + "\n").encode())
    report["artifacts"] = {
        path.name: {"sha256": sha256_file(path)[0], "bytes": path.stat().st_size}
        for path in sorted(output.iterdir())
    }
    if (
        sum(int(binding["bytes"]) for binding in report["artifacts"].values())
        > declaration["limits"]["new_outputs_bytes"]
    ):
        raise ValueError("sealed model output byte budget exceeded")
    report["elapsed_seconds"] = time.monotonic() - started
    if report["elapsed_seconds"] > declaration["limits"]["model_run_seconds"]:
        raise ValueError("sealed model time budget exceeded")
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
