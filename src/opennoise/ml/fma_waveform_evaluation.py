"""Frozen diagnostic baselines and exact component-balanced conditional random retrieval."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.ml import fma_waveform_pipeline as waveform

REVISION = "fma55-frozen-retrieval-diagnostics-v1"
PROTOCOL_SHA = "60fab0ce7a1086999011e46eec2acdf9205921165220f63f4dd7191bc2c98df8"
LISTENS_SHA = "480ba7112f7f6817406c51cd316fa128d1a3d4ee2dde0d180eeccb329d235883"
SOURCE_SHA = "829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729"
MAX_BYTES = 100_000_000
VIEW_BYTES = 200_000
MAX_TAGS = 16
SOURCE_FILES = waveform.FILES | {"inventory.json"}
ROOT_FILES = {
    "protocol.json",
    "declaration.json",
    "receipt.json",
    "evaluation.json",
    "listens.json",
    "inventory.json",
}


def probability(value: Fraction) -> dict[str, Any]:
    """Expose the exact finite-procedure fraction as well as its display value."""
    return {
        "probability": float(value),
        "numerator": value.numerator,
        "denominator": value.denominator,
    }


def conditional_null(
    groups: list[list[set[int]]], tags: set[int], known: set[int], k: int
) -> dict[str, Any]:
    """Enumerate weighted tag unions without enumerating independent track tuples."""
    if len(tags) > MAX_TAGS or k not in (1, 3) or any(not group for group in groups):
        raise ValueError("null scope exceeds frozen bounds")
    ordered_tags = sorted(tags)
    effective = min(k, len(groups))
    layers: list[dict[int, Fraction]] = [{0: Fraction(1)}] + [{} for _ in range(effective)]
    for group in groups:
        counts = Counter(
            sum(1 << i for i, tag in enumerate(ordered_tags) if tag in labels) for labels in group
        )
        for count in range(effective, 0, -1):
            updated = dict(layers[count])
            for before, weight in layers[count - 1].items():
                for mask, amount in counts.items():
                    union = before | mask
                    updated[union] = updated.get(union, Fraction(0)) + weight * Fraction(
                        amount, len(group)
                    )
            layers[count] = updated
    divisor = math.comb(len(groups), effective)
    distribution = {mask: value / divisor for mask, value in layers[effective].items()}
    if sum(distribution.values()) != 1:
        raise ValueError("null probabilities do not sum exactly to one")
    known_mask = sum(1 << i for i, tag in enumerate(ordered_tags) if tag in known)
    all_counts: dict[int, Fraction] = defaultdict(Fraction)
    known_counts: dict[int, Fraction] = defaultdict(Fraction)
    for mask, value in distribution.items():
        all_counts[mask.bit_count()] += value
        known_counts[(mask & known_mask).bit_count()] += value
    all_denominator, known_denominator = len(tags), len(tags & known)
    return {
        "requested_k": k,
        "effective_k": effective,
        "eligible_components": len(groups),
        "hit": probability(1 - distribution.get(0, Fraction(0))),
        "recovered_masks": [
            {
                "tags": [tag for i, tag in enumerate(ordered_tags) if mask & (1 << i)],
                **probability(value),
            }
            for mask, value in sorted(distribution.items())
        ],
        "recall_all": {
            "denominator": all_denominator,
            "expectation": float(
                sum(count * value for count, value in all_counts.items()) / all_denominator
            )
            if all_denominator
            else None,
            "ceiling": max(all_counts) / all_denominator if all_denominator else None,
            "distribution": [
                {"recovered": count, **probability(value)}
                for count, value in sorted(all_counts.items())
            ],
        },
        "recall_known": {
            "denominator": known_denominator,
            "expectation": float(
                sum(count * value for count, value in known_counts.items()) / known_denominator
            )
            if known_denominator
            else None,
            "ceiling": max(known_counts) / known_denominator if known_denominator else None,
            "distribution": [
                {"recovered": count, **probability(value)}
                for count, value in sorted(known_counts.items())
            ],
        },
    }


def poisson_binomial(values: list[Fraction]) -> dict[str, Any]:
    """Return a conditional random-procedure band, not a population confidence interval."""
    distribution = [Fraction(1)]
    for value in values:
        updated = [Fraction(0)] * (len(distribution) + 1)
        for count, weight in enumerate(distribution):
            updated[count] += weight * (1 - value)
            updated[count + 1] += weight * value
        distribution = updated
    quantiles = []
    for threshold in (Fraction(1, 40), Fraction(39, 40)):
        total = Fraction(0)
        for count, value in enumerate(distribution):
            total += value
            if total >= threshold:
                quantiles.append(count)
                break
    return {
        "expected_hits": float(sum(values)),
        "conditional_central_95_hit_count_band": quantiles,
        "distribution": [
            {"hits": count, **probability(value)} for count, value in enumerate(distribution)
        ],
        "interpretation": (
            "Conditional independent random draws per query; "
            "not a population CI, p-value or musical quality."
        ),
    }


def diversify(ordered: list[int], components: dict[int, int]) -> list[int]:
    """Keep the first native recording from each frozen leakage component."""
    result: list[int] = []
    seen: set[int] = set()
    for identity in ordered:
        if components[identity] not in seen:
            result.append(identity)
            seen.add(components[identity])
    return result


def calculate(source: Path, manifest: dict[str, Any], listens: dict[int, int]) -> dict[str, Any]:
    """Compute only frozen heldout diagnostics, without fitting or changing serving."""
    original = json.loads(waveform.read(source / "evaluation.json"))
    declaration = json.loads(waveform.read(source / "declaration.json"))
    components = {row["track_id"]: row["component_id"] for row in declaration["roster"]}
    labels = {row["track_id"]: set(row["genre_ids"]) for row in manifest["tracks"]}
    training = original["training_ids"]
    pool = original["eligible_training_ids"]
    frequencies = Counter(tag for identity in training for tag in labels[identity])
    prior = {
        identity: Fraction(
            sum(frequencies[tag] for tag in labels[identity]), len(training) * len(labels[identity])
        )
        if labels[identity]
        else Fraction(0)
        for identity in pool
    }
    with (
        np.load(source / "features.npz", allow_pickle=False) as saved,
        np.load(source / "model.npz", allow_pickle=False) as model,
    ):
        matrix = (saved["values"] - model["center"]) / model["scale"]
        matrix[:, ~model["active"]] = 0
        vectors = dict(zip(saved["track_ids"].tolist(), matrix[:, 48:52], strict=True))
    ids = sorted(labels)
    label_rows = [labels[identity] for identity in ids]
    indices = {identity: i for i, identity in enumerate(ids)}
    known = set(frequencies)
    queries = []
    for row in original["queries"]:
        if row["fold"] not in (1, 2):
            continue
        identity = row["track_id"]
        eligible = [
            candidate for candidate in pool if components[candidate] != components[identity]
        ]
        simple = (
            diversify(
                sorted(
                    eligible,
                    key=lambda candidate: (
                        float(np.sum((vectors[candidate] - vectors[identity]) ** 2)),
                        candidate,
                    ),
                ),
                components,
            )
            if row["reason"] is None
            else []
        )
        prevalence = (
            diversify(
                sorted(eligible, key=lambda candidate: (-prior[candidate], candidate)), components
            )
            if row["reason"] is None
            else []
        )
        popularity = (
            diversify(
                sorted(eligible, key=lambda candidate: (-listens[candidate], candidate)), components
            )
            if row["reason"] is None
            else []
        )
        arms = {
            method: {
                "ranking": row["rankings"][method],
                "metrics": waveform.metrics(
                    labels[identity],
                    known,
                    [indices[item] for item in row["rankings"][method]],
                    label_rows,
                ),
            }
            for method in ("raw", "pca", "id")
        }
        for method, ranking in (
            ("simple4", simple),
            ("annotation_prevalence", prevalence),
            ("historical_popularity", popularity),
        ):
            arms[method] = {
                "ranking": ranking,
                "metrics": waveform.metrics(
                    labels[identity], known, [indices[item] for item in ranking], label_rows
                ),
            }
        groups: dict[int, list[set[int]]] = defaultdict(list)
        if row["reason"] is None:
            for candidate in eligible:
                groups[components[candidate]].append(labels[candidate])
        queries.append(
            {
                "track_id": identity,
                "fold": row["fold"],
                "component_id": components[identity],
                "reason": row["reason"],
                "observed_tags": sorted(labels[identity]),
                "training_known_tags": sorted(labels[identity] & known),
                "eligible_track_ids": sorted(eligible),
                "arms": arms,
                "null": {
                    str(k): conditional_null(list(groups.values()), labels[identity], known, k)
                    for k in (1, 3)
                },
            }
        )
    return {
        "revision": REVISION,
        "queries": queries,
        "aggregates": aggregate(queries),
        "serving_changed": False,
        "musical_quality_validated": False,
        "interpretation": (
            "Previously inspected selected sample; comparisons do not select a serving model. "
            "Historical listens reflect exposure, not musical quality."
        ),
    }


def aggregate(queries: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve validation/test denominators and exact conditional null hit counts."""
    result = {}
    for fold, name in ((1, "validation"), (2, "test")):
        rows = [row for row in queries if row["fold"] == fold]
        arms = {}
        for method in (
            "raw",
            "pca",
            "id",
            "simple4",
            "annotation_prevalence",
            "historical_popularity",
        ):
            arms[method] = {}
            for k in ("1", "3"):
                metrics = [
                    row["arms"][method]["metrics"][k]
                    for row in rows
                    if row["arms"][method]["metrics"] is not None
                ]
                entry = {
                    "total_queries": len(rows),
                    "defined_queries": len(metrics),
                    "hits": sum(row["hit"] for row in metrics),
                }
                for metric in ("recall_all", "recall_known"):
                    values = [row[metric] for row in metrics if row[metric] is not None]
                    entry[metric] = {
                        "mean": sum(values) / len(values) if values else None,
                        "defined_queries": len(values),
                    }
                arms[method][k] = entry
        null = {}
        for k in ("1", "3"):
            null[k] = poisson_binomial(
                [
                    Fraction(
                        row["null"][k]["hit"]["numerator"], row["null"][k]["hit"]["denominator"]
                    )
                    for row in rows
                ]
            )
            for metric in ("recall_all", "recall_known"):
                values = [
                    row["null"][k][metric]["expectation"]
                    for row in rows
                    if row["null"][k][metric]["expectation"] is not None
                ]
                null[k][metric] = {
                    "expected_mean": sum(values) / len(values) if values else None,
                    "defined_queries": len(values),
                }
        result[name] = {
            "total_queries": len(rows),
            "unsupported_queries": sum(row["reason"] is not None for row in rows),
            "arms": arms,
            "null": null,
        }
    return result


def load_listens(path: Path, identities: set[int]) -> dict[int, int]:
    """Require the reviewed minimized historical projection, with no imputed counts."""
    body = waveform.read(path, 200_000)
    if waveform.digest(body) != LISTENS_SHA:
        raise ValueError("historical-listens projection differs")
    value = json.loads(body)
    rows = value["tracks"]
    if (
        value["revision"] != "fma-permitted55-historical-listens-v1"
        or value["candidate_manifest_sha256"] != waveform.MANIFEST_SHA
    ):
        raise ValueError("historical-listens source scope differs")
    result = {}
    for row in rows:
        identity, count = row["track_id"], row["historical_track_listens"]
        if (
            set(row) != {"track_id", "historical_track_listens"}
            or type(identity) is not int
            or type(count) is not int
            or count < 0
            or identity in result
        ):
            raise ValueError("historical-listens native count differs")
        result[identity] = count
    if set(result) != identities:
        raise ValueError("historical-listens roster differs")
    return result


def input_validation(
    source: Path, manifest_path: Path, listens: Path
) -> tuple[dict[str, Any], dict[int, int]]:
    """Check source artifact custody before reading any new comparator values."""
    if waveform.digest(waveform.read(source / "inventory.json")) != SOURCE_SHA:
        raise ValueError("unreviewed waveform input inventory")
    waveform.validate_waveform_pack(source, manifest_path)
    manifest = waveform.candidate(manifest_path)
    return manifest, load_listens(listens, {row["track_id"] for row in manifest["tracks"]})


def freeze(
    source: Path, manifest: Path, listens: Path, protocol: Path, output: Path
) -> dict[str, Any]:
    """Bind inputs, implementation and protocol before new diagnostic computation."""
    input_validation(source, manifest, listens)
    if waveform.digest(waveform.read(protocol)) != PROTOCOL_SHA or output.exists():
        raise ValueError("protocol or fresh declaration path differs")
    base = Path(__file__).parents[3]
    code = [
        Path(__file__),
        Path(waveform.__file__),
        base / "scripts/evaluate_fma_waveform.py",
        base / "tests/test_fma_waveform_evaluation.py",
    ]
    declaration = {
        "revision": "fma55-evaluation-declaration-v1",
        "protocol_sha256": PROTOCOL_SHA,
        "source": str(source.resolve()),
        "candidate_manifest": str(manifest.resolve()),
        "listens": str(listens.resolve()),
        "protocol": str(protocol.resolve()),
        "inputs": {
            str(path.resolve()): waveform.binding(path)
            for path in [source / "inventory.json", manifest, listens, protocol]
        },
        "implementation": {str(path.resolve()): waveform.binding(path) for path in code},
        "tools": {"numpy": np.__version__, "python": sys.version},
        "limits": {"wall_seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": MAX_BYTES},
    }
    waveform.write(output, declaration)
    return declaration


def inventory(pack: Path) -> dict[str, Any]:
    """Bind only the fixed root artifacts and the exact retained source pack."""
    names = (ROOT_FILES - {"inventory.json"}) | {f"source/{name}" for name in SOURCE_FILES}
    return {name: waveform.binding(pack / name) for name in sorted(names)}


def run(declaration_path: Path, output: Path) -> dict[str, Any]:
    """Evaluate the immutable declaration once, retaining favorable and unfavorable outcomes."""
    declaration = json.loads(waveform.read(declaration_path))
    if declaration["protocol_sha256"] != PROTOCOL_SHA or declaration["tools"] != {
        "numpy": np.__version__,
        "python": sys.version,
    }:
        raise ValueError("declaration protocol or tools differ")
    for group in ("inputs", "implementation"):
        for name, expected in declaration[group].items():
            if waveform.binding(Path(name)) != expected:
                raise ValueError("frozen inputs or implementation changed")
    source, manifest_path, listens_path = (
        Path(declaration["source"]),
        Path(declaration["candidate_manifest"]),
        Path(declaration["listens"]),
    )
    manifest, listens = input_validation(source, manifest_path, listens_path)
    result = calculate(source, manifest, listens)
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("output must be fresh and nonsymlinked")
    output.mkdir(parents=True)
    (output / "source").mkdir()
    for name in SOURCE_FILES:
        (output / "source" / name).write_bytes(waveform.read(source / name))
    (output / "protocol.json").write_bytes(waveform.read(Path(declaration["protocol"])))
    (output / "declaration.json").write_bytes(waveform.read(declaration_path))
    (output / "listens.json").write_bytes(waveform.read(listens_path))
    waveform.write(output / "evaluation.json", result)
    if (output / "evaluation.json").stat().st_size > VIEW_BYTES:
        raise ValueError("diagnostic view exceeds bound")
    waveform.write(
        output / "receipt.json",
        {
            "revision": "fma55-evaluation-receipt-v1",
            "protocol_sha256": PROTOCOL_SHA,
            "source_inventory_sha256": SOURCE_SHA,
            "files": {
                name: waveform.binding(output / name)
                for name in (
                    "protocol.json",
                    "declaration.json",
                    "listens.json",
                    "evaluation.json",
                    "source/inventory.json",
                )
            },
        },
    )
    recorded = inventory(output)
    if sum(value["bytes"] for value in recorded.values()) > MAX_BYTES - 200_000:
        raise ValueError("evaluation output exceeds bound")
    waveform.write(output / "inventory.json", recorded)
    return validate_evaluation_pack(
        output, manifest_path, waveform.digest(waveform.read(output / "inventory.json"))
    )


def validate_evaluation_pack(
    pack: Path, candidate_manifest: Path, inventory_sha256: str
) -> dict[str, Any]:
    """Require an external review pin, closed inventory and deterministic diagnostic replay."""
    body = waveform.read(pack / "inventory.json", 200_000)
    if waveform.digest(body) != inventory_sha256:
        raise ValueError("evaluation review pin differs")
    if {path.name for path in pack.iterdir()} != ROOT_FILES | {"source"} or pack.is_symlink():
        raise ValueError("evaluation inventory differs")
    declared = json.loads(body)
    if (
        inventory(pack) != declared
        or sum(row["bytes"] for row in declared.values()) + len(body) > MAX_BYTES
    ):
        raise ValueError("evaluation artifact bytes differ")
    if waveform.digest(waveform.read(pack / "protocol.json")) != PROTOCOL_SHA:
        raise ValueError("evaluation protocol differs")
    receipt = json.loads(waveform.read(pack / "receipt.json"))
    names = {
        "protocol.json",
        "declaration.json",
        "listens.json",
        "evaluation.json",
        "source/inventory.json",
    }
    if (
        receipt["protocol_sha256"] != PROTOCOL_SHA
        or receipt["source_inventory_sha256"] != SOURCE_SHA
        or set(receipt["files"]) != names
    ):
        raise ValueError("evaluation receipt scope differs")
    for name, expected in receipt["files"].items():
        if waveform.binding(pack / name) != expected:
            raise ValueError("evaluation receipt binding differs")
    declaration = json.loads(waveform.read(pack / "declaration.json"))
    if declaration["protocol_sha256"] != PROTOCOL_SHA:
        raise ValueError("declaration protocol differs")
    manifest, listens = input_validation(pack / "source", candidate_manifest, pack / "listens.json")
    expected = calculate(pack / "source", manifest, listens)
    actual = json.loads(waveform.read(pack / "evaluation.json", 200_000))
    if actual != expected:
        raise ValueError("diagnostics differ from frozen replay")
    return actual
