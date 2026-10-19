"""Frozen unsupervised artist retrieval and observed human-genre coherence diagnostic."""

# ruff: noqa: PLR2004 -- fixed source, schemas and predeclared metric dimensions.
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.ml import jamendo_human_genre as base
from opennoise.ml import jamendo_human_mood as native

PROTOCOL = "ac14d662222fc5241b38598cc2dd74f762d4910f2699c795c1be408356c6e25c"
SOURCE = {
    "metadata": {
        "bytes": 1611903,
        "sha256": "c80e43416e89afc0b2656848e9d4d6f076ca0426003d7e0148ac8cdc6254d366",
    },
    "human": {
        "bytes": 7468828,
        "sha256": "466cbb888fe906f3db22b9e6f63b1694e6a38a8613fb67d9d52149e1cc6decd3",
    },
}
OLD_CODE = {
    "jamendo_human_genre.py": "9f4663644a941f64a78359d2677cc07cadce5b0719f756defc2d26be15869b5d",
    "jamendo_human_mood.py": "9848cd3a855e8b40018c50e949d3d38b6aad533c2323f8d68a7419cd5a5002e9",
}
ARMS = ("genre_tfidf", "genre_instrument_tfidf")
METHODS = (*ARMS, "exact_random_expectation")
METRICS = ("ndcg10", "mean_vote_agreement10")
K = 10
MAX_BYTES = 15_000_000
DISCOUNTS = 1 / np.log2(np.arange(1, K + 1, dtype=float) + 1)
PAYLOADS = {"indices.json", "rankings.json", "evaluation.json"}


@dataclass(frozen=True)
class Inputs:
    """The only source data are the two exact official files; no saved model dependency."""

    metadata: Path
    human: Path
    protocol: Path
    protocol_sha256: str

    @property
    def paths(self) -> tuple[Path, ...]:
        """Protect declared sources during atomic publication."""
        return self.metadata, self.human, self.protocol

    def pins(self) -> dict[str, Any]:
        """Keep source custody hash-only, without embedding historical absolute paths."""
        return {
            "source": SOURCE,
            "protocol_sha256": self.protocol_sha256,
            "amendment_sha256": base.AMENDMENT_SHA256,
        }


def runtime() -> dict[str, Any]:
    """Bind new computation, unchanged parsers/canonicalization and numerical runtime."""
    script = Path(__file__).resolve().parents[3] / "scripts/run_jamendo_artist_coherence.py"
    return {
        "original": base.runtime(),
        "code": {p.name: base.digest(p) for p in (Path(__file__), script)},
    }


def publish(output: Path, files: dict[str, Any], sources: tuple[Path, ...]) -> str:
    """Reuse the bounded atomic research writer with this stricter combined cap."""
    if sum(len(base.file_bytes(name, value)) for name, value in files.items()) > MAX_BYTES:
        raise ValueError("Combined artist-coherence payload cap exceeded")
    return base.publish(output, files, sources)


def load_source(inputs: Inputs) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate complete identities before interpreting one strict human taxonomy."""
    if inputs.protocol_sha256 != PROTOCOL or base.digest(inputs.protocol) != PROTOCOL:
        raise ValueError("Frozen artist-coherence protocol differs")
    protocol = base.read(inputs.protocol)
    if (
        protocol["implementation_dependencies"] != OLD_CODE
        or any(base.runtime()["code"][k] != v for k, v in OLD_CODE.items())
        or protocol["source"]["source_serialization_amendment_sha256"] != base.AMENDMENT_SHA256
    ):
        raise ValueError("Unchanged source canonicalization differs")
    for name in SOURCE:
        path = getattr(inputs, name)
        if (
            any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file()
            or path.stat().st_size != SOURCE[name]["bytes"]
            or base.digest(path) != SOURCE[name]["sha256"]
        ):
            raise ValueError("Exact official source bytes differ")
    metadata_identity = native.parse(inputs.metadata, human=False, identity_only=True)
    human_identity = native.parse(inputs.human, human=True, identity_only=True)
    native.join(metadata_identity, human_identity)
    identities = base.cohort(metadata_identity)
    if (
        hashlib.sha256(base.file_bytes("cohort.json", identities)).hexdigest()
        != protocol["source"]["identity_cohort_sha256"]
    ):
        raise ValueError("Full pre-target native identity cohort differs")
    metadata = native.parse(inputs.metadata, human=False, identity_only=False)
    human, raw, payload = base.parse_targets(inputs.human)
    invalid = {
        r.track_id for r in human if isinstance(r, base.GenreObservation) and r.invalid_raw_vote
    }
    joined = native.join(metadata, human)
    groups = {r["track_id"]: r["component_id"] for r in identities}
    identity_by_id = {r["track_id"]: r for r in identities}
    tracks = []
    artists: dict[int, list[native.Observation]] = defaultdict(list)
    for r in joined:
        row = base.GenreObservation(*r.identity, r.tags, r.votes, r.track_id in invalid)
        artists[r.artist_id].append(row)
        tracks.append(
            {
                **identity_by_id[r.track_id],
                "raw_votes": list(raw[r.track_id] or ()) if raw[r.track_id] else None,
                "canonical_votes": list(r.votes) if r.votes else None,
                "taxonomy_nominated": bool(payload[r.track_id]),
                "target_reason": base.vote_reason(row),
            }
        )
    track_by_id = {r["track_id"]: r for r in tracks}
    artist_rows = []
    for artist, rows in sorted(artists.items()):
        components = {groups[r.track_id] for r in rows}
        if len(components) != 1:
            raise ValueError("Artist spans incompatible native components")
        component = next(iter(components))
        good = [r for r in rows if track_by_id[r.track_id]["target_reason"] is None]
        artist_rows.append(
            {
                "artist_id": artist,
                "component_id": component,
                "fold": base.fold(component),
                "track_ids": [r.track_id for r in rows],
                "album_ids": sorted({r.album_id for r in rows}),
                "tag_counts": dict(
                    sorted(Counter(t for r in rows for t in native.feature_tags(r)).items())
                ),
                "eligible_tracks": len(good),
                "eligible_albums": len({r.album_id for r in good}),
                "positive_classes": [any(c in (r.votes or ()) for r in good) for c in base.CLASSES],
            }
        )
    if len(artist_rows) != 713 or len({r["component_id"] for r in artist_rows}) != 713:
        raise ValueError("Expected one native artist per source component")
    return tracks, artist_rows


def support(tracks: list[dict[str, Any]], artists: list[dict[str, Any]]) -> dict[str, Any]:
    """Count all source/target/gallery support without deriving any IDF weights or vectors."""
    folds = []
    for outer in range(5):
        query = [r for r in artists if r["fold"] == outer]
        gallery = [r for r in artists if r["fold"] != outer]
        judged = [r for r in gallery if r["eligible_tracks"]]
        classes = [sum(r["positive_classes"][c] for r in judged) for c in range(len(base.CLASSES))]
        vocab = set().union(*(r["tag_counts"] for r in gallery))
        folds.append(
            {
                "fold": outer,
                "query_artists": len(query),
                "judged_queries": sum(r["eligible_tracks"] > 0 for r in query),
                "robust_queries": sum(r["eligible_tracks"] >= 2 for r in query),
                "gallery_artists": len(gallery),
                "judged_gallery_artists": len(judged),
                "positive_class_gallery_artists": classes,
                "genre_vocabulary": sum(t.startswith("genre---") for t in vocab),
                "all_vocabulary": len(vocab),
                "evaluation_gate": len(judged) >= K and all(n >= 5 for n in classes),
            }
        )
    return {
        "metadata_tracks": len(tracks),
        "artists": len(artists),
        "components": len({r["component_id"] for r in artists}),
        "albums": len({r["album_id"] for r in tracks}),
        "taxonomy_nominations": sum(r["taxonomy_nominated"] for r in tracks),
        "target_reasons": dict(Counter(r["target_reason"] or "eligible" for r in tracks)),
        "judged_artists": sum(r["eligible_tracks"] > 0 for r in artists),
        "robust_artists": sum(r["eligible_tracks"] >= 2 for r in artists),
        "single_eligible_track_artists": sum(r["eligible_tracks"] == 1 for r in artists),
        "unjudged_artists": sum(r["eligible_tracks"] == 0 for r in artists),
        "folds": folds,
        "evaluation_gate": all(r["evaluation_gate"] for r in folds),
        "supervised_fits": 0,
        "idf_builds": 0,
        "rankings_computed": False,
    }


def receipt(inputs: Inputs, files: dict[str, Any], revision: str) -> dict[str, Any]:
    """Pin exact physical stage bytes, source, implementation and source rights."""
    return {
        "revision": revision,
        "inputs": inputs.pins(),
        "runtime": runtime(),
        "files": base.bindings(files),
        **base.RIGHTS,
    }


def census(inputs: Inputs, output: Path) -> str:
    """Seal source counts and availability before authorizing numerical index execution."""
    base.destination(output, inputs.paths)
    tracks, artists = load_source(inputs)
    files = {
        "census.json": {"tracks": tracks, "artists": artists, "support": support(tracks, artists)}
    }
    return publish(
        output,
        {**files, "seal.json": receipt(inputs, files, "jamendo-artist-coherence-census-v1")},
        inputs.paths,
    )


def load_stage(  # noqa: PLR0913, PLR0917 - explicit external stage roles.
    inputs: Inputs, directory: Path, pin: str, names: set[str], revision: str, marker: str
) -> dict[str, Any]:
    """Verify closed inventory and physical bytes before parsing or replaying stage semantics."""
    base.check_inventory(directory, names | {marker})
    if sum((directory / n).stat().st_size for n in names | {marker}) > MAX_BYTES:
        raise ValueError("Artist-coherence stage byte cap exceeded")
    seal = base.read(directory / marker)
    if base.digest(directory / marker) != pin:
        raise ValueError("External stage pin differs")
    base.check_file_bindings(directory, names, seal["files"])
    files = {name: base.read(directory / name) for name in names}
    if base.encoded(seal) != base.encoded(receipt(inputs, files, revision)):
        raise ValueError("Stage runtime, source, rights or schema differs")
    return files


@dataclass(frozen=True)
class FeatureRows:
    """The index boundary deliberately has no human labels or annotation-availability fields."""

    ids: np.ndarray
    components: np.ndarray
    folds: np.ndarray
    track_counts: np.ndarray
    counts: tuple[dict[str, int], ...]


def feature_rows(artists: list[dict[str, Any]]) -> FeatureRows:
    """Project only label-blind native identity and complete metadata tag counts."""
    return FeatureRows(
        np.array([r["artist_id"] for r in artists], dtype=np.int64),
        np.array([r["component_id"] for r in artists], dtype=np.int64),
        np.array([r["fold"] for r in artists], dtype=np.int64),
        np.array([len(r["track_ids"]) for r in artists], dtype=np.float64),
        tuple(r["tag_counts"] for r in artists),
    )


@dataclass(frozen=True)
class Index:
    """One gallery-only index shared by both predeclared feature arms."""

    query_positions: np.ndarray
    gallery_positions: np.ndarray
    vocabulary: tuple[str, ...]
    df: np.ndarray
    idf: np.ndarray
    query_units: tuple[np.ndarray, ...]
    gallery_units: tuple[np.ndarray, ...]
    query_norms: tuple[np.ndarray, ...]
    gallery_norms: tuple[np.ndarray, ...]
    unseen_query_tags: tuple[tuple[str, ...], ...]


def build_index(features: FeatureRows, outer: int) -> Index:
    """Derive exactly one artist-document IDF bank from gallery metadata only."""
    query = np.flatnonzero(features.folds == outer)
    gallery = np.flatnonzero(features.folds != outer)
    if (
        not len(gallery)
        or outer not in range(5)
        or (features.track_counts <= 0).any()
        or set(features.components[query]) & set(features.components[gallery])
    ):
        raise ValueError("Nonempty component-disjoint gallery required")
    vocabulary = tuple(sorted({t for i in gallery for t in features.counts[i]}))
    df = np.array(
        [sum(t in features.counts[i] for i in gallery) for t in vocabulary], dtype=np.int64
    )
    idf = np.log((1 + len(gallery)) / (1 + df)) + 1
    # Every artist uses ALL native metadata tracks in its TF denominator.
    tf = np.array(
        [
            [row.get(t, 0) / features.track_counts[i] for t in vocabulary]
            for i, row in enumerate(features.counts)
        ],
        dtype=np.float64,
    ).reshape(len(features.ids), len(vocabulary))
    weighted = tf * idf
    query_units, gallery_units, query_norms, gallery_norms = [], [], [], []
    for arm in ARMS:
        columns = np.array(
            [arm != ARMS[0] or t.startswith("genre---") for t in vocabulary], dtype=bool
        )
        values = weighted[:, columns]
        norms = np.linalg.norm(values, axis=1)
        units = values / np.where(norms > 0, norms, 1)[:, None]
        query_units.append(units[query])
        gallery_units.append(units[gallery])
        query_norms.append(norms[query])
        gallery_norms.append(norms[gallery])
    known = set(vocabulary)
    unseen = tuple(tuple(sorted(set(features.counts[i]) - known)) for i in query)
    return Index(
        query,
        gallery,
        vocabulary,
        df,
        idf,
        tuple(query_units),
        tuple(gallery_units),
        tuple(query_norms),
        tuple(gallery_norms),
        unseen,
    )


def rank(features: FeatureRows, index: Index, arm: int) -> dict[int, dict[str, Any]]:
    """Compute feature-only complete positive-cosine orders, with no target mask argument."""
    scores = index.query_units[arm] @ index.gallery_units[arm].T
    if not np.isfinite(scores).all() or (scores > 1 + 1e-12).any() or (scores < -1e-12).any():
        raise ValueError("Finite nonnegative cosine geometry differs")
    gallery_ids = features.ids[index.gallery_positions]
    gallery_components = features.components[index.gallery_positions]
    result = {}
    for j, position in enumerate(index.query_positions):
        order = np.lexsort((gallery_ids, gallery_components, -scores[j]))
        positive = [(int(gallery_ids[k]), float(scores[j, k])) for k in order if scores[j, k] > 0]
        result[int(features.ids[position])] = {
            "positive_order": positive,
            "reason": "empty_profile"
            if index.query_norms[arm][j] == 0
            else None
            if positive
            else "no_eligible_positive_overlap",
            "unseen_query_tags": list(index.unseen_query_tags[j]),
        }
    return result


def index_evidence(features: FeatureRows, index: Index, outer: int) -> dict[str, Any]:
    """Retain gallery DF/IDF and matrix proofs without duplicating full rank matrices."""

    def matrix_pin(matrix: np.ndarray) -> dict[str, Any]:
        return {
            "shape": list(matrix.shape),
            "dtype": "float64",
            "sha256": hashlib.sha256(matrix.tobytes(order="C")).hexdigest(),
        }

    return {
        "fold": outer,
        "query_artists": features.ids[index.query_positions].tolist(),
        "gallery_artists": features.ids[index.gallery_positions].tolist(),
        "vocabulary": list(index.vocabulary),
        "df": index.df.tolist(),
        "idf": index.idf.tolist(),
        "arms": {
            arm: {
                "query_norms": index.query_norms[i].tolist(),
                "gallery_norms": index.gallery_norms[i].tolist(),
                "query_units": matrix_pin(index.query_units[i]),
                "gallery_units": matrix_pin(index.gallery_units[i]),
            }
            for i, arm in enumerate(ARMS)
        },
    }


def human_targets(tracks: list[dict[str, Any]]) -> dict[int, np.ndarray]:
    """Construct sampled artist vote means exclusively for evaluation, never index inputs."""
    by_artist: dict[int, list[list[float]]] = defaultdict(list)
    for row in tracks:
        if row["target_reason"] is None:
            votes = row["canonical_votes"]
            by_artist[row["artist_id"]].append([votes.count(c) / 3 for c in base.CLASSES])
    return {
        a: np.mean(np.array(values, dtype=np.float64), axis=0) for a, values in by_artist.items()
    }


def query_metrics(
    target: np.ndarray,
    gallery_targets: dict[int, np.ndarray],
    positive_order: list[tuple[int, float]],
) -> dict[str, Any]:
    """Score judged-gallery coherence while preserving unjudged and missing full slots."""
    gains = {a: float(target @ y) for a, y in gallery_targets.items()}
    judged = [(a, score) for a, score in positive_order if a in gallery_targets][:K]
    ideal = sorted(gains.values(), reverse=True)[:K]
    idcg = float(np.array(ideal) @ DISCOUNTS[: len(ideal)])
    values = np.array([gains[a] for a, _ in judged])
    dcg = float(values @ DISCOUNTS[: len(values)])
    reason = "no_judged_gallery" if not gains else "zero_idcg" if idcg == 0 else None
    mean = float(np.mean(list(gains.values()))) if gains else 0.0
    full = positive_order[:K]
    observed = [gains[a] for a, _ in full if a in gains]
    return {
        "ndcg10": dcg / idcg if idcg > 0 else 0.0,
        "mean_vote_agreement10": float(values.sum() / K),
        "idcg10": idcg,
        "reason": reason,
        "positive_gain_gallery_artists": sum(g > 0 for g in gains.values()),
        "judged_gallery_artists": len(gains),
        "condensed_judged_top10": [
            {"artist_id": a, "cosine": score, "gain": gains[a]} for a, score in judged
        ],
        "condensed_missing_slots": K - len(judged),
        "random_ndcg10": mean * float(DISCOUNTS.sum()) / idcg if idcg > 0 else 0.0,
        "random_mean_vote_agreement10": mean,
        "full_judged_slots": len(observed),
        "full_unjudged_slots": len(full) - len(observed),
        "full_missing_slots": K - len(full),
        "full_judgment_coverage10": len(observed) / K,
        "full_observed_gain_mean": float(np.mean(observed)) if observed else None,
    }


def summary(rows: list[dict[str, Any]], weights: np.ndarray | None = None) -> dict[str, Any]:
    """Average fixed per-query metrics, without hiding zero-IDCG or retrieval abstentions."""
    judged = [r for r in rows if r["target"] is not None]
    if weights is None:
        weights = np.ones(len(judged), dtype=float)
    total = float(weights.sum())
    return {
        "nominated_queries": len(rows),
        "queries": len(judged),
        "positive_weight_queries": int((weights > 0).sum()),
        "weight_mass": total,
        "scores": {
            method: {
                metric: float(
                    np.average(
                        [
                            r["arms"][ARMS[0]]["metrics"]["random_" + metric]
                            if method == METHODS[-1]
                            else r["arms"][method]["metrics"][metric]
                            for r in judged
                        ],
                        weights=weights,
                    )
                )
                if total > 0
                else None
                for metric in METRICS
            }
            for method in METHODS
        },
        "retrieval_reasons": {
            arm: dict(Counter(r["arms"][arm]["reason"] or "available" for r in rows))
            for arm in ARMS
        },
        "metric_reasons": {
            arm: dict(Counter(r["arms"][arm]["metrics"]["reason"] or "defined" for r in judged))
            for arm in ARMS
        },
        "full_slots": {
            arm: {
                name: sum(r["arms"][arm][name] for r in rows)
                for name in ("full_judged_slots", "full_unjudged_slots", "full_missing_slots")
            }
            for arm in ARMS
        },
        "judged_query_full_slots": {
            arm: {
                name: sum(r["arms"][arm][name] for r in judged)
                for name in ("full_judged_slots", "full_unjudged_slots", "full_missing_slots")
            }
            for arm in ARMS
        },
    }


def bootstrap(rows: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Use fixed paired component resamples of existing ranks, never rebuild an index."""
    judged = [r for r in rows if r["target"] is not None]
    values = np.array(
        [
            [
                [
                    r["arms"][ARMS[0]]["metrics"]["random_" + metric]
                    if method == METHODS[-1]
                    else r["arms"][method]["metrics"][metric]
                    for metric in METRICS
                ]
                for method in METHODS
            ]
            for r in judged
        ]
    ).reshape(-1, len(METHODS), len(METRICS))
    pairs = ((1, 0), (0, 2), (1, 2))
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = np.empty((2000, len(METHODS), len(METRICS)))
    if judged:
        for i in range(2000):
            positions = rng.integers(0, len(judged), size=len(judged))
            draws[i] = values[positions].mean(axis=0)
    return {
        "draws": 2000,
        "valid_draws": 2000 if judged else 0,
        "seed": seed,
        "queries": len(judged),
        "comparisons": {
            f"{METHODS[a]}-minus-{METHODS[b]}": {
                metric: {
                    "difference": float((values[:, a, j] - values[:, b, j]).mean())
                    if judged
                    else None,
                    "interval": np.quantile(
                        draws[:, a, j] - draws[:, b, j], [0.025, 0.975]
                    ).tolist()
                    if judged
                    else None,
                }
                for j, metric in enumerate(METRICS)
            }
            for a, b in pairs
        },
    }


def evaluate_rankings(
    report: dict[str, Any], rankings: dict[str, dict[int, dict[str, Any]]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join labels only after label-blind full positive orders have been fixed."""
    artists = report["artists"]
    targets = human_targets(report["tracks"])
    by_id = {r["artist_id"]: r for r in artists}
    results: list[dict[str, Any]] = []
    for artist in artists:
        a, outer = artist["artist_id"], artist["fold"]
        gallery = {
            r["artist_id"]: targets[r["artist_id"]]
            for r in artists
            if r["fold"] != outer and r["artist_id"] in targets
        }
        arms = {}
        for arm in ARMS:
            ranked = rankings[arm][a]
            full = ranked["positive_order"][:K]
            n_judged = sum(c in targets for c, _ in full)
            metrics = (
                query_metrics(targets[a], gallery, ranked["positive_order"])
                if a in targets
                else None
            )
            arms[arm] = {
                "reason": ranked["reason"],
                "unseen_query_tags": ranked["unseen_query_tags"],
                "positive_overlap_candidates": len(ranked["positive_order"]),
                "full_top10": [
                    {
                        "artist_id": c,
                        "component_id": by_id[c]["component_id"],
                        "cosine": score,
                        "target_available": c in targets,
                    }
                    for c, score in full
                ],
                "full_judged_slots": n_judged,
                "full_unjudged_slots": len(full) - n_judged,
                "full_missing_slots": K - len(full),
                "metrics": metrics,
            }
        results.append(
            {
                "artist_id": a,
                "component_id": artist["component_id"],
                "fold": outer,
                "metadata_tracks": len(artist["track_ids"]),
                "eligible_tracks": artist["eligible_tracks"],
                "instrument_present": any(
                    t.startswith("instrument---") for t in artist["tag_counts"]
                ),
                "target": targets[a].tolist() if a in targets else None,
                "arms": arms,
            }
        )
    judged = [r for r in results if r["target"] is not None]
    robust = [r for r in results if r["eligible_tracks"] >= 2]
    evaluation = {
        "status": "completed",
        "support": report["support"],
        "supervised_fits": 0,
        "gallery_idf_index_builds": 5,
        "overall": summary(results),
        "robust_ge2": summary(robust),
        "folds": [{"fold": f, **summary([r for r in results if r["fold"] == f])} for f in range(5)],
        "per_class": [
            {"class": c, **summary(judged, np.array([r["target"][j] for r in judged]))}
            for j, c in enumerate(base.CLASSES)
        ],
        "instrument_strata": {
            str(present): summary([r for r in results if r["instrument_present"] == present])
            for present in (False, True)
        },
        "bootstrap": bootstrap(results, 20261019),
        "robust_bootstrap": bootstrap(robust, 20261020),
        **base.RIGHTS,
    }
    return results, evaluation


def compute(inputs: Inputs, census_directory: Path, census_pin: str) -> dict[str, Any]:
    """Require a physical and semantic no-index census seal before any actual index computation."""
    sealed = load_stage(
        inputs,
        census_directory,
        census_pin,
        {"census.json"},
        "jamendo-artist-coherence-census-v1",
        "seal.json",
    )
    tracks, artists = load_source(inputs)
    report = {"tracks": tracks, "artists": artists, "support": support(tracks, artists)}
    if base.encoded(sealed["census.json"]) != base.encoded(report):
        raise ValueError("Pre-index source/support census replay differs")
    if not report["support"]["evaluation_gate"]:
        return {
            "indices.json": [],
            "rankings.json": [
                {
                    "artist_id": r["artist_id"],
                    "component_id": r["component_id"],
                    "reason": "support_gate_failed",
                }
                for r in artists
            ],
            "evaluation.json": {
                "status": "support_gate_failed",
                "support": report["support"],
                "gallery_idf_index_builds": 0,
                "supervised_fits": 0,
                **base.RIGHTS,
            },
        }
    features = feature_rows(artists)
    rankings: dict[str, dict[int, dict[str, Any]]] = {arm: {} for arm in ARMS}
    indices = []
    for outer in range(5):
        bank = build_index(features, outer)
        indices.append(index_evidence(features, bank, outer))
        for i, arm in enumerate(ARMS):
            rankings[arm].update(rank(features, bank, i))
    results, evaluation = evaluate_rankings(report, rankings)
    return {"indices.json": indices, "rankings.json": results, "evaluation.json": evaluation}


def run(inputs: Inputs, census_directory: Path, census_pin: str, output: Path) -> str:
    """Publish the one frozen comparison after all numeric stages complete within bounds."""
    sources = (*inputs.paths, census_directory)
    base.destination(output, sources)
    files = compute(inputs, census_directory, census_pin)
    seal = {
        **receipt(inputs, files, "jamendo-artist-coherence-result-v1"),
        "census_sha256": census_pin,
    }
    complete = {**files, "receipt.json": seal}
    if (
        sum(p.stat().st_size for p in census_directory.iterdir())
        + sum(len(base.file_bytes(n, v)) for n, v in complete.items())
        > MAX_BYTES
    ):
        raise ValueError("Combined census/result payload cap exceeded")
    return publish(output, complete, sources)


def replay(
    inputs: Inputs, census_directory: Path, census_pin: str, output: Path, result_pin: str
) -> dict[str, Any]:
    """Rebuild the same five unsupervised indices and reproduce every rank/metric byte binding."""
    base.check_inventory(output, PAYLOADS | {"receipt.json"})
    if (
        sum(p.stat().st_size for p in output.iterdir())
        + sum(p.stat().st_size for p in census_directory.iterdir())
        > MAX_BYTES
        or base.digest(output / "receipt.json") != result_pin
    ):
        raise ValueError("Result byte cap or external pin differs")
    seal = base.read(output / "receipt.json")
    base.check_file_bindings(output, PAYLOADS, seal["files"])
    files = {name: base.read(output / name) for name in PAYLOADS}
    expected = {
        **receipt(inputs, files, "jamendo-artist-coherence-result-v1"),
        "census_sha256": census_pin,
    }
    if base.encoded(seal) != base.encoded(expected) or base.encoded(files) != base.encoded(
        compute(inputs, census_directory, census_pin)
    ):
        raise ValueError("Result runtime, custody, ranking or metric replay differs")
    return files["evaluation.json"]
