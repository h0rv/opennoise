# ruff: noqa: PLR2004
"""Portable inference from an explicitly selected frozen FMA experiment encoder."""

import hashlib
import json
import math
import platform
import re
import zipfile
from dataclasses import fields
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse

from opennoise.ingest.fma_features import SELECTED_COLUMNS
from opennoise.ingest.fma_native_bank import COLUMNS
from opennoise.ml.fma_component_embedding import transfer
from opennoise.ml.fma_fixed_nonlinear import FixedEncoder, transform

BUNDLE_REVISION = "fma-portable-encoder-v1"
QUERY_REVISION = "fma-portable-query-features-v1"
RESULT_REVISION = "fma-portable-neighbor-inference-v1"
BUNDLE_BYTES = 10_000_000
QUERY_BYTES = 2_000_000
MAX_QUERIES = 256
MAX_CANDIDATES = 2048
MAX_ROSTER = 110_000
MAX_OFFSET = 12
NEIGHBORS = 10
BUNDLE_FILES = {"model.npz", "candidates.npz", "roster.npz"}
QUERY_FILES = {"queries.npz"}


def sha(path: Path) -> str:
    """Hash bounded or streamed inputs without interpreting them."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def versions() -> dict[str, str]:
    """Declare the numerical environment needed for reproducible inference."""
    return {"python": platform.python_version(), **{n: version(n) for n in ("numpy", "scipy")}}


def runtime_code() -> dict[str, str]:
    """Bind inference semantics, including inherited transform and vote helpers."""
    root = Path(__file__).resolve().parents[3]
    names = (
        "fma_encoder_bundle.py",
        "fma_fixed_nonlinear.py",
        "fma_component_embedding.py",
        "fma_acoustic_baseline.py",
    )
    return {name: sha(root / "src/opennoise/ml" / name) for name in names}


def encoded(value: Any) -> bytes:  # noqa: ANN401 - canonical JSON boundary.
    """Serialize finite, deterministic JSON."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def write_manifest(
    root: Path, metadata: dict[str, Any], limit: int, *, pending: bool = False
) -> str:
    """Publish the commit marker only after the complete closed artifact fits."""
    records: dict[str, Any] = {
        p.name: {"sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(root.iterdir())
    }
    body = encoded({**metadata, "files": records})
    if len(body) > QUERY_BYTES or len(body) + sum(r["bytes"] for r in records.values()) > limit:
        raise ValueError("Portable artifact exceeds its byte guard")
    name = "manifest.pending" if pending else "manifest.json"
    with (root / name).open("xb") as stream:
        stream.write(body)
    return sha(root / name)


def read_artifact(
    root: Path, pin: str, names: set[str], limit: int, *, marker: str = "manifest.json"
) -> dict[str, Any]:
    """Require an external manifest pin, closed inventory, and regular bounded bytes."""
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Symlink artifact root")
    if {p.name for p in root.iterdir()} != names | {marker}:
        raise ValueError("Portable artifact inventory differs")
    total = 0
    for name in names | {marker}:
        p = root / name
        if p.is_symlink() or not p.is_file():
            raise ValueError("Portable artifact must contain regular files")
        total += p.stat().st_size
    if total > limit or (root / marker).stat().st_size > QUERY_BYTES:
        raise ValueError("Portable artifact byte guard exceeded")
    if sha(root / marker) != pin:
        raise ValueError("External manifest hash differs")
    body = json.loads((root / marker).read_text())
    if set(body["files"]) != names:
        raise ValueError("Manifest file roster differs")
    for name in names:
        if body["files"][name] != {
            "sha256": sha(root / name),
            "bytes": (root / name).stat().st_size,
        }:
            raise ValueError("Portable artifact file changed")
    return body


def arrays(path: Path, limit: int) -> dict[str, np.ndarray]:
    """Reject oversized decompressed arrays before NumPy allocation; never allow pickle."""
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (
            len({r.filename for r in members}) != len(members)
            or sum(r.file_size for r in members) > limit
        ):
            raise ValueError("NPZ duplicate entries or decompressed byte guard")
        if any(not r.filename.endswith(".npy") or "/" in r.filename for r in members):
            raise ValueError("Unexpected NPZ member")
        for member in members:
            with archive.open(member) as stream:
                revision = np.lib.format.read_magic(stream)
                if revision == (1, 0):
                    shape, _fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                elif revision == (2, 0):
                    shape, _fortran, dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise ValueError("Unsupported NPY header version")
                if (
                    dtype.kind not in "biuf"
                    or dtype.fields is not None
                    or dtype.subdtype is not None
                    or len(shape) > 2
                    or any(d < 0 or d > limit for d in shape)
                    or math.prod(shape) * dtype.itemsize != member.file_size - stream.tell()
                ):
                    raise ValueError("NPY declared shape/dtype differs from bounded payload")
    with np.load(path, allow_pickle=False) as data:
        return {name: data[name] for name in data.files}


def schema(arm: str) -> list[list[Any]]:
    """Use exact native FMA tuples; AB or other feature spaces are incompatible."""
    if arm not in {"linear44", "rff44", "linear518", "rff518"}:
        raise ValueError("Explicit known encoder arm required")
    return [list(c) for c in (COLUMNS if arm.endswith("518") else SELECTED_COLUMNS)]


def model_from(saved: dict[str, np.ndarray], arm: str) -> FixedEncoder:
    """Validate all serialized state dimensions before calling the existing transform."""
    if set(saved) != {field.name for field in fields(FixedEncoder)}:
        raise ValueError("Encoder field roster differs")
    model = FixedEncoder(**saved)
    width = len(schema(arm))
    if (
        model.center.shape != (width,)
        or model.scale.shape != (width,)
        or model.active_columns.shape != (width,)
        or model.active_columns.dtype != np.bool_
        or not model.active_columns.any()
        or (model.scale[model.active_columns] <= 0).any()
        or (model.scale < 0).any()
    ):
        raise ValueError("Invalid encoder normalization")
    active = int(model.active_columns.sum())
    mapped = 128 if arm.startswith("rff") else active
    outputs = model.encoder.shape[1] if model.encoder.ndim == 2 else -1
    labels = int(model.active_labels.sum())
    if (
        model.active_labels.dtype != np.bool_
        or model.active_labels.ndim != 1
        or len(model.active_labels) > 164
        or model.map_center.shape != (mapped,)
        or model.encoder.shape != (mapped, outputs)
        or not 0 <= outputs <= 8
        or model.coefficients.shape != (mapped, labels)
        or model.target_mean.shape != (labels,)
        or model.frequencies.shape != (active, 128 if arm.startswith("rff") else 0)
        or model.phases.shape != (128 if arm.startswith("rff") else 0,)
        or model.bandwidth.shape != ()
        or model.singular_values.ndim != 1
        or any(a.dtype.kind not in "fib" or not np.isfinite(a).all() for a in saved.values())
    ):
        raise ValueError("Invalid encoder array schema")
    if (arm.startswith("rff") and model.bandwidth <= 0) or (
        arm.startswith("linear") and model.bandwidth != 0
    ):
        raise ValueError("Encoder bandwidth differs from arm")
    return model


def positive_ids(values: np.ndarray) -> bool:
    """Require strictly increasing positive native integer identities."""
    return (
        values.ndim == 1
        and values.dtype.kind in "iu"
        and bool((values > 0).all())
        and bool((values <= 2**32 - 1).all())
        and bool((np.diff(values.astype(np.int64)) > 0).all())
    )


def load_bundle(
    root: Path, pin: str, *, pending: bool = False
) -> tuple[dict[str, Any], FixedEncoder, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Verify a portable bundle without opening its historical source paths."""
    body = read_artifact(
        root,
        pin,
        BUNDLE_FILES,
        BUNDLE_BYTES,
        marker="manifest.pending" if pending else "manifest.json",
    )
    if (
        body["revision"] != BUNDLE_REVISION
        or body["namespace"] != "FMA/native-track-id"
        or body["columns"] != schema(body["arm"])
        or type(body["fold"]) is not int
        or body["fold"] not in range(5)
        or body["versions"] != versions()
        or body["runtime_code"] != runtime_code()
        or body["max_standardized_offset"] != MAX_OFFSET
        or body["musical_relevance_established"] is not False
        or body["promoted"] is not False
    ):
        raise ValueError("Bundle schema, environment, or inference policy differs")
    model = model_from(arrays(root / "model.npz", BUNDLE_BYTES), body["arm"])
    pool = arrays(root / "candidates.npz", BUNDLE_BYTES)
    roster = arrays(root / "roster.npz", BUNDLE_BYTES)
    if set(pool) != {"ids", "components", "features", "vectors", "labels", "targets"}:
        raise ValueError("Candidate fields differ")
    n = len(pool["ids"])
    if (
        not positive_ids(pool["ids"])
        or not 1 <= n <= MAX_CANDIDATES
        or pool["components"].shape != (n,)
        or pool["components"].dtype.kind not in "iu"
        or len(np.unique(pool["components"])) != n
        or (pool["components"] <= 0).any()
        or pool["features"].shape != (n, len(body["columns"]))
        or pool["features"].dtype != np.float32
        or pool["vectors"].shape != (n, model.encoder.shape[1])
        or not positive_ids(pool["labels"])
        or len(pool["labels"]) != len(model.active_labels)
        or pool["targets"].shape != (n, len(pool["labels"]))
        or pool["targets"].dtype != np.bool_
    ):
        raise ValueError("Candidate identities or feature/label schema differs")
    vectors, valid = transform(model, pool["features"])
    if not valid.all() or not np.allclose(vectors, pool["vectors"], atol=1e-12, rtol=1e-12):
        raise ValueError("Saved candidate vectors differ from frozen transform")
    if set(roster) != {"ids", "components", "artist_known", "outer_fold", "fit_member"}:
        raise ValueError("Native roster fields differ")
    count = len(roster["ids"])
    if (
        not positive_ids(roster["ids"])
        or not 1 <= count <= MAX_ROSTER
        or any(a.shape != (count,) for a in roster.values())
        or roster["components"].dtype.kind not in "iu"
        or (roster["components"] < 0).any()
        or roster["artist_known"].dtype != np.bool_
        or roster["fit_member"].dtype != np.bool_
        or roster["outer_fold"].dtype.kind not in "iu"
        or not np.isin(roster["outer_fold"], [-1, 0, 1, 2]).all()
    ):
        raise ValueError("Native query roster schema differs")
    lookup = {int(t): i for i, t in enumerate(roster["ids"])}
    for i, identity in enumerate(pool["ids"]):
        row = lookup.get(int(identity))
        if (
            row is None
            or not roster["fit_member"][row]
            or not roster["artist_known"][row]
            or roster["components"][row] != pool["components"][i]
        ):
            raise ValueError("Candidate does not belong to the exact fit/native component")
    return body, model, pool, roster


def validate_external(query: dict[str, Any], components: np.ndarray, count: int) -> None:
    """Enforce unverified caller provenance at consumption, not merely during import."""

    def hash_string(value: object) -> bool:
        return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None

    if (
        query.get("identity_claims_independently_verified") is not False
        or not hash_string(query.get("source_file_sha256"))
        or not hash_string(query.get("source_manifest_sha256"))
        or any(
            not isinstance(query.get(k), str) or not 1 <= len(query[k]) <= 1000
            for k in ("extractor", "license", "attribution")
        )
        or not isinstance(query.get("source_row_sha256"), list)
        or len(query["source_row_sha256"]) != count
        or not all(hash_string(h) for h in query["source_row_sha256"])
        or not isinstance(query.get("identity_evidence_sha256"), list)
        or len(query["identity_evidence_sha256"]) != count
    ):
        raise ValueError("External query provenance is missing or misrepresented")
    for component, evidence in zip(components, query["identity_evidence_sha256"], strict=True):
        if (component == 0 and evidence is not None) or (
            component != 0 and not hash_string(evidence)
        ):
            raise ValueError("Declared component evidence is missing or misaligned")


def infer(  # noqa: C901, PLR0912, PLR0915 - explicit identity modes share one inference boundary.
    bundle: Path,
    bundle_sha256: str,
    queries: Path,
    query_sha256: str,
    *,
    allow_unverified_neighbors: bool = False,
) -> list[dict[str, Any]]:
    """Infer compatible features; separate embedding support from identity-safe retrieval."""
    if type(allow_unverified_neighbors) is not bool:
        raise ValueError("Explicit boolean unverified-neighbor policy required")
    body, model, pool, roster = load_bundle(bundle, bundle_sha256)
    query = read_artifact(queries, query_sha256, QUERY_FILES, QUERY_BYTES)
    mode = query.get("mode")
    external = mode == "external-compatible"
    if (
        query["revision"] != QUERY_REVISION
        or query["bundle_sha256"] != bundle_sha256
        or query["columns"] != body["columns"]
        or mode not in {"native-bank", "external-compatible"}
        or query.get("query_labels_consumed") is not False
    ):
        raise ValueError("Query feature schema or identity contract differs")
    if not external and (
        query["namespace"] != body["namespace"]
        or query["bank_receipt_sha256"] != body["bank_receipt_sha256"]
    ):
        raise ValueError("Native source bank differs")
    if external and (
        not isinstance(query["namespace"], str)
        or not query["namespace"]
        or query["namespace"] == body["namespace"]
        or len(body["columns"]) != 518
    ):
        raise ValueError(
            "External features require a distinct explicit namespace and native518 schema"
        )
    q = arrays(queries / "queries.npz", QUERY_BYTES)
    expected = {"ids", "features", "feature_present"} | (
        {"declared_components"} if external else set()
    )
    if set(q) != expected:
        raise ValueError("Query fields differ; labels are not accepted")
    n = len(q["ids"])
    if (
        not 1 <= n <= MAX_QUERIES
        or q["ids"].ndim != 1
        or q["ids"].dtype.kind not in "iu"
        or len(np.unique(q["ids"])) != n
        or (q["ids"] <= 0).any()
        or (q["ids"] > 2**32 - 1).any()
        or q["features"].shape != (n, len(body["columns"]))
        or q["features"].dtype != np.float32
        or q["feature_present"].shape != (n,)
        or q["feature_present"].dtype != np.bool_
        or query["rows"] != n
    ):
        raise ValueError("Query identities or feature shape differs")
    if external and (
        q["declared_components"].shape != (n,)
        or q["declared_components"].dtype.kind not in "iu"
        or (q["declared_components"] < 0).any()
        or not set(q["declared_components"].tolist()).issubset({0, *roster["components"].tolist()})
    ):
        raise ValueError("External declared components must name existing FMA components")
    if external:
        validate_external(query, q["declared_components"], n)
    vectors, supported = transform(model, q["features"])
    known = {int(t): i for i, t in enumerate(roster["ids"])}
    targets = sparse.csr_matrix(pool["targets"])
    outputs = []
    for index, identity in enumerate(q["ids"]):
        row = None if external else known.get(int(identity))
        component = (
            (int(q["declared_components"][index]) or None)
            if external
            else (int(roster["components"][row]) or None if row is not None else None)
        )
        x = q["features"][index]
        embedding_reason = (
            "missing_feature_row"
            if not q["feature_present"][index]
            else "nonfinite_descriptors"
            if not np.isfinite(x).all()
            else "outside_training_support"
            if (
                np.abs(
                    (x[model.active_columns] - model.center[model.active_columns])
                    / model.scale[model.active_columns]
                )
                > MAX_OFFSET
            ).any()
            else "zero_encoded_norm"
            if not supported[index]
            else None
        )
        identity_reason = (
            "neighbor_identity_unverified"
            if external and component is None
            else None
            if external
            else "unknown_native_track_id"
            if row is None
            else "unresolved_artist"
            if not roster["artist_known"][row]
            else "unresolved_component"
            if component is None
            else None
        )
        if external and component is None and allow_unverified_neighbors:
            identity_reason = None
        neighbor_reason = embedding_reason or identity_reason
        neighbors, distances, ranking = [], [], []
        if neighbor_reason is None:
            mask = pool["components"] != component
            if not external:
                mask &= pool["ids"] != identity
            eligible = np.flatnonzero(mask)
            if not len(eligible):
                neighbor_reason = "no_cross_component_candidates"
            else:
                scores = pool["vectors"][eligible] @ vectors[index]
                order = np.lexsort((pool["ids"][eligible], -scores))[:NEIGHBORS]
                selected = eligible[order]
                neighbors = pool["ids"][selected].tolist()
                distances = (1 - scores[order]).tolist()
                ranking = pool["labels"][transfer(selected.tolist(), targets)].tolist()
        outputs.append(
            {
                "identity": {"namespace": query["namespace"], "id": int(identity)},
                "component_id": component,
                "component_exclusion_verified": not external
                and row is not None
                and component is not None
                and bool(roster["artist_known"][row]),
                "identity_status": (
                    "caller_declared_component" if component is not None else "unverified"
                )
                if external
                else "native_roster"
                if row is not None
                else "unknown_native_id",
                "original_outer_fold": int(roster["outer_fold"][row]) if row is not None else None,
                "model_fit_member": bool(roster["fit_member"][row]) if row is not None else None,
                "embedding_reason": embedding_reason,
                "neighbor_reason": neighbor_reason,
                "vector": vectors[index].tolist() if embedding_reason is None else None,
                "neighbor_ids": neighbors,
                "neighbor_namespace": body["namespace"],
                "cosine_distances": distances,
                "ranked_source_genre_ids": ranking,
                "provenance": {
                    "revision": RESULT_REVISION,
                    "bundle_sha256": bundle_sha256,
                    "query_sha256": query_sha256,
                    "arm": body["arm"],
                    "fold": body["fold"],
                    "allow_unverified_neighbors": allow_unverified_neighbors,
                    "query_labels_consumed": False,
                    "fitted_or_calibrated": False,
                    "musical_relevance_established": False,
                },
            }
        )
    if len(encoded(outputs)) > QUERY_BYTES:
        raise ValueError("Inference output exceeds 2 MB")
    return outputs
