"""Independent acceptance checks for a local-research peer layout.

The layout is a projection of receipt-bound candidate-pair scores.  It must
not be presented as a new similarity model: this check replays the compact
index, verifies the component score calculation, and measures only how well
the two-dimensional projection preserves those same source-space neighbors.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.serving.local.research_peer_layout import (
    LocalResearchPeerLayoutArtifact,
    build_local_research_peer_layout,
)

if TYPE_CHECKING:
    from pathlib import Path


class LocalResearchPeerLayoutEvaluation(FrozenModel):
    """A bounded, source-index replay report for one local-only projection."""

    publication_scope: Literal["local_research_only"] = "local_research_only"
    score_semantics: Literal["receipt_bound_peer_weighted_component_score"] = (
        "receipt_bound_peer_weighted_component_score"
    )
    edge_direction_policy: Literal["canonical_undirected_candidate_pairs"] = (
        "canonical_undirected_candidate_pairs"
    )
    retained_seed_count: int = Field(ge=1)
    evidence_connected_seed_count: int = Field(ge=0)
    unplaced_seed_count: int = Field(ge=0)
    retained_peer_edge_count: int = Field(ge=0)
    source_peer_edge_count: int = Field(ge=0)
    component_score_replay_available: Literal[False] = False
    canonical_positive_edge_scores: bool
    direct_only_score_equals_direct_component: bool
    layout_replay_matches: bool
    projected_knn_preservation: float = Field(ge=0.0, le=1.0)


def _canonical_positive_edge_scores(index_path: Path) -> bool:
    """Verify the local index retains only canonical, bounded score weights.

    The compact index intentionally retains component kinds and evidence counts,
    not normalized component values or configured weights.  Exact component
    arithmetic therefore belongs to the sealed candidate artifact gate, not to
    this local layout check.
    """
    valid = True
    with closing(sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT source_genre_id, target_genre_id, score FROM peer_edge")
        for source, target, score in rows:
            if (
                str(source) >= str(target)
                or not math.isfinite(float(score))
                or float(score) <= 0.0
                or float(score) > 1.0
            ):
                valid = False
                break
    return valid


def _direct_only_score_replays(index_path: Path) -> bool:
    """Check the one-component identity used by the current direct-only corpus."""
    valid = True
    with closing(sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT score, direct_score, aggregate_score, sufficiency, component_kinds_json "
            "FROM peer_edge"
        )
        for score, direct_score, aggregate_score, sufficiency, kinds in rows:
            if str(sufficiency) != "direct_only":
                valid = False
                break
            try:
                component_kinds = json.loads(str(kinds))
            except json.JSONDecodeError:
                valid = False
                break
            if component_kinds != ["direct_artist_overlap"] or float(aggregate_score) != 0.0:
                valid = False
                break
            if not math.isclose(float(score), float(direct_score), rel_tol=1e-12, abs_tol=1e-12):
                valid = False
                break
    return valid


def evaluate_local_research_peer_layout(
    index_path: Path,
    artifact: LocalResearchPeerLayoutArtifact,
) -> LocalResearchPeerLayoutEvaluation:
    """Replay a compact index and reject unsupported or altered coordinates."""
    if artifact.publication_scope != "local_research_only" or artifact.export_allowed:
        raise ValueError("peer layout must remain local research only")
    replay = build_local_research_peer_layout(index_path, settings=artifact.settings)
    if replay.source_index_sha256 != artifact.source_index_sha256:
        raise ValueError("peer layout index hash does not match the evaluated index")
    return LocalResearchPeerLayoutEvaluation(
        retained_seed_count=artifact.coverage.retained_seed_count,
        evidence_connected_seed_count=artifact.coverage.evidence_connected_seed_count,
        unplaced_seed_count=artifact.coverage.unplaced_seed_count,
        retained_peer_edge_count=artifact.coverage.retained_peer_edge_count,
        source_peer_edge_count=artifact.coverage.source_peer_edge_count,
        canonical_positive_edge_scores=_canonical_positive_edge_scores(index_path),
        direct_only_score_equals_direct_component=_direct_only_score_replays(index_path),
        layout_replay_matches=replay == artifact,
        projected_knn_preservation=artifact.quality.mean_knn_preservation,
    )
