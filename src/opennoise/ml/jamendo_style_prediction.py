"""Fixed genre-to-human-style development study; reserved roles precede covariates."""

# ruff: noqa: PLR2004 -- immutable cohort, method, target and resource dimensions.
from __future__ import annotations

import hashlib
import math
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from opennoise.ml import jamendo_human_genre as base
from opennoise.ml import jamendo_human_mood as native

PROTOCOL = "8624a347604e341943f5f91046c0a54b2ce5eae6042fbdbbe777a1c21d68430b"
ATTRIBUTES = ("aggressive", "electronic", "party", "relaxed", "sad")
METHODS = ("training_beta_prior", "genre_tfidf_knn10", "genre_fractional_logistic_C1")
PARTS = ("positive", "negative", "total")
METRICS = ("logloss", "individual_vote_brier")
CONTRASTS = ((2, 0), (2, 1), (1, 0))
PAYLOADS = {"models.json", "predictions.json", "evaluation.json"}
MAX_BYTES = 20_000_000
GENRE = re.compile(r"genre---[a-z0-9]{1,64}")


@dataclass(frozen=True)
class Inputs:
    """Only the exact approved two files and externally pinned new protocol."""

    metadata: Path
    human: Path
    protocol: Path
    protocol_sha256: str

    @property
    def paths(self) -> tuple[Path, ...]:
        """Protect source custody from output overlap."""
        return self.metadata, self.human, self.protocol


class LogisticContractError(ValueError):
    """Expose bounded future failure diagnostics without retrying or returning model outputs."""

    def __init__(self, diagnostics: dict[str, Any]) -> None:
        """Retain numerical acceptance facts, never private coefficients or target rows."""
        self.diagnostics = diagnostics
        super().__init__("Frozen logistic convergence/finite-gradient contract failed")


def runtime() -> dict[str, Any]:
    """Bind new implementation, pinned native helpers and locked numeric runtime."""
    script = Path(__file__).resolve().parents[3] / "scripts/run_jamendo_style_prediction.py"
    return {
        "original": base.runtime(),
        "scipy": version("scipy"),
        "code": {p.name: base.digest(p) for p in (Path(__file__), script)},
    }


def validate(inputs: Inputs) -> dict[str, Any]:
    """Reject source, protocol or helper drift before interpreting any rows."""
    if (
        any(p.is_symlink() for p in (inputs.protocol, *inputs.protocol.parents))
        or not inputs.protocol.is_file()
        or inputs.protocol.stat().st_size > 128_000
        or inputs.protocol_sha256 != PROTOCOL
        or base.digest(inputs.protocol) != PROTOCOL
    ):
        raise ValueError("Frozen style-prediction protocol differs")
    spec = base.read(inputs.protocol)
    root = Path(__file__).resolve().parents[3]
    observed = base.runtime()
    if tuple(observed[k] for k in ("python", "numpy", "scipy")) != ("3.13.14", "2.5.2", "1.18.1"):
        raise ValueError("Frozen numerical runtime differs")
    if any(base.digest(root / name) != pin for name, pin in spec["helper_code_sha256"].items()):
        raise ValueError("Pinned native identity/canonicalization code differs")
    for name in ("metadata", "human"):
        path, expected = getattr(inputs, name), spec["source"][name]
        if (
            any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file()
            or path.stat().st_size != expected["bytes"]
            or base.digest(path) != expected["sha256"]
        ):
            raise ValueError("Exact approved raw source bytes differ")
    return spec


def genre_fields(cells: list[str]) -> set[str]:
    """Interpret permitted literal genre tags only after the development role gate."""
    tags = {c for c in cells if c.startswith("genre---")}
    if any(GENRE.fullmatch(tag) is None for tag in tags):
        raise ValueError("Noncanonical development genre tag")
    return tags


def style_fields(cells: list[str]) -> dict[str, dict[str, Any]]:
    """Interpret exactly the fixed five binary taxonomies without normalization."""
    result = {}
    for attribute in ATTRIBUTES:
        prefix = f"mood_{attribute}---"
        values = [c[len(prefix) :] for c in cells if c.startswith(prefix)]
        if len(values) > 1:
            raise ValueError("Duplicate selected style taxonomy")
        votes = values[0].split(",") if values and values[0] else []
        reason = (
            "missing_votes"
            if not votes
            else "wrong_vote_count"
            if len(votes) != 3
            else "invalid_vote"
            if any(v not in (attribute, "not_" + attribute) for v in votes)
            else None
        )
        result[attribute] = {
            "reason": reason,
            "vote_count": len(votes),
            "positive_votes": votes.count(attribute) if reason is None else 0,
        }
    return result


def role_row(identity: dict[str, Any], cells: list[str], *, human: bool) -> dict[str, Any]:
    """Skip the reserved identity before either target or genre accessor is invoked."""
    if identity["fold"] == 4:
        return {**identity, "status": "reserved_skipped"}
    field = "attributes" if human else "genre_tags"
    value = style_fields(cells) if human else sorted(genre_fields(cells))
    return {**identity, "status": "development", field: value}


def artist_roles(identities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create metadata-only native roles, with no reserved feature or target containers."""
    by_artist: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in identities:
        by_artist[row["artist_id"]].append(row)
    if (
        len(identities) != 11565
        or len(by_artist) != 713
        or len({r["component_id"] for r in identities}) != 713
        or len({r["album_id"] for r in identities}) != 2365
        or any(len({r["component_id"] for r in rows}) != 1 for rows in by_artist.values())
    ):
        raise ValueError("Expected exactly713 one-artist native components")
    artists: list[dict[str, Any]] = []
    for artist, rows in sorted(by_artist.items()):
        row = rows[0]
        value: dict[str, Any] = {
            "artist_id": artist,
            "component_id": row["component_id"],
            "fold": row["fold"],
            "track_count": len(rows),
            "album_ids": sorted({r["album_id"] for r in rows}),
            "status": "reserved_skipped" if row["fold"] == 4 else "development",
        }
        if row["fold"] != 4:
            value.update(
                {
                    "tag_counts": {},
                    "attributes": {
                        a: {"eligible_tracks": 0, "positive_votes": 0, "negative_votes": 0}
                        for a in ATTRIBUTES
                    },
                }
            )
        artists.append(value)
    return artists


def source(inputs: Inputs) -> dict[str, Any]:  # noqa: C901 -- Keep both reserved gates explicit.
    """Identity-first raw replay with count-only feature/support census; no IDF or fitting."""
    spec = validate(inputs)
    metadata = native.parse(inputs.metadata, human=False, identity_only=True)
    human = native.parse(inputs.human, human=True, identity_only=True)
    native.join(metadata, human)
    identities = base.cohort(metadata)
    cohort_hash = hashlib.sha256(base.file_bytes("cohort.json", identities)).hexdigest()
    if cohort_hash != spec["source"]["identity_cohort_sha256"]:
        raise ValueError("Full native identity/component seal differs")
    by_id = {r["track_id"]: r for r in identities}
    artists = artist_roles(identities)
    artist_index = {r["artist_id"]: r for r in artists}
    accessors: Counter[str] = Counter()
    tracks: dict[int, dict[str, Any]] = {}
    for path, is_human in ((inputs.metadata, False), (inputs.human, True)):
        for line in path.read_text().splitlines()[1:]:
            fields = line.split("\t")
            identity = by_id[native._identity(fields)[0]]  # noqa: SLF001 -- frozen native grammar.
            key = "style" if is_human else "genre"
            if identity["fold"] == 4:
                row = role_row(identity, [], human=is_human)
                accessors[f"reserved_{key}_skipped"] += 1
                tracks[row["track_id"]] = row
                continue
            row = role_row(identity, fields[5:], human=is_human)
            accessors[f"development_{key}_accessed"] += 1
            artist = artist_index[row["artist_id"]]
            if not is_human:
                artist["tag_counts"] = dict(
                    Counter(artist["tag_counts"]) + Counter(row["genre_tags"])
                )
                continue
            for a in ATTRIBUTES:
                selected = row["attributes"][a]
                if selected["reason"] is None:
                    attribute_support = artist["attributes"][a]
                    attribute_support["eligible_tracks"] += 1
                    attribute_support["positive_votes"] += selected["positive_votes"]
                    attribute_support["negative_votes"] += 3 - selected["positive_votes"]
                row["attributes"][a] = {
                    "reason": selected["reason"],
                    "vote_count": selected["vote_count"],
                }
            tracks[row["track_id"]] = row
    for row in artists:
        if row["status"] == "development":
            row["tag_counts"] = dict(sorted(row["tag_counts"].items()))
            row["complete"] = all(row["attributes"][a]["eligible_tracks"] > 0 for a in ATTRIBUTES)
            row["robust"] = all(row["attributes"][a]["eligible_tracks"] >= 2 for a in ATTRIBUTES)
    expected_counters = {
        "reserved_genre_skipped": 2716,
        "reserved_style_skipped": 2716,
        "development_genre_accessed": 8849,
        "development_style_accessed": 8849,
    }
    if dict(accessors) != expected_counters:
        raise ValueError("Reserved role/accessor accounting differs")
    validate(inputs)
    result = {
        "tracks": [tracks[k] for k in sorted(tracks)],
        "artists": artists,
        "identity_cohort_sha256": cohort_hash,
        "accessor_counts": dict(accessors),
    }
    result["support"] = support(result["tracks"], artists)
    return result


def support(tracks: list[dict[str, Any]], artists: list[dict[str, Any]]) -> dict[str, Any]:
    """Count all roles, labels and training-only vocabulary without numeric feature banks."""
    dev = [r for r in artists if r["status"] == "development"]
    cells = []
    for fold in range(4):
        train = [r for r in dev if r["fold"] != fold]
        query = [r for r in dev if r["fold"] == fold]
        labeled = [r for r in train if r["complete"]]
        vocabulary = sorted({tag for r in train for tag in r["tag_counts"]})
        attrs = {}
        for a in ATTRIBUTES:
            pos = sum(r["attributes"][a]["positive_votes"] > 0 for r in labeled)
            neg = sum(r["attributes"][a]["negative_votes"] > 0 for r in labeled)
            attrs[a] = {
                "positive_components": pos,
                "negative_components": neg,
                **{
                    field: sum(r["attributes"][a][field] for r in labeled)
                    for field in ("eligible_tracks", "positive_votes", "negative_votes")
                },
                "gate": pos >= 5 and neg >= 5,
                "unsupported_reasons": (
                    ["no_finite_logistic_optimum"] if pos == 0 or neg == 0 else []
                )
                + (["insufficient_positive_components"] if pos < 5 else [])
                + (["insufficient_negative_components"] if neg < 5 else []),
            }
        cells.append(
            {
                "fold": fold,
                "training_metadata": len(train),
                "training_complete": len(labeled),
                "query_metadata": len(query),
                "query_complete": sum(r["complete"] for r in query),
                "query_robust": sum(r["robust"] for r in query),
                "vocabulary_size": len(vocabulary),
                "document_frequency": {
                    t: sum(t in r["tag_counts"] for r in train) for t in vocabulary
                },
                "feature_empty_queries": sum(
                    not set(r["tag_counts"]) & set(vocabulary) for r in query
                ),
                "attributes": attrs,
                "gate": all(r["gate"] for r in attrs.values()),
            }
        )
    development_tracks = [r for r in tracks if r["status"] == "development"]
    return {
        "metadata_tracks": len(tracks),
        "artists": len(artists),
        "components": len(artists),
        "development_tracks": len(development_tracks),
        "reserved_tracks": len(tracks) - len(development_tracks),
        "development_artists": len(dev),
        "reserved_artists": len(artists) - len(dev),
        "complete": sum(r["complete"] for r in dev),
        "robust": sum(r["robust"] for r in dev),
        "unjudged": sum(not r["complete"] for r in dev),
        "cells": cells,
        "track_reasons": {
            a: dict(Counter(r["attributes"][a]["reason"] or "eligible" for r in development_tracks))
            for a in ATTRIBUTES
        },
        "gate": all(r["gate"] for r in cells),
        "supervised_fits": 0,
        "idf_builds": 0,
    }


def bindings(files: dict[str, Any]) -> dict[str, Any]:
    """Bind the exact canonical file bytes, not parsed-object equality."""
    return {
        name: {
            "sha256": hashlib.sha256(base.encoded(value)).hexdigest(),
            "bytes": len(base.encoded(value)),
        }
        for name, value in files.items()
    }


def receipt(inputs: Inputs, files: dict[str, Any], revision: str) -> dict[str, Any]:
    """Use hash-only path-free custody with exact runtime and rights."""
    spec = validate(inputs)
    return {
        "revision": revision,
        "protocol_sha256": PROTOCOL,
        "source": spec["source"],
        "runtime": runtime(),
        "rights": spec["rights"],
        "files": bindings(files),
    }


def check_combined(directory: Path | None, files: dict[str, Any]) -> None:
    """Apply the declared combined census/results cap including both seals."""
    existing = 0
    if directory is not None:
        if any(p.is_symlink() for p in (directory, *directory.parents)) or not directory.is_dir():
            raise ValueError("Regular bounded census directory required")
        members = list(directory.iterdir())
        if {p.name for p in members} != {"census.json", "seal.json"} or any(
            p.is_symlink() or not p.is_file() for p in members
        ):
            raise ValueError("Closed regular census inventory required")
        existing = sum(p.stat().st_size for p in members)
    if existing + sum(len(base.encoded(v)) for v in files.values()) > MAX_BYTES:
        raise ValueError("Combined census/result byte limit exceeded")


def publish(output: Path, files: dict[str, Any], paths: tuple[Path, ...]) -> str:
    """Publish atomically after rejecting observed existing destinations at both checks."""
    base.destination(output, paths)
    check_combined(None, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".jamendo-style-prediction-", dir=output.parent) as tmp:
        stage = Path(tmp) / "result"
        stage.mkdir()
        for name, value in files.items():
            (stage / name).write_bytes(base.encoded(value))
        base.destination(output, paths)
        stage.rename(output)
    return base.digest(output / ("seal.json" if "seal.json" in files else "receipt.json"))


def census(inputs: Inputs, output: Path) -> str:
    """Seal all source roles and support before any IDF, cosine or optimizer call."""
    base.destination(output, inputs.paths)
    files = {"census.json": source(inputs)}
    return publish(
        output,
        {**files, "seal.json": receipt(inputs, files, "style-prediction-census-v1")},
        inputs.paths,
    )


def load_stage(  # noqa: C901 -- Keep physical byte checks ahead of payload interpretation.
    inputs: Inputs, directory: Path, pin: str, *, result: bool
) -> dict[str, Any]:
    """Validate closed inventory and physical byte bindings before parsing/replay."""
    validate(inputs)
    if any(p.is_symlink() for p in (directory, *directory.parents)) or not directory.is_dir():
        raise ValueError("Bounded regular research directory required")
    names = PAYLOADS if result else {"census.json"}
    seal_name = "receipt.json" if result else "seal.json"
    members = list(directory.iterdir())
    if (
        len(members) > 12
        or {p.name for p in members} != names | {seal_name}
        or any(p.is_symlink() or not p.is_file() for p in members)
        or sum(p.stat().st_size for p in members) > MAX_BYTES
    ):
        raise ValueError("Research closed inventory/byte bound differs")
    if base.digest(directory / seal_name) != pin:
        raise ValueError("External research seal differs")
    seal = base.read(directory / seal_name)
    revision = "style-prediction-result-v1" if result else "style-prediction-census-v1"
    expected = receipt(inputs, {}, revision)
    if set(seal) != set(expected) | ({"census_sha256"} if result else set()):
        raise ValueError("Research seal schema differs")
    if result and (
        not isinstance(seal["census_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", seal["census_sha256"]) is None
    ):
        raise ValueError("Research census pin schema differs")
    for key in ("revision", "protocol_sha256", "source", "runtime", "rights"):
        if seal.get(key) != expected[key]:
            raise ValueError("Research runtime/source/rights custody differs")
    if set(seal.get("files", {})) != names:
        raise ValueError("Research payload inventory differs")
    for name in names:
        bound, path = seal["files"][name], directory / name
        if (
            not isinstance(bound, dict)
            or set(bound) != {"sha256", "bytes"}
            or type(bound["bytes"]) is not int
            or bound["bytes"] < 0
            or not isinstance(bound["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", bound["sha256"]) is None
            or path.stat().st_size != bound["bytes"]
            or base.digest(path) != bound["sha256"]
        ):
            raise ValueError("Physical research payload binding differs")
    return {name: base.read(directory / name) for name in names}


def target(rows: list[dict[str, Any]]) -> np.ndarray:
    """Equal eligible-track vote fractions; no track-count weighting of artists."""
    return np.array(
        [
            [
                r["attributes"][a]["positive_votes"] / (3 * r["attributes"][a]["eligible_tracks"])
                for a in ATTRIBUTES
            ]
            for r in rows
        ],
        dtype=np.float64,
    )


def frequencies(rows: list[dict[str, Any]], vocabulary: list[str]) -> np.ndarray:
    """Use all native artist tracks as denominator, never only annotated tracks."""
    return np.array(
        [[r["tag_counts"].get(t, 0) / r["track_count"] for t in vocabulary] for r in rows],
        dtype=np.float64,
    ).reshape(len(rows), len(vocabulary))


def objective(theta: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    """Compute SUM fractional BCE plus half nonbias squared norm and analytic gradient."""
    z = theta[0] + x @ theta[1:]
    residual = expit(z) - y
    value = np.sum(np.logaddexp(0, z) - y * z) + 0.5 * (theta[1:] @ theta[1:])
    return float(value), np.r_[residual.sum(), x.T @ residual + theta[1:]]


def fit_one(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    """Fit exactly one frozen head; optimization failures never become fallback predictions."""
    if (
        x.ndim != 2
        or y.shape != (len(x),)
        or not len(y)
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
        or np.any(x < 0)
        or np.any(x > 1)
        or np.any(y < 0)
        or np.any(y > 1)
        or not 0 < y.sum() < len(y)
    ):
        raise ValueError("Unsupported finite fractional logistic training cell")
    initial = np.zeros(x.shape[1] + 1, dtype=np.float64)
    initial_value = objective(initial, x, y)[0]
    result = minimize(
        objective,
        initial,
        args=(x, y),
        method="L-BFGS-B",
        jac=True,
        options={
            "maxiter": 500,
            "maxfun": 20000,
            "maxcor": 10,
            "maxls": 50,
            "ftol": 1e-12,
            "gtol": 1e-8,
        },
    )
    value, gradient = objective(result.x, x, y)
    norm = float(np.max(np.abs(gradient)))
    if (
        not result.success
        or not np.isfinite(result.x).all()
        or not math.isfinite(value)
        or not np.isfinite(gradient).all()
        or norm > 1e-5
        or value > initial_value + 1e-10
    ):
        raise LogisticContractError(
            {
                "optimizer_success": bool(result.success),
                "optimizer_status": getattr(result, "status", None),
                "optimizer_message": str(getattr(result, "message", "unavailable")),
                "iterations": getattr(result, "nit", None),
                "objective_calls": getattr(result, "nfev", None),
                "parameters_finite": bool(np.isfinite(result.x).all()),
                "objective": value if math.isfinite(value) else None,
                "zero_initial_objective": initial_value,
                "gradient_finite": bool(np.isfinite(gradient).all()),
                "gradient_inf_norm": norm if math.isfinite(norm) else None,
                "gradient_inf_maximum": 1e-5,
                "objective_not_increased": bool(value <= initial_value + 1e-10),
            }
        )
    return {
        "bias": float(result.x[0]),
        "coefficients": result.x[1:].tolist(),
        "objective": value,
        "zero_initial_objective": initial_value,
        "gradient_inf_norm": norm,
        "iterations": int(result.nit),
        "objective_calls": int(result.nfev),
        "converged": True,
    }


def normalize(values: np.ndarray) -> np.ndarray:
    """Normalize full genre rows once; empty profiles remain zero."""
    norms = np.linalg.norm(values, axis=1)
    return np.divide(values, norms[:, None], out=np.zeros_like(values), where=norms[:, None] > 0)


def knn_prediction(
    scores: np.ndarray, labeled: list[dict[str, Any]], y: np.ndarray, prior: np.ndarray
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Select exact-positive cosine neighbors, one artist/component, and use fsum regression."""
    if (
        not np.isfinite(scores).all()
        or np.any(scores < 0)
        or np.any(scores > 1 + 1e-12)
        or len({r["component_id"] for r in labeled}) != len(labeled)
    ):
        raise ValueError("Invalid finite one-component cosine bank")
    ranked = sorted(
        (i for i, value in enumerate(scores) if value > 0),
        key=lambda i: (-float(scores[i]), labeled[i]["component_id"], labeled[i]["artist_id"]),
    )[:10]
    if not ranked:
        return prior.copy(), []
    denominator = math.fsum(float(scores[i]) for i in ranked)
    probabilities = np.array(
        [
            math.fsum(float(scores[i]) * float(y[i, a]) for i in ranked) / denominator
            for a in range(len(ATTRIBUTES))
        ]
    )
    if (
        not np.isfinite(probabilities).all()
        or np.any(probabilities < 0)
        or np.any(probabilities > 1)
    ):
        raise ValueError("Cosine-weighted fraction escaped exact convex probability bounds")
    return probabilities, [
        {
            "artist_id": labeled[i]["artist_id"],
            "component_id": labeled[i]["component_id"],
            "cosine": float(scores[i]),
        }
        for i in ranked
    ]


def matrix_pin(values: np.ndarray) -> dict[str, Any]:
    """Pin numeric matrix order/shape/dtype without embedding redundant matrices."""
    values = np.ascontiguousarray(values, dtype="<f8")
    return {
        "shape": list(values.shape),
        "dtype": "float64-little-endian",
        "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
    }


def predict(artists: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Four training-only contexts and exactly20 fixed logistic heads, never reserved covariates."""
    dev = [r for r in artists if r["status"] == "development"]
    predictions = {
        r["artist_id"]: {
            k: r[k]
            for k in ("artist_id", "component_id", "fold", "status", "track_count", "album_ids")
        }
        for r in artists
    }
    banks = []
    for fold in range(4):
        training = [r for r in dev if r["fold"] != fold]
        labeled = [r for r in training if r["complete"]]
        query = [r for r in dev if r["fold"] == fold]
        vocabulary = sorted({t for r in training for t in r["tag_counts"]})
        df = np.array([sum(t in r["tag_counts"] for r in training) for t in vocabulary])
        idf = np.log((1 + len(training)) / (1 + df)) + 1
        x = frequencies(labeled, vocabulary)
        qx = frequencies(query, vocabulary)
        y = target(labeled)
        prior = (1 + y.sum(axis=0)) / (2 + len(y))
        models = []
        for a, attribute in enumerate(ATTRIBUTES):
            try:
                models.append(fit_one(x, y[:, a]))
            except LogisticContractError as error:
                error.diagnostics.update(
                    {
                        "fold": fold,
                        "attribute": attribute,
                        "attempted_head": fold * len(ATTRIBUTES) + a + 1,
                    }
                )
                raise
        logits = np.column_stack([m["bias"] + qx @ np.array(m["coefficients"]) for m in models])
        logistic = expit(logits)
        gallery_unit, query_unit = normalize(x * idf), normalize(qx * idf)
        cosines = query_unit @ gallery_unit.T
        banks.append(
            {
                "fold": fold,
                "training_metadata_artist_ids": [r["artist_id"] for r in training],
                "training_artist_ids": [r["artist_id"] for r in labeled],
                "training_component_ids": [r["component_id"] for r in labeled],
                "query_artist_ids": [r["artist_id"] for r in query],
                "vocabulary": vocabulary,
                "document_frequency": df.tolist(),
                "idf": idf.tolist(),
                "prior": prior.tolist(),
                "models": models,
                "raw_frequency_matrix": matrix_pin(x),
                "query_raw_frequency_matrix": matrix_pin(qx),
                "gallery_unit_matrix": matrix_pin(gallery_unit),
                "query_unit_matrix": matrix_pin(query_unit),
            }
        )
        for i, row in enumerate(query):
            knn, neighbors = knn_prediction(cosines[i], labeled, y, prior)
            reason = (
                None
                if neighbors
                else "feature_empty"
                if not row["tag_counts"]
                else "unseen_genre_tags"
                if not np.any(qx[i])
                else "no_positive_labeled_overlap"
            )
            probabilities = np.array([prior, knn, logistic[i]])
            if (
                not np.isfinite(probabilities).all()
                or np.any(probabilities < 0)
                or np.any(probabilities > 1)
            ):
                raise ValueError("Model output is not a finite probability")
            predictions[row["artist_id"]].update(
                {
                    "complete": row["complete"],
                    "robust": row["robust"],
                    "scored": row["complete"],
                    "recognized_genre_count": int(np.count_nonzero(qx[i])),
                    "unseen_genre_tags": sorted(set(row["tag_counts"]) - set(vocabulary)),
                    "probabilities": probabilities.tolist(),
                    "raw_logistic_logits": logits[i].tolist(),
                    "knn_neighbors": neighbors,
                    "knn_prior_fallback_reason": reason,
                    "model_bank_fold": fold,
                }
            )
    return banks, [predictions[k] for k in sorted(predictions)]


def loss_parts(probabilities: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Compute individual-vote proper losses with max-only clipping confined to logs."""
    p = probabilities
    positive_clip, negative_clip = p < 1e-15, (1 - p) < 1e-15
    positive = -y * np.log(np.maximum(p, 1e-15))
    negative_log = np.full_like(p, math.log(1e-15))
    np.log1p(-p, out=negative_log, where=(1 - p) >= 1e-15)
    negative = -(1 - y) * negative_log
    brier_positive, brier_negative = y * (1 - p) ** 2, (1 - y) * p**2
    values = np.stack(
        (
            np.stack((positive, brier_positive), axis=-1),
            np.stack((negative, brier_negative), axis=-1),
            np.stack((positive + negative, brier_positive + brier_negative), axis=-1),
        ),
        axis=-2,
    )
    return values, {
        "positive_probability_threshold": positive_clip.sum(axis=0).tolist(),
        "negative_probability_threshold": negative_clip.sum(axis=0).tolist(),
        "positive_nonzero_term": (positive_clip & (y > 0)).sum(axis=0).tolist(),
        "negative_nonzero_term": (negative_clip & (y < 1)).sum(axis=0).tolist(),
        "affected_artists_per_attribute": ((positive_clip & (y > 0)) | (negative_clip & (y < 1)))
        .sum(axis=0)
        .tolist(),
        "affected_artists": (np.any((positive_clip & (y > 0)) | (negative_clip & (y < 1)), axis=-1))
        .sum(axis=0)
        .tolist(),
    }


def summarize(rows: list[dict[str, Any]], seed: int | None) -> dict[str, Any]:
    """Artist-equal points and joint n-with-replacement component bootstrap contrasts."""
    rows = sorted(rows, key=lambda r: r["component_id"])
    p = np.array([r["probabilities"] for r in rows])
    y = np.array([r["target"] for r in rows])
    losses, clipping = loss_parts(p, y[:, None, :])
    losses = np.concatenate((losses, losses.mean(axis=2, keepdims=True)), axis=2)
    point = losses.mean(axis=0)
    result = {
        "artists_components": len(rows),
        "losses": point.tolist(),
        "differences": [(point[a] - point[b]).tolist() for a, b in CONTRASTS],
        "clipping": clipping,
        "prevalence_positive": [*y.mean(axis=0).tolist(), float(y.mean())],
        "prevalence_negative": [*(1 - y).mean(axis=0).tolist(), float((1 - y).mean())],
        "support_count_policy": (
            "Pooled recorded track/vote counts below are descriptive; "
            "all primary artists/components weight1."
        ),
        "recorded_target_support": {
            a: {
                field: sum(r["target_support"][a][field] for r in rows)
                for field in ("eligible_tracks", "positive_votes", "negative_votes")
            }
            for a in ATTRIBUTES
        },
        "positive_evidence_components": (y > 0).sum(axis=0).tolist(),
        "negative_evidence_components": (y < 1).sum(axis=0).tolist(),
    }
    if seed is not None:
        draws = np.random.Generator(np.random.PCG64(seed)).integers(
            0, len(rows), size=(2000, len(rows))
        )
        means = np.array([losses[index].mean(axis=0) for index in draws])
        differences = np.stack([means[:, a] - means[:, b] for a, b in CONTRASTS], axis=1)
        result["bootstrap"] = {
            "draws": 2000,
            "seed": seed,
            "generator": "PCG64",
            "intervals": np.moveaxis(
                np.percentile(differences, [2.5, 97.5], axis=0, method="linear"), 0, -1
            ).tolist(),
        }
    return result


def evaluate(artists: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep fixed matched complete-query endpoints and all5attribute/positive-negative parts."""
    source_by_id = {r["artist_id"]: r for r in artists}
    rows = []
    for row in predictions:
        if row["status"] != "development" or not row["complete"]:
            continue
        observed = source_by_id[row["artist_id"]]
        rows.append(
            {
                **row,
                "target": target([observed])[0].tolist(),
                "target_support": observed["attributes"],
            }
        )
    return {
        "attributes": [*ATTRIBUTES, "macro"],
        "methods": list(METHODS),
        "parts": list(PARTS),
        "metrics": list(METRICS),
        "contrasts": [f"{METHODS[a]}-minus-{METHODS[b]}" for a, b in CONTRASTS],
        "primary": summarize(rows, 20261020),
        "robust": summarize([r for r in rows if r["robust"]], 20261021),
        "folds": {str(f): summarize([r for r in rows if r["fold"] == f], None) for f in range(4)},
        "scored_artist_ids": [r["artist_id"] for r in rows],
        "supervised_fits": 20,
        "training_feature_banks": 4,
        "scope": (
            "Exploratory historical development proper prediction scores only; "
            "reserved fold4 unparsed; no listening relevance or public promotion."
        ),
        "rights": {"license": "CC-BY-NC-SA-4.0", "research_only": True},
    }


def compute(inputs: Inputs, directory: Path, pin: str) -> dict[str, Any]:
    """Require a physically sealed source census and exact semantic replay before fitting."""
    sealed = load_stage(inputs, directory, pin, result=False)["census.json"]
    report = source(inputs)
    if base.encoded(sealed) != base.encoded(report):
        raise ValueError("Source census semantic replay differs")
    if not report["support"]["gate"]:
        raise ValueError("Planned comparison unsupported; retain census cell reasons, no fits")
    models, predictions = predict(report["artists"])
    evaluation = evaluate(report["artists"], predictions)
    return {
        "models.json": {
            "methods": list(METHODS),
            "attributes": list(ATTRIBUTES),
            "banks": models,
            "supervised_fits": 20,
            "training_feature_banks": 4,
        },
        "predictions.json": {"artists": predictions},
        "evaluation.json": evaluation,
    }


def run(inputs: Inputs, directory: Path, pin: str, output: Path) -> str:
    """Publish fixed20fit results atomically after all gates and mathematical checks succeed."""
    paths = (*inputs.paths, directory)
    base.destination(output, paths)
    files = compute(inputs, directory, pin)
    seal = {**receipt(inputs, files, "style-prediction-result-v1"), "census_sha256": pin}
    complete = {**files, "receipt.json": seal}
    check_combined(directory, complete)
    return publish(output, complete, paths)


def replay(
    inputs: Inputs, directory: Path, pin: str, output: Path, result_pin: str
) -> dict[str, Any]:
    """Repeat the fixed20fits as separate verification; never try another candidate."""
    files = load_stage(inputs, output, result_pin, result=True)
    seal = base.read(output / "receipt.json")
    if seal["census_sha256"] != pin:
        raise ValueError("Result/census association differs")
    check_combined(directory, {**files, "receipt.json": seal})
    if base.encoded(files) != base.encoded(compute(inputs, directory, pin)):
        raise ValueError("Exact model/prediction/proper-score replay differs")
    return {"status": "passed", "supervised_verification_fits": 20, "training_feature_banks": 4}
