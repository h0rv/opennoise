"""Frozen within-source feature reconstruction with duplicate-safe held-out positives."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np
from pydantic import TypeAdapter
from scipy import sparse

from opennoise.analysis.emergent_community_evaluation import (
    FeatureFact,
    split_feature_evidence,
)
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.emergent_topics import (
    MUSIC_NAMESPACES,
    FeatureMatrix,
    TopicSettings,
    _normalize,
    _usable,
    fit_topics,
    load_features,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SPLIT_SALT = "emergent-musical-feature-holdout-v1-fixed-20260930"
RANK_LIMIT = 10
BLOCK_SIZE = 256
_RG = re.compile(r"(?:release-group[/:]|release_group[/:])([0-9a-f-]{36})")


class TopicFitter(Protocol):
    """A training-only topic fitter exposing diagnostic centroids and memberships."""

    def __call__(
        self, data: FeatureMatrix, settings: TopicSettings, *, include_centroids: bool
    ) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
        """Fit only the supplied, already partitioned observations."""
        ...


@dataclass(frozen=True)
class TopicFitterBinding:
    """Name and pin an alternative fitter's implementation dependencies."""

    name: str
    fitter: TopicFitter
    implementation_paths: tuple[Path, ...]

    def code_bindings(self) -> dict[str, str]:
        """Bind implementation bytes in addition to the shared source feature reader."""
        if not self.name or not self.implementation_paths:
            raise ValueError("alternative fitter requires a name and implementation bindings")
        return {str(path.resolve()): sha256_file(path)[0] for path in self.implementation_paths}


def musical_value(feature: Mapping[str, object]) -> str | None:
    """Apply only the model's fixed semantic filter, without fitting frequencies or IDF."""
    namespace = str(feature["namespace"])
    value = _normalize(str(feature["value"]))
    return value if namespace in MUSIC_NAMESPACES and _usable(namespace, value) else None


def _facts(artist: str, feature: Mapping[str, object], value: str) -> list[FeatureFact]:
    if str(feature["namespace"]).startswith("release_"):
        groups = {
            match.group(1)
            for reference in TypeAdapter(list[str]).validate_python(feature["evidence_refs"])
            for match in _RG.finditer(reference)
        }
        if not groups:
            raise ValueError("release feature holdout requires exact release-group provenance")
        return [FeatureFact(artist, value, f"release-group:{group}") for group in sorted(groups)]
    group = hashlib.sha256(canonical_json([artist, value])).hexdigest()
    return [FeatureFact(artist, value, f"artist-value:{group}")]


def partition_feature_file(
    source: Path, destination: Path, *, salt: str = SPLIT_SALT
) -> tuple[
    dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], tuple[FeatureFact, ...], set[str]
]:
    """Remove all copies of each held musical value before any model fitting."""
    if destination.exists():
        raise FileExistsError("refusing to replace a held-out training partition")
    rows: list[dict[str, object]] = []
    evidence: list[FeatureFact] = []
    seen: set[str] = set()
    proper_values: set[str] = set()
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            row = TypeAdapter(dict[str, object]).validate_json(line)
            artist = str(row["artist_mbid"])
            if artist in seen:
                raise ValueError("feature partition repeats an artist identity")
            seen.add(artist)
            for feature in TypeAdapter(list[dict[str, object]]).validate_python(row["features"]):
                value = musical_value(feature)
                if value is not None:
                    evidence.extend(_facts(artist, feature, value))
                    if feature["namespace"] == "artist_genre":
                        proper_values.add(value)
            rows.append(row)
    train, hidden = split_feature_evidence(evidence, salt=salt)
    withheld = {(fact.artist_id, fact.feature_id) for fact in hidden}
    profiles: dict[str, tuple[str, ...]] = {}
    proper: dict[str, tuple[str, ...]] = {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        for row in rows:
            artist = str(row["artist_mbid"])
            retained = [
                feature
                for feature in TypeAdapter(list[dict[str, object]]).validate_python(row["features"])
                if (artist, musical_value(feature)) not in withheld
            ]
            values = {
                value for feature in retained if (value := musical_value(feature)) is not None
            }
            profiles[artist] = tuple(sorted(values))
            proper[artist] = tuple(
                sorted(
                    {
                        value
                        for feature in retained
                        if feature["namespace"] == "artist_genre"
                        and (value := musical_value(feature)) is not None
                    }
                )
            )
            stream.write(canonical_json({**row, "features": retained}) + b"\n")
    # All target copies were grouped before removal; unseen/cold positives remain targets.
    actual = {(artist, value) for artist, values in profiles.items() for value in values}
    if actual != {(fact.artist_id, fact.feature_id) for fact in train} or actual & withheld:
        raise ValueError("held-out feature removal did not replay the grouped split")
    return profiles, proper, hidden, proper_values


def _binary(
    artists: Sequence[str], profiles: Mapping[str, tuple[str, ...]], values: Sequence[str]
) -> sparse.csr_matrix:
    lookup = {value: column for column, value in enumerate(values)}
    rows, columns = [], []
    for row, artist in enumerate(artists):
        for value in profiles[artist]:
            rows.append(row)
            columns.append(lookup[value])
    return sparse.csr_matrix(
        (np.ones(len(rows)), (rows, columns)), shape=(len(artists), len(values))
    )


def rank_positive_features(scores: np.ndarray, known: np.ndarray) -> tuple[int, ...]:
    """Rank bounded positive candidates with deterministic canonical-value tie order."""
    scores = scores.copy()
    scores[known] = -np.inf
    eligible = np.flatnonzero(scores > 0)
    if len(eligible) > RANK_LIMIT:
        cutoff = np.partition(scores[eligible], -RANK_LIMIT)[-RANK_LIMIT]
        eligible = eligible[scores[eligible] >= cutoff]
    return tuple(
        int(value) for value in eligible[np.lexsort((eligible, -scores[eligible]))[:RANK_LIMIT]]
    )


def _centroid_projection(
    model: Mapping[str, object], features: Sequence[tuple[str, str]], vocabulary: Sequence[str]
) -> tuple[tuple[str, ...], np.ndarray]:
    retained = TypeAdapter(dict[str, list[float]]).validate_python(model["centroids"])
    keys = tuple(sorted(retained))
    values = {value: column for column, value in enumerate(vocabulary)}
    raw = np.array([retained[key] for key in keys])
    result = np.zeros((len(keys), len(vocabulary)))
    for column, (namespace, value) in enumerate(features):
        if namespace in MUSIC_NAMESPACES:
            result[:, values[value]] += raw[:, column]
    return keys, result


def _deepest_memberships(
    artists: Sequence[str], memberships: Mapping[str, list[dict[str, object]]], keys: Sequence[str]
) -> sparse.csr_matrix:
    positions = {key: column for column, key in enumerate(keys)}
    rows, columns, values = [], [], []
    for row, artist in enumerate(artists):
        for level in ("micro", "sub", "broad"):
            selected = [entry for entry in memberships[artist] if entry["level"] == level]
            if selected:
                total = float(sum(float(cast("float", entry["score"])) for entry in selected))
                if total <= 0:
                    raise ValueError("selected topic scores must have positive total weight")
                for entry in selected:
                    rows.append(row)
                    columns.append(positions[str(entry["community_id"])])
                    values.append(float(cast("float", entry["score"])) / total)
                break
    return sparse.csr_matrix((values, (rows, columns)), shape=(len(artists), len(keys)))


def _metric(hits: int, reciprocal: float, positives: int) -> dict[str, int | float | None]:
    return {
        "positive_count": positives,
        "hits_at_10": hits,
        "recall_at_10": hits / positives if positives else None,
        "mrr_at_10_per_positive": reciprocal / positives if positives else None,
    }


def evaluate_topic_feature_holdout(  # noqa: C901, PLR0915 - seal one split, fit, scoring, and code-binding boundary.
    *,
    features_path: Path,
    output: Path,
    settings: TopicSettings,
    fitter_binding: TopicFitterBinding | None = None,
) -> dict[str, object]:
    """Fit once after splitting, then compare fixed centroid and two baseline scorers."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a feature holdout run")
    output.mkdir(parents=True)
    training = output / "training-features.jsonl"
    profiles, proper, targets, proper_values = partition_feature_file(features_path, training)
    target_pairs = sorted({(fact.artist_id, fact.feature_id) for fact in targets})
    (output / "held-out-pairs.json").write_bytes(canonical_json(target_pairs) + b"\n")
    # The partition and parameters are frozen before the training reader is called.
    declaration: dict[str, object] = {
        "split_salt": SPLIT_SALT,
        "settings": asdict(settings),
        "source_sha256": sha256_file(features_path)[0],
        "training_sha256": sha256_file(training)[0],
        "targets_sha256": sha256_file(output / "held-out-pairs.json")[0],
        "scorers": [
            "deepest_assigned_topic_centroids",
            "global_frequency",
            "proper_genre_conditional",
        ],
        "rank_limit": RANK_LIMIT,
        "model_code_sha256": sha256_file(Path(__file__).parents[1] / "ml/emergent_topics.py")[0],
        "evaluator_sha256": sha256_file(Path(__file__))[0],
    }
    alternative = (
        {"name": fitter_binding.name, "implementation_bindings": fitter_binding.code_bindings()}
        if fitter_binding is not None
        else None
    )
    if alternative is not None:
        declaration["alternative_fitter"] = alternative
    (output / "pre-fit-declaration.json").write_bytes(canonical_json(declaration) + b"\n")
    data = load_features(training, settings)
    fit = fitter_binding.fitter if fitter_binding is not None else fit_topics
    model, memberships = fit(data, settings, include_centroids=True)
    artists = tuple(sorted(profiles))
    artist_index = {artist: row for row, artist in enumerate(artists)}
    vocabulary = tuple(sorted({value for values in profiles.values() for value in values}))
    value_index = {value: column for column, value in enumerate(vocabulary)}
    observed = _binary(artists, profiles, vocabulary)
    genres = tuple(sorted({value for values in proper.values() for value in values}))
    genre_matrix = _binary(artists, proper, genres)
    genre_counts = np.asarray(genre_matrix.sum(axis=0)).ravel()
    conditional = (
        sparse.diags(1 / np.maximum(1, genre_counts)) @ genre_matrix.T @ observed
    ).tocsr()
    frequency = np.asarray(observed.sum(axis=0)).ravel()
    keys, centroids = _centroid_projection(model, data.features, vocabulary)
    topic_weights = _deepest_memberships(artists, memberships, keys)
    by_artist: dict[int, list[tuple[str, int | None]]] = defaultdict(list)
    for artist, value in target_pairs:
        by_artist[artist_index[artist]].append((value, value_index.get(value)))
    active = sorted(by_artist)
    scorers = TypeAdapter(list[str]).validate_python(declaration["scorers"])
    totals = {
        name: {
            stratum: [0, 0.0, 0] for stratum in ("all", "proper_genre_values", "tag_only_values")
        }
        for name in scorers
    }
    for offset in range(0, len(active), BLOCK_SIZE):
        rows = active[offset : offset + BLOCK_SIZE]
        predicted = np.asarray(topic_weights[rows] @ centroids)
        conditioned = (genre_matrix[rows] @ conditional).toarray()
        without_genre = np.asarray(genre_matrix[rows].sum(axis=1)).ravel() == 0
        conditioned[without_genre] = frequency
        for local, row in enumerate(rows):
            known = observed.indices[observed.indptr[row] : observed.indptr[row + 1]]
            candidates = (predicted[local], frequency, conditioned[local])
            for name, values in zip(scorers, candidates, strict=True):
                ranking = {
                    column: rank
                    for rank, column in enumerate(rank_positive_features(values, known), 1)
                }
                for value, column in by_artist[row]:
                    rank = ranking.get(column) if column is not None else None
                    for stratum in (
                        "all",
                        "proper_genre_values" if value in proper_values else "tag_only_values",
                    ):
                        count = totals[name][stratum]
                        count[0] += int(rank is not None)
                        count[1] += 1 / rank if rank is not None else 0
                        count[2] += 1
    report: dict[str, object] = {
        "revision": "emergent-topic-feature-holdout-v1",
        "scope": "local_research_only",
        "evaluation_role": "within_source_reconstruction_not_independent_genre_truth",
        "declaration": declaration,
        "model_code_sha256": sha256_file(Path(__file__).parents[1] / "ml/emergent_topics.py")[0],
        "evaluator_sha256": sha256_file(Path(__file__))[0],
        "source_artist_count": len(artists),
        "training_pair_count": observed.nnz,
        "training_feature_count": len(vocabulary),
        "positive_pair_count": len(target_pairs),
        "cold_artist_positive_count": sum(not profiles[artist] for artist, _value in target_pairs),
        "unseen_feature_positive_count": sum(
            value not in value_index for _artist, value in target_pairs
        ),
        "model_training_coverage": model["coverage"],
        "metrics": {
            name: {
                stratum: _metric(int(values[0]), float(values[1]), int(values[2]))
                for stratum, values in strata.items()
            }
            for name, strata in totals.items()
        },
        "absence_is_negative": False,
        "all_duplicate_facets_removed_before_fit": True,
        "release_group_evidence_kept_together": True,
        "test_based_reselection": False,
        "genre_names_validated": False,
        "source_conditioning_note": (
            "Distinct values in the same artist response may straddle the split; "
            "shared votes or source facets for one value cannot."
        ),
    }
    if (
        report["model_code_sha256"] != declaration["model_code_sha256"]
        or report["evaluator_sha256"] != declaration["evaluator_sha256"]
    ):
        raise ValueError("evaluation code changed during the frozen holdout run")
    if fitter_binding is not None and alternative is not None:
        if fitter_binding.code_bindings() != alternative["implementation_bindings"]:
            raise ValueError("alternative fitter code changed during the frozen holdout run")
        report["alternative_fitter"] = alternative
    report["output_sha256"] = sha256_json(report)
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report
