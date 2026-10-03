"""Post-inspection outer source recovery for one already selected training rule.

Old outer results were inspected before this diagnostic was designed. No result
is fresh confirmation, musical confidence, or an acceptance-gate pass.
"""

from __future__ import annotations

import ast
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zstandard

from opennoise.ml import wikidata_training_experiment as training

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "wikidata-selected-rule-post-inspection-v1"
SELECTED = "conditional_a1_mean_w1"
PRIOR = "unconditional_prior"
ARMS = (PRIOR, SELECTED)
TRAINING_CODE_SHA = "d1653f75eb1ca055b589da467cd440b427487811cdf75bb4a010abac95e3d830"
RANK_CUTOFFS = (1, 5, 10)
QUERY_FLUSH_INTERVAL = 100
NORMAL_95 = 1.959963984540054
RECIPROCAL_RANK_SCALE = 2520  # Least common multiple of ranks 1..10; exact integer accumulator.
GLOBAL_ARTIST_COVERAGE = {
    "role": "excluded external source census, not an evaluation denominator",
    "approximately_2990000_source_artists": "not an evaluation population; no cohort extrapolation",
    "unknown_source_genre_labels": "unknown, never fabricated negative labels",
    "global_genre_coverage_estimate": None,
}


def verify_pack(root: Path, expected: str) -> dict[str, Any]:
    """Authenticate a closed inventory by caller-pinned receipt bytes."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("receipt pin must be explicit lowercase SHA256")
    if training.sha(root / "receipt.json") != expected:
        raise ValueError("receipt differs from explicit pin")
    receipt = json.loads((root / "receipt.json").read_bytes())
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("sealed inventory cannot contain symlinks")
    expected_names = set(receipt["files"]) | {"receipt.json"}
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    if actual != expected_names:
        raise ValueError("closed inventory differs")
    for name, entry in receipt["files"].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("inventory path must be contained")
        if path.stat().st_size != entry["bytes"] or training.sha(path) != entry["sha256"]:
            raise ValueError(f"sealed member differs: {name}")
    return receipt


def selected_evidence(selection: Path, receipt_pin: str) -> dict[str, Any]:
    """Read the already frozen training selection, never rerun arm selection."""
    receipt = verify_pack(selection, receipt_pin)
    if receipt["files"]["implementation.py"]["sha256"] != TRAINING_CODE_SHA:
        raise ValueError("training selection implementation differs from frozen original")
    report = json.loads((selection / "report.json").read_bytes())
    if (
        report["selected_arm_training_only"] != SELECTED
        or report["confirmation_evaluation"] is not False
        or report["selected_model_refit"] is not False
    ):
        raise ValueError("selection must be the one frozen training-only conditional rule")
    return {
        "receipt_sha256": receipt_pin,
        "report_sha256": receipt["files"]["report.json"]["sha256"],
        "policy_sha256": receipt["files"]["frozen-policy.json"]["sha256"],
        "selected_arm": SELECTED,
        "selection_method": "already frozen highest unweighted mean training-innerfold R@10",
        "selected_training_mean_r10": report["mean_innerfold_recall_at_10"][SELECTED],
        "prior_training_mean_r10": report["mean_innerfold_recall_at_10"][PRIOR],
        "input_sha256": report["input_sha256"],
    }


def original_contract(source: Path) -> dict[str, Any]:
    """Authenticate original sealed split/mask constants without executing old code."""
    tree = ast.parse((source / "implementation.py").read_bytes())
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "SEED",
                "TRAIN_BUCKETS",
                "CALIBRATION_BOUNDARY",
            }:
                constants[target.id] = ast.literal_eval(node.value)
    if constants != {
        "SEED": training.MASK_SEED,
        "TRAIN_BUCKETS": training.ORIGINAL_TRAIN_BUCKETS,
        "CALIBRATION_BOUNDARY": training.ORIGINAL_CONFIRMATION_BOUNDARY,
    }:
        raise ValueError("independent UUID split/mask implementation differs from sealed old code")
    return {
        "sealed_original_code_sha256": training.sha(source / "implementation.py"),
        "constants": constants,
        "split": "independently rederive SHA256(original seed:canonical UUID) modulo 10",
        "mask": "independently minimize SHA256(original seed:mask:UUID:observed QID)",
        "saved_split_and_masks": "checked against independent derivation, never trusted",
    }


def scored(model: training.Counts, seeds: tuple[str, ...], arm: str) -> list[tuple[str, float]]:
    """Return every eligible candidate score, excluding observed seed QIDs."""
    if arm not in ARMS:
        raise ValueError("only the two frozen arms are admitted")
    supported = tuple(seed for seed in seeds if seed in model.vocabulary)
    result = []
    for candidate in model.vocabulary:
        if candidate in seeds:
            continue
        prior = model.support[candidate] / model.artists
        score = prior
        if supported and arm == SELECTED:
            score = sum(
                (model.pairs.get(seed, {}).get(candidate, 0) + prior) / (model.support[seed] + 1)
                for seed in supported
            ) / len(supported)
        result.append((candidate, score))
    return sorted(result, key=lambda pair: (-pair[1], pair[0]))


def model_value(model: training.Counts) -> dict[str, Any]:
    """Serialize fitted sufficient statistics independently of any outer query."""
    return {
        "fit_scope": "original exact-UUID training artists only; all their source positives",
        "fit_artists": model.artists,
        "support": dict(sorted(model.support.items())),
        "vocabulary": model.vocabulary,
        "pairs": {
            seed: dict(sorted(counts.items())) for seed, counts in sorted(model.pairs.items())
        },
    }


def outer_rows(
    path: Path, sealed_model: Path, model_sha: str
) -> Iterator[tuple[str, training.Row]]:
    """Decode outer labels only after authenticating the already fitted model seal."""
    if training.sha(sealed_model) != model_sha:
        raise ValueError("training model must be sealed before outer label decoding")
    seen = set()
    decoded_bytes = 0
    rows = 0
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor(max_window_size=training.MAX_ZSTD_WINDOW_BYTES).stream_reader(
            raw
        ) as stream,
        io.BufferedReader(stream) as buffered,
    ):
        while line := buffered.readline(training.MAX_LINE_BYTES + 1):
            decoded_bytes += len(line)
            rows += 1
            if (
                len(line) > training.MAX_LINE_BYTES
                or rows > training.MAX_ROWS
                or decoded_bytes > training.MAX_DECODED_BYTES
            ):
                raise ValueError("bounded original outer stream exceeded limits")
            split = training.route(line)
            if split == "train":
                continue
            row = training._train_row(json.loads(line))  # noqa: SLF001 - Pinned original mask replay.
            if row.mbid in seen:
                raise ValueError("duplicate outer exact UUID")
            seen.add(row.mbid)
            yield split, row


def query_strata(row: training.Row, model: training.Counts) -> tuple[str, ...]:
    """Keep cold, missing, outside-vocabulary, unseen and supported queries visible."""
    names = ["all"]
    if row.target is None:
        names.append("missing_source_target_unknown")
    else:
        support = model.support[row.target]
        names.append(
            "unseen_target"
            if not support
            else "rare_target_1_to_10_training_artists"
            if support <= training.RARE_SUPPORT
            else "common_target_over_10_training_artists"
        )
        if row.target not in model.vocabulary:
            names.append("target_outside_training_vocabulary")
    if len(row.labels) <= 1:
        names.append("sparse_source_0_or_1_positive")
    if not row.seeds:
        names.extend(("no_observed_seed", "cold_query_prior_fallback"))
    elif not any(seed in model.vocabulary for seed in row.seeds):
        names.extend(("unsupported_observed_seeds", "cold_query_prior_fallback"))
    else:
        names.append("supported_observed_seed")
    return tuple(names)


def wilson(hits: int, denominator: int) -> list[float] | None:
    """Descriptive Wilson 95% interval under an exchangeable-artist approximation."""
    if not denominator:
        return None
    z2 = NORMAL_95**2
    proportion = hits / denominator
    center = (proportion + z2 / (2 * denominator)) / (1 + z2 / denominator)
    radius = (
        NORMAL_95
        * math.sqrt(proportion * (1 - proportion) / denominator + z2 / (4 * denominator**2))
        / (1 + z2 / denominator)
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def metrics(counts: Counter[str]) -> dict[str, Any]:
    """Use observed targets only in recovery denominators; absence stays unknown."""
    positives = counts["positive"]
    return {
        "all_exact_outer_queries": counts["rows"],
        "masked_source_positive_queries": positives,
        "missing_source_target_unknown_queries": counts["rows"] - positives,
        "empty_rankings": counts["empty_rankings"],
        "recall": {
            str(k): counts[f"hit{k}"] / positives if positives else None for k in RANK_CUTOFFS
        },
        "hits": {str(k): counts[f"hit{k}"] for k in RANK_CUTOFFS},
        "wilson_95": {str(k): wilson(counts[f"hit{k}"], positives) for k in RANK_CUTOFFS},
        "mrr_at_10": (
            counts["reciprocal_rank_scaled"] / RECIPROCAL_RANK_SCALE / positives
            if positives
            else None
        ),
    }


def paired_metrics(counts: Counter[str]) -> dict[str, Any]:
    """Estimate the paired difference from discordances of the same masked artists."""
    n = counts["positive"]
    result: dict[str, Any] = {"masked_source_positive_queries": n, "cutoffs": {}}
    for k in RANK_CUTOFFS:
        win, loss = counts[f"selected_only{k}"], counts[f"prior_only{k}"]
        delta = (win - loss) / n if n else None
        interval = None
        if n:
            difference = (win - loss) / n
            error = math.sqrt(max(0.0, (win + loss) / n - difference**2) / n)
            interval = [
                max(-1.0, difference - NORMAL_95 * error),
                min(1.0, difference + NORMAL_95 * error),
            ]
        result["cutoffs"][str(k)] = {
            "selected_only_hits": win,
            "prior_only_hits": loss,
            "both_hits": counts[f"both{k}"],
            "neither_hits": n - win - loss - counts[f"both{k}"],
            "selected_minus_prior": delta,
            "paired_normal_95": interval,
        }
    return result


def _event(
    split: str,
    row: training.Row,
    model: training.Counts,
    totals: dict[str, dict[str, Counter[str]]],
    paired: dict[str, Counter[str]],
) -> dict[str, Any]:
    groups = query_strata(row, model)
    all_scores = {arm: scored(model, row.seeds, arm) for arm in ARMS}
    rankings = {arm: tuple(qid for qid, _ in scores[:10]) for arm, scores in all_scores.items()}
    for group in groups:
        p = paired[group]
        p["rows"] += 1
        p["positive"] += int(row.target is not None)
        for arm in ARMS:
            counts = totals[arm][group]
            ranked = rankings[arm]
            counts["rows"] += 1
            counts["positive"] += int(row.target is not None)
            counts["empty_rankings"] += int(not ranked)
            counts["reciprocal_rank_scaled"] += (
                RECIPROCAL_RANK_SCALE // (ranked.index(row.target) + 1)
                if row.target is not None and row.target in ranked
                else 0
            )
            for k in RANK_CUTOFFS:
                counts[f"hit{k}"] += int(row.target is not None and row.target in ranked[:k])
        if row.target is not None:
            for k in RANK_CUTOFFS:
                prior_hit = row.target in rankings[PRIOR][:k]
                selected_hit = row.target in rankings[SELECTED][:k]
                p[f"selected_only{k}"] += int(selected_hit and not prior_hit)
                p[f"prior_only{k}"] += int(prior_hit and not selected_hit)
                p[f"both{k}"] += int(prior_hit and selected_hit)
    return {
        "artist_mbid": row.mbid,
        "original_outer_split": split,
        "masked_observed_target": row.target,
        "seed_genre_qids": row.seeds,
        "observed_source_positive_count": len(row.labels),
        "target_training_support": model.support[row.target] if row.target else 0,
        "strata": groups,
        "rankings_at_10": rankings,
        "all_ranked_candidate_source_scores": all_scores,
        "score_interpretation": "source count ranking score, not calibrated musical probability",
    }


def diagnostic(
    source: Path,
    source_receipt_pin: str,
    selection: Path,
    selection_receipt_pin: str,
    output: Path,
) -> dict[str, Any]:
    """Freeze two arms, fit training once, seal, then evaluate both original outer splits."""
    if training.sha(Path(training.__file__)) != TRAINING_CODE_SHA:
        raise ValueError("immutable training dependency code pin differs")
    source_receipt = verify_pack(source, source_receipt_pin)
    evidence = selected_evidence(selection, selection_receipt_pin)
    original = original_contract(source)
    input_path = source / "artist-fold-targets.jsonl.zst"
    input_sha = source_receipt["files"][input_path.name]["sha256"]
    if evidence["input_sha256"] != input_sha:
        raise ValueError("selected training rule must bind this exact source input")
    output.mkdir(parents=True, exist_ok=False)
    (output / "implementation.py").write_bytes(Path(__file__).read_bytes())
    (output / "training-dependency.py").write_bytes(Path(training.__file__).read_bytes())
    training._write_json(output / "selection-evidence.json", evidence)  # noqa: SLF001
    policy = {
        "revision": REVISION,
        "timing": "POST-INSPECTION: earlier outer results already inspected",
        "fresh_confirmation": False,
        "acceptance_gate_pass": False,
        "product_promotion": False,
        "calibrated_musical_probability": False,
        "source_receipt_sha256": source_receipt_pin,
        "input_sha256": input_sha,
        "selection": evidence,
        "original_split_and_mask": original,
        "implementation_sha256": training.sha(output / "implementation.py"),
        "training_dependency_sha256": TRAINING_CODE_SHA,
        "arms": [
            {"name": PRIOR, "score": "training artist label prevalence"},
            {
                "name": SELECTED,
                "alpha": 1,
                "aggregation": "mean",
                "weight": 1,
                "score": "mean((pair + training_prior)/(supported_seed_support + 1))",
            },
        ],
        "minimum_training_artist_support": training.MINIMUM_SUPPORT,
        "unsupported_or_empty_seeds": "unconditional training prior",
        "candidates": "training vocabulary only; exclude every observed seed QID",
        "candidate_ties": "descending score then exact QID lexical order",
        "ranking_metrics": ["source-positive R@1", "R@5", "R@10", "MRR@10"],
        "query_retention": (
            "all outer UUIDs and complete candidate rankings/scores; no target drops"
        ),
        "fit_scope": "original training labels only; full fit sealed before outer label decoding",
        "outer_tuning_or_refitting": False,
        "source_cohort": "source-positive biased selected roster, not unlabelled-representative",
        "unknown_global_source_coverage": GLOBAL_ARTIST_COVERAGE,
        "uncertainty": (
            "descriptive Wilson 95% for each arm; paired Bernoulli normal 95% for differences; "
            "exchangeable independent-artist approximation within this source-selected cohort; "
            "does not account for source dependence, selection bias, prior outer inspection, "
            "or generalization to a representative artist population; no causal/fresh-test claim"
        ),
        "max_rss_bytes": training.MAX_RSS_BYTES,
        "max_output_bytes": training.MAX_OUTPUT_BYTES,
        "max_zstd_window_bytes": training.MAX_ZSTD_WINDOW_BYTES,
        "http_requests": 0,
    }
    training._write_json(output / "frozen-policy.json", policy)  # noqa: SLF001
    policy_sha = training.sha(output / "frozen-policy.json")
    rows, routes = training.load_training(input_path)
    model = training.fit(rows, -1)
    training_missing = sum(row.target is None for row in rows)
    del rows
    training._write_json(output / "fitted-training-model.json", model_value(model))  # noqa: SLF001
    fitted_path = output / "fitted-training-model.json"
    model_sha = training.sha(fitted_path)
    training._write_json(  # noqa: SLF001
        output / "training-fit-seal.json",
        {
            "model_sha256": model_sha,
            "policy_sha256": policy_sha,
            "input_sha256": input_sha,
            "fit_artists": model.artists,
            "outer_label_decoding_started": False,
        },
    )
    training._bounds(output)  # noqa: SLF001
    totals: dict[str, dict[str, dict[str, Counter[str]]]] = {
        split: {arm: defaultdict(Counter) for arm in ARMS}
        for split in ("calibration", "confirmation")
    }
    paired = {split: defaultdict(Counter) for split in totals}
    with (
        (output / "outer-queries.jsonl.zst").open("xb") as raw,
        zstandard.ZstdCompressor(level=3).stream_writer(raw) as stream,
    ):
        for index, (split, row) in enumerate(outer_rows(input_path, fitted_path, model_sha), 1):
            event = _event(split, row, model, totals[split], paired[split])
            stream.write((json.dumps(event, sort_keys=True) + "\n").encode())
            if index % QUERY_FLUSH_INTERVAL == 0:
                stream.flush(zstandard.FLUSH_BLOCK)
                training._bounds(output)  # noqa: SLF001
    if training.sha(fitted_path) != model_sha:
        raise ValueError("training model changed during outer evaluation")
    if training.sha(input_path) != input_sha:
        raise ValueError("source input changed during evaluation")
    if training.sha(output / "frozen-policy.json") != policy_sha:
        raise ValueError("frozen policy changed during evaluation")
    for split in totals:
        if totals[split][PRIOR]["all"]["rows"] != routes.get(split, 0):
            raise ValueError("outer queries must match every independently routed original UUID")
    report = {
        "revision": REVISION,
        "frozen_policy_sha256": policy_sha,
        "fitted_model_sha256": model_sha,
        "input_sha256": input_sha,
        "original_split_route_counts": routes,
        "fitted_training_artists": model.artists,
        "training_missing_source_target_unknown_queries": training_missing,
        "training_vocabulary_size": len(model.vocabulary),
        "selection": evidence,
        "outer_splits": {
            split: {
                "arms": {
                    arm: {group: metrics(n) for group, n in groups.items()}
                    for arm, groups in totals[split].items()
                },
                "paired_selected_minus_prior": {
                    group: paired_metrics(n) for group, n in paired[split].items()
                },
            }
            for split in totals
        },
        "interpretation": policy["timing"],
        "fresh_confirmation": False,
        "calibrated_musical_probability": False,
        "acceptance_gate_pass": False,
        "outer_tuning_or_refitting": False,
        "product_promotion": False,
        "uncertainty_interpretation": policy["uncertainty"],
        "unknown_global_source_coverage": GLOBAL_ARTIST_COVERAGE,
        "required_external_evidence": (
            "Independently freeze a new external artist/source sample and evaluation protocol "
            "before inspection; obtain blinded listener judgments with explicit sampling, "
            "uncertainty and calibration analysis for any musical-membership claims."
        ),
        "peak_rss_bytes": training._bounds(output),  # noqa: SLF001
    }
    training._write_json(output / "report.json", report)  # noqa: SLF001
    training._write_json(  # noqa: SLF001
        output / "receipt.json",
        {
            "revision": REVISION,
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": training.sha(path)}
                for path in sorted(output.iterdir())
            },
        },
    )
    training._bounds(output)  # noqa: SLF001
    return report
