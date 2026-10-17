# ruff: noqa: PLR2004
"""Export portable inference artifacts from verified saved states, without fitting."""

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

from opennoise.ingest.fma_native_bank import COLUMNS, verify_native_bank
from opennoise.ml import fma_nonlinear_experiment as experiment
from opennoise.ml.fma_encoder_bundle import (
    BUNDLE_BYTES,
    BUNDLE_REVISION,
    MAX_OFFSET,
    MAX_QUERIES,
    QUERY_BYTES,
    QUERY_REVISION,
    encoded,
    load_bundle,
    runtime_code,
    schema,
    sha,
    versions,
    write_manifest,
)
from opennoise.ml.fma_fixed_nonlinear import FixedEncoder, transform
from opennoise.pipeline.fma_backend import verify


def fresh_destination(output: Path, inputs: tuple[Path, ...]) -> None:
    """Reject indirection or overlap before touching a closed input artifact."""
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Fresh regular output destination required")
    resolved = output.resolve()
    if any(
        resolved.is_relative_to(p.resolve()) or p.resolve().is_relative_to(resolved) for p in inputs
    ):
        raise ValueError("Output must not overlap input artifacts")


def export_bundle(  # noqa: PLR0913 - explicit externally pinned source roles.
    pipeline: Path,
    inputs: Path,
    plan_sha256: str,
    checkpoint_sha256: str,
    output: Path,
    *,
    arm: str,
    fold: int,
) -> str:
    """Copy one explicit completed encoder and exact common candidate pool."""
    fresh_destination(output, (pipeline,))
    if fold not in range(5):
        raise ValueError("Explicit original inner fold required")
    columns = schema(arm)
    state = verify(pipeline, inputs, plan_sha256, checkpoint_sha256)
    if not state["ready"]:
        raise ValueError("Completed externally pinned backend run required")
    seal_path = pipeline / "model-seal.json"
    seal = experiment.verify_seal(seal_path)
    fresh_destination(output, (pipeline, Path(seal["source"]), Path(seal["bank"])))
    data, full = experiment.load_inputs(seal_path)
    root = pipeline / "experiment"
    fit_receipt = experiment.verify_stage(root, seal_path, fold, arm, "fit")
    score_receipt = experiment.verify_stage(root, seal_path, fold, arm, "score")
    fit = root / f"fold-{fold}" / arm / "fit"
    scored = root / f"fold-{fold}" / arm / "score"
    fit_ids = json.loads((fit / "training.json").read_text())["ids"]
    common = json.loads((scored / "candidates.json").read_text())["common_ids"]
    index = {int(t): i for i, t in enumerate(data.ids)}
    if (
        len(set(common)) != len(common)
        or common != sorted(common)
        or not set(common).issubset(fit_ids)
    ):
        raise ValueError("Saved candidates differ from the fixed fit roster")
    rows = np.array([index[t] for t in common], dtype=np.int64)
    if len(np.unique(data.groups[rows])) != len(rows) or (data.inner_folds[rows] == fold).any():
        raise ValueError("Candidate component/fold isolation differs")
    with np.load(fit / "model.npz", allow_pickle=False) as saved:
        model = FixedEncoder(**{key: saved[key] for key in saved.files})
    features = np.asarray(
        full[rows] if arm.endswith("518") else data.features[rows], dtype=np.float32
    )
    vectors, supported = transform(model, features)
    if not supported.all():
        raise ValueError("Saved candidate pool includes an unsupported row")
    source = Path(seal["source"])
    with zstandard.open(source / "saved-replay/native-folds.jsonl.zst", "rt") as stream:
        ledger = sorted((json.loads(line) for line in stream), key=lambda row: row["track_id"])
    fit_set = set(fit_ids)
    roster = {
        "ids": np.array([r["track_id"] for r in ledger], dtype=np.int64),
        "components": np.array([r["component_id"] or 0 for r in ledger], dtype=np.int64),
        "artist_known": np.array([r["artist_known"] for r in ledger], dtype=bool),
        "outer_fold": np.array([r["fold"] for r in ledger], dtype=np.int8),
        "fit_member": np.array([r["track_id"] in fit_set for r in ledger], dtype=bool),
    }
    bank = Path(seal["bank"])
    bank_receipt = verify_native_bank(bank)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(fit / "model.npz", output / "model.npz")
    np.savez(
        output / "candidates.npz",
        ids=data.ids[rows],
        components=data.groups[rows],
        features=features,
        vectors=vectors,
        labels=np.array(data.labels, dtype=np.int64),
        targets=data.targets[rows].toarray().astype(bool),
    )
    np.savez(
        output / "roster.npz",
        ids=roster["ids"],
        components=roster["components"],
        artist_known=roster["artist_known"],
        outer_fold=roster["outer_fold"],
        fit_member=roster["fit_member"],
    )
    metadata: dict[str, Any] = {
        "revision": BUNDLE_REVISION,
        "namespace": "FMA/native-track-id",
        "arm": arm,
        "fold": fold,
        "columns": columns,
        "versions": versions(),
        "runtime_code": runtime_code(),
        "max_standardized_offset": MAX_OFFSET,
        "musical_relevance_established": False,
        "promoted": False,
        "fitted_or_calibrated": False,
        "bank_receipt_sha256": sha(bank / "projection-receipt.json"),
        "source_manifest_sha256": sha(source / "MANIFEST.json"),
        "source_plan_sha256": plan_sha256,
        "source_checkpoint_sha256": checkpoint_sha256,
        "source_model_seal_sha256": sha(seal_path),
        "source_fit_receipt_sha256": sha(fit / "receipt.json"),
        "source_score_receipt_sha256": sha(scored / "receipt.json"),
        "model_sha256": fit_receipt["files"]["model.npz"]["sha256"],
        "source_candidate_sha256": score_receipt["files"]["candidates.json"]["sha256"],
        "native_observed_sha256": bank_receipt["native_observed_sha256"],
        "native_source_receipt_sha256": bank_receipt["source_receipt_sha256"],
        "license": bank_receipt["license"],
        "attribution": bank_receipt["attribution"],
        "role": "explicit development-fold encoder; not a final full-training serving model",
        "candidate_policy": (
            "exact saved four-arm jointly supported training-component representatives"
        ),
        "query_policy": "exclude identical native ID and entire known identity component",
        "candidate_labels": "observed native source tags; absences are not verified negatives",
    }
    pin = write_manifest(output, metadata, BUNDLE_BYTES, pending=True)
    load_bundle(output, pin, pending=True)
    (output / "manifest.pending").rename(output / "manifest.json")
    return pin


def export_queries(
    bundle: Path, bundle_sha256: str, bank: Path, track_ids: list[int], output: Path
) -> str:
    """Export a small, exact native query-feature pack; no target labels are read."""
    fresh_destination(output, (bundle, bank))
    body, _model, _pool, _roster = load_bundle(bundle, bundle_sha256)
    if (
        not 1 <= len(track_ids) <= MAX_QUERIES
        or len(set(track_ids)) != len(track_ids)
        or any(type(t) is not int or not 1 <= t <= 2**32 - 1 for t in track_ids)
    ):
        raise ValueError("Request requires 1..256 unique positive native uint32 IDs")
    if sha(bank / "projection-receipt.json") != body["bank_receipt_sha256"]:
        raise ValueError("Query bank does not match the encoder's exact source bank")
    receipt = verify_native_bank(bank)
    native_ids = np.fromfile(bank / "track_ids.uint32", dtype="<u4")
    if len(np.unique(native_ids)) != len(native_ids) or (native_ids == 0).any():
        raise ValueError("Native bank ID roster differs")
    raw = np.memmap(
        bank / "features.float32", dtype="<f4", mode="r", shape=(len(native_ids), len(COLUMNS))
    )
    lookup = {int(t): i for i, t in enumerate(native_ids)}
    positions = [receipt["columns"].index(column) for column in body["columns"]]
    features = np.full((len(track_ids), len(positions)), np.nan, dtype=np.float32)
    present = np.array([t in lookup for t in track_ids], dtype=bool)
    for i, identity in enumerate(track_ids):
        if present[i]:
            features[i] = raw[lookup[identity], positions]
    output.mkdir(parents=True, exist_ok=False)
    np.savez(
        output / "queries.npz",
        ids=np.array(track_ids, dtype=np.int64),
        features=features,
        feature_present=present,
    )
    return write_manifest(
        output,
        {
            "revision": QUERY_REVISION,
            "mode": "native-bank",
            "namespace": body["namespace"],
            "columns": body["columns"],
            "bundle_sha256": bundle_sha256,
            "bank_receipt_sha256": body["bank_receipt_sha256"],
            "native_observed_sha256": body["native_observed_sha256"],
            "license": body["license"],
            "attribution": body["attribution"],
            "query_labels_consumed": False,
            "rows": len(track_ids),
        },
        QUERY_BYTES,
    )


def import_queries(
    bundle: Path, bundle_sha256: str, source: Path, source_sha256: str, output: Path
) -> str:
    """Import explicitly supplied native518-compatible rows, not invented FMA identities."""
    fresh_destination(output, (bundle, source))
    body, _model, _pool, roster = load_bundle(bundle, bundle_sha256)
    if (
        any(p.is_symlink() for p in (source, *source.parents))
        or not source.is_file()
        or source.stat().st_size > QUERY_BYTES
        or sha(source) != source_sha256
    ):
        raise ValueError("External query source hash, regularity, or byte guard differs")
    request = json.loads(source.read_text())
    expected = {
        "revision",
        "namespace",
        "columns",
        "extractor",
        "source_manifest_sha256",
        "license",
        "attribution",
        "rows",
    }
    if (
        set(request) != expected
        or request["revision"] != "fma-compatible-external-rows-v1"
        or request["columns"] != schema("linear518")
        or body["columns"] != request["columns"]
        or not isinstance(request["namespace"], str)
        or not 1 <= len(request["namespace"]) <= 128
        or request["namespace"] == body["namespace"]
        or any(
            not isinstance(request[k], str) or not 1 <= len(request[k]) <= 1000
            for k in ("extractor", "license", "attribution")
        )
        or re.fullmatch("[0-9a-f]{64}", request["source_manifest_sha256"]) is None
        or not isinstance(request["rows"], list)
        or not 1 <= len(request["rows"]) <= MAX_QUERIES
    ):
        raise ValueError("External row schema, namespace, or provenance differs")
    ids, components, values, row_hashes = [], [], [], []
    allowed = set(roster["components"].tolist()) - {0}
    for row in request["rows"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "features", "fma_component_id", "identity_evidence_sha256"}
            or type(row["id"]) is not int
            or not 1 <= row["id"] <= 2**32 - 1
            or not isinstance(row["features"], list)
            or len(row["features"]) != 518
            or any(
                v is not None and (type(v) not in (int, float) or not np.isfinite(v))
                for v in row["features"]
            )
        ):
            raise ValueError("External row ID/features differ")
        component = row["fma_component_id"]
        evidence = row["identity_evidence_sha256"]
        if component is None:
            if evidence is not None:
                raise ValueError("Identity evidence without a declared component")
        elif (
            type(component) is not int
            or component not in allowed
            or not isinstance(evidence, str)
            or re.fullmatch("[0-9a-f]{64}", evidence) is None
        ):
            raise ValueError("Caller-declared FMA component requires explicit evidence hash")
        ids.append(row["id"])
        components.append(component or 0)
        values.append([np.nan if value is None else value for value in row["features"]])
        row_hashes.append(hashlib.sha256(encoded(row)).hexdigest())
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate external namespaced identity")
    with np.errstate(over="ignore"):
        features = np.asarray(values, dtype=np.float32)
    if np.isinf(features).any():
        raise ValueError("External feature value overflows declared float32 representation")
    output.mkdir(parents=True, exist_ok=False)
    np.savez(
        output / "queries.npz",
        ids=np.asarray(ids, dtype=np.int64),
        features=features,
        feature_present=np.ones(len(ids), dtype=bool),
        declared_components=np.asarray(components, dtype=np.int64),
    )
    return write_manifest(
        output,
        {
            "revision": QUERY_REVISION,
            "mode": "external-compatible",
            "namespace": request["namespace"],
            "columns": body["columns"],
            "bundle_sha256": bundle_sha256,
            "rows": len(ids),
            "source_file_sha256": source_sha256,
            "source_manifest_sha256": request["source_manifest_sha256"],
            "source_row_sha256": row_hashes,
            "extractor": request["extractor"],
            "license": request["license"],
            "attribution": request["attribution"],
            "identity_evidence_sha256": [
                row["identity_evidence_sha256"] for row in request["rows"]
            ],
            "identity_claims_independently_verified": False,
            "query_labels_consumed": False,
        },
        QUERY_BYTES,
    )
