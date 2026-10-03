"""Train-only native FMA descriptor PCA with explicit source-context coordinates.

Mathematical axes do not reproduce Every Noise's musical meanings. Genre
centroids use only training source labels; artist coordinates assert no genres.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import _json_rows
from opennoise.ml.fma_saved_replay import replay_saved_pack

REVISION = "fma-sonic-pca-context-v1"
DECLARATION_SHA = "91f31dc04859203a5a56dccb1d093f414201f89f379702f62b565bf006bde246"
MODEL_SHA = "eb5e8091837dff54c1d373c660f7c722ad5f8a7eb6393493f972e2e7878bbb38"
FOLD_SHA = "a43584aeb88c874576b2e7a84a25a2ebd1908385935f1c2a20b84e1273642ea7"
FEATURE_SHA = "b427d29b55b9b27c9e38b0aae635478dbebae5dcb381f00e00a9fcadf70032d4"
ID_SHA = "8fb77ce50f3da09b7fb7c04bfc21948ef72e3dd50dbb63cd082291d75b180c07"
MIN_GENRE_SUPPORT = 5
BATCH = 128
BUCKETS = 8
DIMENSIONS = 44
MIN_PCA_ROWS = 2
MAX_OUTPUT_BYTES = 10_000_000


@dataclass
class Moments:
    """Mergeable numerically stable centered moments; rows need not be held in memory."""

    count: int = 0
    mean: np.ndarray = field(default_factory=lambda: np.zeros(DIMENSIONS))
    scatter: np.ndarray = field(default_factory=lambda: np.zeros((DIMENSIONS, DIMENSIONS)))

    def add(self, values: np.ndarray) -> None:
        """Combine a finite batch with the exact between-mean correction."""
        if not len(values):
            return
        if values.shape[1] != len(self.mean) or not np.isfinite(values).all():
            raise ValueError("PCA moments require finite correctly shaped descriptors")
        mean = values.mean(axis=0)
        centered = values - mean
        self.merge(Moments(len(values), mean, centered.T @ centered))

    def merge(self, other: Moments) -> None:
        """Preserve centered covariance when combining differently distributed source groups."""
        if not other.count:
            return
        if not self.count:
            self.count, self.mean, self.scatter = (
                other.count,
                other.mean.copy(),
                other.scatter.copy(),
            )
            return
        total = self.count + other.count
        delta = other.mean - self.mean
        self.scatter += other.scatter + np.outer(delta, delta) * self.count * other.count / total
        self.mean += delta * other.count / total
        self.count = total


def pca(moments: Moments) -> tuple[np.ndarray, np.ndarray]:
    """Order symmetric covariance eigenvectors and canonically orient mathematical axes."""
    if moments.count < MIN_PCA_ROWS:
        raise ValueError("PCA requires at least two finite training rows")
    covariance = moments.scatter / (moments.count - 1)
    eigenvalues, eigenvectors = np.linalg.eigh((covariance + covariance.T) / 2)
    order = np.argsort(-eigenvalues, kind="stable")
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    for column in range(eigenvectors.shape[1]):
        vector = eigenvectors[:, column]
        if vector[np.argmax(np.abs(vector))] < 0:
            eigenvectors[:, column] *= -1
    return eigenvalues, eigenvectors


def component_bucket(component: int | None) -> int:
    """Hash native connected components before descriptors or labels influence bucket membership."""
    if type(component) is not int or component <= 0:
        raise ValueError("training PCA requires a known native component")
    return (
        int.from_bytes(hashlib.sha256(f"{REVISION}\0{component}".encode()).digest(), "big")
        % BUCKETS
    )


def _load_inputs(  # noqa: C901 - immutable model/source identities and distinct license custody guards.
    metadata: Path, features: Path, saved: Path
) -> tuple[
    dict[int, tuple[int, bool, int | None, int | None]],
    dict[str, np.ndarray],
    np.ndarray,
    np.ndarray,
    dict[str, str],
]:
    replay_saved_pack(saved)
    if (
        sha256_file(saved / "model.npz")[0] != MODEL_SHA
        or sha256_file(saved / "native-folds.jsonl.zst")[0] != FOLD_SHA
    ):
        raise ValueError("frozen training model or component split differs")
    for name, expected in (("features.float32", FEATURE_SHA), ("track_ids.uint32", ID_SHA)):
        if (features / name).is_symlink() or sha256_file(features / name)[0] != expected:
            raise ValueError("native descriptor projection differs")
    feature_receipt = json.loads((features / "projection-receipt.json").read_bytes())
    original_features = json.loads((saved / "feature-projection-receipt.json").read_bytes())
    for key in (
        "files",
        "columns",
        "license",
        "rows",
        "source_receipt_sha256",
        "audio_downloaded",
        "echo_nest_consumed",
        "native_observed_sha256",
    ):
        if feature_receipt[key] != original_features[key]:
            raise ValueError("native feature provenance or descriptor labels differ")
    if (
        feature_receipt["license"] != "CC-BY-4.0"
        or feature_receipt["audio_downloaded"] is not False
        or feature_receipt["echo_nest_consumed"] is not False
    ):
        raise ValueError("native feature source is outside approved metadata scope")
    receipt = json.loads((metadata / "corpus-receipt.json").read_bytes())
    pinned = json.loads((saved / "metadata-projection-receipt.json").read_bytes())
    if receipt != pinned:
        raise ValueError("native metadata projection receipt differs from original model input")
    for item in receipt["files"].values():
        if sha256_file(metadata / item["path"]) != (item["sha256"], item["bytes"]):
            raise ValueError("native metadata projection bytes differ")
    fold_rows = {}
    for row in _json_rows(saved / "native-folds.jsonl.zst"):
        if row["track_id"] in fold_rows:
            raise ValueError("duplicate native component ledger track")
        fold_rows[row["track_id"]] = (
            row["fold"],
            row["artist_known"],
            row["artist_id"],
            row["component_id"],
        )
    n = (features / "track_ids.uint32").stat().st_size // 4
    identities = np.memmap(features / "track_ids.uint32", dtype="<u4", mode="r", shape=(n,))
    values = np.memmap(features / "features.float32", dtype="<f4", mode="r", shape=(n, DIMENSIONS))
    with np.load(saved / "model.npz") as source:
        model = {name: source[name].copy() for name in ("center", "scale", "active_columns")}
    if not model["active_columns"].all() or len(model["center"]) != DIMENSIONS:
        raise ValueError("PCA declaration requires the original 44 active native descriptors")
    binding = {
        "metadata_receipt_sha256": sha256_file(metadata / "corpus-receipt.json")[0],
        "feature_receipt_sha256": sha256_file(features / "projection-receipt.json")[0],
        "model_sha256": MODEL_SHA,
        "fold_sha256": FOLD_SHA,
        "feature_values_sha256": FEATURE_SHA,
        "track_ids_sha256": ID_SHA,
    }
    return fold_rows, model, identities, values, binding


def derive_map(metadata: Path, features: Path, saved: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - explicit independent source domains and counts.
    """Stream every source row, fit training covariance, retain every output identity."""
    folds, model, identities, values, bindings = _load_inputs(metadata, features, saved)
    total = Moments()
    buckets = [Moments() for _ in range(BUCKETS)]
    for start in range(0, len(identities), BATCH):
        ids = identities[start : start + BATCH]
        batch = np.asarray(values[start : start + BATCH], dtype=np.float64)
        good = np.isfinite(batch).all(axis=1)
        training = (
            np.array([folds[int(identity)][0] == 0 and folds[int(identity)][1] for identity in ids])
            & good
        )
        x = (batch[training] - model["center"]) / model["scale"]
        total.add(x)
        bucket_ids = np.array(
            [component_bucket(folds[int(identity)][3]) for identity in ids[training]]
        )
        for bucket, moment in enumerate(buckets):
            moment.add(x[bucket_ids == bucket])
    eigenvalues, axes = pca(total)
    projection = axes[:, :2]
    track_coordinates: dict[int, tuple[float, float]] = {}
    artist_sums: dict[int, np.ndarray] = {}
    artist_counts: dict[int, int] = {}
    for start in range(0, len(identities), BATCH):
        batch = np.asarray(values[start : start + BATCH], dtype=np.float64)
        good = np.isfinite(batch).all(axis=1)
        ids = identities[start : start + BATCH][good]
        xy = (((batch[good] - model["center"]) / model["scale"]) - total.mean) @ projection
        for identity, coordinate in zip(ids, xy, strict=True):
            native = int(identity)
            track_coordinates[native] = (float(coordinate[0]), float(coordinate[1]))
            _fold, known, artist, _component = folds[native]
            if known:
                if artist is None:
                    raise ValueError("known artist track has no native identity")
                artist_sums.setdefault(artist, np.zeros(2))[:] += coordinate
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
    artists = []
    for row in _json_rows(metadata / "artists.jsonl.zst"):
        identity = row["artist_id"]
        count = artist_counts.get(identity, 0)
        artists.append(
            {
                "artist_id": identity,
                "name": row["name"],
                "feature_tracks": count,
                "position": (artist_sums[identity] / count).tolist() if count else None,
                "abstention": None if count else "no_finite_native_track_descriptors",
                "scope": "native_artist_descriptor_context_not_artist_genre",
            }
        )
    genres = {row["genre_id"]: row for row in _json_rows(metadata / "genres.jsonl.zst")}
    genre_sums = {identity: np.zeros(2) for identity in genres}
    genre_counts: dict[int, int] = {}
    raw_tracks = unlabeled = missing = unresolved = 0
    for row in _json_rows(metadata / "tracks.jsonl.zst"):
        identity = row["track_id"]
        raw_tracks += 1
        unlabeled += not row["genre_ids"]
        missing += identity not in track_coordinates
        fold, known, _artist, _component = folds[identity]
        unresolved += not known
        if fold == 0 and known and identity in track_coordinates:
            for label in row["genre_ids"] or []:
                genre_sums[label] += track_coordinates[identity]
                genre_counts[label] = genre_counts.get(label, 0) + 1
    genre_rows = []
    for identity, row in sorted(genres.items()):
        count = genre_counts.get(identity, 0)
        genre_rows.append(
            {
                "genre_id": identity,
                "name": row["title"],
                "training_feature_positives": count,
                "position": (genre_sums[identity] / count).tolist()
                if count >= MIN_GENRE_SUPPORT
                else None,
                "abstention": None
                if count >= MIN_GENRE_SUPPORT
                else "below_five_training_feature_positives",
                "scope": "training_source_track_annotation_centroid_not_musical_genre_truth",
            }
        )
    sensitivity = []
    for omitted in range(BUCKETS):
        reduced = Moments()
        for index, moments in enumerate(buckets):
            if index != omitted:
                reduced.merge(moments)
        reduced_eigenvalues, reduced_axes = pca(reduced)
        singular = np.linalg.svd(projection.T @ reduced_axes[:, :2], compute_uv=False)
        angles = np.degrees(np.arccos(np.clip(singular, -1, 1)))
        sensitivity.append(
            {
                "omitted_bucket": omitted,
                "omitted_training_tracks": buckets[omitted].count,
                "retained_training_tracks": reduced.count,
                "principal_angles_degrees": angles.tolist(),
                "explained_variance_first_two": float(
                    reduced_eigenvalues[:2].sum() / reduced_eigenvalues.sum()
                ),
            }
        )
    feature_receipt = json.loads((features / "projection-receipt.json").read_bytes())
    return {
        "revision": REVISION,
        "namespace": "native-fma-sonic-pca-context-v1",
        "source": bindings,
        "metadata_license": "CC-BY-4.0",
        "audio_used": False,
        "musical_axis_semantics": None,
        "artist_genres_inferred": False,
        "musical_validation_established": False,
        "public_product_promotion_authorized": False,
        "axes": [
            {
                "name": f"PC{index + 1}",
                "eigenvalue": float(eigenvalues[index]),
                "explained_variance_fraction": float(eigenvalues[index] / eigenvalues.sum()),
                "loadings": [
                    {"native_column": column, "loading": float(value)}
                    for column, value in zip(
                        feature_receipt["columns"], axes[:, index], strict=True
                    )
                ],
            }
            for index in range(2)
        ],
        "pca_training": {
            "finite_training_tracks": total.count,
            "standardized_center": total.mean.tolist(),
            "eigenvalues": eigenvalues.tolist(),
            "fit_heldout_tracks": 0,
        },
        "denominators": {
            "raw_tracks": raw_tracks,
            "unlabeled_tracks": unlabeled,
            "unresolved_artist_tracks": unresolved,
            "missing_finite_descriptors": missing,
            "native_artists": len(artists),
            "native_genres": len(genre_rows),
            "positioned_artists": sum(row["position"] is not None for row in artists),
            "positioned_genres": sum(row["position"] is not None for row in genre_rows),
        },
        "component_bucket_sensitivity": sensitivity,
        "stability_scope": (
            "leave-one-training-component-bucket-out subspace sensitivity; not bootstrap confidence"
        ),
        "artists": artists,
        "genres": genre_rows,
    }


def build_map(
    metadata: Path, features: Path, saved: Path, declaration: Path, output: Path
) -> dict[str, Any]:
    """Write a fresh source map, loading receipt and static view."""
    if sha256_file(declaration)[0] != DECLARATION_SHA:
        raise ValueError("frozen PCA declaration differs")
    if output.exists():
        raise ValueError("map output must be fresh")
    result = derive_map(metadata, features, saved)
    output.mkdir(parents=True)
    (output / "coordinates.json").write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    )
    (output / "declaration.json").write_bytes(declaration.read_bytes())
    (output / "fma_sonic_map.py").write_bytes(Path(__file__).read_bytes())
    assets = Path(__file__).resolve().parents[1] / "static"
    for name in ("fma-sonic-map.html", "fma-sonic-map.mjs", "fma-sonic-map.css"):
        (output / ("index.html" if name.endswith(".html") else name)).write_bytes(
            (assets / name).read_bytes()
        )
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(output.iterdir()):
        digest, size = sha256_file(path)
        files[path.name] = {"sha256": digest, "bytes": size}
    receipt = {
        "revision": REVISION,
        "files": files,
        "source": result["source"],
        "declaration_sha256": DECLARATION_SHA,
        "license": "CC-BY-4.0",
        "musical_validation_established": False,
    }
    if sum(item["bytes"] for item in files.values()) > MAX_OUTPUT_BYTES:
        raise ValueError("map output exceeds frozen byte budget")
    (output / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return {
        "receipt_sha256": sha256_file(output / "receipt.json")[0],
        "denominators": result["denominators"],
        "pca_training_tracks": result["pca_training"]["finite_training_tracks"],
        "explained_variance_first_two": sum(
            axis["explained_variance_fraction"] for axis in result["axes"]
        ),
        "component_bucket_sensitivity": result["component_bucket_sensitivity"],
    }


def replay_map(metadata: Path, features: Path, saved: Path, output: Path) -> dict[str, Any]:
    """Refit prespecified training covariance and replay every source coordinate."""
    receipt = json.loads((output / "receipt.json").read_bytes())
    expected_files = {
        "coordinates.json",
        "declaration.json",
        "fma_sonic_map.py",
        "index.html",
        "fma-sonic-map.mjs",
        "fma-sonic-map.css",
    }
    if receipt["license"] != "CC-BY-4.0" or receipt["musical_validation_established"] is not False:
        raise ValueError("map source role or musical promotion differs")
    if set(receipt["files"]) != expected_files or receipt["declaration_sha256"] != DECLARATION_SHA:
        raise ValueError("map receipt boundary differs")
    if {path.name for path in output.iterdir()} != expected_files | {"receipt.json"}:
        raise ValueError("map file set differs")
    for name, item in receipt["files"].items():
        path = output / name
        if path.is_symlink() or sha256_file(path) != (item["sha256"], item["bytes"]):
            raise ValueError("map byte binding differs")
    if sha256_file(output / "declaration.json")[0] != DECLARATION_SHA:
        raise ValueError("map declaration bytes differ")
    actual = derive_map(metadata, features, saved)
    if actual != json.loads((output / "coordinates.json").read_bytes()):
        raise ValueError("source coordinate replay differs")
    return {
        "all_source_coordinates_replayed": True,
        "source": actual["source"],
        "denominators": actual["denominators"],
        "fit_heldout_tracks": 0,
        "musical_validation_established": False,
    }
