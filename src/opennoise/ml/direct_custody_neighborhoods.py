"""Source-only sparse neighborhoods with nested direct-observation holdouts.

All outputs are local research candidates. Missing MusicBrainz observations
are unknown, and the full-data preview is distinct from either evaluation fit.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, cast

import numpy as np
import scipy
from scipy import sparse

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.ml.full_graph_signal.contracts import FullGraphSignalSettings
from opennoise.ml.full_graph_signal.sparse_baselines import _cosine_neighbors
from opennoise.peers.direct_custody_membership_holdout import _split_memberships

if TYPE_CHECKING:
    from collections.abc import Mapping

type Arm = Literal["binary_cosine", "degree_cosine", "degree_shrunk", "specificity_transfer"]
ARMS: Final[tuple[Arm, ...]] = (
    "binary_cosine",
    "degree_cosine",
    "degree_shrunk",
    "specificity_transfer",
)
TOP_K: Final = 20
BLOCK_SIZE: Final = 512
MAX_GENRES: Final = 1000
MAX_ARTISTS: Final = 1_000_000
MAX_ARTIST_DEGREE: Final = 256
MAX_PAIR_VISITS: Final = 5_000_000
SHRINKAGE: Final = 5.0
MIN_SHARED: Final = 2
RECALL_MIDDLE_K: Final = 5
RARE_SUPPORT: Final = 20
MEDIUM_SUPPORT: Final = 100
REVISION: Final = "direct-custody-sparse-neighborhoods-v1"


@dataclass(frozen=True)
class ObservationIndex:
    """Sorted source identities and a deduplicated binary artist-by-seed matrix."""

    artists: tuple[str, ...]
    seeds: tuple[str, ...]
    binary: sparse.csr_matrix


@dataclass(frozen=True)
class RetrievalMetric:
    """All-positive denominators, including unsupported and cold artists."""

    positive_count: int
    supported_positive_count: int
    cold_artist_positive_count: int
    hits_at_1: int
    hits_at_5: int
    hits_at_10: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    macro_seed_recall_at_10: float
    mrr_at_10: float
    evaluated_seed_count: int
    unevaluated_seed_count: int
    train_support_strata: dict[str, dict[str, int | float]]


def observation_index(memberships: Mapping[str, tuple[str, ...]]) -> ObservationIndex:
    """Build bounded canonical sparse identities without names or historical fields."""
    seeds = tuple(sorted(memberships))
    artists = tuple(sorted({artist for values in memberships.values() for artist in values}))
    if len(seeds) > MAX_GENRES or len(artists) > MAX_ARTISTS:
        raise ValueError("source identity bounds exceeded")
    artist_index = {artist: row for row, artist in enumerate(artists)}
    rows, columns = [], []
    for column, seed in enumerate(seeds):
        for artist in sorted(set(memberships[seed])):
            rows.append(artist_index[artist])
            columns.append(column)
    binary = sparse.csr_matrix(
        (np.ones(len(rows), dtype=np.float32), (rows, columns)),
        shape=(len(artists), len(seeds)),
    )
    degrees = np.diff(binary.indptr).astype(np.int64)
    if degrees.max(initial=0) > MAX_ARTIST_DEGREE:
        raise ValueError("artist genre-degree bound exceeded; no silent feature truncation")
    if int(np.sum(degrees * (degrees - 1) // 2)) > MAX_PAIR_VISITS:
        raise ValueError("sparse pair expansion bound exceeded")
    return ObservationIndex(artists, seeds, binary)


def _top_indices(values: np.ndarray, indices: np.ndarray, limit: int) -> np.ndarray:
    """Sort ties by the canonical identity index, including across the cutoff."""
    return np.lexsort((indices, -values))[:limit]


def genre_neighbors(index: ObservationIndex, arm: Arm) -> sparse.csr_matrix:
    """Reuse the sparse cosine engine with explicit train-only weighting and bounds."""
    binary = index.binary
    degree = np.maximum(1, np.diff(binary.indptr))
    weighted = (
        binary
        if arm == "binary_cosine"
        else cast("sparse.csr_matrix", sparse.diags(1 / np.sqrt(degree)) @ binary)
    )
    # Keep every possible seed pair in the shared engine, then apply a stable
    # score-and-ID cutoff ourselves. This avoids its argpartition cutoff ties.
    settings = FullGraphSignalSettings(
        maximum_genres_per_artist_for_cooccurrence=MAX_ARTIST_DEGREE,
        maximum_genre_neighbors=max(10, len(index.seeds)),
        maximum_cooccurrence_nnz=MAX_GENRES * MAX_GENRES,
    )
    graph = _cosine_neighbors(weighted, settings)
    shared = (binary.T @ binary).tocsr()
    output_rows, output_columns, output_values = [], [], []
    for row in range(len(index.seeds)):
        start, end = graph.indptr[row : row + 2]
        columns = graph.indices[start:end]
        values = graph.data[start:end].copy()
        support = np.asarray(shared[row, columns].toarray()).ravel()
        eligible = support >= MIN_SHARED
        columns, values, support = columns[eligible], values[eligible], support[eligible]
        if arm in {"degree_shrunk", "specificity_transfer"}:
            values *= support / (support + SHRINKAGE)
        selected = _top_indices(values, columns, TOP_K)
        output_rows.extend([row] * len(selected))
        output_columns.extend(columns[selected].tolist())
        output_values.extend(values[selected].tolist())
    return sparse.csr_matrix(
        (output_values, (output_rows, output_columns)), shape=graph.shape, dtype=np.float32
    )


def _transfer(index: ObservationIndex, graph: sparse.csr_matrix, arm: Arm) -> sparse.csr_matrix:
    """Orient each target genre's neighbors into artist-to-target prediction columns."""
    transfer = graph.T.tocsr()
    if arm == "specificity_transfer":
        frequency = np.maximum(1, np.asarray(index.binary.sum(axis=0)).ravel())
        transfer = (sparse.diags(1 / np.sqrt(frequency)) @ transfer).tocsr()
    return cast("sparse.csr_matrix", transfer)


def evaluate(  # noqa: C901, PLR0915 - keep fit-only ranking and full-denominator accounting together.
    index: ObservationIndex, targets: Mapping[str, tuple[str, ...]], arm: Arm
) -> RetrievalMetric:
    """Rank hidden direct source genres using only each artist's remaining observations."""
    graph = genre_neighbors(index, arm)
    transfer = _transfer(index, graph, arm)
    artist_rows = {artist: row for row, artist in enumerate(index.artists)}
    by_artist: dict[int, list[int]] = defaultdict(list)
    total_by_seed: dict[int, int] = {}
    cold_by_seed: dict[int, int] = defaultdict(int)
    cold = 0
    for column, seed in enumerate(index.seeds):
        total_by_seed[column] = len(targets.get(seed, ()))
        for artist in targets.get(seed, ()):
            if artist in artist_rows:
                row = artist_rows[artist]
                if index.binary[row, column] != 0:
                    raise ValueError("held-out target leaked into training observations")
                by_artist[row].append(column)
            else:
                cold += 1
                cold_by_seed[column] += 1
    if set(targets) - set(index.seeds):
        raise ValueError("target seed missing from retained seed universe")
    hits = [0, 0, 0]
    supported, reciprocal = 0, 0.0
    seed_hits: dict[int, int] = defaultdict(int)
    seed_supported: dict[int, int] = defaultdict(int)
    active = sorted(by_artist)
    for offset in range(0, len(active), BLOCK_SIZE):
        row_ids = active[offset : offset + BLOCK_SIZE]
        scores = (index.binary[row_ids] @ transfer).tocsr()
        for local, row in enumerate(row_ids):
            start, end = scores.indptr[local : local + 2]
            columns, values = scores.indices[start:end], scores.data[start:end]
            known = index.binary.indices[index.binary.indptr[row] : index.binary.indptr[row + 1]]
            eligible = ~np.isin(columns, known)
            columns, values = columns[eligible], values[eligible]
            selected = _top_indices(values, columns, 10)
            ranks = {int(columns[item]): rank for rank, item in enumerate(selected, 1)}
            candidates = set(columns.tolist())
            for target in by_artist[row]:
                supported += int(target in candidates)
                seed_supported[target] += int(target in candidates)
                rank = ranks.get(target)
                if rank is not None:
                    hits[0] += int(rank <= 1)
                    hits[1] += int(rank <= RECALL_MIDDLE_K)
                    hits[2] += 1
                    reciprocal += 1 / rank
                    seed_hits[target] += 1
    total = sum(total_by_seed.values())
    macro = [seed_hits[column] / count for column, count in total_by_seed.items() if count]
    train_counts = np.asarray(index.binary.sum(axis=0)).ravel()
    strata: dict[str, dict[str, int | float]] = {}
    for label, minimum, maximum in (
        ("4_to_20", 0, RARE_SUPPORT),
        ("21_to_100", RARE_SUPPORT, MEDIUM_SUPPORT),
        ("over_100", MEDIUM_SUPPORT, MAX_ARTISTS),
    ):
        selected_seeds = [
            column
            for column, count in total_by_seed.items()
            if count and minimum < train_counts[column] <= maximum
        ]
        denominator = sum(total_by_seed[column] for column in selected_seeds)
        recovered = sum(seed_hits[column] for column in selected_seeds)
        strata[label] = {
            "seed_count": len(selected_seeds),
            "positive_count": denominator,
            "hits_at_10": recovered,
            "supported_positive_count": sum(seed_supported[x] for x in selected_seeds),
            "cold_artist_positive_count": sum(cold_by_seed[x] for x in selected_seeds),
            "recall_at_10": recovered / denominator if denominator else 0.0,
        }
    return RetrievalMetric(
        positive_count=total,
        supported_positive_count=supported,
        cold_artist_positive_count=cold,
        hits_at_1=hits[0],
        hits_at_5=hits[1],
        hits_at_10=hits[2],
        recall_at_1=hits[0] / total if total else 0.0,
        recall_at_5=hits[1] / total if total else 0.0,
        recall_at_10=hits[2] / total if total else 0.0,
        macro_seed_recall_at_10=float(np.mean(macro)) if macro else 0.0,
        mrr_at_10=reciprocal / total if total else 0.0,
        evaluated_seed_count=len(macro),
        unevaluated_seed_count=len(index.seeds) - len(macro),
        train_support_strata=strata,
    )


def artist_neighbors(index: ObservationIndex, artist_mbid: str) -> list[dict[str, object]]:
    """Answer one bounded artist query using IDF-weighted direct-genre overlap cosine.

    This separate explanation-first query is not evaluated by the genre recovery
    metric. At least two shared direct genres are required; singleton profiles abstain.
    """
    if artist_mbid not in index.artists:
        return []
    row = index.artists.index(artist_mbid)
    binary = index.binary
    frequency = np.asarray(binary.sum(axis=0)).ravel()
    weights = 1 + np.log((len(index.artists) + 1) / (frequency + 1))
    query = binary.getrow(row)
    shared = (binary @ query.T).tocoo()
    candidates = shared.row[(shared.data >= MIN_SHARED) & (shared.row != row)]
    if len(candidates) == 0:
        return []
    mass = np.asarray(binary @ weights).ravel()
    numerator = (binary[candidates] @ query.multiply(weights).T).toarray().ravel()
    scores = numerator / np.sqrt(mass[candidates] * mass[row])
    selected = _top_indices(scores, candidates, TOP_K)
    return [
        {
            "artist_mbid": index.artists[int(candidates[item])],
            "score": float(scores[item]),
            "role": "inferred_shared_direct_genre_neighbor",
            "shared_seed_ids": [
                index.seeds[int(column)]
                for column in np.intersect1d(
                    query.indices, binary.getrow(int(candidates[item])).indices
                )
            ],
        }
        for item in selected
    ]


def _preview(index: ObservationIndex, arm: Arm) -> list[dict[str, object]]:
    """Emit bounded explainable genre peers and artist discovery proposals."""
    graph = genre_neighbors(index, arm)
    shared = (index.binary.T @ index.binary).tocsr()
    observed = index.binary.tocsc()
    transfer = _transfer(index, graph, arm)
    genres: list[dict[str, object]] = []
    for row, seed in enumerate(index.seeds):
        start, end = graph.indptr[row : row + 2]
        columns, values = graph.indices[start:end], graph.data[start:end]
        order = _top_indices(values, columns, TOP_K)
        scores = (index.binary @ transfer.getcol(row)).tocoo()
        known = observed.indices[observed.indptr[row] : observed.indptr[row + 1]]
        eligible = ~np.isin(scores.row, known)
        candidates, candidate_scores = scores.row[eligible], scores.data[eligible]
        selected = _top_indices(candidate_scores, candidates, TOP_K)
        genres.append(
            {
                "seed_id": seed,
                "observed_artist_count": len(known),
                "state": "supported" if len(order) else "abstained_insufficient_shared_artists",
                "peers": [
                    {
                        "seed_id": index.seeds[int(columns[item])],
                        "score": float(values[item]),
                        "shared_artist_count": int(shared[row, columns[item]]),
                        "role": "inferred_genre_overlap_neighbor",
                    }
                    for item in order
                ],
                "artist_candidates": [
                    {
                        "artist_mbid": index.artists[int(candidates[item])],
                        "score": float(candidate_scores[item]),
                        "role": "inferred_artist_candidate",
                        "via_seed_ids": [
                            index.seeds[int(column)]
                            for column in np.intersect1d(
                                columns, index.binary.getrow(int(candidates[item])).indices
                            )
                        ],
                    }
                    for item in selected
                ],
            }
        )
    return genres


def _write_json(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(value) + b"\n")


def _artist_query_coverage(index: ObservationIndex) -> dict[str, int]:
    """Count exact query abstentions through bounded genre pairs, never all artist pairs."""
    binary = index.binary
    shared = (binary.T @ binary).tocsr()
    supported = 0
    for row in range(len(index.artists)):
        columns = binary.indices[binary.indptr[row] : binary.indptr[row + 1]]
        supported += int(
            any(
                shared[left, right] >= MIN_SHARED
                for left, right in itertools.combinations(columns, 2)
            )
        )
    return {
        "source_singleton_artist_count": int(np.sum(np.diff(binary.indptr) == 1)),
        "supported_artist_query_count": supported,
        "abstained_artist_query_count": len(index.artists) - supported,
    }


def load_neighborhood_index(directory: Path) -> ObservationIndex:
    """Verify the local artifact byte bindings before querying retained observations."""
    report = json.loads((directory / "report.json").read_bytes())
    digest = report.pop("output_sha256")
    if hashlib.sha256(canonical_json(report)).hexdigest() != digest:
        raise ValueError("neighborhood report hash mismatch")
    for name in ("model.json", "identities.json", "observations.npz"):
        binding = report["files"][name]
        if sha256_file(directory / name) != (binding["sha256"], binding["bytes"]):
            raise ValueError("neighborhood artifact byte binding mismatch")
    identities = json.loads((directory / "identities.json").read_bytes())
    matrix = sparse.load_npz(directory / "observations.npz").tocsr()
    artists, seeds = tuple(identities["artists"]), tuple(identities["seeds"])
    if (
        matrix.shape != (len(artists), len(seeds))
        or len(artists) != report["artist_count"]
        or len(seeds) != report["observed_seed_count"]
        or tuple(sorted(set(artists))) != artists
        or tuple(sorted(set(seeds))) != seeds
        or not np.all(matrix.data == 1)
    ):
        raise ValueError("neighborhood sparse identity contract mismatch")
    return ObservationIndex(artists, seeds, matrix)


def build_neighborhoods(
    *, receipt_path: Path, object_store: Path, output: Path
) -> dict[str, object]:
    """Verify portable custody, compare fixed arms, evaluate once, and refit locally."""
    cache = Path(__file__).resolve().parents[3] / ".cache"
    if not output.resolve().is_relative_to(cache.resolve()):
        raise ValueError("research artifacts must remain below the checkout .cache")
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace an existing research run")
    receipt_bytes = receipt_path.read_bytes()
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(receipt_bytes)
    grouped: dict[str, set[str]] = defaultdict(set)
    for claim in iter_verified_portable_direct_proper_genre_claims(
        receipt, object_store=object_store
    ):
        grouped[claim.seed_id].add(claim.artist_mbid)
    memberships = {seed: tuple(sorted(artists)) for seed, artists in sorted(grouped.items())}
    outer_train, test = _split_memberships(memberships)
    inner_train, validation = _split_memberships(outer_train)
    inner = observation_index(inner_train)
    validation_metrics = {arm: evaluate(inner, validation, arm) for arm in ARMS}
    selected = max(
        ARMS,
        key=lambda arm: (
            validation_metrics[arm].recall_at_10,
            validation_metrics[arm].mrr_at_10,
            -ARMS.index(arm),
        ),
    )
    outer = observation_index(outer_train)
    # All arms are frozen before test evaluation; selection uses validation only.
    test_metrics = {arm: evaluate(outer, test, arm) for arm in ARMS}
    full = observation_index(memberships)
    model = {
        "revision": REVISION,
        "scope": "local_research_only",
        "fit": "full_source_refit",
        "selected_arm": selected,
        "public_export_authorized": False,
        "serving_authorized": False,
        "custody_receipt_output_sha256": receipt.output_sha256,
        "custody_object_sha256": receipt.claims_object_sha256,
        "input_role": "direct_artist_proper_genre_observations_only",
        "artist_candidates_evaluation": (
            "genre-to-artist ranking not evaluated by artist-to-genre recall"
        ),
        "genres": _preview(full, selected),
    }
    output.mkdir(parents=True)
    _write_json(output / "model.json", model)
    _write_json(output / "identities.json", {"artists": full.artists, "seeds": full.seeds})
    sparse.save_npz(output / "observations.npz", full.binary)
    report: dict[str, object] = {
        "revision": REVISION,
        "scope": "local_research_only",
        "custody_receipt_byte_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "custody_receipt_output_sha256": receipt.output_sha256,
        "custody_object_sha256": receipt.claims_object_sha256,
        "code_sha256": sha256_file(Path(__file__))[0],
        "sparse_engine_sha256": sha256_file(
            Path(__file__).parent / "full_graph_signal/sparse_baselines.py"
        )[0],
        "split_engine_sha256": sha256_file(
            Path(__file__).parents[1] / "peers/direct_custody_membership_holdout.py"
        )[0],
        "input_role": "direct_artist_proper_genre_observations_only",
        "claim_count": receipt.claim_count,
        "unique_observation_count": full.binary.nnz,
        "artist_count": len(full.artists),
        "artist_neighbor_query": _artist_query_coverage(full),
        "observed_seed_count": len(full.seeds),
        "seed_universe_claimed": False,
        "unobserved_seeds": "abstain; not part of source custody",
        "historical_coordinates_or_assignments_used": False,
        "names_used_for_training": False,
        "absence_is_negative": False,
        "independent_source_gold": False,
        "artist_neighbor_ranking_evaluated": False,
        "genre_to_artist_ranking_evaluated": False,
        "runtime_versions": {"numpy": np.__version__, "scipy": scipy.__version__},
        "public_export_authorized": False,
        "serving_authorized": False,
        "split_rule": "nested existing per-seed SHA256(seed,NUL,artist) lowest fifth; retain four",
        "split_counts": {
            "inner_train": inner.binary.nnz,
            "outer_train": outer.binary.nnz,
            "validation": sum(map(len, validation.values())),
            "test": sum(map(len, test.values())),
        },
        "selection_rule": "validation Recall@10, then MRR@10, then declared arm order",
        "selected_arm": selected,
        "settings": {
            "top_k": TOP_K,
            "minimum_shared_artists": MIN_SHARED,
            "shrinkage": SHRINKAGE,
            "block_size": BLOCK_SIZE,
            "max_artist_degree": MAX_ARTIST_DEGREE,
            "max_pair_visits": MAX_PAIR_VISITS,
            "max_genres": MAX_GENRES,
            "max_artists": MAX_ARTISTS,
        },
        "formulas": {
            "binary_cosine": "binary artist profiles; genre cosine",
            "degree_cosine": "artist row weight 1/sqrt(train artist degree); genre cosine",
            "degree_shrunk": "degree cosine * shared_count/(shared_count+5)",
            "specificity_transfer": "degree_shrunk; transfer weight /sqrt(source genre frequency)",
        },
        "validation": {arm: asdict(metric) for arm, metric in validation_metrics.items()},
        "test": {arm: asdict(metric) for arm, metric in test_metrics.items()},
        "files": {
            name: {"sha256": sha256_file(output / name)[0], "bytes": (output / name).stat().st_size}
            for name in ("model.json", "identities.json", "observations.npz")
        },
    }
    report["output_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
    _write_json(output / "report.json", report)
    return report
