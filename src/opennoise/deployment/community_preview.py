"""Export verified emergent music communities as a local static explorer."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas

_COSINE_EPSILON = 1e-10
_STATIC = Path(__file__).resolve().parents[1] / "static"


def verified_receipt(directory: Path, name: str) -> dict[str, Any]:
    """Verify receipt identity and every declared relative artifact before use."""
    receipt = json.loads((directory / name).read_bytes())
    expected = receipt.pop("output_sha256")
    if sha256_json(receipt) != expected:
        raise ValueError("receipt identity mismatch")
    receipt["output_sha256"] = expected
    for relative, binding in receipt["files"].items():
        path = directory / relative
        if Path(relative).is_absolute() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("artifact path escapes receipt directory")
        if path.is_symlink() or not path.is_file():
            raise ValueError("artifact is absent or symlinked")
        if sha256_file(path)[0] != binding["sha256"] or path.stat().st_size != binding["bytes"]:
            raise ValueError("artifact byte binding mismatch")
    return receipt


def community_positions(model: dict[str, Any], directory: Path) -> dict[str, tuple[float, float]]:
    """Place sibling communities using musical centroid cosine, without labels."""
    identities = json.loads((directory / "topic-feature-identities.json").read_bytes())
    matrix = sparse.load_npz(directory / "topic-centroids.npz").tocsr()
    ids = identities["community_ids"]
    features = identities["features"]
    if matrix.shape != (len(ids), len(features)) or len(set(ids)) != len(ids):
        raise ValueError("centroid dimensions or identities differ")
    if not np.isfinite(matrix.data).all() or (matrix.data < 0).any():
        raise ValueError("invalid centroid values")
    columns = [
        i
        for i, row in enumerate(features)
        if row["namespace"] in ("artist_genre", "artist_tag", "release_genre", "release_tag")
    ]
    musical = matrix[:, columns]
    norms = np.sqrt(np.asarray(musical.multiply(musical).sum(axis=1)).ravel())
    musical = sparse.diags(np.divide(1, norms, out=np.zeros_like(norms), where=norms > 0)) @ musical
    similarity = (musical @ musical.T).toarray()
    rows = {row["id"]: row for row in model["communities"]}
    if set(rows) != set(ids):
        raise ValueError("community and centroid identities differ")
    groups = defaultdict(list)
    for index, key in enumerate(ids):
        row = rows[key]
        groups[row["level"], row["parent_id"]].append(index)
    positions = {}
    for siblings in groups.values():
        # Abstain every member of a repeated musical-centroid equivalence class.
        # Removing only duplicate-pair edges still separates twins via a third node.
        duplicates = {
            left
            for left in siblings
            for right in siblings
            if left != right and abs(float(similarity[left, right]) - 1) <= _COSINE_EPSILON
        }
        indices = [index for index in siblings if index not in duplicates]
        weights = {}
        for left in indices:
            ranked = sorted(
                (right for right in indices if right != left),
                key=lambda r: (-similarity[left, r], ids[r]),
            )[:8]
            for right in ranked:
                score = float(similarity[left, right])
                # Identical centroids cannot support distinct positions.
                if _COSINE_EPSILON < score < 1 - _COSINE_EPSILON:
                    weights[tuple(sorted((ids[left], ids[right])))] = score
        connected = tuple(sorted({key for pair in weights for key in pair}))
        if not connected:
            continue
        coordinates = build_weighted_spectral_coordinates(connected, weights)
        atlas = build_rectangular_atlas(
            tuple(
                AtlasPoint(point.genre_id, float(point.x), float(point.y), str(point.component))
                for point in coordinates
            )
        )
        positions.update(
            {key: (round(x, 10), round(y, 10)) for key, (x, y) in atlas.positions.items()}
        )
    return positions


def validate_hierarchy(model: dict[str, Any]) -> dict[str, Any]:
    """Reject duplicate, dangling, inconsistent, and cyclic community edges."""
    rows = {row["id"]: row for row in model["communities"]}
    if len(rows) != len(model["communities"]):
        raise ValueError("duplicate community identity")
    for key, row in rows.items():
        parent = row["parent_id"]
        if parent is not None and (parent not in rows or key not in rows[parent]["child_ids"]):
            raise ValueError("inconsistent community ancestry")
        for child in row["child_ids"]:
            if child not in rows or rows[child]["parent_id"] != key:
                raise ValueError("inconsistent community descendants")
        seen = {key}
        while parent is not None:
            if parent in seen:
                raise ValueError("cyclic community ancestry")
            seen.add(parent)
            parent = rows[parent]["parent_id"]
    return rows


def assignment_profiles(
    model_directory: Path, source: Path, rows: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Join model identities to verified source profiles only after construction."""
    shards = defaultdict(dict)
    for line in (model_directory / "assignments.jsonl").read_bytes().splitlines():
        assignment = json.loads(line)
        artist = assignment["artist_mbid"]
        prefix = artist[:3]
        if artist in shards[prefix]:
            raise ValueError("duplicate artist assignment")
        for membership in assignment["memberships"]:
            if membership["community_id"] not in rows:
                raise ValueError("unknown community assignment")
        shards[prefix][artist] = assignment
    profiles = {}
    examples = {artist for row in rows.values() for artist in row["artist_ids"]}
    for prefix, artists in shards.items():
        source_profiles = json.loads((source / "artists" / f"{prefix}.json").read_bytes())[
            "artists"
        ]
        if not set(artists).issubset(source_profiles):
            raise ValueError("model artist absent from verified source catalog")
        profiles.update(
            {artist: source_profiles[artist] for artist in examples.intersection(artists)}
        )
    if set(profiles) != examples:
        raise ValueError("community example lacks an exact source profile")
    return shards, profiles


def verify_boundaries(source_receipt: dict[str, Any], report: dict[str, Any]) -> None:
    """Require consumed artifacts and declared source-only training boundaries."""
    required = {
        "communities.json",
        "assignments.jsonl",
        "topic-centroids.npz",
        "topic-feature-identities.json",
    }
    if not required.issubset(report["files"]):
        raise ValueError("consumed model artifact lacks receipt binding")
    if not {"index.html", "data.json"}.issubset(source_receipt["files"]):
        raise ValueError("source overview lacks receipt binding")
    if (
        report["historical_inputs_used"]
        or report["artist_names_used_for_construction"]
        or report["native_genre_memberships_added"] != 0
    ):
        raise ValueError("model violates source-only construction boundary")


def require_assignment_source_bindings(
    model_directory: Path, source_receipt: dict[str, Any]
) -> None:
    """Require each consumed source-profile shard in the verified file manifest."""
    for line in (model_directory / "assignments.jsonl").read_bytes().splitlines():
        prefix = json.loads(line)["artist_mbid"][:3]
        if f"artists/{prefix}.json" not in source_receipt["files"]:
            raise ValueError("consumed artist source lacks receipt binding")


def verify_feature_lineage(features: Path) -> dict[str, Any]:
    """Check exact feature bytes, source bindings, exclusions, and license scope."""
    receipt = json.loads((features.parent / "receipt.json").read_bytes())
    if (
        receipt["scope"] not in {"local_research_only", "local_noncommercial_research"}
        or receipt["public_export_authorized"]
        or receipt["audio_inputs_used"]
        or receipt["historical_assignments_read"]
        or sha256_file(features)[0] != receipt["feature_sha256"]
    ):
        raise ValueError("unsupported or mismatched feature lineage")
    root = Path(__file__).resolve().parents[3]
    for binding in receipt["inputs"].values():
        path = root / binding["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("feature source escapes repository")
        if sha256_file(path)[0] != binding["sha256"]:
            raise ValueError("feature source byte binding differs")
    return receipt


def build_community_preview(
    *, source: Path, model_directory: Path, features: Path, output: Path
) -> dict[str, Any]:
    """Create a fresh cache-only export retaining exact source and model roles."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a community preview")
    source_receipt = verified_receipt(source, "preview-receipt.json")
    report = verified_receipt(model_directory, "report.json")
    if report["scope"] != "local_research_only" or report["public_export_authorized"]:
        raise ValueError("unsupported model boundary")
    if (
        source_receipt["scope"] != "local_research_only"
        or source_receipt["public_export_authorized"]
    ):
        raise ValueError("unsupported source boundary")
    if sha256_file(features)[0] != report["features_sha256"]:
        raise ValueError("model training features differ")
    verify_boundaries(source_receipt, report)
    feature_receipt = verify_feature_lineage(features)
    model = json.loads((model_directory / "communities.json").read_bytes())
    rows = validate_hierarchy(model)
    positions = community_positions(model, model_directory)
    for key, row in rows.items():
        row["x"], row["y"] = positions.get(key, (None, None))
        row["layout_state"] = (
            "positioned_musical_centroid_overlap"
            if key in positions
            else "abstained_no_distinct_musical_neighbors"
        )
    require_assignment_source_bindings(model_directory, source_receipt)
    shards, profiles = assignment_profiles(model_directory, source, rows)
    output.mkdir(parents=True)
    for relative in source_receipt["files"]:
        destination = output / ("source-explorer.html" if relative == "index.html" else relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
    for suffix in ("html", "css", "js"):
        name = f"community-preview.{suffix}"
        shutil.copyfile(_STATIC / name, output / ("index.html" if suffix == "html" else name))
    (output / "community-artists").mkdir()
    for prefix, artists in shards.items():
        (output / "community-artists" / f"{prefix}.json").write_bytes(
            canonical_json({"artists": artists}) + b"\n"
        )
    model.update(
        role="inferred_emergent_music_communities",
        scope="local_research_only",
        public_export_authorized=False,
        artist_profiles=profiles,
        quality_evaluated=False,
        layout_method="offline_sibling_musical_centroid_cosine_spectral_atlas",
    )
    (output / "community-data.json").write_bytes(canonical_json(model) + b"\n")
    receipt = {
        "revision": "emergent-community-local-preview-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "serving_authorized": False,
        "source_preview_output_sha256": source_receipt["output_sha256"],
        "model_output_sha256": report["output_sha256"],
        "features_sha256": report["features_sha256"],
        "feature_receipt_sha256": sha256_file(features.parent / "receipt.json")[0],
        "source_licenses": {
            "core": feature_receipt["musicbrainz_core_metadata_license"],
            "tags": feature_receipt["musicbrainz_open_tags_license"],
        },
        "derived_output_obligations": feature_receipt["derived_output_obligations"],
        "builder_sha256": sha256_file(Path(__file__))[0],
        "artist_names_used_for_construction": False,
        "native_genre_memberships_added": 0,
        "coverage": model["coverage"],
        "positioned_community_count": len(positions),
        "files": {
            path.relative_to(output).as_posix(): {
                "sha256": sha256_file(path)[0],
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (output / "community-preview-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt
