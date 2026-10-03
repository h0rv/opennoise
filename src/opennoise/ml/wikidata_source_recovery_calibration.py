"""Training-only calibration of a source recovery event, with explicit abstention.

The event is top10_recovery_of_masked_observed_source_positive. Its estimated
rate is never a probability of individual membership or musical relevance.
Absent source labels are unknown. This is a post-selection development study,
not fresh confirmation of the historically selected score rule.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import zstandard

from opennoise.ml import wikidata_selected_rule_diagnostic as diagnostic
from opennoise.ml import wikidata_training_experiment as training

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO

REVISION = "wikidata-training-source-recovery-event-calibration-v1"
ROLE_SEED = "opennoise-source-recovery-disjoint-roles-20261003-v1"
MULTILABEL_MASK_SEED = "opennoise-source-recovery-multilabel-mask-20261003-v1"
EVENT = "top10_recovery_of_masked_observed_source_positive"
BIN_EDGES = (0.0, 0.02, 0.05, 0.1, 0.2, 0.4, 1.0000000001)
MIN_CALIBRATION_ARTISTS = 50
MIN_LOWER_EVENT_RATE = 0.8
# One-sided normal critical value for 0.05 / (six bins * two fixed arms).
# Wilson is an approximate descriptive interval, not a distribution-free guarantee.
BONFERRONI_NORMAL = 2.638257273476751
MAX_OUTPUT_BYTES = 5_000_000
FIT_ROLE_BUCKETS = 3
RESOURCE_CHECK_INTERVAL = 25


def role(mbid: str) -> str:
    """Split original-training UUIDs independently of every source label."""
    training.original_split(mbid)  # Validate canonical identity independently.
    bucket = int.from_bytes(hashlib.sha256(f"{ROLE_SEED}:{mbid}".encode()).digest()) % 5
    return (
        "fit"
        if bucket < FIT_ROLE_BUCKETS
        else "calibrate"
        if bucket == FIT_ROLE_BUCKETS
        else "development_assess"
    )


@dataclass(frozen=True, slots=True)
class Query:
    """A separately frozen multilabel mask over observed source positives."""

    mbid: str
    seeds: tuple[str, ...]
    targets: tuple[str, ...]


def multilabel_query(row: training.Row) -> Query:
    """Alternate a deterministic hash order; singleton queries retain no seeds."""
    ordered = sorted(
        row.labels,
        key=lambda qid: hashlib.sha256(
            f"{MULTILABEL_MASK_SEED}:{row.mbid}:{qid}".encode()
        ).digest(),
    )
    return Query(row.mbid, tuple(sorted(ordered[1::2])), tuple(sorted(ordered[::2])))


def rows_for_role(  # noqa: PLR0913 - Both explicit fit and calibrator seals guard label decoding.
    path: Path,
    wanted: str,
    fitted_path: Path | None = None,
    fitted_sha: str | None = None,
    *,
    calibrator_path: Path | None = None,
    calibrator_sha: str | None = None,
) -> Iterator[training.Row]:
    """Decode only admitted role labels, after fit sealing for both later roles.

    Top-level original split/identity routing uses bytes. Outer labels are never
    decoded. Saved splits and original masks must independently authenticate.
    """
    if wanted not in {"fit", "calibrate", "development_assess"}:
        raise ValueError("unknown experiment role")
    if wanted != "fit" and (
        fitted_path is None or fitted_sha is None or training.sha(fitted_path) != fitted_sha
    ):
        raise ValueError("fixed fit must be sealed before later-role labels are decoded")
    if wanted == "development_assess" and (
        calibrator_path is None
        or calibrator_sha is None
        or training.sha(calibrator_path) != calibrator_sha
    ):
        raise ValueError("calibrator must be sealed before assessment labels are decoded")
    seen: set[str] = set()
    size = 0
    count = 0
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor(max_window_size=training.MAX_ZSTD_WINDOW_BYTES).stream_reader(
            raw
        ) as stream,
        io.BufferedReader(stream) as buffered,
    ):
        while line := buffered.readline(training.MAX_LINE_BYTES + 1):
            size += len(line)
            count += 1
            if (
                len(line) > training.MAX_LINE_BYTES
                or size > training.MAX_DECODED_BYTES
                or count > training.MAX_ROWS
            ):
                raise ValueError("bounded source-role routing exceeded")
            if training.route(line) != "train":
                continue
            # Extract only exact identity before deciding whether labels may decode.
            mbid = _identity(line)
            if mbid in seen:
                raise ValueError("duplicate original-training identity")
            seen.add(mbid)
            if role(mbid) != wanted:
                continue
            yield training._train_row(json.loads(line))  # noqa: SLF001 - Pinned mask authentication.


def _identity(line: bytes) -> str:  # noqa: C901 - Explicit top-level byte tokenizer state machine.
    """Read a top-level identity only, reusing the pinned bounded byte tokenizer."""
    depth = 0
    key = False
    wanted = False
    for match in training.TOKEN.finditer(line):
        token = match.group()
        if token in {b"{", b"["}:
            depth += 1
            if depth == 1:
                key = True
        elif token in {b"}", b"]"}:
            depth -= 1
        elif depth == 1:
            if token == b",":
                key = True
            elif token == b":":
                continue
            elif key:
                wanted = token == b'"artist_mbid"'
                key = False
            elif wanted:
                value = json.loads(token)
                if not isinstance(value, str):
                    raise ValueError("source identity must be an exact string")
                return value
    raise ValueError("missing exact identity")


def bin_number(score: float) -> int:
    """Assign fixed prespecified score bins, without learned boundaries."""
    if not math.isfinite(score) or score < 0 or score > 1:
        raise ValueError("source score must be finite within zero and one")
    return next(i for i in range(len(BIN_EDGES) - 1) if score < BIN_EDGES[i + 1])


def lower_event_rate(hits: int, count: int) -> float | None:
    """Approximate multiplicity-adjusted Wilson lower bound for the fixed event."""
    if hits < 0 or count < hits:
        raise ValueError("invalid event counts")
    if not count:
        return None
    z = BONFERRONI_NORMAL
    proportion = hits / count
    return max(
        0.0,
        (
            proportion
            + z * z / (2 * count)
            - z * math.sqrt(proportion * (1 - proportion) / count + z * z / (4 * count**2))
        )
        / (1 + z * z / count),
    )


def query_scores(
    model: training.Counts, seeds: tuple[str, ...], arm: str, *, source_observed: bool
) -> dict[str, Any]:
    """Inference depends on observed seeds and the fixed fit, never target labels."""
    if seeds != tuple(sorted(set(seeds))) or any(
        not re.fullmatch(r"Q[1-9][0-9]*", seed) for seed in seeds
    ):
        raise ValueError("observed source seeds must be unique sorted canonical QIDs")
    ranking = diagnostic.scored(model, seeds, arm)
    reason = (
        "missing_source_observation_unknown"
        if not source_observed
        else "no_observed_seed"
        if not seeds
        else "unsupported_observed_seed"
        if any(seed not in model.vocabulary for seed in seeds)
        else "empty_candidate_vocabulary"
        if not ranking
        else None
    )
    return {
        "arm": arm,
        "raw_overlapping_candidate_ranking": ranking,
        "raw_candidate_training_support": {
            candidate: model.support[candidate] for candidate, _ in ranking
        },
        "score_bin": bin_number(ranking[0][1]) if reason is None else None,
        "abstention_reason": reason,
        "individual_membership_probability": None,
        "musical_probability": None,
    }


def label_coverage(model: training.Counts, qid: str) -> str:
    """Declare requested source identities that a closed fitted vocabulary cannot score."""
    if not re.fullmatch(r"Q[1-9][0-9]*", qid):
        raise ValueError("requested source identity must be a canonical QID")
    return (
        "unseen_source_identity_unknown"
        if not model.support[qid]
        else "outside_fitted_vocabulary_unknown"
        if qid not in model.vocabulary
        else "supported_source_identity"
    )


def load_reusable(
    root: Path,
    receipt_pin: str,
) -> tuple[training.Counts, dict[str, list[dict[str, Any]]]]:
    """Authenticate the coupled frozen fit/calibrator; changing the fit invalidates it."""
    receipt = diagnostic.verify_pack(root, receipt_pin)
    policy = json.loads((root / "frozen-policy.json").read_bytes())
    model = json.loads((root / "fixed-fit-model.json").read_bytes())
    artifact = json.loads((root / "fixed-fit-calibrator.json").read_bytes())
    for key, value in frozen_policy().items():
        if json.dumps(policy.get(key), sort_keys=True) != json.dumps(value, sort_keys=True):
            raise ValueError("frozen inference policy differs from the current exact contract")
    for name, current in _producing_sources().items():
        expected = policy["code_sha256"][name]
        if training.sha(current) != expected or receipt["files"][name]["sha256"] != expected:
            raise ValueError("exact inference implementation/dependency pin differs")
    if (
        policy["revision"] != REVISION
        or artifact["event"] != EVENT
        or artifact["refit_allowed"] is not False
        or artifact["fitted_model_sha256"] != receipt["files"]["fixed-fit-model.json"]["sha256"]
        or artifact["policy_sha256"] != receipt["files"]["frozen-policy.json"]["sha256"]
    ):
        raise ValueError("source event calibrator must bind the exact fixed fit and frozen policy")
    counts = training.Counts(
        model["fit_artists"],
        Counter(model["support"]),
        {seed: Counter(pairs) for seed, pairs in model["pairs"].items()},
        tuple(model["vocabulary"]),
    )
    return counts, artifact["arms"]


def calibrate(model: training.Counts, queries: Iterator[Query]) -> dict[str, list[dict[str, Any]]]:
    """Select bin abstention from the calibration role only; missing targets stay unknown."""
    bins = {arm: [Counter[str]() for _ in range(len(BIN_EDGES) - 1)] for arm in diagnostic.ARMS}
    seen: set[str] = set()
    for query in queries:
        if query.mbid in seen:
            raise ValueError("calibration support counts require unique exact artists")
        seen.add(query.mbid)
        for arm in diagnostic.ARMS:
            prediction = query_scores(model, query.seeds, arm, source_observed=bool(query.targets))
            number = prediction["score_bin"]
            if number is None or not query.targets:
                continue
            top = {
                candidate for candidate, _ in prediction["raw_overlapping_candidate_ranking"][:10]
            }
            bins[arm][number]["artists"] += 1
            bins[arm][number]["event_hits"] += bool(top.intersection(query.targets))
    result: dict[str, list[dict[str, Any]]] = {}
    for arm, counts in bins.items():
        result[arm] = []
        for number, counter in enumerate(counts):
            count, hits = counter["artists"], counter["event_hits"]
            lower = lower_event_rate(hits, count)
            result[arm].append(
                {
                    "bin": number,
                    "score_interval": list(BIN_EDGES[number : number + 2]),
                    "calibration_artists": count,
                    "event_hits": hits,
                    "empirical_event_rate": hits / count if count else None,
                    "smoothed_event_rate": (hits + 1) / (count + 2) if count else None,
                    "approximate_adjusted_wilson_lower": lower,
                    "accepted": count >= MIN_CALIBRATION_ARTISTS
                    and lower is not None
                    and lower >= MIN_LOWER_EVENT_RATE,
                }
            )
    return result


def predict(
    model: training.Counts,
    calibrator: dict[str, list[dict[str, Any]]],
    seeds: tuple[str, ...],
    arm: str,
    *,
    source_observed: bool,
) -> dict[str, Any]:
    """Emit optional source suggestions with an explicitly named recovery-event rate."""
    result = query_scores(model, seeds, arm, source_observed=source_observed)
    number = result["score_bin"]
    result["calibrated_event"] = EVENT
    result["estimated_source_recovery_event_rate"] = None
    if number is not None:
        evidence = calibrator[arm][number]
        if evidence["calibration_artists"] >= MIN_CALIBRATION_ARTISTS:
            result["estimated_source_recovery_event_rate"] = evidence["smoothed_event_rate"]
        result["abstention_reason"] = (
            None
            if evidence["accepted"]
            else "insufficient_calibration_artists"
            if evidence["calibration_artists"] < MIN_CALIBRATION_ARTISTS
            else "source_recovery_lower_bound_below_frozen_threshold"
        )
    result["emitted_source_suggestions"] = (
        [qid for qid, _ in result["raw_overlapping_candidate_ranking"][:10]]
        if result["abstention_reason"] is None
        else []
    )
    return result


def retrieval_metrics(ranking: list[tuple[str, float]], targets: tuple[str, ...]) -> dict[str, Any]:
    """Multilabel observed-positive retrieval; every absent membership remains unknown."""
    if not targets:
        return {"target_count": 0, "recall": None, "ndcg10": None, "recovery_yield10": None}
    positions = {qid: i + 1 for i, (qid, _) in enumerate(ranking[:10])}
    hits = {k: sum(positions.get(qid, 11) <= k for qid in targets) for k in (1, 5, 10)}
    dcg = sum(1 / math.log2(positions[qid] + 1) for qid in targets if qid in positions)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(targets))))
    return {
        "target_count": len(targets),
        "hits": hits,
        "recall": {k: hit / len(targets) for k, hit in hits.items()},
        "ndcg10": dcg / ideal,
        "recovery_yield10": hits[10] / min(10, len(ranking)) if ranking else 0.0,
        "unmatched_candidates_are_unknown_membership": True,
    }


def frozen_policy() -> dict[str, Any]:
    """Prespecified decisions; source/calibration results cannot modify this policy."""
    return {
        "revision": REVISION,
        "event": EVENT,
        "role_seed": ROLE_SEED,
        "roles": {
            "fit": "hash modulo5 <3",
            "calibrate": "hash modulo5 ==3",
            "development_assess": "hash modulo5 ==4",
        },
        "population": "original training UUIDs only, source-positive-selected cohort",
        "outer_label_decoding": False,
        "fresh_confirmation": False,
        "score_arms": diagnostic.ARMS,
        "multilabel_mask_seed": MULTILABEL_MASK_SEED,
        "mask": "hash-sort all observed positives; even positions targets, odd positions seeds",
        "score_bins": BIN_EDGES,
        "minimum_calibration_artists_per_bin": MIN_CALIBRATION_ARTISTS,
        "minimum_lower_event_rate": MIN_LOWER_EVENT_RATE,
        "lower_bound": (
            "approximate one-sided Wilson with normal critical value adjusted for12 fixed arm/bins"
        ),
        "normal_critical_value": BONFERRONI_NORMAL,
        "risk_guarantee": False,
        "refit_after_calibration": False,
        "individual_membership_calibration": (
            "not established; needs independent source coverage and blinded musical labels"
        ),
        "missing_memberships": "unknown, never fabricated negative labels",
        "maximum_output_bytes": MAX_OUTPUT_BYTES,
        "maximum_actual_rss_bytes": training.MAX_RSS_BYTES,
    }


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _check_output_growth(directory: Path, new_bytes: int) -> None:
    total = sum(path.stat().st_size for path in directory.iterdir() if path.is_file())
    if total + new_bytes > MAX_OUTPUT_BYTES:
        raise ValueError("hard output cap would be exceeded; preserve failed attempt")


def _write(path: Path, value: object) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _check_output_growth(path.parent, len(data))
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _producing_sources() -> dict[str, Path]:
    return {
        "implementation.py": Path(__file__),
        "training-dependency.py": Path(training.__file__),
        "selected-rule-dependency.py": Path(diagnostic.__file__),
        "cli.py": Path(__file__).parents[3] / "scripts" / "calibrate_wikidata_source_recovery.py",
    }


class _BoundedWriter:
    """Reject each compressed block before it can exceed the artifact byte cap."""

    def __init__(self, stream: BinaryIO, output: Path) -> None:
        self.stream = stream
        self.output = output

    def write(self, data: bytes) -> int:
        _check_output_growth(self.output, len(data))
        written = self.stream.write(data)
        if written != len(data):
            raise OSError("compressed rank write was short; preserve failed attempt")
        return written

    def flush(self) -> None:
        self.stream.flush()


@contextmanager
def _query_writer(output: Path) -> Iterator[Any]:
    with (output / "all-query-ranks.jsonl.zst").open("xb", buffering=0) as raw:
        with zstandard.ZstdCompressor(level=3).stream_writer(
            # zstandard uses write/flush; its stub demands the broader BinaryIO interface.
            cast("BinaryIO", _BoundedWriter(raw, output)),
            closefd=False,
        ) as stream:
            yield stream
        raw.flush()
        os.fsync(raw.fileno())
    _sync_directory(output)


def _check_destination(output: Path, *protected: Path) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("output must be a new exclusive path")
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("output cannot have symlink ancestors")
    resolved = output.resolve()
    if any(resolved.is_relative_to(root.resolve()) for root in protected):
        raise ValueError("output cannot modify source or selection inventory subtrees")


def _tally(
    counts: Counter[str],
    sums: dict[str, float],
    model: training.Counts,
    query: Query,
    prediction: dict[str, Any],
) -> None:
    counts["all_queries"] += 1
    reason = prediction["abstention_reason"]
    counts[f"abstention:{reason}"] += 1
    counts["emitted_queries"] += reason is None
    counts["missing_source_queries_unknown"] += not query.targets
    if not query.targets:
        return
    counts["positive_queries"] += 1
    counts["observed_positive_targets"] += len(query.targets)
    for qid in query.targets:
        counts[f"target_coverage:{label_coverage(model, qid)}"] += 1
    ranking = prediction["raw_overlapping_candidate_ranking"]
    raw = retrieval_metrics(ranking, query.targets)
    emitted = retrieval_metrics(ranking if reason is None else [], query.targets)
    for name, result in (("raw", raw), ("emitted", emitted)):
        for cutoff in (1, 5, 10):
            counts[f"{name}:hits{cutoff}"] += result["hits"][cutoff]
            key = f"{name}:macro_recall{cutoff}"
            sums[key] = sums.get(key, 0.0) + result["recall"][cutoff]
        for metric in ("ndcg10", "recovery_yield10"):
            key = f"{name}:{metric}"
            sums[key] = sums.get(key, 0.0) + result[metric]
    event_rate = prediction.get("estimated_source_recovery_event_rate")
    if event_rate is not None:
        counts["event_rate_queries"] += 1
        observed = raw["hits"][10] > 0
        sums["event_brier_sum"] = sums.get("event_brier_sum", 0.0) + (event_rate - observed) ** 2
        number = prediction["score_bin"]
        counts[f"reliability_bin{number}:queries"] += 1
        counts[f"reliability_bin{number}:event_hits"] += observed
        key = f"reliability_bin{number}:event_rate_sum"
        sums[key] = sums.get(key, 0.0) + event_rate


def _summary(counts: Counter[str], sums: dict[str, float]) -> dict[str, Any]:
    positives = counts["positive_queries"]
    targets = counts["observed_positive_targets"]
    result: dict[str, Any] = {"counts": dict(sorted(counts.items())), "ranking": {}}
    for name in ("raw", "emitted"):
        result["ranking"][name] = {
            "micro_recall": {
                str(k): counts[f"{name}:hits{k}"] / targets if targets else None for k in (1, 5, 10)
            },
            "macro_recall": {
                str(k): sums.get(f"{name}:macro_recall{k}", 0.0) / positives if positives else None
                for k in (1, 5, 10)
            },
            "mean_ndcg10": sums.get(f"{name}:ndcg10", 0.0) / positives if positives else None,
            "mean_observed_positive_recovery_yield10": (
                sums.get(f"{name}:recovery_yield10", 0.0) / positives if positives else None
            ),
        }
    result["query_emission_coverage"] = (
        counts["emitted_queries"] / counts["all_queries"] if counts["all_queries"] else None
    )
    result["source_recovery_event_brier"] = (
        sums.get("event_brier_sum", 0.0) / counts["event_rate_queries"]
        if counts["event_rate_queries"]
        else None
    )
    result["event_reliability"] = {
        str(number): {
            "queries": counts[f"reliability_bin{number}:queries"],
            "observed_event_rate": counts[f"reliability_bin{number}:event_hits"]
            / counts[f"reliability_bin{number}:queries"]
            if counts[f"reliability_bin{number}:queries"]
            else None,
            "mean_estimated_event_rate": sums.get(f"reliability_bin{number}:event_rate_sum", 0.0)
            / counts[f"reliability_bin{number}:queries"]
            if counts[f"reliability_bin{number}:queries"]
            else None,
        }
        for number in range(len(BIN_EDGES) - 1)
    }
    return result


def _input_policy(
    source: Path, source_pin: str, selection: Path, selection_pin: str
) -> dict[str, Any]:
    if training.sha(Path(training.__file__)) != diagnostic.TRAINING_CODE_SHA:
        raise ValueError("immutable training dependency differs from frozen code")
    source_receipt = diagnostic.verify_pack(source, source_pin)
    contract = diagnostic.original_contract(source)
    evidence = diagnostic.selected_evidence(selection, selection_pin)
    member = "artist-fold-targets.jsonl.zst"
    input_sha = source_receipt["files"][member]["sha256"]
    if input_sha != evidence["input_sha256"]:
        raise ValueError("selection must concern this exact source cohort")
    policy = frozen_policy()
    policy["source_receipt_sha256"] = source_pin
    policy["source_input_sha256"] = input_sha
    policy["selection_evidence"] = evidence
    policy["original_split_mask_contract"] = contract
    snapshot_paths = _producing_sources()
    policy["code_sha256"] = {name: training.sha(path) for name, path in snapshot_paths.items()}
    return policy


def _copy_durable(source: Path, destination: Path) -> None:
    _check_output_growth(destination.parent, source.stat().st_size)
    with source.open("rb") as incoming, destination.open("xb") as stream:
        for chunk in iter(lambda: incoming.read(65_536), b""):
            if stream.write(chunk) != len(chunk):
                raise OSError("frozen snapshot copy was short; preserve failed attempt")
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(destination.parent)


def _seal_inventory(output: Path, stage: str) -> str:
    files = {
        path.name: {"bytes": path.stat().st_size, "sha256": training.sha(path)}
        for path in output.iterdir()
        if path.is_file()
    }
    _write(output / "receipt.json", {"revision": REVISION, "stage": stage, "files": files})
    training._bounds(output)  # noqa: SLF001 - Final actual cumulative RSS and complete byte cap.
    return training.sha(output / "receipt.json")


def _preparation_metadata(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": "pre-fit-no-label-decode",
        "source_labels_decoded": False,
        "model_fit_performed": False,
        "calibration_performed": False,
        "development_assessment_performed": False,
        "source_input_sha256": policy["source_input_sha256"],
        "role_routing_recipe_in_frozen_policy": True,
    }


def prepare(
    source: Path, source_pin: str, selection: Path, selection_pin: str, output: Path
) -> dict[str, Any]:
    """Seal externally reviewable source/policy provenance without decoding fit labels."""
    policy = _input_policy(source, source_pin, selection, selection_pin)
    _check_destination(output, source, selection)
    output.mkdir(exist_ok=False)
    _sync_directory(output.parent)
    snapshot_paths = _producing_sources()
    for name, path in snapshot_paths.items():
        _copy_durable(path, output / name)
    _write(output / "frozen-policy.json", policy)
    _write(output / "selection-evidence.json", policy["selection_evidence"])
    _write(output / "preparation.json", _preparation_metadata(policy))
    pin = _seal_inventory(output, "pre-fit-no-label-decode")
    return {
        "preparation_receipt_sha256": pin,
        "source_labels_decoded": False,
        "model_fit_performed": False,
        "frozen_policy_sha256": training.sha(output / "frozen-policy.json"),
    }


def _verify_preparation(preparation: Path, pin: str, policy: dict[str, Any]) -> dict[str, Any]:
    receipt = diagnostic.verify_pack(preparation, pin)
    expected_names = set(_producing_sources()) | {
        "frozen-policy.json",
        "selection-evidence.json",
        "preparation.json",
    }
    if (
        receipt.get("revision") != REVISION
        or receipt.get("stage") != "pre-fit-no-label-decode"
        or set(receipt["files"]) != expected_names
    ):
        raise ValueError("pre-fit preparation requires an exact closed provenance inventory")
    frozen = json.loads((preparation / "frozen-policy.json").read_bytes())
    if json.dumps(frozen, sort_keys=True) != json.dumps(policy, sort_keys=True):
        raise ValueError("authenticated preparation policy differs from current inputs/inference")
    for name, expected in policy["code_sha256"].items():
        if receipt["files"][name]["sha256"] != expected:
            raise ValueError("authenticated preparation code snapshot differs from producing pin")
    metadata = json.loads((preparation / "preparation.json").read_bytes())
    if metadata != _preparation_metadata(policy):
        raise ValueError("pre-fit provenance flags/input/role declaration differs")
    if (
        json.loads((preparation / "selection-evidence.json").read_bytes())
        != policy["selection_evidence"]
    ):
        raise ValueError("pre-fit separate selection evidence differs from frozen policy")
    return receipt


def run(  # noqa: C901, PLR0913, PLR0915 - Explicit pins and the auditable sealed role sequence.
    source: Path,
    source_pin: str,
    selection: Path,
    selection_pin: str,
    output: Path,
    *,
    preparation: Path,
    preparation_pin: str,
) -> dict[str, Any]:
    """Require exact reviewed preparation, then fit once, calibrate and assess."""
    policy = _input_policy(source, source_pin, selection, selection_pin)
    frozen = _verify_preparation(preparation, preparation_pin, policy)
    _check_destination(output, source, selection, preparation)
    output.mkdir(exist_ok=False)
    _sync_directory(output.parent)
    for name in frozen["files"]:
        _copy_durable(preparation / name, output / name)
    _copy_durable(preparation / "receipt.json", output / "pre-fit-receipt.json")
    _write(
        output / "preparation-admission.json",
        {
            "preparation_receipt_sha256": preparation_pin,
            "prepared_policy_sha256": frozen["files"]["frozen-policy.json"]["sha256"],
            "fit_labels_decoded_before_authentication": False,
        },
    )
    # Every source snapshot, policy, and admission is durable before any fit label decodes.
    member = "artist-fold-targets.jsonl.zst"
    fit_rows = list(rows_for_role(source / member, "fit"))
    model = training.fit(fit_rows, -1)
    training._bounds(output)  # noqa: SLF001 - Actual cumulative fit peak before later-role decode.
    fit_ids = sorted(row.mbid for row in fit_rows)
    del fit_rows
    fitted_value = diagnostic.model_value(model)
    fitted_value["fit_scope"] = (
        "fixed original-training fit-role UUIDs only; no calibration or assessment labels"
    )
    _write(output / "fixed-fit-model.json", fitted_value)
    model_sha = training.sha(output / "fixed-fit-model.json")
    _write(
        output / "fixed-fit-seal.json",
        {
            "model_sha256": model_sha,
            "exact_fit_artist_ids": fit_ids,
            "fit_role_only": True,
            "calibration_and_assessment_labels_decoded_before_fit": False,
        },
    )
    role_ids: dict[str, list[str]] = {"fit": fit_ids, "calibrate": [], "development_assess": []}
    phase_counts: dict[str, dict[str, Counter[str]]] = {
        phase: {arm: Counter() for arm in diagnostic.ARMS}
        for phase in ("calibrate", "development_assess")
    }
    phase_sums: dict[str, dict[str, dict[str, float]]] = {
        phase: {arm: {} for arm in diagnostic.ARMS} for phase in ("calibrate", "development_assess")
    }
    with _query_writer(output) as stream:

        def calibration_queries() -> Iterator[Query]:
            for row in rows_for_role(
                source / member, "calibrate", output / "fixed-fit-model.json", model_sha
            ):
                role_ids["calibrate"].append(row.mbid)
                if len(role_ids["calibrate"]) % RESOURCE_CHECK_INTERVAL == 0:
                    training._bounds(output)  # noqa: SLF001 - Periodic actual /proc guard.
                query = multilabel_query(row)
                predictions = {}
                for arm in diagnostic.ARMS:
                    prediction = query_scores(
                        model, query.seeds, arm, source_observed=bool(query.targets)
                    )
                    prediction["raw_query_eligibility_reason"] = prediction["abstention_reason"]
                    if prediction["abstention_reason"] is None:
                        prediction["abstention_reason"] = (
                            "calibration_role_no_fitted_policy_emission"
                        )
                    predictions[arm] = prediction
                    _tally(
                        phase_counts["calibrate"][arm],
                        phase_sums["calibrate"][arm],
                        model,
                        query,
                        prediction,
                    )
                stream.write(
                    (
                        json.dumps(
                            {
                                "role": "calibrate",
                                "artist_mbid": query.mbid,
                                "observed_seeds": query.seeds,
                                "held_observed_source_positives": query.targets,
                                "predictions": predictions,
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode()
                )
                yield query

        calibrator = calibrate(model, calibration_queries())
        _write(
            output / "fixed-fit-calibrator.json",
            {
                "event": EVENT,
                "fitted_model_sha256": model_sha,
                "policy_sha256": training.sha(output / "frozen-policy.json"),
                "arms": calibrator,
                "refit_allowed": False,
                "individual_membership_probability": None,
            },
        )
        calibrator_sha = training.sha(output / "fixed-fit-calibrator.json")
        _write(
            output / "calibration-seal.json",
            {
                "calibrator_sha256": calibrator_sha,
                "development_assessment_labels_decoded_before_calibration": False,
            },
        )
        for row in rows_for_role(
            source / member,
            "development_assess",
            output / "fixed-fit-model.json",
            model_sha,
            calibrator_path=output / "fixed-fit-calibrator.json",
            calibrator_sha=calibrator_sha,
        ):
            if training.sha(output / "fixed-fit-calibrator.json") != calibrator_sha:
                raise ValueError("calibrator must stay sealed before assessment")
            role_ids["development_assess"].append(row.mbid)
            if len(role_ids["development_assess"]) % RESOURCE_CHECK_INTERVAL == 0:
                training._bounds(output)  # noqa: SLF001 - Periodic actual /proc guard.
            query = multilabel_query(row)
            predictions = {}
            for arm in diagnostic.ARMS:
                prediction = predict(
                    model, calibrator, query.seeds, arm, source_observed=bool(query.targets)
                )
                predictions[arm] = prediction
                _tally(
                    phase_counts["development_assess"][arm],
                    phase_sums["development_assess"][arm],
                    model,
                    query,
                    prediction,
                )
            stream.write(
                (
                    json.dumps(
                        {
                            "role": "development_assess",
                            "artist_mbid": query.mbid,
                            "observed_seeds": query.seeds,
                            "held_observed_source_positives": query.targets,
                            "predictions": predictions,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode()
            )
    all_ids = [identity for identities in role_ids.values() for identity in identities]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("experiment roles must be exact-UUID disjoint")
    _write(
        output / "exact-role-artists.json", {key: sorted(value) for key, value in role_ids.items()}
    )
    report = {
        "revision": REVISION,
        "preparation_receipt_sha256": preparation_pin,
        "event": EVENT,
        "role_counts": {key: len(value) for key, value in role_ids.items()},
        "fit_artists": model.artists,
        "fitted_vocabulary": len(model.vocabulary),
        "calibration": calibrator,
        "metrics": {
            phase: {
                arm: _summary(phase_counts[phase][arm], phase_sums[phase][arm])
                for arm in diagnostic.ARMS
            }
            for phase in phase_counts
        },
        "interpretation": (
            "post-selection development only; no outer labels; no fresh confirmation "
            "or individual/musical membership calibration"
        ),
        "unknown_global_source_artists": diagnostic.GLOBAL_ARTIST_COVERAGE,
        "independent_missing_evidence": (
            "independent source observations and coverage sample, frozen external "
            "evaluation, and blinded overlapping musical membership judgments"
        ),
        "fixed_fit_model_sha256": model_sha,
        "calibrator_sha256": calibrator_sha,
        "deployment_refit_performed": False,
        "fresh_confirmation": False,
        "acceptance_gate_pass": False,
        "individual_membership_probability": None,
        "musical_probability": None,
        "linux_vmhwm_bytes": training._bounds(output),  # noqa: SLF001 - Immutable Linux resource guard.
    }
    _write(output / "report.json", report)
    _seal_inventory(output, "fixed-fit-calibrated-development-assessed")
    total = sum(path.stat().st_size for path in output.iterdir() if path.is_file())
    if total > MAX_OUTPUT_BYTES:
        raise ValueError("bounded artifact output exceeded; preserve failed attempt")
    training._bounds(output)  # noqa: SLF001 - Check the final output and cumulative actual RSS.
    return report
