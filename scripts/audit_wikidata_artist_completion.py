"""Independently audit frozen artist masks, train counts and source-recovery events."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import resource
import sys
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

import ijson
import zstandard

SEED = "opennoise-artist-completion-v1-frozen"
ARMS = ("popularity", "co_observation", "typed_parent", "combined")
MIN_LABEL_SUPPORT = 5
MIN_PAIR_SUPPORT = 3
CALIBRATION_MINIMUM = 20
PARENT_WEIGHT = 0.25
TRAIN_BOUNDARY = 6
CALIBRATION_BOUNDARY = 8
BIN_EDGES = (0, 0.1, 0.2, 0.4, 0.6, 0.8, 1.000001)


def digest(path: Path) -> str:
    """Hash original byte custody without large allocations."""
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def rows(path: Path) -> Iterator[dict[str, Any]]:
    """Read a saved event ledger without the model implementation."""
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as reader,
        io.TextIOWrapper(reader) as text,
    ):
        for line in text:
            yield json.loads(line)


def source_labels(source: Path) -> dict[str, tuple[str, ...]]:
    """Independently extract literal native P136 IDs from the bound source projection."""
    labels: dict[str, tuple[str, ...]] = {}
    with (source / "projection.json").open("rb") as stream:
        for row in ijson.items(stream, "artists.item"):
            if row["status"] != "exact_identity":
                continue
            native = set()
            for claim in row["claims"]["P136"]:
                value = claim["datavalue"]
                if value.get("type") == "wikibase-entityid" and isinstance(
                    value.get("value"), dict
                ):
                    qid = value["value"].get("id")
                    if isinstance(qid, str) and re.fullmatch(r"Q[1-9][0-9]*", qid):
                        native.add(qid)
            mbid = row["artist_mbid"]
            if not isinstance(mbid, str):
                raise TypeError("native artist identity must be a string")
            if mbid in labels:
                raise ValueError("native projection repeated an exact artist")
            labels[mbid] = tuple(sorted(native))
    return labels


def audit(pack: Path, source: Path, genre_source: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - independent complete frozen census and four arms.
    """Reconstruct every artist fold/mask, training statistic, rank and calibration event."""
    receipt = json.loads((pack / "receipt.json").read_bytes())
    for filename, item in receipt["files"].items():
        path = pack / filename
        if (
            path.is_symlink()
            or path.name != filename
            or digest(path) != item["sha256"]
            or path.stat().st_size != item["bytes"]
        ):
            raise ValueError("artifact byte custody differs")
    policy = json.loads((pack / "frozen-policy.json").read_bytes())
    if policy["seed"] != SEED or tuple(policy["arms"]) != ARMS:
        raise ValueError("frozen artist seed or arms changed")
    params = policy["parameters"]
    if (
        params["minimum_label_support"] != MIN_LABEL_SUPPORT
        or params["minimum_pair_support"] != MIN_PAIR_SUPPORT
        or params["combined_parent_weight"] != PARENT_WEIGHT
        or params["minimum_calibration_events"] != CALIBRATION_MINIMUM
        or tuple(params["score_bins"]) != BIN_EDGES
    ):
        raise ValueError("frozen artist parameters changed")
    report = json.loads((pack / "report.json").read_bytes())
    if report["artist_replay"]["receipt_sha256"] != digest(source / "receipt.json"):
        raise ValueError("native artist source is not bound to this model")
    native = source_labels(source)
    ledger = {}
    support: Counter[str] = Counter()
    pairs: dict[str, Counter[str]] = defaultdict(Counter)
    folds: Counter[str] = Counter()
    for row in rows(pack / "artist-fold-targets.jsonl.zst"):
        mbid = row["artist_mbid"]
        if mbid in ledger or tuple(row["observed_genre_qids"]) != native[mbid]:
            raise ValueError("artist target ledger differs from native exact observations")
        bucket = int.from_bytes(hashlib.sha256(f"{SEED}:{mbid}".encode()).digest(), "big") % 10
        expected_fold = (
            "train"
            if bucket < TRAIN_BOUNDARY
            else "calibration"
            if bucket < CALIBRATION_BOUNDARY
            else "confirmation"
        )
        labels = native[mbid]
        target = (
            min(
                labels,
                key=lambda qid: hashlib.sha256(f"{SEED}:mask:{mbid}:{qid}".encode()).digest(),
            )
            if labels
            else None
        )
        seed = tuple(label for label in labels if label != target)
        if (
            row["split"] != expected_fold
            or row["masked_observed_target"] != target
            or tuple(row["seed_genre_qids"]) != seed
        ):
            raise ValueError("independent hash fold or mask differs")
        ledger[mbid] = row
        folds[expected_fold] += 1
        if expected_fold == "train":
            support.update(labels)
            for label in labels:
                pairs[label].update(other for other in labels if other != label)
    if set(ledger) != set(native):
        raise ValueError("model dropped native exact artist denominator")
    model = json.loads((pack / "fitted-model.json").read_bytes())
    vocabulary = sorted(label for label, count in support.items() if count >= MIN_LABEL_SUPPORT)
    if (
        model["training_artists"] != folds["train"]
        or model["training_support"] != dict(support)
        or model["training_pairs"] != {label: dict(counts) for label, counts in pairs.items()}
        or model["training_vocabulary"] != vocabulary
    ):
        raise ValueError("train-only model counts or vocabulary differ")
    if report["genre_replay"]["receipt_sha256"] != digest(genre_source / "receipt.json"):
        raise ValueError("native genre source is not bound to this model")
    native_parents = {}
    with (genre_source / "projection.json").open("rb") as stream:
        for qid, row in ijson.kvitems(stream, "entities"):
            if row["status"] != "native_entity":
                continue
            identifiers = set()
            for claim in row["claims"].get("P279", []):
                value = claim["datavalue"]
                if value.get("type") == "wikibase-entityid" and isinstance(
                    value.get("value"), dict
                ):
                    parent = value["value"].get("id")
                    if isinstance(parent, str) and re.fullmatch(r"Q[1-9][0-9]*", parent):
                        identifiers.add(parent)
            native_parents[qid] = sorted(identifiers)
    if model["native_typed_parents"] != native_parents:
        raise ValueError("fitted typed parent graph differs from native P279 observations")
    parents = model["native_typed_parents"]

    def ranking(seed: list[str], arm: str) -> list[list[Any]]:
        supported = [label for label in seed if label in vocabulary]
        if not supported:
            return []
        candidates: list[list[Any]] = []
        for label in vocabulary:
            if label in seed:
                continue
            co_values = []
            for observed in supported:
                pair_count = pairs[observed][label]
                co_values.append(
                    (pair_count + 1) / (support[observed] + 2)
                    if pair_count >= MIN_PAIR_SUPPORT
                    else 0
                )
            co = max(co_values)
            parent = float(any(label in parents.get(observed, []) for observed in supported))
            value = (
                support[label] / folds["train"]
                if arm == "popularity"
                else co
                if arm == "co_observation"
                else parent
                if arm == "typed_parent"
                else 0.75 * co + 0.25 * parent
            )
            if value > 0:
                candidates.append([label, value])
        return sorted(candidates, key=lambda candidate: (-candidate[1], candidate[0]))[:10]

    checks = {}
    for arm in ARMS:
        events = {}
        calibration_totals: Counter[int] = Counter()
        calibration_hits: Counter[int] = Counter()
        for mbid, row in ledger.items():
            if row["split"] == "train":
                continue
            ranked = ranking(row["seed_genre_qids"], arm)
            events[mbid] = ranked
            if (
                row["split"] == "calibration"
                and ranked
                and row["masked_observed_target"] is not None
            ):
                score = ranked[0][1]
                bucket = next(
                    index
                    for index, (low, high) in enumerate(pairwise(BIN_EDGES))
                    if low <= score < high
                )
                calibration_totals[bucket] += 1
                calibration_hits[bucket] += ranked[0][0] == row["masked_observed_target"]
        saved_bins = report["arms"][arm]["calibration_bins"]
        for index in range(len(BIN_EDGES) - 1):
            expected_probability = (
                calibration_hits[index] / calibration_totals[index]
                if calibration_totals[index] >= CALIBRATION_MINIMUM
                else None
            )
            if (
                saved_bins[str(index)]["count"] != calibration_totals[index]
                or saved_bins[str(index)]["recoveries"] != calibration_hits[index]
                or saved_bins[str(index)]["probability"] != expected_probability
            ):
                raise ValueError("calibration native event denominator differs")
        confirmation = set()
        hits = dict.fromkeys((1, 5, 10), 0)
        positives = 0
        calibrated_errors = []
        for row in rows(pack / f"{arm}-confirmation.jsonl.zst"):
            mbid = row["artist_mbid"]
            if (
                mbid in confirmation
                or ledger[mbid]["split"] != "confirmation"
                or row["ranked"] != events[mbid]
            ):
                raise ValueError("independent confirmation rank or fold differs")
            confirmation.add(mbid)
            target = ledger[mbid]["masked_observed_target"]
            if row["masked_observed_target"] != target:
                raise ValueError("confirmation target differs")
            if target is not None:
                positives += 1
                for k in hits:
                    hits[k] += target in [label for label, _score in events[mbid][:k]]
            if target is not None and row["ranked"]:
                label, score = row["ranked"][0]
                bucket = next(
                    index
                    for index, (low, high) in enumerate(pairwise(BIN_EDGES))
                    if low <= score < high
                )
                probability = saved_bins[str(bucket)]["probability"]
                if probability is not None:
                    calibrated_errors.append((probability - int(label == target)) ** 2)
        if confirmation != {mbid for mbid, row in ledger.items() if row["split"] == "confirmation"}:
            raise ValueError("confirmation ledger dropped an exact query")
        metrics = report["arms"][arm]["confirmation"]
        expected_brier = (
            sum(calibrated_errors) / len(calibrated_errors) if calibrated_errors else None
        )
        if (
            metrics["all_exact_artist_queries"] != len(confirmation)
            or metrics["masked_observed_positive_queries"] != positives
            or metrics["recall"]
            != {str(k): hits[k] / positives if positives else None for k in hits}
            or metrics["calibrated_confirmation_events"] != len(calibrated_errors)
            or metrics["masked_recovery_brier"] != expected_brier
        ):
            raise ValueError("complete confirmation coverage/recall/Brier differs")
        checks[arm] = {
            "confirmation_queries": len(confirmation),
            "calibration_events": sum(calibration_totals.values()),
            "all_ranks_counts_recall_brier_match": True,
        }
    return {
        "all_native_fold_mask_train_statistics_and_confirmation_events_match": True,
        "pack_receipt_sha256": digest(pack / "receipt.json"),
        "native_artist_receipt_sha256": digest(source / "receipt.json"),
        "native_genre_receipt_sha256": digest(genre_source / "receipt.json"),
        "native_typed_P279_graph_replayed": True,
        "auditor_sha256": digest(Path(__file__)),
        "folds": dict(folds),
        "training_vocabulary": len(vocabulary),
        "arms": checks,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "native_capture_transport_replay": "separately checked by source pack verifier",
        "musical_truth_or_full_seed_probability_claimed": False,
    }


def main() -> None:
    """Keep all inputs unchanged and write new independent evidence only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--genre-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.pack, args.source, args.genre_source)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
