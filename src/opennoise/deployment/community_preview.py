"""Export verified emergent music communities as a local static explorer."""

from __future__ import annotations

import json
import math
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import load_enrichment
from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas

_COSINE_EPSILON = 1e-10
_REQUIRED_FEATURE_BINDINGS = frozenset(
    {
        "artist_name_enrichment_receipt",
        "candidate_catalog_database",
        "candidate_catalog_receipt",
        "direct_genre_claim_object",
        "direct_genre_receipt",
        "genre_labels",
        "open_artist_features",
        "open_artist_features_receipt",
        "open_artist_source_manifest",
    }
)
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


def validate_membership(
    membership: dict[str, Any], assigned: set[str], rows: dict[str, Any]
) -> None:
    """Reject unknown, mislabeled, nonfinite, or orphan inferred memberships."""
    key = membership["community_id"]
    if key not in rows:
        raise ValueError("unknown community assignment")
    if (
        membership["role"] != "inferred_community_membership"
        or membership["level"] != rows[key]["level"]
    ):
        raise ValueError("membership role or level differs")
    score = membership["score"]
    if (
        not isinstance(score, (int, float))
        or isinstance(score, bool)
        or not math.isfinite(score)
        or not 0 <= score <= 1 + _COSINE_EPSILON
    ):
        raise ValueError("invalid membership affinity")
    if rows[key]["parent_id"] is not None and rows[key]["parent_id"] not in assigned:
        raise ValueError("membership lacks its ancestor")


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
        assigned = {membership["community_id"] for membership in assignment["memberships"]}
        if len(assigned) != len(assignment["memberships"]):
            raise ValueError("duplicate community assignment")
        for membership in assignment["memberships"]:
            validate_membership(membership, assigned, rows)
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


def require_feature_bindings(inputs: dict[str, Any]) -> None:
    """Accept complete original or explicitly indexed multi-source feature manifests."""
    original = {
        "open_artist_features",
        "open_artist_features_receipt",
        "open_artist_source_manifest",
    }
    core = _REQUIRED_FEATURE_BINDINGS - original
    if not core.issubset(inputs):
        raise ValueError("feature lineage omits mandatory source bindings")
    original_present = bool(original.intersection(inputs))
    if original_present and not original.issubset(inputs):
        raise ValueError("feature lineage omits mandatory source bindings")
    indices = sorted(
        {
            int(match.group(1))
            for key in inputs
            if (match := re.fullmatch(r"open_artist_features_(\d+)(?:_receipt|_manifest)?", key))
        }
    )
    if (not original_present and not indices) or indices != list(range(len(indices))):
        raise ValueError("feature lineage omits mandatory source bindings")
    for index in indices:
        key = f"open_artist_features_{index}"
        if not {key, key + "_receipt", key + "_manifest"}.issubset(inputs):
            raise ValueError("feature lineage omits mandatory source bindings")


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
    require_feature_bindings(receipt["inputs"])
    root = Path(__file__).resolve().parents[3]
    for binding in receipt["inputs"].values():
        path = root / binding["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("feature source escapes repository")
        if sha256_file(path)[0] != binding["sha256"]:
            raise ValueError("feature source byte binding differs")
    return receipt


def validate_feature_proposals(
    record: dict[str, Any], training_sha256: str, model_sha256: str
) -> None:
    """Keep derived style suggestions separate from known source musical values."""
    known = set(record["observed_music_values"])
    seen = set()
    for proposal in record["feature_proposals"]:
        value = proposal["value"]
        if value in known or value in seen:
            raise ValueError("style suggestion repeats an observed or proposed value")
        seen.add(value)
        if (
            proposal["role"] != "inferred_feature_proposal"
            or proposal["native_fact"] is not False
            or proposal["score_calibrated"] is not False
            or proposal["training_source_sha256"] != training_sha256
            or proposal["training_input_sha256"] != training_sha256
            or proposal["source_model_sha256"] != model_sha256
        ):
            raise ValueError("style suggestion violates inference boundary")
        score = proposal["score"]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or score <= 0
        ):
            raise ValueError("invalid style suggestion score")
        if not proposal["evidence"]:
            raise ValueError("style suggestion lacks source explanation")
        for cue in proposal["evidence"]:
            validate_proposal_cue(cue, known, proposal["training_target_artist_support"])


def validate_proposal_cue(cue: dict[str, Any], known: set[str], target_support: int) -> None:
    """Require an observed cue and consistent positive native training support."""
    if cue["value"] not in known or cue["cue_role"] not in {"music", "proper_genre"}:
        raise ValueError("style suggestion explanation lacks an observed musical cue")
    joint, support = cue["training_joint_artist_support"], cue["training_cue_artist_support"]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1
        for value in (joint, support, target_support)
    ) or joint > min(support, target_support):
        raise ValueError("style suggestion training counts differ")
    refs = cue["query_evidence_refs"]
    if (
        not isinstance(refs, list)
        or not refs
        or any(not isinstance(ref, str) or not ref for ref in refs)
    ):
        raise ValueError("style suggestion lacks observed query references")
    if cue["query_evidence_ref_count"] < len(refs):
        raise ValueError("style suggestion reference count differs")


def merge_feature_proposals(
    directory: Path, shards: dict[str, Any], training_sha256: str
) -> dict[str, Any]:
    """Verify and join complete style predictions to existing exact artist identities."""
    receipt = verified_receipt(directory, "prediction-receipt.json")
    if (
        receipt["training_sha256"] != training_sha256
        or receipt["public_export_authorized"]
        or receipt["scope"] not in {"local_research_only", "local_noncommercial_research"}
        or receipt["role"] != "inferred_feature_proposals"
    ):
        raise ValueError("unsupported style prediction artifact")
    if (
        receipt["audio_used"] is not False
        or receipt["historical_inputs_used"] is not False
        or receipt["native_fact"] is not False
        or receipt["scores_calibrated"] is not False
        or receipt["training_input_sha256"] != training_sha256
    ):
        raise ValueError("style prediction artifact violates inference boundary")
    if "model/receipt.json" not in receipt["files"]:
        raise ValueError("style prediction model lacks byte binding")
    model = load_enrichment(directory / "model")
    if model.training_sha256 != training_sha256 or model.model_sha256 != receipt["model_sha256"]:
        raise ValueError("style prediction model differs")
    seen = set()
    for relative in sorted(receipt["files"]):
        if not relative.startswith("feature-proposals/") or not relative.endswith(".json"):
            continue
        records = json.loads((directory / relative).read_bytes())["artists"]
        for artist, record in records.items():
            prefix = artist[:3]
            if artist in seen or prefix not in shards or artist not in shards[prefix]:
                raise ValueError("style prediction artist differs from community corpus")
            validate_feature_proposals(record, training_sha256, receipt["model_sha256"])
            seen.add(artist)
            shards[prefix][artist].update(
                feature_proposals=record["feature_proposals"],
                observed_music_values=record["observed_music_values"],
                enrichment_state=record["state"],
            )
    if len(seen) != sum(len(artists) for artists in shards.values()):
        raise ValueError("style prediction projection is incomplete")
    return receipt


def build_community_preview(
    *,
    source: Path,
    model_directory: Path,
    features: Path,
    output: Path,
    enrichment_directory: Path | None = None,
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
    enrichment_receipt = (
        merge_feature_proposals(enrichment_directory, shards, report["features_sha256"])
        if enrichment_directory
        else None
    )
    output.mkdir(parents=True)
    for relative in source_receipt["files"]:
        destination = output / ("source-explorer.html" if relative == "index.html" else relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
        if sha256_file(destination)[0] != source_receipt["files"][relative]["sha256"]:
            raise ValueError("source bytes changed during preview copy")
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
        enrichment_available=enrichment_receipt is not None,
        enrichment_prediction_output_sha256=enrichment_receipt["output_sha256"]
        if enrichment_receipt
        else None,
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
        "enrichment_prediction_output_sha256": enrichment_receipt["output_sha256"]
        if enrichment_receipt
        else None,
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
