"""Paired fixed-target reconstruction measuring additional source evidence."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import (
    BLOCK_SIZE,
    _binary,
    _centroid_projection,
    _deepest_memberships,
    _facts,
    musical_value,
    partition_feature_file,
    rank_positive_features,
)
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import MAX_FEATURES as ENRICHMENT_MAX_FEATURES
from opennoise.ml.artist_feature_enrichment import EnrichmentSettings, fit_enrichment, read_profiles
from opennoise.ml.emergent_adaptive_topics import fit_adaptive_topics
from opennoise.ml.emergent_topics import MAX_FEATURES as TOPIC_MAX_FEATURES
from opennoise.ml.emergent_topics import TopicSettings, _normalize, _usable, load_features

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SPLIT_SALT = "bulk-source-increment-paired-positive-fold-v1-fixed-20260930"
PREDICTOR_SETTINGS = EnrichmentSettings(smoothing=4)
SCORERS = ("adaptive_topics", "feature_enrichment", "global_frequency", "proper_genre_conditional")
MAX_ARTISTS = 250_000
PREVIOUS_FEATURE_BOUND = 30_000


def _release_groups(path: Path) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            for feature in row["features"]:
                value = musical_value(feature)
                if value is not None and feature["namespace"].startswith("release_"):
                    for fact in _facts(row["artist_mbid"], feature, value):
                        result[fact.artist_id, fact.feature_id].add(fact.evidence_group)
    return result


def training_resource_counts(path: Path) -> dict[str, int | bool]:
    """Report actual accepted identities before support pruning or any model fitting."""
    profiles, _proper = read_profiles(path)
    canonical = {value for values in profiles.values() for value in values}
    identities: set[tuple[str, str]] = set()
    observations = maximum = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            facts = {
                (str(feature["namespace"]), _normalize(str(feature["value"])))
                for feature in row["features"]
            }
            facts = {key for key in facts if _usable(*key)}
            identities.update(facts)
            observations += len(facts)
            maximum = max(maximum, len(facts))
    return {
        "predictor_canonical_value_count": len(canonical),
        "community_raw_namespace_value_count": len(identities),
        "feature_observation_count": observations,
        "maximum_row_feature_count": maximum,
        "admissible_under_previous_predictor_feature_cap": len(canonical) <= PREVIOUS_FEATURE_BOUND,
        "admissible_under_previous_community_feature_cap": len(identities)
        <= PREVIOUS_FEATURE_BOUND,
    }


def prepare_paired_training(
    old: Path, augmented: Path, output: Path
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], list[tuple[str, str]], set[str]]:
    """Freeze one augmented target fold and remove its complete facts from both inputs."""
    old_full, _proper = read_profiles(old)
    augmented_full, _proper = read_profiles(augmented)
    if old_full.keys() != augmented_full.keys() or len(old_full) > MAX_ARTISTS:
        raise ValueError("paired source inputs must have the same bounded artist identity cohort")
    if any(set(values) - set(augmented_full[artist]) for artist, values in old_full.items()):
        raise ValueError(
            "augmented source removed old musical values; addition-only contrast invalid"
        )
    augmented_groups = _release_groups(augmented)
    if any(
        groups - augmented_groups.get(pair, set()) for pair, groups in _release_groups(old).items()
    ):
        raise ValueError("augmented source lost prior release-group provenance")
    augmented_train, _proper, targets, proper_values = partition_feature_file(
        augmented, output / "augmented-training.jsonl", salt=SPLIT_SALT
    )
    pairs = sorted({(fact.artist_id, fact.feature_id) for fact in targets})
    hidden = set(pairs)
    with old.open(encoding="utf-8") as source, (output / "old-training.jsonl").open("xb") as target:
        for line in source:
            row = json.loads(line)
            row["features"] = [
                feature
                for feature in row["features"]
                if (row["artist_mbid"], musical_value(feature)) not in hidden
            ]
            target.write(canonical_json(row) + b"\n")
    old_train, _proper = read_profiles(output / "old-training.jsonl")
    if any(
        value in old_train[artist] or value in augmented_train[artist] for artist, value in pairs
    ):
        raise ValueError("paired source split leaked a held-out musical value")
    (output / "held-out-pairs.json").write_bytes(canonical_json(pairs) + b"\n")
    return old_full, augmented_train, pairs, proper_values


def target_strata(
    pairs: Sequence[tuple[str, str]],
    old_full: Mapping[str, Sequence[str]],
    augmented_train: Mapping[str, Sequence[str]],
    proper_values: set[str],
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Use the same declared strata and denominators for every fitted source variant."""
    old_vocabulary = {value for values in old_full.values() for value in values}
    support = Counter(value for values in augmented_train.values() for value in values)
    result = {}
    for artist, value in pairs:
        strata = [
            "all",
            "proper_genre_values" if value in proper_values else "tag_only_values",
            "previous_artist_value" if value in old_full[artist] else "new_artist_value",
            "previous_global_value" if value in old_vocabulary else "new_global_value",
        ]
        if not augmented_train[artist]:
            strata.append("augmented_training_cold_artist")
        if support[value] == 0:
            strata.append("augmented_training_unseen_value")
        if support[value] <= 5:  # noqa: PLR2004 - prespecified rare-support diagnostic.
            strata.append("augmented_training_support_le5")
        result[artist, value] = tuple(strata)
    return result


def evidence_component_diagnostics(
    source: Path, held_pairs: Sequence[tuple[str, str]]
) -> dict[str, int | float]:
    """Count canonical-value components and replay complete release-group isolation."""
    profiles, _proper = read_profiles(source)
    pair_count = sum(len(values) for values in profiles.values())
    references = _release_groups(source)
    parents: dict[str, str] = {}

    def root(group: str) -> str:
        parents.setdefault(group, group)
        while parents[group] != group:
            parents[group] = parents[parents[group]]
            group = parents[group]
        return group

    for groups in references.values():
        representative = min(groups)
        for group in groups:
            left, right = root(representative), root(group)
            parents[max(left, right)] = min(left, right)
    sizes: Counter[str] = Counter()
    held: Counter[str] = Counter()
    hidden = set(held_pairs)
    for pair, groups in references.items():
        key = root(min(groups))
        sizes[key] += 1
        held[key] += pair in hidden
    if any(held[key] not in (0, count) for key, count in sizes.items()):
        raise ValueError("paired target fold split a global release evidence component")
    independent_pairs = pair_count - len(references)
    return {
        "canonical_positive_pair_count": pair_count,
        "canonical_evidence_component_count": independent_pairs + len(sizes),
        "release_group_identity_count": len(parents),
        "connected_release_component_count": len(sizes),
        "largest_component_positive_pair_count": max(
            [int(bool(independent_pairs)), *sizes.values()]
        ),
        "largest_held_component_positive_pair_count": max([int(bool(hidden)), *held.values()]),
        "actual_held_positive_fraction": len(hidden) / pair_count if pair_count else 0,
    }


def score_positive_rankings(
    ranks: Mapping[str, Sequence[str]],
    targets: Sequence[str],
    strata: Mapping[str, Sequence[str]],
    totals: dict[str, dict[str, list[float]]],
) -> None:
    """Count all held positives, including unsupported and unseen values, without negatives."""
    for scorer, values in ranks.items():
        if len(values) != len(set(values)) or len(values) > 10:  # noqa: PLR2004 - frozen rank limit.
            raise ValueError("paired scorer emitted duplicate or excessive rankings")
        positions = {value: position for position, value in enumerate(values, 1)}
        for value in targets:
            rank = positions.get(value)
            for stratum in strata[value]:
                counts = totals[scorer].setdefault(stratum, [0, 0, 0])
                counts[0] += 1
                counts[1] += int(rank is not None)
                counts[2] += 1 / rank if rank else 0


def _variant(
    training: Path,
    output: Path,
    targets: Mapping[str, list[str]],
    strata: Mapping[tuple[str, str], tuple[str, ...]],
    settings: TopicSettings,
) -> dict[str, object]:
    profiles, proper = read_profiles(training)
    predictor = fit_enrichment(
        profiles, proper, settings=PREDICTOR_SETTINGS, training_sha256=sha256_file(training)[0]
    )
    data = load_features(training, settings)
    model, memberships = fit_adaptive_topics(data, settings, include_centroids=True)
    artists = tuple(sorted(profiles))
    indices = {artist: index for index, artist in enumerate(artists)}
    vocabulary = tuple(sorted({value for values in profiles.values() for value in values}))
    observed = _binary(artists, profiles, vocabulary)
    genres = tuple(sorted({value for values in proper.values() for value in values}))
    genre_matrix = _binary(artists, proper, genres)
    genre_counts = np.asarray(genre_matrix.sum(axis=0)).ravel()
    conditional = (
        sparse.diags(1 / np.maximum(1, genre_counts)) @ genre_matrix.T @ observed
    ).tocsr()
    frequency = np.asarray(observed.sum(axis=0)).ravel()
    keys, centroids = _centroid_projection(model, data.features, vocabulary)
    weights = _deepest_memberships(artists, memberships, keys)
    totals: dict[str, dict[str, list[float]]] = {name: {} for name in SCORERS}
    active = tuple(sorted(targets))
    with output.open("xb") as stream:
        for offset in range(0, len(active), BLOCK_SIZE):
            block = active[offset : offset + BLOCK_SIZE]
            rows = [indices[artist] for artist in block]
            topic_scores = np.asarray(weights[rows] @ centroids)
            conditional_scores = (genre_matrix[rows] @ conditional).toarray()
            no_genres = np.asarray(genre_matrix[rows].sum(axis=1)).ravel() == 0
            conditional_scores[no_genres] = frequency
            enriched = predictor.rank_batch(
                {artist: profiles[artist] for artist in block},
                {artist: proper[artist] for artist in block},
            )
            for local, artist in enumerate(block):
                row = rows[local]
                known = observed.indices[observed.indptr[row] : observed.indptr[row + 1]]
                ranks = {"feature_enrichment": enriched[artist]}
                for name, scores in (
                    ("adaptive_topics", topic_scores[local]),
                    ("global_frequency", frequency),
                    ("proper_genre_conditional", conditional_scores[local]),
                ):
                    ranks[name] = tuple(
                        vocabulary[column] for column in rank_positive_features(scores, known)
                    )
                if any(set(values) & set(profiles[artist]) for values in ranks.values()):
                    raise ValueError("paired scorer emitted a known musical value")
                score_positive_rankings(
                    ranks,
                    targets[artist],
                    {value: strata[artist, value] for value in targets[artist]},
                    totals,
                )
                stream.write(canonical_json({"artist_mbid": artist, "rankings": ranks}) + b"\n")
    vocabulary_set = set(vocabulary)
    return {
        "training_sha256": sha256_file(training)[0],
        "training_pair_count": observed.nnz,
        "training_value_count": len(vocabulary),
        "cold_positive_count": sum(
            len(values) for artist, values in targets.items() if not profiles[artist]
        ),
        "unseen_positive_count": sum(
            value not in vocabulary_set for values in targets.values() for value in values
        ),
        "topic_coverage": model["coverage"],
        "metrics": {
            name: {
                key: {
                    "positive_count": int(n),
                    "hits_at_10": int(hits),
                    "recall_at_10": hits / n,
                    "mrr_at_10_per_positive": reciprocal / n,
                }
                for key, (n, hits, reciprocal) in values.items()
            }
            for name, values in totals.items()
        },
    }


def evaluate_paired_increment(
    *, old: Path, augmented: Path, output: Path, settings: TopicSettings | None = None
) -> dict[str, object]:
    """Fit fixed models twice with one target fold; never select parameters from scores."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a paired source-increment evaluation")
    resolved = settings or TopicSettings()
    project = Path(__file__).resolve().parents[3]
    paths = [Path(__file__)] + [
        project / "src/opennoise" / relative
        for relative in (
            "analysis/emergent_topic_holdout.py",
            "analysis/emergent_community_evaluation.py",
            "ml/artist_feature_enrichment.py",
            "ml/emergent_adaptive_topics.py",
            "ml/emergent_lexical_topics.py",
            "ml/emergent_feature_graph.py",
            "ml/emergent_topics.py",
        )
    ]
    bindings = {str(path): sha256_file(path)[0] for path in paths}
    output.mkdir(parents=True)
    declaration = {
        "revision": "paired-bulk-source-increment-prespecification-v1",
        "split_salt": SPLIT_SALT,
        "old_features_sha256": sha256_file(old)[0],
        "augmented_features_sha256": sha256_file(augmented)[0],
        "implementation_bindings": bindings,
        "predictor_settings": asdict(PREDICTOR_SETTINGS),
        "topic_settings": asdict(resolved),
        "scorers": SCORERS,
        "rank_limit": 10,
        "test_based_reselection": False,
        "shared_augmented_targets_and_denominators": True,
        "positive_only_reconstruction_not_independent_genre_truth": True,
        "prior_corpus_exploration": True,
        "resource_feature_bounds": {
            "previous": PREVIOUS_FEATURE_BOUND,
            "community_current": TOPIC_MAX_FEATURES,
            "predictor_current": ENRICHMENT_MAX_FEATURES,
        },
    }
    (output / "prespecification.json").write_bytes(canonical_json(declaration) + b"\n")
    old_full, augmented_train, pairs, proper_values = prepare_paired_training(
        old, augmented, output
    )
    components = evidence_component_diagnostics(augmented, pairs)
    resources = {
        variant: training_resource_counts(output / f"{variant}-training.jsonl")
        for variant in ("old", "augmented")
    }
    strata = target_strata(pairs, old_full, augmented_train, proper_values)
    targets: dict[str, list[str]] = defaultdict(list)
    for artist, value in pairs:
        targets[artist].append(value)
    (output / "prepared-partition.json").write_bytes(
        canonical_json(
            {
                "old_training_sha256": sha256_file(output / "old-training.jsonl")[0],
                "augmented_training_sha256": sha256_file(output / "augmented-training.jsonl")[0],
                "targets_sha256": sha256_file(output / "held-out-pairs.json")[0],
                "positive_pair_count": len(pairs),
                "evidence_components": components,
                "training_resources": resources,
            }
        )
        + b"\n"
    )
    results = {
        variant: _variant(
            output / f"{variant}-training.jsonl",
            output / f"{variant}-rankings.jsonl",
            targets,
            strata,
            resolved,
        )
        for variant in ("old", "augmented")
    }
    if bindings != {str(path): sha256_file(path)[0] for path in paths}:
        raise ValueError("paired diagnostic implementation changed during frozen fitting")
    denominators = Counter(key for values in strata.values() for key in values)
    for variant in results.values():
        for scorer in cast("dict[str, dict[str, dict[str, float]]]", variant["metrics"]).values():
            if {key: row["positive_count"] for key, row in scorer.items()} != denominators:
                raise ValueError("paired diagnostic target denominators differ")
    report = {
        "revision": "paired-bulk-source-increment-evaluation-v1",
        "scope": "local_research_only",
        "prespecification": declaration,
        "positive_pair_count": len(pairs),
        "evidence_components": components,
        "training_resources": resources,
        "results": results,
        "genre_truth_validated": False,
        "absence_is_negative": False,
        "files": {
            path.name: sha256_file(path)[0] for path in sorted(output.iterdir()) if path.is_file()
        },
    }
    report["output_sha256"] = sha256_json(report)
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report
