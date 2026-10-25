"""Reproduce the public artist-neighborhood source from closed CC0 inputs.

This producer uses only the prior public snapshot and 1000 public aggregate
responses. Spectral coordinates supply navigation geometry only. Suggestions
retain the existing sparse common-context method. No external target labels,
user histories, recording content or private identity mappings are inputs.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import eigsh

BASE = Path("data/examples/native-artist-network-v2/snapshot.json.gz")
BASE_CONTRACT = Path(
    "data/examples/native-artist-neighborhoods-sparse-20261025/baseline-contract.json"
)
BASE_CONTRACT_SHA256 = "f2f5ef38a1f9c9dbabf29acc117609ba4a0bc054510544ef77ed2cb959913e3e"
MANIFEST = Path("data/examples/native-artist-neighborhoods-sparse-20261025/manifest.json")
MANIFEST_SHA256 = "5a3bf7a201ad9c354ac0a67ba3a495007b41bcc7ebc9c8d44fe94ea6304a143e"
SNAPSHOT = "data/examples/native-artist-network-sparse-v2/snapshot.json.gz"
DIMENSIONS = 2
MIN_SCALE = 1e-9
REFERENCES = 1000
HTTP_OK = 200
MAX_RESPONSE = 500_000
MAX_ROWS = 250
MAX_NAME = 1000
MIN_AGGREGATE = 10
EIGEN_EXCLUSION = 0.99999
MIN_CONTEXT = 3
MIN_CONTEXT_SCORE = 1e-8
MIN_CONNECTIONS = 5
MAX_SOURCE = 40_000_000


def digest(path: Path) -> str:
    """Hash a closed public source file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    """Save a deterministic JSON source receipt."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def valid_id(value: object) -> bool:
    """Accept only literal canonical native artist identifiers."""
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def local_map(
    artist: str,
    connections: list[str],
    embedding: np.ndarray,
    index: dict[str, int],
    names: dict[str, str],
) -> list[dict[str, Any]]:
    """Pack the query and strongest 24 source neighbors using the existing geometry."""
    chosen = [artist, *connections[:24]]
    vectors = embedding[[index[a] for a in chosen]]
    centered = vectors - vectors.mean(axis=0)
    u, singular, _ = np.linalg.svd(centered, full_matrices=False)
    xy = u[:, :2] * singular[:2]
    if xy.shape[1] < DIMENSIONS:
        xy = np.pad(xy, ((0, 0), (0, 2 - xy.shape[1])))
    scales = np.ptp(xy, axis=0)
    scales[scales < MIN_SCALE] = 1
    xy = 90 + (xy - xy.min(axis=0)) / scales * np.array([1000, 580])
    result: list[dict[str, Any]] = []
    # These are initial source-derived targets. The existing browser measures
    # actual text and packs every label with its authoritative pixel dimensions.
    for k, aid in enumerate(chosen):
        size = 19 if k == 0 else 16
        width = min(1050, max(45, len(names[aid]) * size * 0.68))
        x, y = xy[k]
        result.append(
            {
                "id": aid,
                "x": round(float(np.clip(x, 15, 1185 - width)), 2),
                "y": round(float(np.clip(y, 30, 750)), 2),
                "size": size,
                "width": round(width + 12, 2),
            }
        )

    return result


def build(root: Path, output: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 -- Keep the closed source projection and its full rejection ledger together.
    """Validate every public source row and generate a fixed-gallery candidate."""
    if output.exists():
        raise ValueError("Refuse overwriting a prior source candidate")
    if digest(root / MANIFEST) != MANIFEST_SHA256:
        raise ValueError("Public capture manifest differs")
    manifest = json.loads((root / MANIFEST).read_text())
    if digest(root / BASE) != manifest["baseline_snapshot_sha256"]:
        raise ValueError("Prior public source differs")
    capture_path = root / manifest["captures_path"]
    if (
        digest(capture_path) != manifest["captures_sha256"]
        or capture_path.stat().st_size != manifest["captures_bytes"]
    ):
        raise ValueError("Public raw captures differ")
    baseline = json.loads(gzip.decompress((root / BASE).read_bytes()))
    if digest(root / BASE_CONTRACT) != BASE_CONTRACT_SHA256:
        raise ValueError("Prior public contract differs")
    baseline_contract = json.loads((root / BASE_CONTRACT).read_text())
    if baseline_contract["snapshot_sha256"] != manifest["baseline_snapshot_sha256"]:
        raise ValueError("Prior public contract/source disagree")
    expanded = gzip.decompress(capture_path.read_bytes())
    if len(expanded) != manifest["expanded_bytes"]:
        raise ValueError("Raw capture expanded size differs")
    records = [json.loads(line) for line in expanded.splitlines()]
    if len(records) != manifest["captures"] or len(records) != REFERENCES:
        raise ValueError("Public reference count differs")
    artists = baseline["artists"]
    ids = [a["id"] for a in artists]
    names = {a["id"]: a["name"] for a in artists}
    index = {a: i for i, a in enumerate(ids)}
    attempted = {r["reference"] for r in baseline["source"]["captures"]} | set(
        manifest["excluded_prior_attempts"]
    )
    baseline_degree: Counter[str] = Counter()
    for left, right, _ in baseline["pairs"]:
        baseline_degree[left] += 1
        baseline_degree[right] += 1
    if len(attempted) != manifest["previously_attempted"]:
        raise ValueError("Prior attempt denominator differs")
    bins: dict[str, list[str]] = {"1-2": [], "3-4": []}
    for aid in set(ids) - attempted:
        if 0 < baseline_degree[aid] < MIN_CONNECTIONS:
            bins["1-2" if baseline_degree[aid] < MIN_CONTEXT else "3-4"].append(aid)
    if {key: len(values) for key, values in bins.items()} != manifest["eligible_by_degree_bin"]:
        raise ValueError("Sparse source strata differ")
    eligible_count = sum(map(len, bins.values()))
    quotas = {key: REFERENCES * len(values) // eligible_count for key, values in bins.items()}
    remainders = sorted(
        bins, key=lambda key: (-(REFERENCES * len(bins[key]) % eligible_count), key)
    )
    for key in remainders[: REFERENCES - sum(quotas.values())]:
        quotas[key] += 1
    if quotas != manifest["sample_by_degree_bin"]:
        raise ValueError("Sparse source quotas differ")

    def sample_key(aid: str) -> tuple[str, str]:
        return hashlib.sha256((manifest["selection_tag"] + aid).encode()).hexdigest(), aid

    selected = sorted(
        [
            aid
            for key, values in bins.items()
            for aid in sorted(values, key=sample_key)[: quotas[key]]
        ],
        key=sample_key,
    )
    if [r["reference"] for r in records] != selected:
        raise ValueError("Public sample differs from deterministic source cohort")
    pairs = {(a, b): float(score) for a, b, score in baseline["pairs"]}
    observed_names: dict[str, set[str]] = defaultdict(set)
    causes: Counter[str] = Counter()
    quarantine: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    raw_rows = duplicate_rows = outside_rows = nonempty_references = 0
    for record in records:
        reference = record["reference"]
        parsed_url = urlparse(record["url"])
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != "labs.api.listenbrainz.org"
            or parsed_url.path != "/similar-artists/json"
            or parse_qs(parsed_url.query)
            != {"artist_mbids": [reference], "algorithm": [manifest["algorithm"]]}
        ):
            raise ValueError("Unexpected public request target")
        body = base64.b64decode(record["body_base64"], validate=True)
        if (
            record["status"] != HTTP_OK
            or len(body) != record["bytes"]
            or len(body) > MAX_RESPONSE
            or hashlib.sha256(body).hexdigest() != record["sha256"]
        ):
            raise ValueError("Public response identity differs")
        raw = json.loads(body)
        if not isinstance(raw, list) or len(raw) > MAX_ROWS:
            raise ValueError("Unexpected aggregate root")
        raw_rows += len(raw)
        retained: dict[str, dict[str, Any]] = {}
        for ordinal, row in enumerate(raw):
            invalid = []
            if not isinstance(row, dict):
                invalid.append("not_object")
            else:
                aid, score, name = row.get("artist_mbid"), row.get("score"), row.get("name")
                if not valid_id(aid):
                    invalid.append("invalid_artist_mbid")
                if row.get("reference_mbid") != reference:
                    invalid.append("missing_or_conflicting_reference_attribution")
                if aid == reference:
                    invalid.append("self_relationship")
                if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
                    invalid.append("missing_or_invalid_native_name")
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(score)
                    or score <= MIN_AGGREGATE
                ):
                    invalid.append("invalid_or_nonpositive_thresholded_score")
            if invalid:
                quarantine.append({"reference": reference, "ordinal": ordinal, "causes": invalid})
                causes.update(invalid)
                continue
            aid = row["artist_mbid"]
            if aid in retained:
                duplicate_rows += 1
            if aid not in retained or row["score"] > retained[aid]["score"]:
                retained[aid] = row
        nonempty_references += bool(retained)
        for aid, row in retained.items():
            if aid not in names:
                outside_rows += 1
                continue
            observed_names[aid].add(row["name"])
            left, right = sorted((reference, aid))
            pair = (left, right)
            pairs[pair] = max(pairs.get(pair, 0), row["score"])
        captures.append(
            {k: record[k] for k in ["reference", "url", "sha256", "bytes", "captured_utc"]}
        )
    # This batch never replaces an existing native name or adds an identity.
    corrections: list[dict[str, Any]] = []
    neighbors: dict[str, dict[str, float]] = defaultdict(dict)
    rows, cols, weights = [], [], []
    for (a, b), score in sorted(pairs.items()):
        neighbors[a][b] = score
        neighbors[b][a] = score
        i, j = index[a], index[b]
        rows.extend([i, j])
        cols.extend([j, i])
        weights.extend([math.log1p(score)] * 2)
    adjacency = sparse.csr_matrix((weights, (rows, cols)), shape=(len(ids), len(ids)))
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    inv = np.zeros_like(degree)
    np.divide(1, np.sqrt(degree), out=inv, where=degree > 0)
    norm = sparse.diags(inv) @ adjacency @ sparse.diags(inv)
    rng = np.random.default_rng(20261024)
    values, vectors = eigsh(
        norm, k=80, which="LA", v0=rng.normal(size=len(ids)), tol=1e-5, maxiter=2000
    )
    order = [i for i in np.argsort(-values) if values[i] < EIGEN_EXCLUSION][:64]
    embedding = vectors[:, order] * np.sqrt(np.maximum(values[order], 0))[None, :]
    lengths = np.linalg.norm(embedding, axis=1, keepdims=True)
    np.divide(embedding, lengths, out=embedding, where=lengths > 0)
    l2 = np.sqrt(np.asarray(adjacency.multiply(adjacency).sum(axis=1)).ravel())
    inverse = np.zeros_like(l2)
    np.divide(1, l2, out=inverse, where=l2 > 0)
    profiles = sparse.diags(inverse) @ adjacency
    layouts, suggested = {}, 0
    for step, aid in enumerate(ids):
        connections = sorted(neighbors[aid], key=lambda b: (-neighbors[aid][b], b))
        layouts[aid] = local_map(aid, connections, embedding, index, names) if connections else []
        if len(connections) >= MIN_CONTEXT:
            score = (profiles[index[aid]] @ profiles.T).toarray().ravel()
            score[index[aid]] = 0
            score[[index[b] for b in connections]] = 0
            suggested += bool(np.any(score > MIN_CONTEXT_SCORE))
        if step % 2000 == 0:
            sys.stdout.write(f"Source maps {step}/{len(ids)}\n")
            sys.stdout.flush()
    counts = {
        "artists": len(ids),
        "connected_artists": sum(bool(neighbors[a]) for a in ids),
        "at_least5_connections": sum(len(neighbors[a]) >= MIN_CONNECTIONS for a in ids),
        "queried_references": baseline["source"]["successful_reference_responses"] + len(captures),
        "nonempty_queried_references": baseline_contract["counts"]["nonempty_queried_references"]
        + nonempty_references,
        "observed_undirected_pairs": len(pairs),
        "suggested_artists": suggested,
    }
    merged_captures = [*baseline["source"]["captures"], *captures]
    capture_manifest_bytes = (
        json.dumps(merged_captures, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    source = {
        **baseline["source"],
        "capture_sha256": hashlib.sha256(capture_manifest_bytes).hexdigest(),
        "capture_manifest_kind": "canonical listed-capture metadata JSON plus LF",
        "sparse_completion_base_capture_sha256": baseline["source"]["capture_sha256"],
        "sparse_completion_capture_sha256": manifest["captures_sha256"],
        "excluded_unattributed_rows": {
            **baseline["source"]["excluded_unattributed_rows"],
            "sparse_completion_v2_missing_or_conflicting_reference": causes[
                "missing_or_conflicting_reference_attribution"
            ],
        },
        "sparse_completion_baseline_snapshot_sha256": manifest["baseline_snapshot_sha256"],
        "sparse_completion_manifest_sha256": MANIFEST_SHA256,
        "captures": merged_captures,
        "successful_reference_responses": counts["queried_references"],
        "attempted_references": baseline["source"]["attempted_references"] + len(captures),
        "raw_neighbor_rows": baseline["source"]["raw_neighbor_rows"] + raw_rows,
        "last_capture_utc": max(c["captured_utc"] for c in captures),
        "sparse_completion_quarantine_causes": dict(causes),
        "sparse_completion_duplicate_rows": duplicate_rows,
        "sparse_completion_outside_fixed_gallery_rows": outside_rows,
        "name_corrections": baseline["source"].get("name_corrections", []),
        "layout": (
            "Source-only spectral initial targets; browser measures and packs labels; "
            "no musical axes"
        ),
    }
    snapshot = {
        "revision": "native-artist-network-source-sparse-v2",
        "artists": [{"id": a, "name": names[a]} for a in ids],
        "pairs": [[a, b, score] for (a, b), score in sorted(pairs.items())],
        "layouts": layouts,
        "source": source,
    }
    raw_snapshot = (
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if len(raw_snapshot) > MAX_SOURCE:
        raise ValueError("Expanded source exceeds public bounds")
    compressed = gzip.compress(raw_snapshot, mtime=0)
    output.mkdir(parents=True)
    (output / "snapshot.json.gz").write_bytes(compressed)
    contract = {
        "revision": "native-artist-network-inputs-v1",
        "snapshot_path": SNAPSHOT,
        "snapshot_sha256": hashlib.sha256(compressed).hexdigest(),
        "snapshot_bytes": len(compressed),
        "expanded_bytes": len(raw_snapshot),
        "counts": counts,
        "genres_with_suggestions": 148,
        "rights": "CC0-1.0",
        "source_scope": source["scope"],
        "audio_lyrics_or_user_histories": False,
        "genre_memberships_inferred": False,
    }
    write(output / "contract.json", contract)
    report = {
        "counts": counts,
        "quarantine_causes": dict(causes),
        "quarantined_rows": len(quarantine),
        "duplicate_rows": duplicate_rows,
        "outside_fixed_gallery_rows": outside_rows,
        "name_corrections": corrections,
        "manifest_sha256": MANIFEST_SHA256,
        "snapshot_sha256": contract["snapshot_sha256"],
        "private_inputs": False,
    }
    write(output / "report.json", report)
    write(output / "quarantine.json", quarantine)
    return report


def main() -> None:
    """Build a reviewable local source artifact without promotion or publication."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    sys.stdout.write(json.dumps(build(Path.cwd(), arguments.output)) + "\n")


if __name__ == "__main__":
    main()
