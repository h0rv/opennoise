"""Build an explainable public-only music graph without audio or historical inputs."""

import hashlib
import json
import math
import resource
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from pydantic import BaseModel
from scipy import sparse
from scipy.linalg import eigh
from scipy.sparse.csgraph import connected_components, laplacian
from scipy.sparse.linalg import eigsh

from musix.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    FacetAgreement,
    GenreCoordinate,
    GenreIdentity,
    GenreNeighbor,
    GenreProfile,
    MembershipComponent,
    MembershipFacet,
    MembershipScore,
    MetadataCandidate,
    MetadataKind,
    ModelCoverage,
    ModelResources,
    ProfileKind,
    PublicArtifact,
    PublicModelArtifact,
    PublicModelInput,
    PublicModelSettings,
    RepresentativeItem,
    SimilarityMetric,
)
from musix.types import Sha256

_DENSE_EIGEN_LIMIT = 64
_PAIR_COMPONENT_SIZE = 2
_LAYOUT_METRIC: SimilarityMetric = "weighted_jaccard"


class PublicModelLimitError(RuntimeError):
    """Report that a declared laptop bound was exceeded."""


@dataclass(frozen=True, slots=True)
class _PropagationContext:
    raw_edge_weights: Mapping[tuple[str, str], float]
    strength: Mapping[str, float]
    seeds: Mapping[str, list[MembershipScore]]
    direct_pairs: set[tuple[str, str]]


def _canonical_bytes(value: BaseModel | dict[str, object]) -> bytes:
    if isinstance(value, BaseModel):
        return json.dumps(
            json.loads(value.model_dump_json()),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256(value: BaseModel | dict[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _output_payload(  # noqa: PLR0913
    *,
    profiles: tuple[GenreProfile, ...],
    neighbors: tuple[GenreNeighbor, ...],
    coordinates: tuple[GenreCoordinate, ...],
    representatives: tuple[RepresentativeItem, ...],
    facet_agreement: tuple[FacetAgreement, ...],
    coverage: ModelCoverage,
    export_allowed: bool,
    genres: tuple[GenreIdentity, ...],
    artifacts: tuple[PublicArtifact, ...],
) -> dict[str, object]:
    """Build the stable logical payload covered by the published output hash."""
    return {
        "profiles": [item.model_dump(mode="json") for item in profiles],
        "neighbors": [item.model_dump(mode="json") for item in neighbors],
        "coordinates": [item.model_dump(mode="json") for item in coordinates],
        "representatives": [item.model_dump(mode="json") for item in representatives],
        "facet_agreement": [item.model_dump(mode="json") for item in facet_agreement],
        "coverage": coverage.model_dump(mode="json"),
        "export_allowed": export_allowed,
        "genres": [item.model_dump(mode="json") for item in genres],
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
    }


def public_model_output_sha256(artifact: PublicModelArtifact) -> Sha256:
    """Recompute the logical hash of a parsed public model artifact."""
    return _sha256(
        _output_payload(
            profiles=artifact.profiles,
            neighbors=artifact.neighbors,
            coordinates=artifact.coordinates,
            representatives=artifact.representatives,
            facet_agreement=artifact.facet_agreement,
            coverage=artifact.coverage,
            export_allowed=artifact.export_allowed,
            genres=artifact.genres,
            artifacts=artifact.artifacts,
        )
    )


def _peak_rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1_024


def _check_input_limits(inputs: PublicModelInput, settings: PublicModelSettings) -> None:
    artists = {item.artist_id for item in inputs.direct_memberships}
    artists.update(
        artist
        for pair in inputs.artist_pairs
        for artist in (pair.left_artist_id, pair.right_artist_id)
    )
    genres = {item.genre_id for item in inputs.direct_memberships}
    genres.update(item.genre_id for item in inputs.metadata_candidates)
    checks = (
        (len(artists), settings.max_artists, "artists"),
        (len(genres), settings.max_genres, "genres"),
        (len(inputs.artist_pairs), settings.max_artist_pairs, "artist pairs"),
        (
            len(inputs.direct_memberships),
            settings.max_direct_memberships,
            "direct memberships",
        ),
    )
    for actual, limit, label in checks:
        if actual > limit:
            raise PublicModelLimitError(f"{label} exceed declared limit {limit}")


def _direct_scores(
    evidence: Iterable[DirectMembershipEvidence],
) -> tuple[MembershipScore, ...]:
    rows = tuple(evidence)
    artist_count = len({item.artist_id for item in rows})
    genre_artists: dict[tuple[MembershipFacet, str], set[str]] = defaultdict(set)
    raw: dict[tuple[str, str, MembershipFacet], float] = defaultdict(float)
    refs: dict[tuple[str, str, MembershipFacet], set[str]] = defaultdict(set)
    for item in rows:
        genre_artists[(item.facet, item.genre_id)].add(item.artist_id)
        raw[(item.artist_id, item.genre_id, item.facet)] += float(item.value)
        refs[(item.artist_id, item.genre_id, item.facet)].add(item.evidence_ref)
    facet_scores: dict[tuple[str, str, MembershipFacet], float] = {}
    maxima: dict[tuple[MembershipFacet, str], float] = defaultdict(float)
    for key, value in raw.items():
        _artist_id, genre_id, facet = key
        document_frequency = len(genre_artists[(facet, genre_id)])
        score = math.log1p(value) * (math.log((1 + artist_count) / (1 + document_frequency)) + 1)
        facet_scores[key] = score
        maxima[(facet, genre_id)] = max(maxima[(facet, genre_id)], score)
    combined: dict[tuple[str, str], float] = defaultdict(float)
    components: dict[tuple[str, str], list[MembershipComponent]] = defaultdict(list)
    for (artist_id, genre_id, facet), value in facet_scores.items():
        maximum = maxima[(facet, genre_id)]
        normalized = value / maximum
        combined[(artist_id, genre_id)] = max(combined[(artist_id, genre_id)], normalized)
        components[(artist_id, genre_id)].append(
            MembershipComponent(
                component_kind=facet,
                raw_value=raw[(artist_id, genre_id, facet)],
                normalized_value=round(normalized, 12),
                evidence_refs=tuple(sorted(refs[(artist_id, genre_id, facet)])),
            )
        )
    return tuple(
        MembershipScore(
            artist_id=artist_id,
            genre_id=genre_id,
            profile_kind="direct",
            score=round(score, 12),
            evidence_refs=tuple(
                sorted(
                    evidence_ref
                    for component in components[(artist_id, genre_id)]
                    for evidence_ref in component.evidence_refs
                )
            ),
            components=tuple(
                sorted(components[(artist_id, genre_id)], key=lambda item: item.component_kind)
            ),
        )
        for (artist_id, genre_id), score in sorted(combined.items())
    )


def _eligible_pair(
    pair: ArtistPairEvidence,
    settings: PublicModelSettings,
) -> bool:
    return (
        pair.listener_day_support >= settings.minimum_pair_support
        and pair.supporting_windows >= settings.minimum_pair_windows
    )


def _one_hop_scores(
    pairs: Iterable[ArtistPairEvidence],
    direct: tuple[MembershipScore, ...],
    settings: PublicModelSettings,
) -> tuple[MembershipScore, ...]:
    eligible = tuple(pair for pair in pairs if _eligible_pair(pair, settings))
    raw_edge_weights = {
        (pair.left_artist_id, pair.right_artist_id): math.log1p(pair.listener_day_support)
        for pair in eligible
    }
    strength: dict[str, float] = defaultdict(float)
    for (left, right), value in raw_edge_weights.items():
        strength[left] += value
        strength[right] += value
    seeds: dict[str, list[MembershipScore]] = defaultdict(list)
    direct_pairs = {(item.artist_id, item.genre_id) for item in direct}
    for item in direct:
        seeds[item.artist_id].append(item)
    contributions, refs = _propagate_edges(
        eligible,
        _PropagationContext(
            raw_edge_weights=raw_edge_weights,
            strength=strength,
            seeds=seeds,
            direct_pairs=direct_pairs,
        ),
        settings,
    )
    maxima: dict[str, float] = defaultdict(float)
    for (_artist, genre), score in contributions.items():
        maxima[genre] = max(maxima[genre], score)
    by_genre: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (artist, genre), score in contributions.items():
        by_genre[genre].append((artist, score / maxima[genre]))
    result: list[MembershipScore] = []
    for genre, candidates in sorted(by_genre.items()):
        ordered = sorted(candidates, key=lambda item: (-item[1], item[0]))[
            : settings.inferred_memberships_per_genre
        ]
        result.extend(
            MembershipScore(
                artist_id=artist,
                genre_id=genre,
                profile_kind="one_hop",
                score=round(score, 12),
                evidence_refs=tuple(sorted(refs[(artist, genre)])),
                components=(
                    MembershipComponent(
                        component_kind="listenbrainz_one_hop",
                        raw_value=score * maxima[genre],
                        normalized_value=round(score, 12),
                        evidence_refs=tuple(sorted(refs[(artist, genre)])),
                    ),
                ),
            )
            for artist, score in ordered
            if score > 0.0
        )
    return tuple(result)


def _propagate_edges(
    eligible: tuple[ArtistPairEvidence, ...],
    context: _PropagationContext,
    settings: PublicModelSettings,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], set[str]]]:
    contributions: dict[tuple[str, str], float] = defaultdict(float)
    refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    visits = 0
    for pair in eligible:
        left = pair.left_artist_id
        right = pair.right_artist_id
        edge = context.raw_edge_weights[(left, right)] / math.sqrt(
            context.strength[left] * context.strength[right]
        )
        for target, source in ((left, right), (right, left)):
            for seed in context.seeds.get(source, ()):
                visits += 1
                if visits > settings.max_propagation_visits:
                    raise PublicModelLimitError(
                        "propagation visits exceed declared limit "
                        f"{settings.max_propagation_visits}"
                    )
                key = (target, seed.genre_id)
                if key in context.direct_pairs:
                    continue
                contributions[key] += edge * float(seed.score)
                refs[key].update(seed.evidence_refs)
                refs[key].update(pair.evidence_refs)
    return contributions, refs


def _profiles(
    direct: tuple[MembershipScore, ...], inferred: tuple[MembershipScore, ...]
) -> tuple[GenreProfile, ...]:
    grouped: dict[tuple[str, ProfileKind], list[MembershipScore]] = defaultdict(list)
    for item in (*direct, *inferred):
        grouped[(item.genre_id, item.profile_kind)].append(item)
    return tuple(
        GenreProfile(
            genre_id=genre,
            profile_kind=kind,
            memberships=tuple(sorted(items, key=lambda item: (-item.score, item.artist_id))),
        )
        for (genre, kind), items in sorted(grouped.items())
    )


def _neighbor_rows(
    profiles: tuple[GenreProfile, ...],
    settings: PublicModelSettings,
) -> tuple[GenreNeighbor, ...]:
    return tuple(
        item
        for kind in ("direct", "one_hop")
        for item in _profile_neighbor_rows(profiles, kind, settings)
    )


def _profile_neighbor_rows(
    profiles: tuple[GenreProfile, ...],
    kind: ProfileKind,
    settings: PublicModelSettings,
) -> tuple[GenreNeighbor, ...]:
    selected = tuple(profile for profile in profiles if profile.profile_kind == kind)
    vectors = {
        profile.genre_id: {item.artist_id: float(item.score) for item in profile.memberships}
        for profile in selected
    }
    inverted: dict[str, list[str]] = defaultdict(list)
    for genre, vector in vectors.items():
        for artist in vector:
            inverted[artist].append(genre)
    shared = _shared_genre_counts(inverted, settings)
    candidates: dict[tuple[SimilarityMetric, str], list[tuple[str, float, int]]] = defaultdict(list)
    sums = {genre: sum(vector.values()) for genre, vector in vectors.items()}
    norms = {
        genre: math.sqrt(sum(value * value for value in vector.values()))
        for genre, vector in vectors.items()
    }
    for (left, right), shared_count in sorted(shared.items()):
        if shared_count < settings.minimum_shared_artists:
            continue
        common = vectors[left].keys() & vectors[right].keys()
        minimum_sum = sum(min(vectors[left][artist], vectors[right][artist]) for artist in common)
        jaccard_denominator = sums[left] + sums[right] - minimum_sum
        dot = sum(vectors[left][artist] * vectors[right][artist] for artist in common)
        cosine_denominator = norms[left] * norms[right]
        scores: tuple[tuple[SimilarityMetric, float], ...] = (
            ("weighted_jaccard", minimum_sum / jaccard_denominator),
            ("cosine", dot / cosine_denominator),
        )
        for metric, score in scores:
            if score <= 0.0:
                continue
            candidates[(metric, left)].append((right, score, shared_count))
            candidates[(metric, right)].append((left, score, shared_count))
    results: list[GenreNeighbor] = []
    for (metric, genre), items in sorted(candidates.items()):
        ordered = sorted(items, key=lambda item: (-item[1], item[0]))[
            : settings.neighbors_per_genre
        ]
        results.extend(
            GenreNeighbor(
                genre_id=genre,
                neighbor_genre_id=neighbor,
                profile_kind=kind,
                metric=metric,
                score=round(score, 12),
                shared_artist_count=shared_count,
                rank=rank,
            )
            for rank, (neighbor, score, shared_count) in enumerate(ordered, start=1)
        )
    return tuple(results)


def _shared_genre_counts(
    inverted: Mapping[str, list[str]], settings: PublicModelSettings
) -> dict[tuple[str, str], int]:
    shared: dict[tuple[str, str], int] = defaultdict(int)
    visits = 0
    for genres in inverted.values():
        for left, right in combinations(sorted(genres), 2):
            visits += 1
            if visits > settings.max_similarity_pair_visits:
                raise PublicModelLimitError(
                    "similarity pair visits exceed declared limit "
                    f"{settings.max_similarity_pair_visits}"
                )
            shared[(left, right)] += 1
    return shared


def _fix_axis_sign(values: np.ndarray) -> np.ndarray:
    anchor = int(np.argmax(np.abs(values)))
    return -values if values[anchor] < 0.0 else values


def _scale_axis(values: np.ndarray) -> np.ndarray:
    minimum = float(values.min())
    maximum = float(values.max())
    if maximum == minimum:
        return np.full(values.shape, 0.5, dtype=np.float64)
    return (values - minimum) / (maximum - minimum)


def _component_coordinates(adjacency: sparse.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
    count = adjacency.shape[0]
    if count == 1:
        return np.array([0.5]), np.array([0.5])
    if count == _PAIR_COMPONENT_SIZE:
        return np.array([0.0, 1.0]), np.array([0.5, 0.5])
    graph_laplacian = laplacian(adjacency, normed=True)
    if count <= _DENSE_EIGEN_LIMIT:
        _values, vectors = eigh(graph_laplacian.toarray(), subset_by_index=(0, 2))
    else:
        _values, vectors = eigsh(
            graph_laplacian,
            k=3,
            which="SM",
            tol=1e-10,
            v0=np.linspace(1.0, 2.0, count, dtype=np.float64),
        )
    x = _scale_axis(_fix_axis_sign(vectors[:, 1]))
    y = _scale_axis(_fix_axis_sign(vectors[:, 2]))
    return x, y


def _coordinates(
    genres: tuple[str, ...],
    neighbors: tuple[GenreNeighbor, ...],
    profile_kind: ProfileKind,
) -> tuple[GenreCoordinate, ...]:
    index = {genre: position for position, genre in enumerate(genres)}
    weights: dict[tuple[int, int], float] = defaultdict(float)
    for item in neighbors:
        if item.profile_kind != profile_kind or item.metric != _LAYOUT_METRIC:
            continue
        left = index[item.genre_id]
        right = index[item.neighbor_genre_id]
        key = (min(left, right), max(left, right))
        weights[key] = max(weights[key], float(item.score))
    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    for (left, right), value in sorted(weights.items()):
        rows.extend((left, right))
        columns.extend((right, left))
        values.extend((value, value))
    adjacency = sparse.csr_matrix((values, (rows, columns)), shape=(len(genres), len(genres)))
    component_count, labels = connected_components(adjacency, directed=False, return_labels=True)
    ordered_components = sorted(
        range(component_count),
        key=lambda component: (
            -int(np.count_nonzero(labels == component)),
            min(genres[index] for index in np.flatnonzero(labels == component)),
        ),
    )
    grid_width = math.ceil(math.sqrt(component_count))
    cell_scale = 0.8 / grid_width
    result: list[GenreCoordinate] = []
    for published_component, component in enumerate(ordered_components):
        selected = np.flatnonzero(labels == component)
        local = adjacency[selected][:, selected].tocsr()
        x, y = _component_coordinates(local)
        column = published_component % grid_width
        row = published_component // grid_width
        for offset, genre_index in enumerate(selected):
            result.append(
                GenreCoordinate(
                    genre_id=genres[int(genre_index)],
                    x=round(
                        0.1 / grid_width + column / grid_width + float(x[offset]) * cell_scale,
                        12,
                    ),
                    y=round(
                        0.1 / grid_width + row / grid_width + float(y[offset]) * cell_scale,
                        12,
                    ),
                    component=published_component,
                )
            )
    return tuple(sorted(result, key=lambda item: item.genre_id))


def _representatives(
    candidates: Iterable[MetadataCandidate], settings: PublicModelSettings
) -> tuple[RepresentativeItem, ...]:
    grouped: dict[tuple[str, MetadataKind], list[MetadataCandidate]] = defaultdict(list)
    for item in candidates:
        grouped[(item.genre_id, item.entity_kind)].append(item)
    result: list[RepresentativeItem] = []
    for (genre, kind), items in sorted(grouped.items()):
        ordered = sorted(
            items,
            key=lambda item: (
                -item.direct_evidence_value,
                -item.source_count,
                item.name.casefold(),
                item.entity_id,
            ),
        )[: settings.representatives_per_kind]
        result.extend(
            RepresentativeItem(
                genre_id=genre,
                entity_kind=kind,
                entity_id=item.entity_id,
                name=item.name,
                rank=rank,
                direct_evidence_value=item.direct_evidence_value,
                source_count=item.source_count,
                evidence_refs=item.evidence_refs,
            )
            for rank, item in enumerate(ordered, start=1)
        )
    return tuple(result)


def _facet_agreement(evidence: Iterable[DirectMembershipEvidence]) -> tuple[FacetAgreement, ...]:
    pairs: dict[MembershipFacet, set[tuple[str, str]]] = defaultdict(set)
    for item in evidence:
        pairs[item.facet].add((item.artist_id, item.genre_id))
    left_facet: MembershipFacet = "musicbrainz_tag"
    right_facet: MembershipFacet = "wikidata_p136"
    left = pairs[left_facet]
    right = pairs[right_facet]
    intersection = left & right
    union = left | right
    return (
        FacetAgreement(
            left_facet=left_facet,
            right_facet=right_facet,
            intersection_count=len(intersection),
            union_count=len(union),
            jaccard=len(intersection) / len(union) if union else 1.0,
            left_recall_from_right=len(intersection) / len(left) if left else 0.0,
            right_recall_from_left=len(intersection) / len(right) if right else 0.0,
        ),
    )


def build_public_model(
    inputs: PublicModelInput, settings: PublicModelSettings
) -> PublicModelArtifact:
    """Build a bounded deterministic reconstruction from public metadata only."""
    started = time.monotonic()
    _check_input_limits(inputs, settings)
    direct = _direct_scores(inputs.direct_memberships)
    inferred = _one_hop_scores(inputs.artist_pairs, direct, settings)
    profiles = _profiles(direct, inferred)
    neighbors = _neighbor_rows(profiles, settings)
    genres = tuple(sorted({item.genre_id for item in direct}))
    coordinates = _coordinates(genres, neighbors, settings.layout_profile)
    representatives = _representatives(inputs.metadata_candidates, settings)
    agreement = _facet_agreement(inputs.direct_memberships)
    export_allowed = all(artifact.export_allowed for artifact in inputs.artifacts)
    coordinate_genres = {item.genre_id for item in coordinates}
    neighbor_genres = {item.genre_id for item in neighbors}
    coverage = ModelCoverage(
        input_artists=len(
            {item.artist_id for item in inputs.direct_memberships}
            | {
                artist
                for pair in inputs.artist_pairs
                for artist in (pair.left_artist_id, pair.right_artist_id)
            }
        ),
        input_genres=len(inputs.genres),
        direct_observations=len(inputs.direct_memberships),
        direct_memberships=len(direct),
        eligible_artist_pairs=sum(_eligible_pair(pair, settings) for pair in inputs.artist_pairs),
        inferred_memberships=len(inferred),
        neighbor_genres=len(neighbor_genres),
        coordinate_genres=len(coordinate_genres),
        unplaced_genres=tuple(
            sorted({item.genre_id for item in inputs.genres} - coordinate_genres)
        ),
        representative_items=len(representatives),
    )
    payload = _output_payload(
        profiles=profiles,
        neighbors=neighbors,
        coordinates=coordinates,
        representatives=representatives,
        facet_agreement=agreement,
        coverage=coverage,
        export_allowed=export_allowed,
        genres=inputs.genres,
        artifacts=inputs.artifacts,
    )
    return PublicModelArtifact(
        input_sha256=_sha256(inputs),
        settings_sha256=_sha256(settings),
        output_sha256=_sha256(payload),
        export_allowed=export_allowed,
        artifacts=inputs.artifacts,
        genres=inputs.genres,
        profiles=profiles,
        neighbors=neighbors,
        coordinates=coordinates,
        representatives=representatives,
        facet_agreement=agreement,
        coverage=coverage,
        resources=ModelResources(
            elapsed_ms=round((time.monotonic() - started) * 1_000),
            peak_rss_bytes=_peak_rss_bytes(),
        ),
    )
