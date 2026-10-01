"""Source-derived hierarchical overlapping music topics, never native genre facts."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast

import numpy as np
from scipy import sparse

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file

REVISION: Final = "emergent-source-music-topics-v4"
MUSIC_NAMESPACES: Final = frozenset({"artist_genre", "artist_tag", "release_genre", "release_tag"})
CONTEXT_NAMESPACES: Final = frozenset({"area", "decade"})
NOISE: Final = frozenset(
    {
        "seen live",
        "favorites",
        "favourites",
        "favorite",
        "favourite",
        "my favorites",
        "music",
        "good",
        "awesome",
        "albums i own",
        "female vocalists",
        "male vocalists",
        "male vocalist",
        "female vocalist",
        "spotify",
        "last.fm",
        "lastfm",
        "all",
        "unknown",
        "untagged",
        "test",
        "check out",
        "to listen",
        "owned",
        "beautiful",
        "love",
        "best",
        "great",
        "singer",
        "british",
        "american",
        "english",
        "german",
        "french",
        "japanese",
    }
)
NONMUSICAL_TAGS: Final = frozenset(
    {
        "uk",
        "us",
        "usa",
        "gb",
        "de",
        "fr",
        "jp",
        "au",
        "nz",
        "united kingdom",
        "united states",
        "england",
        "scotland",
        "wales",
        "ireland",
        "london",
        "berlin",
        "paris",
        "tokyo",
        "new york",
        "los angeles",
        "canada",
        "germany",
        "france",
        "japan",
        "china",
        "sweden",
        "finland",
        "norway",
        "australia",
        "new zealand",
        "brazil",
        "argentina",
        "mexico",
        "spain",
        "italy",
        "russia",
        "poland",
        "netherlands",
        "belgium",
        "austria",
        "switzerland",
        "portugal",
        "turkey",
        "south korea",
        "korea",
        "south africa",
        "swedish",
        "norwegian",
        "finnish",
        "scottish",
        "irish",
        "dutch",
        "canadian",
        "australian",
        "producer",
        "composer",
        "musician",
        "remixer",
        "mc",
        "dj",
        "rapper",
        "songwriter",
        "guitarist",
        "drummer",
        "bassist",
        "pianist",
        "performer",
        "vocalist",
        "multi-instrumentalist",
        "recording engineer",
        "server name",
        "discogs",
        "wikidata",
        "musicbrainz",
        "wikipedia",
        "allmusic",
    }
)
GENERIC: Final = frozenset(
    {
        "rock",
        "pop",
        "electronic",
        "jazz",
        "classical",
        "hip hop",
        "dance",
        "alternative",
        "indie",
        "experimental",
    }
)
MAX_ARTISTS: Final = 1_000_000
MAX_FEATURES: Final = 50_000
MAX_ROW_FEATURES: Final = 512
MAX_FEATURE_OBSERVATIONS: Final = 8_000_000
EPSILON: Final = 1e-12
MAX_FEATURE_LABEL: Final = 100
DESCRIPTOR_COUNT: Final = 5
MAX_TREE_DEPTH: Final = 32
MAX_CUT_POWER: Final = 13
MAX_ITERATIONS: Final = 50
MIN_MUSIC_FEATURES: Final = 2


@dataclass(frozen=True)
class TopicSettings:
    """Fixed construction parameters; no test-based hyperparameter selection."""

    depths: tuple[int, int, int] = (4, 8, 12)
    minimum_artists: int = 20
    minimum_feature_support: int = 2
    iterations: int = 12
    minimum_split_gain: float = 0.002
    membership_threshold: float = 0.35
    maximum_memberships_per_level: int = 3
    example_limit: int = 30

    def __post_init__(self) -> None:
        """Reject invalid or unbounded topic construction parameters."""
        if not (0 < self.depths[0] < self.depths[1] < self.depths[2] <= MAX_CUT_POWER):
            raise ValueError("topic budget powers must increase from 1 through 13")
        if self.minimum_artists < MIN_MUSIC_FEATURES or self.minimum_feature_support < 1:
            raise ValueError("topic source support must be positive with at least two artists")
        if (
            not 1 <= self.iterations <= MAX_ITERATIONS
            or not 1 <= self.maximum_memberships_per_level <= MAX_CUT_POWER
        ):
            raise ValueError("topic iteration or overlap bound exceeded")
        if not 0 < self.membership_threshold <= 1 or not 0 <= self.minimum_split_gain < 1:
            raise ValueError("invalid topic score or gain threshold")


@dataclass(frozen=True)
class FeatureMatrix:
    """Canonical source features with exact music-profile equivalence classes."""

    artists: tuple[str, ...]
    features: tuple[tuple[str, str], ...]
    binary: sparse.csr_matrix
    weighted: sparse.csr_matrix
    musical_profiles: tuple[tuple[str, ...], ...]
    group_keys: tuple[tuple[str, ...], ...]
    artist_groups: np.ndarray
    group_counts: np.ndarray
    group_matrix: sparse.csr_matrix
    group_presence: sparse.csr_matrix
    filtered_feature_count: int
    input_sha256: str


@dataclass
class _Node:
    groups: np.ndarray
    centroid: np.ndarray
    depth: int
    parent: _Node | None
    children: tuple[_Node, ...] = ()
    split_gain: float = 0.0


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _usable(namespace: str, value: str) -> bool:
    if namespace not in MUSIC_NAMESPACES | CONTEXT_NAMESPACES:
        raise ValueError("unsupported feature namespace; names and historical fields are forbidden")
    return (
        bool(value)
        and len(value) <= MAX_FEATURE_LABEL
        and not (
            namespace in {"artist_tag", "release_tag"}
            and (
                value in NOISE | NONMUSICAL_TAGS
                or "://" in value
                or re.fullmatch(r"[\d\W]+", value) is not None
            )
        )
    )


def _row_normalize(matrix: sparse.csr_matrix) -> sparse.csr_matrix:
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    return cast(
        "sparse.csr_matrix", (sparse.diags(1 / np.maximum(EPSILON, norms)) @ matrix).tocsr()
    )


def load_features(  # noqa: C901, PLR0915 - one audited source-feature ingestion boundary.
    path: Path, settings: TopicSettings | None = None
) -> FeatureMatrix:
    """Load source-only feature JSONL and collapse identical musical evidence profiles.

    Namespace/value facts deduplicate per artist; vote magnitudes are capped at one.
    Duplicate values across source facets share one musical feature's total mass.
    Artist names, historical targets, and coordinates are rejected as namespaces.
    """
    resolved = settings or TopicSettings()
    records: dict[str, dict[tuple[str, str], float]] = {}
    frequency: Counter[tuple[str, str]] = Counter()
    filtered = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            raw = json.loads(line)
            artist = str(raw["artist_mbid"])
            if artist in records or not artist:
                raise ValueError("feature artists must be unique and nonempty")
            facts: dict[tuple[str, str], float] = {}
            for feature in raw["features"]:
                namespace, value = str(feature["namespace"]), _normalize(str(feature["value"]))
                weight = float(feature.get("weight", 1))
                if not np.isfinite(weight) or weight <= 0:
                    raise ValueError("feature weight must be finite and positive")
                if not feature.get("evidence_refs"):
                    raise ValueError("every feature requires retained source evidence references")
                if not _usable(namespace, value):
                    filtered += 1
                    continue
                key = namespace, value
                facts[key] = max(facts.get(key, 0), min(1.0, weight))
            if len(facts) > MAX_ROW_FEATURES:
                raise ValueError("artist feature bound exceeded; no silent truncation")
            records[artist] = facts
            frequency.update(facts.keys())
    if (
        len(records) > MAX_ARTISTS
        or len(frequency) > MAX_FEATURES
        or sum(frequency.values()) > MAX_FEATURE_OBSERVATIONS
    ):
        raise ValueError("feature identity bounds exceeded")
    artists = tuple(sorted(records))
    features = tuple(
        sorted(key for key, count in frequency.items() if count >= resolved.minimum_feature_support)
    )
    feature_lookup = {feature: i for i, feature in enumerate(features)}
    rows, columns, values = [], [], []
    profiles = []
    for row, artist in enumerate(artists):
        facts = records[artist]
        music = tuple(
            sorted(
                {
                    value
                    for namespace, value in facts
                    if namespace in MUSIC_NAMESPACES and (namespace, value) in feature_lookup
                }
            )
        )
        profiles.append(music)
        facets = Counter(
            value
            for namespace, value in facts
            if namespace in MUSIC_NAMESPACES and (namespace, value) in feature_lookup
        )
        for key, weight in sorted(facts.items()):
            if key not in feature_lookup:
                continue
            namespace, value = key
            multiplier = (
                (0.35 if value in GENERIC else 1.0) / facets[value]
                if namespace in MUSIC_NAMESPACES
                else 0.15
            )
            idf = 1 + np.log((len(artists) + 1) / (frequency[key] + 1))
            rows.append(row)
            columns.append(feature_lookup[key])
            values.append(weight * multiplier * idf)
    weighted = sparse.csr_matrix(
        (values, (rows, columns)), shape=(len(artists), len(features)), dtype=np.float64
    )
    binary = weighted.copy()
    binary.data[:] = 1
    group_keys = tuple(sorted(set(profiles)))
    group_lookup = {profile: i for i, profile in enumerate(group_keys)}
    artist_groups = np.array([group_lookup[profile] for profile in profiles], dtype=np.int32)
    group_counts = np.bincount(artist_groups, minlength=len(group_keys))
    aggregation = sparse.csr_matrix(
        (np.ones(len(artists)), (artist_groups, np.arange(len(artists)))),
        shape=(len(group_keys), len(artists)),
    )
    group_matrix = _row_normalize(
        (sparse.diags(1 / np.maximum(1, group_counts)) @ aggregation @ weighted).tocsr()
    )
    return FeatureMatrix(
        artists,
        features,
        binary,
        _row_normalize(weighted),
        tuple(profiles),
        group_keys,
        artist_groups,
        group_counts,
        group_matrix,
        (aggregation @ binary).tocsr(),
        filtered + sum(count for key, count in frequency.items() if key not in feature_lookup),
        sha256_file(path)[0],
    )


def _centroid(matrix: sparse.csr_matrix, counts: np.ndarray) -> np.ndarray:
    result = np.asarray(matrix.T @ counts).ravel()
    return result / max(EPSILON, float(np.linalg.norm(result)))


def _split_candidate(
    matrix: sparse.csr_matrix, counts: np.ndarray, settings: TopicSettings, seed_exponent: float
) -> tuple[np.ndarray, float] | None:
    if len(counts) < MIN_MUSIC_FEATURES or counts.sum() < settings.minimum_artists * 2:
        return None
    center = _centroid(matrix, counts)
    first = int(np.argmax((1 - np.asarray(matrix @ center).ravel()) * counts**seed_exponent))
    first_vector = matrix.getrow(first).toarray().ravel()
    second = int(np.argmax((1 - np.asarray(matrix @ first_vector).ravel()) * counts**seed_exponent))
    if first == second:
        return None
    centers = np.vstack((first_vector, matrix.getrow(second).toarray().ravel()))
    labels = np.zeros(len(counts), dtype=np.int8)
    for iteration in range(settings.iterations):
        scores = np.asarray(matrix @ centers.T)
        new_labels = np.argmax(scores, axis=1).astype(np.int8)
        if any(not np.any(new_labels == side) for side in (0, 1)):
            return None
        if iteration and np.array_equal(labels, new_labels):
            break
        labels = new_labels
        centers = np.vstack(
            [_centroid(matrix[labels == side], counts[labels == side]) for side in (0, 1)]
        )
    if any(counts[labels == side].sum() < settings.minimum_artists for side in (0, 1)):
        return None
    before = float(np.sum(counts * np.asarray(matrix @ center).ravel()))
    after = float(
        sum(
            np.sum(
                counts[labels == side] * np.asarray(matrix[labels == side] @ centers[side]).ravel()
            )
            for side in (0, 1)
        )
    )
    gain = (after - before) / counts.sum()
    return (labels, float(gain)) if gain >= settings.minimum_split_gain else None


def _split(
    matrix: sparse.csr_matrix, counts: np.ndarray, settings: TopicSettings
) -> tuple[np.ndarray, float] | None:
    """Compare fixed deterministic starts on training gain; validate converged support.

    Small initial Voronoi cells do not prove that a supported subdivision is
    absent. Full mass and square-root mass starts are both fitted before choosing.
    """
    candidates = [
        result
        for exponent in (1.0, 0.5)
        if (result := _split_candidate(matrix, counts, settings, exponent)) is not None
    ]
    return max(candidates, key=lambda candidate: candidate[1]) if candidates else None


def _split_node(node: _Node, data: FeatureMatrix, settings: TopicSettings) -> None:
    if node.depth >= MAX_TREE_DEPTH:
        return
    split = _split(data.group_matrix[node.groups], data.group_counts[node.groups], settings)
    if split is None:
        return
    labels, gain = split
    musical_columns = np.array(
        [namespace in MUSIC_NAMESPACES for namespace, _value in data.features]
    )
    musical = _row_normalize(data.group_matrix[node.groups][:, musical_columns].tocsr())
    counts = data.group_counts[node.groups]
    before = float(np.sum(counts * np.asarray(musical @ _centroid(musical, counts)).ravel()))
    after = sum(
        float(
            np.sum(
                counts[labels == side]
                * np.asarray(
                    musical[labels == side]
                    @ _centroid(musical[labels == side], counts[labels == side])
                ).ravel()
            )
        )
        for side in (0, 1)
    )
    if (after - before) / counts.sum() < settings.minimum_split_gain:
        return
    children = []
    for side in (0, 1):
        groups = node.groups[labels == side]
        children.append(
            _Node(
                groups,
                _centroid(data.group_matrix[groups], data.group_counts[groups]),
                node.depth + 1,
                node,
            )
        )
    node.children = tuple(sorted(children, key=lambda child: int(child.groups.min())))
    node.split_gain = gain


def _tree_frontiers(data: FeatureMatrix, settings: TopicSettings) -> list[list[_Node]]:
    """Refine the greatest weighted dispersion first, avoiding depth-driven imbalance."""
    eligible = np.array([i for i, profile in enumerate(data.group_keys) if profile], dtype=np.int32)
    if not len(eligible):
        raise ValueError("no usable musical profiles for topic construction")
    root = _Node(
        eligible, _centroid(data.group_matrix[eligible], data.group_counts[eligible]), 0, None
    )
    frontier = {id(root): root}
    queue: list[tuple[float, int, _Node]] = []

    def enqueue(node: _Node) -> None:
        counts = data.group_counts[node.groups]
        affinity = np.asarray(data.group_matrix[node.groups] @ node.centroid).ravel()
        dispersion = float(np.sum(counts * np.maximum(0, 1 - affinity)))
        heapq.heappush(queue, (-dispersion, int(node.groups.min()), node))

    enqueue(root)
    cuts = []
    for power in settings.depths:
        while queue and len(frontier) < 2**power:
            _priority, _tie, node = heapq.heappop(queue)
            _split_node(node, data, settings)
            if not node.children:
                continue
            del frontier[id(node)]
            for child in node.children:
                frontier[id(child)] = child
                enqueue(child)
        cuts.append(sorted(frontier.values(), key=lambda node: int(node.groups.min())))
    return cuts


def _node_id(node: _Node, data: FeatureMatrix) -> str:
    digest = hashlib.sha256(
        canonical_json([data.group_keys[int(i)] for i in sorted(node.groups)])
    ).hexdigest()
    return f"community-{digest[:20]}"


def _descriptors(node: _Node, data: FeatureMatrix) -> list[dict[str, object]]:
    support = np.asarray(data.group_presence[node.groups].sum(axis=0)).ravel()
    ranked = np.lexsort((np.arange(len(data.features)), -node.centroid))
    seen: set[str] = set()
    descriptors: list[dict[str, object]] = []
    for column in ranked:
        namespace, value = data.features[int(column)]
        if (
            namespace not in MUSIC_NAMESPACES
            or support[column] < MIN_MUSIC_FEATURES
            or value in seen
        ):
            continue
        seen.add(value)
        descriptors.append(
            {
                "feature_id": f"{namespace}:{value}",
                "namespace": namespace,
                "value": value,
                "weight": float(node.centroid[column]),
                "support_count": int(support[column]),
            }
        )
        if len(descriptors) == DESCRIPTOR_COUNT:
            break
    return descriptors


def fit_topics(  # noqa: C901, PLR0912, PLR0915 - keep hierarchy construction and assignment accounting together.
    data: FeatureMatrix, settings: TopicSettings | None = None, *, include_centroids: bool = False
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    """Construct a deterministic hierarchy and overlapping source-topic assignments.

    All artists with the same musical value set share one group vector and every
    assignment. Area, date, source facets, and vote counts cannot split that group.
    """
    resolved = settings or TopicSettings()
    frontiers = _tree_frontiers(data, resolved)
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
        "frontier_rule": "best_first_weighted_dispersion_with_2_to_power_budgets",
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


def build_emergent_topics(
    *, features_path: Path, output: Path, settings: TopicSettings | None = None
) -> dict[str, object]:
    """Write auditable local communities and complete artist assignment artifacts."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace existing emergent topic run")
    data = load_features(features_path, settings)
    model, assignments = fit_topics(data, settings, include_centroids=True)
    primary = model.pop("primary_assignments")
    centroids = cast("dict[str, list[float]]", model.pop("centroids"))
    core_groups = model.pop("core_group_ids")
    output.mkdir(parents=True)
    community_ids = tuple(sorted(centroids))
    centroid_matrix = sparse.csr_matrix(np.asarray([centroids[key] for key in community_ids]))
    sparse.save_npz(output / "topic-centroids.npz", centroid_matrix)
    (output / "topic-feature-identities.json").write_bytes(
        canonical_json(
            {
                "community_ids": community_ids,
                "features": [
                    {"namespace": namespace, "value": value} for namespace, value in data.features
                ],
            }
        )
        + b"\n"
    )
    (output / "core-profile-groups.json").write_bytes(canonical_json(core_groups) + b"\n")
    (output / "communities.json").write_bytes(canonical_json(model) + b"\n")
    (output / "primary-assignments.json").write_bytes(canonical_json(primary) + b"\n")
    with (output / "assignments.jsonl").open("wb") as stream:
        for artist, memberships in assignments.items():
            stream.write(
                canonical_json(
                    {
                        "artist_mbid": artist,
                        "memberships": memberships,
                        "state": "assigned"
                        if memberships
                        else "abstained_insufficient_musical_evidence",
                    }
                )
                + b"\n"
            )
    with (output / "musical-profiles.jsonl").open("wb") as stream:
        for artist, profile in zip(data.artists, data.musical_profiles, strict=True):
            stream.write(
                canonical_json({"artist_mbid": artist, "musical_features": profile}) + b"\n"
            )
    report = {
        "revision": REVISION,
        "scope": "local_research_only",
        "features_sha256": data.input_sha256,
        "code_sha256": sha256_file(Path(__file__))[0],
        "coverage": model["coverage"],
        "settings": model["settings"],
        "historical_inputs_used": False,
        "artist_names_used_for_construction": False,
        "native_genre_memberships_added": 0,
        "independent_relevance_evaluated": False,
        "public_export_authorized": False,
        "files": {
            name: {"sha256": sha256_file(output / name)[0], "bytes": (output / name).stat().st_size}
            for name in (
                "communities.json",
                "assignments.jsonl",
                "primary-assignments.json",
                "musical-profiles.jsonl",
                "topic-centroids.npz",
                "topic-feature-identities.json",
                "core-profile-groups.json",
            )
        },
    }
    report["output_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
    (output / "report.json").write_bytes(canonical_json(report) + b"\n")
    return report
