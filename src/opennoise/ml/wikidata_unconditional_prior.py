"""Untuned unconditional train-frequency diagnostic for a frozen source experiment."""

from __future__ import annotations

import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import zstandard

from opennoise.ml.wikidata_artist_completion import Model, calibrate, check_files, metrics, sha


def rank_prior(model: Model, seeds: tuple[str, ...]) -> list[tuple[str, float]]:
    """Predict from training counts even when no observed seed is supported."""
    return sorted(
        [
            (qid, model.support[qid] / model.train_count)
            for qid in model.vocabulary
            if qid not in seeds
        ],
        key=lambda pair: (-pair[1], pair[0]),
    )[:10]


def diagnose(model_root: Path, output: Path) -> dict[str, Any]:
    """Create a post-inspection diagnostic without changing the frozen experiment."""
    check_files(model_root)
    output.mkdir(parents=True, exist_ok=False)
    policy = {
        "revision": "wikidata-unconditional-source-prior-diagnostic-v1",
        "model_receipt_sha256": sha(model_root / "receipt.json"),
        "implementation_sha256": sha(Path(__file__)),
        "timing": "post-inspection diagnostic on existing source splits; not fresh confirmation",
        "rule": (
            "all train-active labels ordered by train artist support; "
            "exclude observed seeds, never require them"
        ),
        "refit": False,
        "retuning": False,
        "arm_reselection": False,
    }
    (output / "policy.json").write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n")
    saved = json.loads((model_root / "fitted-model.json").read_bytes())
    model = Model(
        Counter(saved["training_support"]),
        {},
        tuple(saved["training_vocabulary"]),
        {},
        saved["training_artists"],
    )
    cohorts: dict[str, list[dict[str, Any]]] = {"calibration": [], "confirmation": []}
    with (
        (model_root / "artist-fold-targets.jsonl.zst").open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as source,
    ):
        for line in io.TextIOWrapper(source):
            row = json.loads(line)
            if row["split"] in cohorts:
                target = row["masked_observed_target"]
                seeds = tuple(row["seed_genre_qids"])
                cohorts[row["split"]].append(
                    {
                        "artist_mbid": row["artist_mbid"],
                        "observed_labels": len(row["observed_genre_qids"]),
                        "seed_labels": list(seeds),
                        "masked_observed_target": target,
                        "target_in_training_vocabulary": target in model.vocabulary,
                        "target_training_support": model.support.get(target, 0),
                        "ranked": rank_prior(model, seeds),
                        "abstention": None,
                    }
                )
    bins = calibrate(cohorts["calibration"])
    report = {
        **policy,
        "calibration_bins": bins,
        "calibration": metrics(cohorts["calibration"], bins),
        "confirmation": metrics(cohorts["confirmation"], bins),
        "scope": (
            "masked observed P136 recovery only; missing source labels unknown; no musical truth"
        ),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    with (
        (output / "confirmation.jsonl.zst").open("xb") as raw,
        zstandard.ZstdCompressor(level=3).stream_writer(raw) as stream,
    ):
        for row in cohorts["confirmation"]:
            stream.write((json.dumps(row, sort_keys=True) + "\n").encode())
    (output / "receipt.json").write_text(
        json.dumps(
            {
                "files": {
                    path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                    for path in sorted(output.iterdir())
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return report
