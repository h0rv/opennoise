"""Evaluation-only H3 comparison for source-neutral local peer artifacts."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.models import FrozenModel
from musix.models.modeling import PublicModelInput
from musix.peers.similarity.peer_similarity_h3_bridge import (
    _historical_jaccard_neighbors,
    _load_positives,
)
from musix.peers.support.release_group_support_peer import (
    SupportPeerArtifact,
    artifact_neighbors,
    file_sha,
    logical_sha,
)
from musix.ingest.spotify.spotify_bridge_artifact import (
    iter_accepted_spotify_to_musicbrainz,
    load_receipted_musicbrainz_spotify_bridge,
)
from musix.taxonomy.seeds.genre_seed_universe import normalize_label
from musix.taxonomy.seeds.seed_reconciliation import load_seed_reconciliation
from musix.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


_SEED_COUNT: Final = 6_291


class SupportPeerH3Metrics(FrozenModel):
    """Positive-only recall metrics with explicit candidate availability conditioning."""

    micro_overlap_count: int = Field(ge=0)
    historical_neighbor_reference_count: int = Field(ge=0)
    evaluated_genre_count: int = Field(ge=0)
    candidate_available_reference_count: int = Field(ge=0)
    candidate_available_evaluated_genre_count: int = Field(ge=0)
    micro_recall_at_25: float | None = Field(default=None, ge=0, le=1)
    macro_recall_at_25: float | None = Field(default=None, ge=0, le=1)
    conditional_micro_recall_at_25: float | None = Field(default=None, ge=0, le=1)
    precision_at_25: None = None
    precision_unavailable_reason: Literal["positive_only_h3_absences_are_unknown"] = (
        "positive_only_h3_absences_are_unknown"
    )


class SupportPeerH3Coverage(FrozenModel):
    """Counts with units that keep H3 observation and membership coverage distinct."""

    h3_observation_count: int = Field(ge=0)
    h3_mapped_positive_observation_count: int = Field(ge=0)
    h3_unique_mapped_positive_membership_count: int = Field(ge=0)
    h3_unique_mapped_artist_count: int = Field(ge=0)
    h3_positive_genre_count: int = Field(ge=0)
    candidate_genre_with_h3_positive_count: int = Field(ge=0)
    h3_unmapped_genre_observation_count: int = Field(ge=0)
    h3_unbridged_artist_observation_count: int = Field(ge=0)
    h3_conflicted_artist_observation_count: int = Field(ge=0)


class SupportPeerH3Report(FrozenModel):
    """A sealed evaluation report which cannot be used as construction input."""

    revision: Literal["release-group-support-peer-h3-evaluation-v1"] = (
        "release-group-support-peer-h3-evaluation-v1"
    )
    candidate_output_sha256: Sha256
    candidate_component_kind: Literal["release_group_artist_overlap", "direct_artist_overlap"]
    reconciliation_seed_count: Literal[6291] = 6291
    bridge_output_sha256: Sha256
    historical_database_sha256: Sha256
    k: Literal[25] = 25
    historical_inputs_used_for_construction: Literal[False] = False
    absence_is_negative: Literal[False] = False
    coverage: SupportPeerH3Coverage
    metrics: SupportPeerH3Metrics
    output_sha256: Sha256


def evaluate_support_peer_h3(  # noqa: PLR0913
    *,
    candidate_path: Path,
    reconciliation_path: Path,
    public_input_path: Path,
    bridge_path: Path,
    bridge_receipt_path: Path,
    bridge_receipt_sha256: Sha256,
    historical_database_path: Path,
) -> SupportPeerH3Report:
    """Compare one source artifact with the fixed bridge-resolved H3 cohort."""
    candidate = SupportPeerArtifact.model_validate_json(candidate_path.read_bytes())
    if candidate.reconciliation_sha256 != file_sha(reconciliation_path):
        raise ValueError("candidate reconciliation hash does not match evaluation input")
    if candidate.output_sha256 != logical_sha(
        candidate.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("candidate logical hash does not match its contents")
    reconciliation = load_seed_reconciliation(reconciliation_path)
    if reconciliation.seed_count != _SEED_COUNT:
        raise ValueError("evaluation reconciliation must retain the complete 6291-seed universe")
    if candidate.seed_count != reconciliation.seed_count:
        raise ValueError("candidate seed count does not match evaluation reconciliation")
    public_input = PublicModelInput.model_validate_json(public_input_path.read_bytes())
    names: dict[str, list[str]] = defaultdict(list)
    for genre in public_input.genres:
        names[normalize_label(genre.name)].append(genre.genre_id)
    seed_by_name = {name: values[0] for name, values in names.items() if len(values) == 1}
    bridge = load_receipted_musicbrainz_spotify_bridge(
        bridge_path, bridge_receipt_path, bridge_receipt_sha256
    )
    try:
        accepted = dict(iter_accepted_spotify_to_musicbrainz(bridge))
        conflicted = frozenset(
            spotify_id
            for conflict in bridge.conflicts
            for spotify_id in conflict.spotify_artist_ids
        )
        positives, counters = _load_positives(
            historical_database_path,
            seed_by_name=seed_by_name,
            spotify_to_mbid=accepted,
            conflicted=conflicted,
            maximum_observations=350_000,
        )
        bridge_sha = bridge.header.output_sha256
        database_sha = bridge.header.historical_database_sha256
    finally:
        bridge.close()
    if file_sha(historical_database_path) != database_sha:
        raise ValueError("H3 database does not match bridge custody")
    reference = _historical_jaccard_neighbors(positives, k=25)
    neighbors = artifact_neighbors(candidate, genre_ids=set(positives), k=25)
    overlap = reference_count = conditional_overlap = conditional_count = conditional_genres = 0
    recalls: list[float] = []
    for seed in positives:
        targets = set(neighbors.get(seed, ()))
        targets_reference = set(reference.get(seed, ()))
        if not targets_reference:
            continue
        hits = len(targets & targets_reference)
        overlap += hits
        reference_count += len(targets_reference)
        recalls.append(hits / len(targets_reference))
        if targets:
            conditional_overlap += hits
            conditional_count += len(targets_reference)
            conditional_genres += 1
    coverage = SupportPeerH3Coverage(
        h3_observation_count=counters["h3_observation_count"],
        h3_mapped_positive_observation_count=counters["h3_mapped_positive_count"],
        h3_unique_mapped_positive_membership_count=sum(len(rows) for rows in positives.values()),
        h3_unique_mapped_artist_count=len(set().union(*positives.values())) if positives else 0,
        h3_positive_genre_count=len(positives),
        candidate_genre_with_h3_positive_count=len(set(positives) & set(neighbors)),
        h3_unmapped_genre_observation_count=counters["h3_unmapped_genre_observation_count"],
        h3_unbridged_artist_observation_count=counters["h3_unbridged_artist_observation_count"],
        h3_conflicted_artist_observation_count=counters["h3_conflicted_artist_observation_count"],
    )
    preliminary = SupportPeerH3Report(
        candidate_output_sha256=candidate.output_sha256,
        candidate_component_kind=candidate.component_kind,
        reconciliation_seed_count=reconciliation.seed_count,
        bridge_output_sha256=bridge_sha,
        historical_database_sha256=database_sha,
        coverage=coverage,
        metrics=SupportPeerH3Metrics(
            micro_overlap_count=overlap,
            historical_neighbor_reference_count=reference_count,
            evaluated_genre_count=len(recalls),
            candidate_available_reference_count=conditional_count,
            candidate_available_evaluated_genre_count=conditional_genres,
            micro_recall_at_25=overlap / reference_count if reference_count else None,
            macro_recall_at_25=sum(recalls) / len(recalls) if recalls else None,
            conditional_micro_recall_at_25=(
                conditional_overlap / conditional_count if conditional_count else None
            ),
        ),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": logical_sha(
                preliminary.model_dump(mode="json", exclude={"output_sha256"})
            )
        }
    )
