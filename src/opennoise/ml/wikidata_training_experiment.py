"""Training-only innerfold source-positive recovery, without outer-fold label reads.

Scores rank literal source labels. Missing statements remain unknown; neither
scores nor recovery events measure musical truth or calibrated membership.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import zstandard

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "wikidata-training-innerfold-v1"
INNER_SEED = "opennoise-training-only-innerfold-20261003-v1"
MASK_SEED = "opennoise-artist-completion-v1-frozen"
FOLDS = 5
ORIGINAL_TRAIN_BUCKETS = 6
ORIGINAL_CONFIRMATION_BOUNDARY = 8
MINIMUM_SUPPORT = 5
RARE_SUPPORT = 10
RANK_LIMIT = 10
MAX_ROWS = 20_000
MAX_LABELS = 128
MAX_LINE_BYTES = 65_536
MAX_DECODED_BYTES = 5_000_000
MAX_ZSTD_WINDOW_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 5_000_000
MAX_RSS_BYTES = 35 * 1024 * 1024
TOKEN = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\]:,]|[^\s{}\[\]:,]+')


def sha(path: Path) -> str:
    """Hash sealed bytes without loading source bodies."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def original_split(mbid: str) -> str:
    """Authenticate the original outer assignment using canonical exact identity."""
    if str(UUID(mbid)) != mbid:
        raise ValueError("source artist identity must be a canonical exact UUID")
    bucket = int.from_bytes(hashlib.sha256(f"{MASK_SEED}:{mbid}".encode()).digest()) % 10
    return (
        "train"
        if bucket < ORIGINAL_TRAIN_BUCKETS
        else "calibration"
        if bucket < ORIGINAL_CONFIRMATION_BOUNDARY
        else "confirmation"
    )


def route(line: bytes) -> str:  # noqa: C901, PLR0912 - Explicit byte-only routing state machine.
    """Read only top-level identity and split; authenticate before label decoding.

    The compressed reader necessarily has byte custody of the complete line.
    String tokens are never decoded, retained, or treated as label objects.
    """
    depth = 0
    key = False
    wanted: bytes | None = None
    metadata: dict[bytes, str] = {}
    for match in TOKEN.finditer(line):
        token = match.group()
        if token in (b"{", b"["):
            depth += 1
            if depth == 1:
                key = True
        elif token in (b"}", b"]"):
            depth -= 1
        elif depth == 1:
            if token == b",":
                key = True
            elif token == b":":
                continue
            elif key:
                wanted = token if token in {b'"split"', b'"artist_mbid"'} else None
                key = False
            elif wanted:
                if wanted in metadata:
                    raise ValueError("duplicate top-level source route")
                value = json.loads(token)
                if not isinstance(value, str):
                    raise ValueError("source routing metadata must be strings")
                metadata[wanted] = value
                wanted = None
    split = metadata.get(b'"split"')
    mbid = metadata.get(b'"artist_mbid"')
    if split not in {"train", "calibration", "confirmation"} or mbid is None:
        raise ValueError("missing or invalid top-level source route")
    if original_split(mbid) != split:
        raise ValueError("source route differs from original exact-UUID outer split")
    return split


@dataclass(frozen=True, slots=True)
class Row:
    """Only admitted original-training identities, positives, and frozen masks."""

    mbid: str
    labels: tuple[str, ...]
    seeds: tuple[str, ...]
    target: str | None
    fold: int


def inner_fold(mbid: str) -> int:
    """Assign a new deterministic split using exact artist identity only."""
    return int.from_bytes(hashlib.sha256(f"{INNER_SEED}:{mbid}".encode()).digest()) % FOLDS


def _train_row(raw: dict[str, Any]) -> Row:
    mbid = raw["artist_mbid"]
    if str(UUID(mbid)) != mbid:
        raise ValueError("training artist identity must be a canonical exact UUID")
    labels = tuple(raw["observed_genre_qids"])
    if (
        len(labels) > MAX_LABELS
        or labels != tuple(sorted(set(labels)))
        or any(not re.fullmatch(r"Q[1-9][0-9]*", label) for label in labels)
    ):
        raise ValueError("training source labels must be bounded unique sorted exact QIDs")
    target = min(
        labels,
        key=lambda qid: hashlib.sha256(f"{MASK_SEED}:mask:{mbid}:{qid}".encode()).digest(),
        default=None,
    )
    seeds = tuple(label for label in labels if label != target)
    if raw["masked_observed_target"] != target or tuple(raw["seed_genre_qids"]) != seeds:
        raise ValueError("saved training mask differs from original deterministic mask")
    return Row(mbid, labels, seeds, target, inner_fold(mbid))


def load_training(path: Path) -> tuple[list[Row], dict[str, int]]:
    """Decode label fields only after a line has routed to original training."""
    rows = []
    seen = set()
    routes: Counter[str] = Counter()
    decoded_bytes = 0
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor(max_window_size=MAX_ZSTD_WINDOW_BYTES).stream_reader(
            raw
        ) as source,
        io.BufferedReader(source) as buffered,
    ):
        while line := buffered.readline(MAX_LINE_BYTES + 1):
            decoded_bytes += len(line)
            if (
                len(line) > MAX_LINE_BYTES
                or sum(routes.values()) >= MAX_ROWS
                or decoded_bytes > MAX_DECODED_BYTES
            ):
                raise ValueError("source routing bounds exceeded")
            split = route(line)
            routes[split] += 1
            if split != "train":
                continue
            row = _train_row(json.loads(line))
            if row.mbid in seen:
                raise ValueError("duplicate exact training artist UUID")
            seen.add(row.mbid)
            rows.append(row)
    if not rows:
        raise ValueError("no original-training source rows")
    return rows, dict(sorted(routes.items()))


@dataclass(frozen=True, slots=True)
class Arm:
    """One prespecified score rule; zero blend is a duplicate prior control."""

    name: str
    alpha: int
    aggregation: str
    blend: float


ARMS = (
    Arm("unconditional_prior", 0, "prior", 0.0),
    *(
        Arm(f"conditional_a{alpha}_{aggregation}_w{blend:g}", alpha, aggregation, blend)
        for alpha in (1, 10, 100)
        for aggregation in ("max", "mean")
        for blend in (0.0, 0.25, 0.5, 0.75, 1.0)
    ),
)


@dataclass(slots=True)
class Counts:
    """Counts from one inner-training fold, with vocabulary frozen before query."""

    artists: int
    support: Counter[str]
    pairs: dict[str, Counter[str]]
    vocabulary: tuple[str, ...]


def fit(rows: list[Row], held_fold: int) -> Counts:
    """Use every inner-training positive, never a held-fold target or seed."""
    support: Counter[str] = Counter()
    count = 0
    for row in rows:
        if row.fold != held_fold:
            count += 1
            support.update(row.labels)
    vocabulary = tuple(sorted(qid for qid, n in support.items() if n >= MINIMUM_SUPPORT))
    active = set(vocabulary)
    pairs: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.fold != held_fold:
            labels = tuple(qid for qid in row.labels if qid in active)
            for seed in labels:
                pairs[seed].update(qid for qid in labels if qid != seed)
    return Counts(count, support, dict(pairs), vocabulary)


def rank(model: Counts, seeds: tuple[str, ...], arm: Arm) -> tuple[str, ...]:
    """Smooth conditional source counts toward train prevalence and blend prior.

    Empty or entirely unsupported seeds use the unconditional prior. Seed
    labels are excluded even when unsupported, without inventing negatives.
    """
    supported = tuple(seed for seed in seeds if seed in model.vocabulary)
    scored = []
    for candidate in model.vocabulary:
        if candidate in seeds:
            continue
        prior = model.support[candidate] / model.artists
        score = prior
        if supported and arm.blend:
            conditional = [
                (model.pairs.get(seed, {}).get(candidate, 0) + arm.alpha * prior)
                / (model.support[seed] + arm.alpha)
                for seed in supported
            ]
            aggregated = (
                max(conditional)
                if arm.aggregation == "max"
                else sum(conditional) / len(conditional)
            )
            score = arm.blend * aggregated + (1 - arm.blend) * prior
        scored.append((candidate, score))
    return tuple(
        qid for qid, _ in sorted(scored, key=lambda pair: (-pair[1], pair[0]))[:RANK_LIMIT]
    )


def strata(row: Row, model: Counts) -> tuple[str, ...]:
    """Prespecified source sparsity, vocabulary, support, and seed diagnostics."""
    names = ["all"]
    if row.target is None:
        names.append("missing_source_target_unknown")
    else:
        support = model.support[row.target]
        names.append(
            "unseen_target"
            if support == 0
            else "rare_target_1_to_10_innertrain_artists"
            if support <= RARE_SUPPORT
            else "common_target_over_10_innertrain_artists"
        )
        if row.target not in model.vocabulary:
            names.append("target_outside_innertrain_vocabulary")
    if len(row.labels) <= 1:
        names.append("sparse_source_0_or_1_positive")
    if not row.seeds:
        names.append("no_observed_seed")
    elif not any(seed in model.vocabulary for seed in row.seeds):
        names.append("no_supported_seed")
    else:
        names.append("supported_seed")
    return tuple(names)


def summarize(counts: Counter[str]) -> dict[str, Any]:
    """Keep absent source targets in all rows and out of positive denominators."""
    positive = counts["positive"]
    return {
        "all_exact_training_queries": counts["rows"],
        "masked_source_positive_queries": positive,
        "missing_source_target_unknown_queries": counts["rows"] - positive,
        "recall": {str(k): counts[f"hit{k}"] / positive if positive else None for k in (1, 5, 10)},
        "recovered_at_10": counts["hit10"],
        "empty_rankings": counts["empty_rankings"],
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _peak_rss() -> int:
    """Measure Linux peak since exec, excluding an inherited fork high-water mark."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            fields = line.split()
            if fields[-1] != "kB":
                raise ValueError("unexpected Linux RSS units")
            return int(fields[1]) * 1024
    raise ValueError("Linux process RSS high-water measurement unavailable")


def _bounds(output: Path) -> int:
    peak = _peak_rss()
    if peak > MAX_RSS_BYTES:
        raise ValueError(f"training experiment exceeded RSS bound: {peak}")
    if sum(path.stat().st_size for path in output.iterdir()) > MAX_OUTPUT_BYTES:
        raise ValueError("training experiment exceeded output byte bound")
    return peak


def _fold_events(
    rows: list[Row], fold: int, model: Counts, totals: dict[str, dict[str, Counter[str]]]
) -> Iterator[dict[str, Any]]:
    for row in rows:
        if row.fold != fold:
            continue
        groups = strata(row, model)
        rankings = {}
        for arm in ARMS:
            ranked = rank(model, row.seeds, arm)
            rankings[arm.name] = ranked
            for group in groups:
                counts = totals[arm.name][group]
                counts["rows"] += 1
                counts["positive"] += int(row.target is not None)
                counts["empty_rankings"] += int(not ranked)
                for k in (1, 5, 10):
                    counts[f"hit{k}"] += int(row.target is not None and row.target in ranked[:k])
        yield {
            "artist_mbid": row.mbid,
            "inner_fold": fold,
            "observed_source_positive_count": len(row.labels),
            "masked_observed_target": row.target,
            "seed_genre_qids": row.seeds,
            "target_innertrain_support": model.support[row.target] if row.target else 0,
            "strata": groups,
            "rankings": rankings,
        }


def experiment(source_pack: Path, output: Path, expected_receipt_sha256: str) -> dict[str, Any]:
    """Freeze new policy/code/input before loading training labels or fitting.

    Existing inventory verification hashes all members without interpreting
    their labels. No outer-fold model, prediction, or result is consulted.
    """
    from opennoise.ml.wikidata_artist_completion import check_files  # noqa: PLC0415

    if not re.fullmatch(r"[a-f0-9]{64}", expected_receipt_sha256):
        raise ValueError("expected source receipt SHA256 must be explicit lowercase hexadecimal")
    if sha(source_pack / "receipt.json") != expected_receipt_sha256:
        raise ValueError("source receipt differs from pinned expected SHA256")
    verified = check_files(source_pack)
    source_path = source_pack / "artist-fold-targets.jsonl.zst"
    receipt = json.loads((source_pack / "receipt.json").read_bytes())
    input_sha = receipt["files"][source_path.name]["sha256"]
    if sha(source_path) != input_sha:
        raise ValueError("source input differs from pinned receipt SHA256")
    output.mkdir(parents=True, exist_ok=False)
    (output / "implementation.py").write_bytes(Path(__file__).read_bytes())
    policy = {
        "revision": REVISION,
        "scope": "exact-ID masked observed P136 recovery; absence unknown; no musical truth",
        "outer_fold_access": (
            "byte custody and top-level UUID/split routing only; no label decoding"
        ),
        "original_split_validation": "SHA256(original mask seed:canonical UUID) modulo 10",
        "expected_source_receipt_sha256": expected_receipt_sha256,
        "timing": "new training-only diagnostic after prior outer results were inspected",
        "source_inventory_verification": verified,
        "input_sha256": input_sha,
        "implementation_sha256": sha(output / "implementation.py"),
        "inner_seed": INNER_SEED,
        "inner_folds": FOLDS,
        "mask_seed": MASK_SEED,
        "minimum_innertrain_label_support": MINIMUM_SUPPORT,
        "conditional_score": "(pair + alpha * innertrain_prior) / (seed_support + alpha)",
        "blend": "weight * conditional + (1 - weight) * innertrain_prior",
        "cold_or_empty_seed": "unconditional innertrain prior; source absence unknown",
        "arms": [
            {
                "name": arm.name,
                "alpha": arm.alpha,
                "aggregation": arm.aggregation,
                "blend": arm.blend,
            }
            for arm in ARMS
        ],
        "selection": "highest unweighted mean fold R@10; ties by frozen arm order, prior first",
        "candidate_ties": "descending score then exact QID lexicographically",
        "confirmation_evaluation": False,
        "selected_model_refit": False,
        "product_promotion": False,
        "max_rss_bytes": MAX_RSS_BYTES,
        "rss_measurement": "Linux /proc/self/status VmHWM, peak since exec",
        "max_output_bytes": MAX_OUTPUT_BYTES,
        "max_decoded_input_bytes": MAX_DECODED_BYTES,
        "max_zstd_window_bytes": MAX_ZSTD_WINDOW_BYTES,
    }
    _write_json(output / "frozen-policy.json", policy)
    frozen_policy_sha = sha(output / "frozen-policy.json")
    rows, routes = load_training(source_path)
    fold_reports: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, Counter[str]]] = {arm.name: defaultdict(Counter) for arm in ARMS}
    with (
        (output / "innerfold-queries.jsonl.zst").open("xb") as raw,
        zstandard.ZstdCompressor(level=3).stream_writer(raw) as stream,
    ):
        for fold in range(FOLDS):
            model = fit(rows, fold)
            totals: dict[str, dict[str, Counter[str]]] = {
                arm.name: defaultdict(Counter) for arm in ARMS
            }
            for event in _fold_events(rows, fold, model, totals):
                stream.write((json.dumps(event, sort_keys=True) + "\n").encode())
            fold_reports.append(
                {
                    "fold": fold,
                    "inner_training_artists": model.artists,
                    "inner_training_vocabulary": len(model.vocabulary),
                    "arms": {
                        name: {group: summarize(counts) for group, counts in groups.items()}
                        for name, groups in totals.items()
                    },
                }
            )
            for name, groups in totals.items():
                for group, counts in groups.items():
                    aggregate[name][group].update(counts)
            del model, totals
            stream.flush(zstandard.FLUSH_BLOCK)
            _bounds(output)
    means = {
        arm.name: [
            fold["arms"][arm.name].get("all", {}).get("recall", {}).get("10")
            for fold in fold_reports
        ]
        for arm in ARMS
    }
    if any(any(value is None for value in values) for values in means.values()):
        raise ValueError("each prespecified innerfold must contain source-positive targets")
    mean_recall = {name: sum(values) / FOLDS for name, values in means.items()}
    selected = max(ARMS, key=lambda arm: (mean_recall[arm.name], -ARMS.index(arm)))
    report = {
        "revision": REVISION,
        "frozen_policy_sha256": frozen_policy_sha,
        "input_sha256": policy["input_sha256"],
        "routing_counts_only": routes,
        "all_original_training_queries": len(rows),
        "folds": fold_reports,
        "arms": {
            name: {group: summarize(counts) for group, counts in groups.items()}
            for name, groups in aggregate.items()
        },
        "mean_innerfold_recall_at_10": mean_recall,
        "selected_arm_training_only": selected.name,
        "confirmation_evaluation": False,
        "selected_model_refit": False,
        "product_promotion": False,
        "interpretation": "training-only selection diagnostic; no fresh confirmation claim",
        "peak_rss_bytes": _bounds(output),
    }
    _write_json(output / "report.json", report)
    _write_json(
        output / "receipt.json",
        {
            "revision": REVISION,
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                for path in sorted(output.iterdir())
            },
        },
    )
    _bounds(output)
    return report
