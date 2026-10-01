"""Train-only native tag text and source cooccurrence representation experiment."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import replace
from typing import cast

import numpy as np
from scipy import sparse

from opennoise.common import canonical_json
from opennoise.ml.emergent_feature_graph import musical_feature_graph
from opennoise.ml.emergent_topics import (
    MUSIC_NAMESPACES,
    FeatureMatrix,
    TopicSettings,
    _centroid,
    _descriptors,
    _Node,
    _row_normalize,
    fit_topics,
)

REVISION = "emergent-native-tag-lexical-topics-v1"
LEXICAL_WEIGHT = 0.35
RESIDUAL_WEIGHT = 0.5
WORD_WEIGHT = 0.5
CHARACTER_ONLY_MINIMUM = 0.6
NEIGHBORS = 20
BLOCK_SIZE = 128
CHARACTER_SIZES = (3, 4, 5)


def _terms(value: str, *, characters: bool) -> tuple[str, ...]:
    words = cast("list[str]", re.findall(r"[^\W_]+", value, flags=re.UNICODE))
    if not characters:
        return tuple(words)
    return tuple(
        padded[start : start + size]
        for word in words
        for padded in (f" {word} ",)
        for size in CHARACTER_SIZES
        for start in range(max(0, len(padded) - size + 1))
    )


def _tfidf(values: tuple[str, ...], *, characters: bool) -> tuple[sparse.csr_matrix, str]:
    """Fit vocabulary and document frequency only to retained source tag values."""
    terms = [_terms(value, characters=characters) for value in values]
    vocabulary = tuple(sorted({term for row in terms for term in row}))
    lookup = {term: index for index, term in enumerate(vocabulary)}
    documents = Counter(term for row in terms for term in set(row))
    rows, columns, weights = [], [], []
    for row, tokens in enumerate(terms):
        for term, count in Counter(tokens).items():
            rows.append(row)
            columns.append(lookup[term])
            weights.append(
                (1 + np.log(count)) * (1 + np.log((len(values) + 1) / (documents[term] + 1)))
            )
    matrix = sparse.csr_matrix((weights, (rows, columns)), shape=(len(values), len(vocabulary)))
    return _row_normalize(matrix), hashlib.sha256(canonical_json(vocabulary)).hexdigest()


def lexical_graph(values: tuple[str, ...]) -> tuple[sparse.csr_matrix, dict[str, object]]:
    """Build bounded native-text affinities without external language-model weights."""
    word, word_hash = _tfidf(values, characters=False)
    character, character_hash = _tfidf(values, characters=True)
    rows, columns, weights = [], [], []
    for offset in range(0, len(values), BLOCK_SIZE):
        end = min(offset + BLOCK_SIZE, len(values))
        word_scores = (word[offset:end] @ word.T).toarray()
        character_scores = (character[offset:end] @ character.T).toarray()
        scores = WORD_WEIGHT * word_scores + (1 - WORD_WEIGHT) * character_scores
        scores[(word_scores == 0) & (character_scores < CHARACTER_ONLY_MINIMUM)] = 0
        for local, row in enumerate(range(offset, end)):
            scores[local, row] = 0
            candidates = np.flatnonzero(scores[local] > 0)
            selected = candidates[np.lexsort((candidates, -scores[local, candidates]))[:NEIGHBORS]]
            rows.extend([row] * len(selected))
            columns.extend(selected)
            weights.extend(scores[local, selected])
    directed = sparse.csr_matrix((weights, (rows, columns)), shape=(len(values), len(values)))
    graph = directed.maximum(directed.T).tocsr()
    return cast("sparse.csr_matrix", graph), {
        "word_vocabulary_sha256": word_hash,
        "character_vocabulary_sha256": character_hash,
        "word_vocabulary_size": word.shape[1],
        "character_vocabulary_size": character.shape[1],
        "lexical_edge_count": graph.nnz // 2,
        "word_weight": WORD_WEIGHT,
        "character_sizes": CHARACTER_SIZES,
        "character_only_minimum": CHARACTER_ONLY_MINIMUM,
        "neighbors": NEIGHBORS,
    }


def _stochastic(matrix: sparse.csr_matrix) -> sparse.csr_matrix:
    sums = np.asarray(matrix.sum(axis=1)).ravel()
    normalized = sparse.diags(1 / np.maximum(sums, 1e-12)) @ matrix
    return cast("sparse.csr_matrix", (normalized + sparse.diags((sums == 0).astype(float))).tocsr())


def lexical_representation(data: FeatureMatrix) -> tuple[FeatureMatrix, dict[str, object]]:
    """Diffuse source musical profiles while retaining exact original profile equivalence."""
    values, cooccurrence = musical_feature_graph(data)
    text_graph, metadata = lexical_graph(values)
    lookup = {value: position for position, value in enumerate(values)}
    columns, canonical = [], []
    for column, (namespace, value) in enumerate(data.features):
        if namespace in MUSIC_NAMESPACES:
            columns.append(column)
            canonical.append(lookup[value])
    projection = sparse.csr_matrix(
        (np.ones(len(columns)), (columns, canonical)), shape=(len(data.features), len(values))
    )
    source = _row_normalize((data.group_matrix @ projection).tocsr())
    transition = (1 - LEXICAL_WEIGHT) * _stochastic(cooccurrence) + LEXICAL_WEIGHT * _stochastic(
        text_graph
    )
    diffused = _row_normalize(
        (RESIDUAL_WEIGHT * source + (1 - RESIDUAL_WEIGHT) * source @ transition).tocsr()
    )
    facet_count = np.asarray(projection.sum(axis=0)).ravel()
    back = sparse.diags(1 / np.maximum(1, facet_count)) @ projection.T
    represented = _row_normalize((diffused @ back).tocsr())
    return replace(data, group_matrix=represented), {
        **metadata,
        "method": "native_value_word_character_tfidf_and_source_cooccurrence_diffusion",
        "canonical_value_count": len(values),
        "canonical_value_sha256": hashlib.sha256(canonical_json(values)).hexdigest(),
        "source_cooccurrence_edge_count": cooccurrence.nnz // 2,
        "lexical_transition_weight": LEXICAL_WEIGHT,
        "source_residual_weight": RESIDUAL_WEIGHT,
        "external_pretrained_weights_used": False,
        "artist_names_used": False,
        "historical_inputs_used": False,
        "context_facets_used_for_representation": False,
        "vocabulary_and_idf_fitted_on_training_values_only": True,
        "interpretation": "lexical_similarity_is_not_validated_musical_similarity",
    }


def fit_lexical_topics(
    data: FeatureMatrix, settings: TopicSettings | None = None, *, include_centroids: bool = False
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    """Fit with lexical profiles, retaining observed source descriptors and prediction centroids."""
    represented, metadata = lexical_representation(data)
    model, memberships = fit_topics(represented, settings, include_centroids=True)
    core = cast("dict[str, list[int]]", model["core_group_ids"])
    centers: dict[str, list[float]] = {}
    for item in cast("list[dict[str, object]]", model["communities"]):
        key = str(item["id"])
        groups = np.array(core[key], dtype=np.int32)
        centroid = _centroid(data.group_matrix[groups], data.group_counts[groups])
        source_node = _Node(groups, centroid, 0, None)
        descriptors = _descriptors(source_node, data)
        item["descriptors"] = descriptors
        item["label"] = " / ".join(str(descriptor["value"]) for descriptor in descriptors[:3])
        item["representation_core_mean_cosine"] = item["core_mean_cosine"]
        item["core_mean_cosine"] = float(
            np.average(
                np.asarray(data.group_matrix[groups] @ centroid).ravel(),
                weights=data.group_counts[groups],
            )
        )
        item["membership_score_method"] = "lexical_source_representation_cosine_uncalibrated"
        centers[key] = centroid.tolist()
    model["centroids"] = centers
    model["revision"] = REVISION
    model["lexical_representation"] = metadata
    model["centroid_role"] = "observed_source_feature_projection_for_prediction_and_display"
    if not include_centroids:
        model.pop("centroids")
        model.pop("core_group_ids")
    return model, memberships
