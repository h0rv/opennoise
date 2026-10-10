"""Separately frozen fresh-source FMA descriptor map; no historical receipt substitution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import _json_rows
from opennoise.ml.fma_sonic_map import (
    DIMENSIONS,
    FEATURE_SHA,
    FOLD_SHA,
    ID_SHA,
    MAX_OUTPUT_BYTES,
    MODEL_SHA,
    derive_loaded_map,
)

REVISION = "fma-fresh-descriptor-pca-v1"
LIMITS = {"wall_seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": MAX_OUTPUT_BYTES}
PROTOCOL = {
    "revision": REVISION,
    "dimensions": DIMENSIONS,
    "limits": LIMITS,
    "fit": "original fold0 known-artist finite descriptors only; original frozen normalization",
    "genres": "fold0 source-positive centroid; minimum five finite training positives",
    "artists": "mean of all finite native associated tracks; display context only, not fitting",
    "axes": "symmetric covariance PCA; descending eigenvalue; largest loading positive",
    "sensitivity": "8 SHA256 fma-sonic-pca-context-v1 NUL component buckets; leave one out",
    "musical_validation_established": False,
    "audio_used": False,
    "public_product_promotion_authorized": False,
}
INPUTS = (
    "metadata/corpus-receipt.json",
    "metadata/artists.jsonl.zst",
    "metadata/genres.jsonl.zst",
    "metadata/tracks.jsonl.zst",
    "metadata-source/source-receipt.json",
    "feature-source/source-receipt.json",
    "feature-source/projection/projection-receipt.json",
    "feature-source/projection/features.float32",
    "feature-source/projection/track_ids.uint32",
    "model/model.npz",
    "model/native-folds.jsonl.zst",
    "model/evaluation.json",
    "native-feature-audit.json",
    "native-metadata-audit.json",
    "independent-model-replay.json",
)


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked fresh map path")


def _binding(path: Path) -> dict[str, Any]:
    _safe(path)
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def _json(path: Path) -> dict[str, Any]:
    _safe(path)
    if path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("map JSON exceeds input bound")
    return json.loads(path.read_bytes())


def _bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def freeze_fresh_map(root: Path, declaration: Path) -> dict[str, Any]:
    """Seal exact fresh custody before fitting; never modify the historical declaration."""
    result = {
        "protocol": PROTOCOL,
        "inputs": {name: _binding(root / name) for name in INPUTS},
        "implementation": {
            name: _binding(Path(__file__).with_name(name))
            for name in ("fma_fresh_map.py", "fma_sonic_map.py")
        },
    }
    _safe(declaration)
    declaration.parent.mkdir(parents=True, exist_ok=True)
    with declaration.open("xb") as stream:
        stream.write(_bytes(result))
    return result


def _load(  # noqa: C901, PLR0912 -- distinct native/model custody guards.
    root: Path, declaration: Path
) -> tuple[
    dict[int, tuple[int, bool, int | None, int | None]],
    dict[str, np.ndarray],
    np.ndarray,
    np.ndarray,
    dict[str, str],
]:
    frozen = _json(declaration)
    if frozen["protocol"] != PROTOCOL or set(frozen["inputs"]) != set(INPUTS):
        raise ValueError("fresh map declaration protocol differs")
    if frozen["implementation"] != {
        name: _binding(Path(__file__).with_name(name))
        for name in ("fma_fresh_map.py", "fma_sonic_map.py")
    }:
        raise ValueError("frozen map implementation differs")
    for name, binding in frozen["inputs"].items():
        if _binding(root / name) != binding:
            raise ValueError("fresh map frozen input differs")
    expected = {
        "model/model.npz": MODEL_SHA,
        "model/native-folds.jsonl.zst": FOLD_SHA,
        "feature-source/projection/features.float32": FEATURE_SHA,
        "feature-source/projection/track_ids.uint32": ID_SHA,
    }
    if any(frozen["inputs"][name]["sha256"] != digest for name, digest in expected.items()):
        raise ValueError("original 44-D model, split or descriptors differ")
    metadata = _json(root / "metadata/corpus-receipt.json")
    features = _json(root / "feature-source/projection/projection-receipt.json")
    evaluation = _json(root / "model/evaluation.json")
    if (
        metadata["metadata_license"] != "CC-BY-4.0"
        or metadata["audio_downloaded"] is not False
        or features["license"] != "CC-BY-4.0"
        or features["audio_downloaded"] is not False
        or features["echo_nest_consumed"] is not False
        or len(features["columns"]) != DIMENSIONS
    ):
        raise ValueError("fresh metadata or numeric descriptor scope differs")
    for receipt, source in ((metadata, "metadata-source"), (features, "feature-source")):
        if (
            receipt["source_receipt_sha256"]
            != frozen["inputs"][f"{source}/source-receipt.json"]["sha256"]
        ):
            raise ValueError("fresh native source custody differs")
    for key, path in (
        ("metadata_receipt_sha256", "metadata/corpus-receipt.json"),
        ("feature_receipt_sha256", "feature-source/projection/projection-receipt.json"),
    ):
        if evaluation[key] != frozen["inputs"][path]["sha256"]:
            raise ValueError("original model fresh provenance differs")
    for item in metadata["files"].values():
        if _binding(root / "metadata" / item["path"]) != {
            "sha256": item["sha256"],
            "bytes": item["bytes"],
        }:
            raise ValueError("native metadata projection differs")
    folds = {}
    for row in _json_rows(root / "model/native-folds.jsonl.zst"):
        identity = row["track_id"]
        if identity in folds:
            raise ValueError("duplicate fold identity")
        folds[identity] = (row["fold"], row["artist_known"], row["artist_id"], row["component_id"])
    n = features["rows"]
    base = root / "feature-source/projection"
    ids = np.memmap(base / "track_ids.uint32", dtype="<u4", mode="r", shape=(n,))
    values = np.memmap(base / "features.float32", dtype="<f4", mode="r", shape=(n, DIMENSIONS))
    with np.load(root / "model/model.npz", allow_pickle=False) as model_file:
        model = {key: model_file[key].copy() for key in ("center", "scale", "active_columns")}
    if (
        model["center"].shape != (DIMENSIONS,)
        or not model["active_columns"].all()
        or not np.isfinite(model["center"]).all()
        or not np.isfinite(model["scale"]).all()
        or not (model["scale"] > 0).all()
    ):
        raise ValueError("invalid original normalization")
    return (
        folds,
        model,
        ids,
        values,
        {name: value["sha256"] for name, value in frozen["inputs"].items()},
    )


def derive_fresh_map(root: Path, declaration: Path) -> dict[str, Any]:
    """Fit training-only PCA under independently frozen fresh-source custody."""
    result = derive_loaded_map(
        root / "metadata", root / "feature-source/projection", _load(root, declaration)
    )
    result["revision"] = REVISION
    result["namespace"] = "native-fma-fresh-descriptor-pca-v1"
    return result


def build_fresh_map(root: Path, declaration: Path, output: Path) -> dict[str, Any]:
    """Write fresh coordinates and exact closed receipt under the unchanged output budget."""
    _safe(output)
    if output.exists():
        raise ValueError("fresh map output exists")
    coordinates = derive_fresh_map(root, declaration)
    blobs = {
        "coordinates.json": _bytes(coordinates),
        "declaration.json": declaration.read_bytes(),
        "fma_fresh_map.py": Path(__file__).read_bytes(),
        "fma_sonic_map.py": Path(__file__).with_name("fma_sonic_map.py").read_bytes(),
    }

    files = {
        name: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        for name, body in blobs.items()
    }
    receipt = {
        "revision": REVISION,
        "protocol": PROTOCOL,
        "files": files,
        "source": coordinates["source"],
        "declaration_sha256": files["declaration.json"]["sha256"],
    }
    blobs["receipt.json"] = _bytes(receipt)
    if sum(map(len, blobs.values())) > MAX_OUTPUT_BYTES:
        raise ValueError("fresh map output exceeds budget")
    output.mkdir(parents=True)
    for name, body in blobs.items():
        (output / name).write_bytes(body)
    validate_fresh_map(output)
    return {
        "denominators": coordinates["denominators"],
        "pca_training": coordinates["pca_training"],
        "receipt": _binding(output / "receipt.json"),
    }


def validate_fresh_map(output: Path) -> dict[str, Any]:
    """Verify closed artifacts, source bindings and semantic role before an offline export."""
    _safe(output)
    receipt = _json(output / "receipt.json")
    expected = {"coordinates.json", "declaration.json", "fma_fresh_map.py", "fma_sonic_map.py"}
    if (
        receipt["revision"] != REVISION
        or receipt["protocol"] != PROTOCOL
        or set(receipt["files"]) != expected
        or {p.name for p in output.iterdir()} != expected | {"receipt.json"}
    ):
        raise ValueError("fresh map protocol or closed inventory differs")
    for name, item in receipt["files"].items():
        if _binding(output / name) != item:
            raise ValueError("fresh map artifact bytes differ")
    if sum(p.stat().st_size for p in output.iterdir()) > MAX_OUTPUT_BYTES:
        raise ValueError("fresh map output exceeds budget")
    declaration = _json(output / "declaration.json")
    result = _json(output / "coordinates.json")
    if (
        declaration["implementation"]
        != {name: receipt["files"][name] for name in ("fma_fresh_map.py", "fma_sonic_map.py")}
        or declaration["protocol"] != PROTOCOL
        or receipt["declaration_sha256"] != receipt["files"]["declaration.json"]["sha256"]
        or result["revision"] != REVISION
        or result["namespace"] != "native-fma-fresh-descriptor-pca-v1"
        or result["source"] != receipt["source"]
        or result["source"] != {k: v["sha256"] for k, v in declaration["inputs"].items()}
        or result["metadata_license"] != "CC-BY-4.0"
        or result["audio_used"] is not False
        or result["musical_axis_semantics"] is not None
        or result["artist_genres_inferred"] is not False
        or result["musical_validation_established"] is not False
        or result["public_product_promotion_authorized"] is not False
        or result["pca_training"]["fit_heldout_tracks"] != 0
    ):
        raise ValueError("fresh map source role differs")
    return result


def replay_fresh_map(root: Path, output: Path) -> dict[str, Any]:
    """Recompute every coordinate and sensitivity diagnostic from frozen fresh inputs."""
    actual = validate_fresh_map(output)
    if derive_fresh_map(root, output / "declaration.json") != actual:
        raise ValueError("fresh numerical replay differs")
    return {"all_source_coordinates_replayed": True, "denominators": actual["denominators"]}
