"""Adaptive source-supported coarse frontier over the frozen lexical representation.

The assignment adapter retains the frozen v4 source-evidence and ancestry
contract while accepting an independently constructed frontier. Frozen v4 and
lexical implementations are not modified by this separate experiment.
"""

from __future__ import annotations

import heapq
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import cast

import numpy as np

from opennoise.ml.emergent_lexical_topics import lexical_representation
from opennoise.ml.emergent_topics import (
    GENERIC,
    MIN_MUSIC_FEATURES,
    FeatureMatrix,
    TopicSettings,
    _centroid,
    _descriptors,
    _Node,
    _node_id,
    _split_node,
)

REVISION = "emergent-adaptive-lexical-coarse-topics-v1"
MINIMUM_REPRESENTATION_COHERENCE = 0.60
MINIMUM_SOURCE_COHERENCE = 0.50
MAXIMUM_BROAD_COMMUNITIES = 128
MINIMUM_SOURCE_SPLIT_GAIN = 0.002
MINIMUM_CROSS_PROFILE_COSINE = 0.10


def _coherence(node: _Node, data: FeatureMatrix) -> float:
    matrix = data.group_matrix[node.groups]
    counts = data.group_counts[node.groups]
    return float(np.average(np.asarray(matrix @ _centroid(matrix, counts)).ravel(), weights=counts))


def _cross_profile_coherence(node: _Node, data: FeatureMatrix) -> float:
    """Exclude all identical-profile self-pairs from weighted representation coherence."""
    if len(node.groups) == 1:
        return 1.0
    counts = data.group_counts[node.groups].astype(float)
    matrix = data.group_matrix[node.groups]
    summed = np.asarray(matrix.T @ counts).ravel()
    self_mass = float(np.square(counts).sum())
    denominator = float(counts.sum() ** 2 - self_mass)
    return float((summed @ summed - self_mass) / denominator) if denominator > 0 else 0.0


def adaptive_frontiers(  # noqa: C901, PLR0915 - one bounded evidence-driven frontier.
    represented: FeatureMatrix, source: FeatureMatrix, settings: TopicSettings
) -> tuple[list[list[_Node]], dict[str, object], dict[str, str]]:
    """Refine unsupported coarse leaves up to a fixed safety cap, never a count target."""
    eligible = np.array(
        [i for i, profile in enumerate(source.group_keys) if profile], dtype=np.int32
    )
    if not len(eligible):
        raise ValueError("no usable musical profiles for adaptive construction")
    root = _Node(
        eligible,
        _centroid(represented.group_matrix[eligible], represented.group_counts[eligible]),
        0,
        None,
    )
    frontier = {id(root): root}
    queue: list[tuple[float, int, _Node]] = []
    state: dict[int, str] = {}

    def inspect(node: _Node) -> None:
        actual = _coherence(node, source)
        representation = _coherence(node, represented)
        deficit = (
            max(0, MINIMUM_SOURCE_COHERENCE - actual)
            + max(0, MINIMUM_REPRESENTATION_COHERENCE - representation)
            + max(0, MINIMUM_CROSS_PROFILE_COSINE - _cross_profile_coherence(node, represented))
        )
        if deficit == 0:
            state[id(node)] = "supported_by_source_and_representation_coherence"
        else:
            state[id(node)] = "abstained_coarse_budget_exhausted"
            priority = float(source.group_counts[node.groups].sum()) * deficit
            heapq.heappush(queue, (-priority, int(node.groups.min()), node))

    inspect(root)
    while queue and len(frontier) < MAXIMUM_BROAD_COMMUNITIES:
        _priority, _tie, node = heapq.heappop(queue)
        _split_node(node, represented, settings)
        if not node.children:
            state[id(node)] = "abstained_no_supported_coarse_split"
            continue
        count = float(source.group_counts[node.groups].sum())
        gain = sum(
            _coherence(child, source) * source.group_counts[child.groups].sum()
            for child in node.children
        ) / count - _coherence(node, source)
        if gain < MINIMUM_SOURCE_SPLIT_GAIN:
            node.children = ()
            state[id(node)] = "abstained_insufficient_source_split_gain"
            continue
        del frontier[id(node)]
        for child in node.children:
            frontier[id(child)] = child
            inspect(child)
    coarse = sorted(frontier.values(), key=lambda node: int(node.groups.min()))
    coarse_states = {_node_id(node, source): state[id(node)] for node in coarse}
    queue = []

    def enqueue_fine(node: _Node) -> None:
        scores = np.asarray(represented.group_matrix[node.groups] @ node.centroid).ravel()
        dispersion = float(
            np.sum(represented.group_counts[node.groups] * np.maximum(0, 1 - scores))
        )
        heapq.heappush(queue, (-dispersion, int(node.groups.min()), node))

    for node in coarse:
        enqueue_fine(node)
    cuts = [coarse]
    for power in settings.depths[1:]:
        while queue and len(frontier) < 2**power:
            _priority, _tie, node = heapq.heappop(queue)
            _split_node(node, represented, settings)
            if not node.children:
                continue
            del frontier[id(node)]
            for child in node.children:
                frontier[id(child)] = child
                enqueue_fine(child)
        cuts.append(sorted(frontier.values(), key=lambda node: int(node.groups.min())))
    return (
        cuts,
        {
            "minimum_representation_mean_cosine": MINIMUM_REPRESENTATION_COHERENCE,
            "minimum_source_mean_cosine": MINIMUM_SOURCE_COHERENCE,
            "minimum_original_source_split_gain": MINIMUM_SOURCE_SPLIT_GAIN,
            "minimum_cross_profile_representation_cosine": MINIMUM_CROSS_PROFILE_COSINE,
            "cross_profile_self_pairs_excluded": True,
            "maximum_broad_communities": MAXIMUM_BROAD_COMMUNITIES,
            "broad_count_is_target": False,
            "broad_support_states": dict(Counter(coarse_states.values())),
        },
        coarse_states,
    )


def _assign_frontiers(  # noqa: C901, PLR0912, PLR0915 - keep hierarchy construction and assignment accounting together.
    data: FeatureMatrix,
    frontiers: list[list[_Node]],
    settings: TopicSettings | None = None,
    *,
    include_centroids: bool = False,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    """Construct a deterministic hierarchy and overlapping source-topic assignments.

    All artists with the same musical value set share one group vector and every
    assignment. Area, date, source facets, and vote counts cannot split that group.
    """
    resolved = settings or TopicSettings()
    nodes: dict[str, _Node] = {}
    levels: dict[str, str] = {}
    for level, frontier in zip(("broad", "sub", "micro"), frontiers, strict=True):
        for node in frontier:
            key = _node_id(node, data)
            if key not in nodes and (
                level == "broad" or len(_descriptors(node, data)) >= MIN_MUSIC_FEATURES
            ):
                nodes[key], levels[key] = node, level
    communities: dict[str, dict[str, object]] = {}
    node_ids = {id(node): key for key, node in nodes.items()}
    for key, node in sorted(nodes.items()):
        parent = node.parent
        while parent is not None and id(parent) not in node_ids:
            parent = parent.parent
        descriptors = _descriptors(node, data)
        communities[key] = {
            "id": key,
            "label": " / ".join(str(item["value"]) for item in descriptors[:3]),
            "label_origin": "derived_feature_descriptors",
            "level": levels[key],
            "parent_id": node_ids.get(id(parent)) if parent else None,
            "child_ids": [],
            "artist_count": 0,
            "core_artist_count": int(data.group_counts[node.groups].sum()),
            "distinct_profile_count": len(node.groups),
            "core_mean_cosine": float(
                np.average(
                    np.asarray(data.group_matrix[node.groups] @ node.centroid).ravel(),
                    weights=data.group_counts[node.groups],
                )
            ),
            "descriptors": descriptors,
            "artist_ids": [],
            "example_order": "model_cosine_descending_then_mbid_not_relevance",
            "role": "inferred_music_community",
            "quality_evaluated": False,
            "x": None,
            "y": None,
            "layout_state": "not_computed",
        }
    for key, community in communities.items():
        parent = community["parent_id"]
        if isinstance(parent, str):
            children = communities[parent]["child_ids"]
            assert isinstance(children, list)  # noqa: S101 - internal constructed node contract.
            children.append(key)
    musical_support = {
        key: set().union(*(set(data.group_keys[int(group)]) for group in node.groups))
        for key, node in nodes.items()
    }
    semantic_support: dict[str, Counter[str]] = {}
    for key, node in nodes.items():
        counts: Counter[str] = Counter()
        for group in node.groups:
            counts.update(
                {value: int(data.group_counts[group]) for value in data.group_keys[int(group)]}
            )
        semantic_support[key] = counts
    differentiating: dict[str, set[str]] = {}
    for key, node in nodes.items():
        parent = communities[key]["parent_id"]
        if not isinstance(parent, str):
            differentiating[key] = musical_support[key] - GENERIC
        else:
            total = float(data.group_counts[node.groups].sum())
            parent_total = float(data.group_counts[nodes[parent].groups].sum())
            differentiating[key] = {
                value
                for value, count in semantic_support[key].items()
                if value not in GENERIC
                and count >= MIN_MUSIC_FEATURES
                and count / total >= 1.25 * semantic_support[parent][value] / parent_total
            }
        communities[key]["differentiating_values"] = sorted(differentiating[key])
    group_memberships: dict[int, list[dict[str, object]]] = defaultdict(list)
    primary: dict[str, dict[str, str | None]] = {level: {} for level in ("broad", "sub", "micro")}
    for level in primary:
        keys = sorted(key for key in nodes if levels[key] == level)
        if not keys:
            continue
        centers = np.vstack([nodes[key].centroid for key in keys])
        value_positions: dict[str, list[int]] = defaultdict(list)
        for position, key in enumerate(keys):
            for value in musical_support[key]:
                value_positions[value].append(position)
        for offset in range(0, len(data.group_keys), 512):
            rows = np.arange(offset, min(offset + 512, len(data.group_keys)))
            scores = np.asarray(data.group_matrix[rows] @ centers.T)
            for local, group in enumerate(rows):
                if len(data.group_keys[int(group)]) < (
                    1 if level == "broad" else MIN_MUSIC_FEATURES
                ):
                    continue
                profile = set(data.group_keys[int(group)])
                overlap = Counter(
                    position for value in profile for position in value_positions[value]
                )
                eligible = np.array(
                    [
                        position
                        for position, count in sorted(overlap.items())
                        if count >= (1 if level == "broad" else MIN_MUSIC_FEATURES)
                        and (level == "broad" or bool(profile & differentiating[keys[position]]))
                    ],
                    dtype=np.int32,
                )
                selected = eligible[
                    np.lexsort((eligible, -scores[local, eligible]))[
                        : resolved.maximum_memberships_per_level
                    ]
                ]
                for position in selected:
                    if scores[local, position] < resolved.membership_threshold:
                        continue
                    group_memberships[int(group)].append(
                        {
                            "community_id": keys[int(position)],
                            "level": level,
                            "score": float(scores[local, position]),
                            "role": "inferred_community_membership",
                            "assignment_reason": "positive_source_topic_cosine",
                        }
                    )
    # Every fitted profile has an explicit core partition, independent of the
    # optional cosine cutoff used to propose additional overlapping memberships.
    for key, node in nodes.items():
        level = levels[key]
        scores = np.asarray(data.group_matrix[node.groups] @ node.centroid).ravel()
        for offset, group in enumerate(node.groups):
            profile = set(data.group_keys[int(group)])
            if level != "broad" and (
                len(profile & musical_support[key]) < MIN_MUSIC_FEATURES
                or not profile & differentiating[key]
            ):
                continue
            present = {str(item["community_id"]) for item in group_memberships.get(int(group), ())}
            if key not in present:
                group_memberships[int(group)].append(
                    {
                        "community_id": key,
                        "level": level,
                        "score": float(scores[offset]),
                        "role": "inferred_community_membership",
                        "assignment_reason": "hierarchical_core_partition",
                    }
                )
    # Fine-topic support implies ancestry even when a broad centroid is diffuse.
    for group, memberships in group_memberships.items():
        present = {str(item["community_id"]) for item in memberships}
        for item in list(memberships):
            parent = communities[str(item["community_id"])]["parent_id"]
            while isinstance(parent, str):
                if parent not in present:
                    score = float(
                        np.asarray(data.group_matrix[group] @ nodes[parent].centroid).ravel()[0]
                    )
                    memberships.append(
                        {
                            "community_id": parent,
                            "level": levels[parent],
                            "score": score,
                            "role": "inferred_community_membership",
                            "assignment_reason": "ancestor_of_supported_topic",
                        }
                    )
                    present.add(parent)
                parent = communities[parent]["parent_id"]
        memberships.sort(
            key=lambda item: (
                ("broad", "sub", "micro").index(str(item["level"])),
                -float(cast("float", item["score"])),
                str(item["community_id"]),
            )
        )
    assignments = {
        artist: group_memberships.get(int(data.artist_groups[row]), [])
        for row, artist in enumerate(data.artists)
    }
    examples: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for artist, memberships in assignments.items():
        for level, primary_rows in primary.items():
            candidates = [item for item in memberships if item["level"] == level]
            primary_rows[artist] = str(candidates[0]["community_id"]) if candidates else None
        for membership in memberships:
            key = str(membership["community_id"])
            score = float(cast("float", membership["score"]))
            examples[key].append((score, artist))
    for key, values in examples.items():
        communities[key]["artist_count"] = len(values)
        communities[key]["artist_ids"] = [
            artist
            for _score, artist in sorted(values, key=lambda pair: (-pair[0], pair[1]))[
                : resolved.example_limit
            ]
        ]
    model: dict[str, object] = {
        "revision": REVISION,
        "role": "inferred_emergent_music_communities",
        "scope": "local_research_only",
        "quality_evaluated": False,
        "public_export_authorized": False,
        "native_genre_memberships_added": 0,
        "settings": asdict(resolved),
        "frontier_rule": "adaptive_evidence_coarse_cut_then_fixed_fine_budgets",
        "ancestor_closure_may_exceed_direct_membership_limit": True,
        "core_partition_membership_is_inference": True,
        "communities": list(communities.values()),
        "primary_assignments": primary,
        "coverage": {
            "artist_count": len(data.artists),
            "source_feature_count": len(data.features),
            "distinct_musical_profile_count": len(data.group_keys),
            "singleton_musical_profile_artist_count": sum(
                len(profile) == 1 for profile in data.musical_profiles
            ),
            "empty_musical_profile_artist_count": sum(
                not profile for profile in data.musical_profiles
            ),
            "assigned_artist_count": sum(bool(values) for values in assignments.values()),
            "assigned_by_level": {
                level: sum(value is not None for value in rows.values())
                for level, rows in primary.items()
            },
            "community_count_by_level": dict(Counter(levels.values())),
            "filtered_feature_observation_count": data.filtered_feature_count,
        },
    }
    if include_centroids:
        model["centroids"] = {key: node.centroid.tolist() for key, node in nodes.items()}
        model["core_group_ids"] = {key: node.groups.tolist() for key, node in nodes.items()}
    return model, assignments


def fit_adaptive_topics(
    data: FeatureMatrix, settings: TopicSettings | None = None, *, include_centroids: bool = False
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    """Fit adaptive coarse groups and preserve observed-feature prediction projections."""
    resolved = settings or TopicSettings()
    represented, lexical = lexical_representation(data)
    frontiers, diagnostics, states = adaptive_frontiers(represented, data, resolved)
    model, memberships = _assign_frontiers(represented, frontiers, resolved, include_centroids=True)
    core = cast("dict[str, list[int]]", model["core_group_ids"])
    centers: dict[str, list[float]] = {}
    for item in cast("list[dict[str, object]]", model["communities"]):
        key = str(item["id"])
        groups = np.array(core[key], dtype=np.int32)
        centroid = _centroid(data.group_matrix[groups], data.group_counts[groups])
        node = _Node(groups, centroid, 0, None)
        descriptors = _descriptors(node, data)
        item["descriptors"] = descriptors
        item["label"] = " / ".join(str(descriptor["value"]) for descriptor in descriptors[:3])
        item["representation_core_mean_cosine"] = item["core_mean_cosine"]
        item["core_mean_cosine"] = _coherence(node, data)
        item["membership_score_method"] = "lexical_source_representation_cosine_uncalibrated"
        if key in states:
            item["cross_profile_representation_cosine"] = _cross_profile_coherence(
                node, represented
            )
            item["coarse_support_state"] = states[key]
            item["coarse_evidence_supported"] = states[key].startswith("supported_")
        centers[key] = centroid.tolist()
    model["centroids"] = centers
    model["lexical_representation"] = lexical
    model["adaptive_coarse_cut"] = diagnostics
    model["unsupported_broad_nodes_are_explicit_candidates_not_supported_taxonomy"] = True
    model["centroid_role"] = "observed_source_feature_projection_for_prediction_and_display"
    if not include_centroids:
        model.pop("centroids")
        model.pop("core_group_ids")
    return model, memberships
