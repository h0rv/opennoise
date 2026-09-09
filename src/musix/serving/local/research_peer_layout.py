"""Project a sealed local-research peer index without fabricating seed positions.

This adapter is intentionally outside the public-model and serving paths.  It
maps only seed identities that occur in a positive peer edge; every other
retained seed is accounted for as unplaced rather than being mixed into a hash
or taxonomy-navigation landscape.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping  # noqa: TC003
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import Field, model_validator

from musix.ml.layout_lenses import (
    build_weighted_community_spectral_coordinates,
    build_weighted_spectral_coordinates,
    weighted_spectral_quality,
)
from musix.models import FrozenModel
from musix.models.modeling import GenreCoordinate, LayoutQuality  # noqa: TC001
from musix.types import Sha256  # noqa: TC001

_REVISION = "local-research-peer-layout-v1"
_SHA256_LENGTH = 64


class LocalResearchPeerLayoutSettings(FrozenModel):
    """Bound deterministic local-only layout construction."""

    revision: Literal["local-research-peer-layout-v1"] = _REVISION
    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    neighbors_per_genre: int = Field(default=10, ge=1, le=100)
    layout_method: Literal["normalized_laplacian_spectral", "community_packed_spectral"] = (
        "community_packed_spectral"
    )
    community_seed: int = Field(default=20260831, ge=0)
    maximum_community_iterations: int = Field(default=100, ge=1, le=1_000)


class ResearchUnplacedSeed(FrozenModel):
    """One retained identity without a coordinate claim in this evidence plane."""

    source_item_id: str = Field(min_length=1, max_length=300)
    reason: Literal["no_peer_similarity_evidence"] = "no_peer_similarity_evidence"


class LocalResearchPeerLayoutCoverage(FrozenModel):
    """Coverage makes the supported and unsupported cohorts reviewable."""

    retained_seed_count: int = Field(ge=1)
    peer_edge_seed_count: int = Field(ge=0)
    evidence_connected_seed_count: int = Field(ge=0)
    coordinate_count: int = Field(ge=0)
    unplaced_seed_count: int = Field(ge=0)
    source_peer_edge_count: int = Field(ge=0)
    retained_peer_edge_count: int = Field(ge=0)
    unmapped_peer_edge_count: int = Field(ge=0)
    community_count: int = Field(ge=0)
    community_iterations: int = Field(ge=0)
    community_converged: bool

    @model_validator(mode="after")
    def require_complete_seed_accounting(self) -> LocalResearchPeerLayoutCoverage:
        """Require the supported and unplaced cohorts to partition retained seeds."""
        if self.coordinate_count != self.evidence_connected_seed_count:
            raise ValueError("every evidence-connected seed must receive one coordinate")
        if self.coordinate_count + self.unplaced_seed_count != self.retained_seed_count:
            raise ValueError("local research layout must account for every retained seed")
        if self.retained_peer_edge_count > self.source_peer_edge_count:
            raise ValueError("retained peer edges cannot exceed source peer edges")
        return self


class LocalResearchPeerLayoutArtifact(FrozenModel):
    """Hashable, non-exportable coordinates derived only from weighted peer edges."""

    revision: Literal["local-research-peer-layout-v1"] = _REVISION
    publication_scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    source_index_sha256: Sha256
    source_peer_similarity_output_sha256: Sha256
    edge_score_semantics: Literal["receipt_bound_peer_weighted_component_score"] = (
        "receipt_bound_peer_weighted_component_score"
    )
    edge_direction_policy: Literal["canonical_undirected_candidate_pairs"] = (
        "canonical_undirected_candidate_pairs"
    )
    deterministic_replay_scope: Literal["same_scipy_runtime"] = "same_scipy_runtime"
    settings: LocalResearchPeerLayoutSettings
    coordinates: tuple[GenreCoordinate, ...]
    unplaced: tuple[ResearchUnplacedSeed, ...]
    quality: LayoutQuality
    coverage: LocalResearchPeerLayoutCoverage
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_disjoint_complete_coordinates(self) -> LocalResearchPeerLayoutArtifact:
        """Reject coordinate coverage that hides missing or duplicated seed identities."""
        coordinate_ids = {item.genre_id for item in self.coordinates}
        unplaced_ids = {item.source_item_id for item in self.unplaced}
        if len(coordinate_ids) != len(self.coordinates) or len(unplaced_ids) != len(self.unplaced):
            raise ValueError("local research seed IDs must be unique")
        if coordinate_ids & unplaced_ids:
            raise ValueError("a retained seed cannot be both placed and unplaced")
        if len(coordinate_ids) + len(unplaced_ids) != self.settings.expected_seed_count:
            raise ValueError("local research layout seed accounting disagrees with settings")
        if self.quality.placed_genres != len(self.coordinates):
            raise ValueError("layout quality coordinate count disagrees with coordinates")
        return self


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _path_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def local_research_peer_layout_output_sha256(artifact: LocalResearchPeerLayoutArtifact) -> str:
    """Recompute the logical hash without trusting a serialized declaration."""
    return _canonical_sha256(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def _metadata(connection: sqlite3.Connection) -> Mapping[str, str]:
    rows = connection.execute("SELECT key, value FROM metadata")
    values = {str(key): str(value) for key, value in rows}
    required = {
        "non_production_candidate": "true",
        "all_inputs_export_allowed": "false",
    }
    for key, expected in required.items():
        if values.get(key) != expected:
            raise ValueError(f"local peer index metadata requires {key}={expected}")
    return values


def _peer_similarity_hash(metadata: Mapping[str, str]) -> str:
    value = metadata.get("artifact_output_sha256")
    if value is None:
        raise ValueError("local peer index metadata has no artifact_output_sha256")
    if len(value) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("local peer index artifact_output_sha256 is invalid")
    return value


def build_local_research_peer_layout(
    index_path: Path, *, settings: LocalResearchPeerLayoutSettings | None = None
) -> LocalResearchPeerLayoutArtifact:
    """Read a compact peer index once and emit only evidence-supported coordinates."""
    resolved = settings or LocalResearchPeerLayoutSettings()
    index_sha256 = _path_sha256(index_path)
    with closing(sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)) as connection:
        metadata = _metadata(connection)
        peer_hash = _peer_similarity_hash(metadata)
        seeds = tuple(
            str(item_id)
            for (item_id,) in connection.execute(
                "SELECT source_item_id FROM seed ORDER BY source_item_id"
            )
        )
        peer_edges = tuple(
            (str(source), str(target), float(score))
            for source, target, score in connection.execute(
                "SELECT source_genre_id, target_genre_id, score "
                "FROM peer_edge ORDER BY source_genre_id, target_genre_id"
            )
        )
    if len(seeds) != resolved.expected_seed_count:
        raise ValueError(
            f"expected {resolved.expected_seed_count} retained seeds, found {len(seeds)}"
        )
    seed_ids = set(seeds)
    if len(seed_ids) != len(seeds):
        raise ValueError("local peer index has duplicate seed identities")
    weights: dict[tuple[str, str], float] = {}
    unmapped_edge_count = 0
    for source, target, score in peer_edges:
        if source >= target or not math.isfinite(score) or score <= 0.0:
            raise ValueError("local peer index edges must be canonical with positive scores")
        if source not in seed_ids or target not in seed_ids:
            unmapped_edge_count += 1
            continue
        key = (source, target)
        if key in weights:
            raise ValueError("local peer index maps multiple edges to one retained seed pair")
        weights[key] = score
    connected = tuple(sorted({seed_id for edge in weights for seed_id in edge}))
    community_count = 0
    community_iterations = 0
    community_converged = True
    layout_weights = weights
    if not connected:
        coordinates = ()
    elif resolved.layout_method == "normalized_laplacian_spectral":
        coordinates = build_weighted_spectral_coordinates(connected, weights)
    else:
        community = build_weighted_community_spectral_coordinates(
            connected,
            weights,
            seed=resolved.community_seed,
            maximum_iterations=resolved.maximum_community_iterations,
        )
        coordinates = community.coordinates
        community_count = community.community_count
        community_iterations = community.iterations
        community_converged = community.converged
        layout_weights = community.layout_weights
    quality = weighted_spectral_quality(
        coordinates,
        weights,
        neighbors_per_genre=resolved.neighbors_per_genre,
        layout_weights=layout_weights,
    )
    unplaced = tuple(
        ResearchUnplacedSeed(source_item_id=seed_id)
        for seed_id in sorted(seed_ids - set(connected))
    )
    preliminary = LocalResearchPeerLayoutArtifact(
        source_index_sha256=index_sha256,
        source_peer_similarity_output_sha256=peer_hash,
        settings=resolved,
        coordinates=coordinates,
        unplaced=unplaced,
        quality=quality,
        coverage=LocalResearchPeerLayoutCoverage(
            retained_seed_count=len(seeds),
            peer_edge_seed_count=len({seed_id for edge in weights for seed_id in edge}),
            evidence_connected_seed_count=len(connected),
            coordinate_count=len(coordinates),
            unplaced_seed_count=len(unplaced),
            source_peer_edge_count=len(peer_edges),
            retained_peer_edge_count=len(weights),
            unmapped_peer_edge_count=unmapped_edge_count,
            community_count=community_count,
            community_iterations=community_iterations,
            community_converged=community_converged,
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={"output_sha256": local_research_peer_layout_output_sha256(preliminary)}
    )
