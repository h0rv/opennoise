"""Measure open MusicBrainz name coverage without creating genre claims.

This joins only stable seed IDs.  It deliberately keeps artist-record proper
genres, aggregate release-group proper genres, release-group tags, public
identity corroboration, and hierarchy candidates as separate source roles.
The legacy map contributes its immutable names and IDs only.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.ingest.musicbrainz.release_group_native_census import (
    ReleaseGroupNativeCensusReport,
)
from opennoise.ingest.musicbrainz.release_group_native_census import (
    report_sha256 as native_report_sha256,
)
from opennoise.ingest.musicbrainz.release_group_tag_census import (
    ReleaseGroupTagCensusReport,
)
from opennoise.ingest.musicbrainz.release_group_tag_census import (
    report_sha256 as tag_report_sha256,
)
from opennoise.models import FrozenModel
from opennoise.taxonomy.seeds.reconciliation import SeedReconciliationArtifact
from opennoise.taxonomy.seeds.universe import normalize_label
from opennoise.taxonomy.structure.hierarchy_candidates import GenreHierarchyCandidateArtifact

if TYPE_CHECKING:
    from pathlib import Path

_REVISION = "musicbrainz-open-name-coverage-frontier-v1"
_SEED_COUNT = 6_291


class SourceAnchorCoverage(FrozenModel):
    """Only the all-seed source-anchor totals needed for comparison."""

    seed_count: Literal[6291]
    direct_observed_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    observed_musicbrainz_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    observed_wikidata_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    observed_cross_source_seed_count: int = Field(ge=0, le=_SEED_COUNT)


class OpenNameCoverageFrontier(FrozenModel):
    """A local-only coverage frontier, not a microgenre classifier or release input."""

    revision: Literal["musicbrainz-open-name-coverage-frontier-v1"] = _REVISION
    local_only: Literal[True] = True
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    artist_membership_constructed: Literal[False] = False
    static_or_model_promotion: Literal[False] = False
    microgenre_stratum_available: Literal[False] = False
    microgenre_stratum_blocker: str
    seed_reconciliation_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    direct_custody_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_census_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tag_census_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hierarchy_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_anchor_frontier_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stable_seed_count: Literal[6291] = _SEED_COUNT
    source_anchor_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    source_anchor_musicbrainz_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    source_anchor_wikidata_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    source_anchor_cross_source_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    direct_artist_proper_genre_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    direct_artist_proper_genre_claim_count: int = Field(ge=0)
    direct_artist_proper_genre_artist_count: int = Field(ge=0)
    native_release_group_proper_name_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    native_release_group_proper_observation_count: int = Field(ge=0)
    release_group_tag_name_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    release_group_tag_observation_count: int = Field(ge=0)
    public_and_musicbrainz_identity_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    direct_artist_proper_and_public_identity_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    hierarchy_accepted_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    direct_artist_proper_and_native_proper_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    native_proper_and_tag_name_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    direct_artist_proper_and_hierarchy_accepted_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _source_roles_stay_bounded(self) -> OpenNameCoverageFrontier:
        if self.direct_artist_proper_genre_seed_count > self.source_anchor_musicbrainz_seed_count:
            raise ValueError("proper-genre custody cannot exceed the MusicBrainz anchor frontier")
        if (
            self.native_proper_and_tag_name_seed_count
            > self.native_release_group_proper_name_seed_count
        ):
            raise ValueError("native/tag overlap cannot exceed native proper-name coverage")
        return self


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def frontier_sha256(frontier: OpenNameCoverageFrontier) -> str:
    """Return the canonical hash excluding the self-reference."""
    return _sha(frontier.model_dump(mode="json", exclude={"output_sha256"}))


def verify_open_name_coverage_frontier(frontier: OpenNameCoverageFrontier) -> None:
    """Replay the report's self-hash and no-promotion boundary."""
    OpenNameCoverageFrontier.model_validate_json(frontier.model_dump_json())
    if frontier.output_sha256 != frontier_sha256(frontier):
        raise ValueError("open name coverage frontier hash does not replay")


def _load_anchor_coverage(path: Path) -> tuple[SourceAnchorCoverage, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("coverage"), dict):
        raise TypeError("source-anchor frontier must contain a coverage object")
    output_sha = raw.get("output_sha256")
    if not isinstance(output_sha, str):
        raise TypeError("source-anchor frontier must declare output_sha256")
    return SourceAnchorCoverage.model_validate(raw["coverage"]), output_sha


def build_open_name_coverage_frontier(  # noqa: PLR0913 - the CLI makes every custody boundary explicit.
    *,
    reconciliation_path: Path,
    custody_receipt_path: Path,
    custody_object_store: Path,
    native_census_path: Path,
    tag_census_path: Path,
    hierarchy_path: Path,
    source_anchor_frontier_path: Path,
) -> OpenNameCoverageFrontier:
    """Build a typed, source-role-preserving local coverage frontier."""
    reconciliation = SeedReconciliationArtifact.model_validate_json(
        reconciliation_path.read_text(encoding="utf-8")
    )
    native = ReleaseGroupNativeCensusReport.model_validate_json(
        native_census_path.read_text(encoding="utf-8")
    )
    tags = ReleaseGroupTagCensusReport.model_validate_json(
        tag_census_path.read_text(encoding="utf-8")
    )
    hierarchy = GenreHierarchyCandidateArtifact.model_validate_json(
        hierarchy_path.read_text(encoding="utf-8")
    )
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(
        custody_receipt_path.read_text(encoding="utf-8")
    )
    anchors, anchor_sha = _load_anchor_coverage(source_anchor_frontier_path)
    if reconciliation.seed_count != _SEED_COUNT or hierarchy.coverage.seed_count != _SEED_COUNT:
        raise ValueError("inputs do not cover the immutable 6,291-name seed scope")
    if native.output_sha256 != native_report_sha256(
        native
    ) or tags.output_sha256 != tag_report_sha256(tags):
        raise ValueError("release-group census report hash does not replay")
    if receipt.reconciliation_output_sha256 != reconciliation.output_sha256:
        raise ValueError("direct proper-genre custody and reconciliation do not agree")

    by_name = {row.normalized_name: row.source_item_id for row in reconciliation.dispositions}
    native_ids = {
        by_name[normalized]
        for row in native.genre_rows
        if (normalized := normalize_label(row.name)) in by_name
    }
    tag_ids = {by_name[row.normalized_seed_name] for row in tags.exact_seed_tag_rows}
    direct_claims = tuple(
        iter_verified_portable_direct_proper_genre_claims(
            receipt, object_store=custody_object_store
        )
    )
    direct_ids = {claim.seed_id for claim in direct_claims}
    direct_artists = {claim.artist_mbid for claim in direct_claims}
    public_and_mb_ids = {
        row.source_item_id for row in reconciliation.dispositions if row.disposition == "reconciled"
    }
    accepted_hierarchy_ids = {
        row.source_item_id for row in hierarchy.seed_coverage if row.accepted_count > 0
    }
    if len(direct_ids) != receipt.seed_count or len(direct_claims) != receipt.claim_count:
        raise ValueError("direct proper-genre custody stream does not replay receipt counts")

    base = OpenNameCoverageFrontier(
        microgenre_stratum_blocker=(
            "The immutable legacy names have no open, independently declared microgenre level; "
            "name shape and MusicBrainz support must not invent that stratum."
        ),
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        direct_custody_output_sha256=receipt.output_sha256,
        native_census_output_sha256=native.output_sha256,
        tag_census_output_sha256=tags.output_sha256,
        hierarchy_output_sha256=hierarchy.output_sha256,
        source_anchor_frontier_output_sha256=anchor_sha,
        source_anchor_seed_count=anchors.direct_observed_seed_count,
        source_anchor_musicbrainz_seed_count=anchors.observed_musicbrainz_seed_count,
        source_anchor_wikidata_seed_count=anchors.observed_wikidata_seed_count,
        source_anchor_cross_source_seed_count=anchors.observed_cross_source_seed_count,
        direct_artist_proper_genre_seed_count=len(direct_ids),
        direct_artist_proper_genre_claim_count=len(direct_claims),
        direct_artist_proper_genre_artist_count=len(direct_artists),
        native_release_group_proper_name_seed_count=len(native_ids),
        native_release_group_proper_observation_count=native.proper_genre_observation_count,
        release_group_tag_name_seed_count=len(tag_ids),
        release_group_tag_observation_count=tags.exact_seed_tag_vote_totals.observation_count,
        public_and_musicbrainz_identity_seed_count=len(public_and_mb_ids),
        direct_artist_proper_and_public_identity_seed_count=len(direct_ids & public_and_mb_ids),
        hierarchy_accepted_seed_count=len(accepted_hierarchy_ids),
        direct_artist_proper_and_native_proper_seed_count=len(direct_ids & native_ids),
        native_proper_and_tag_name_seed_count=len(native_ids & tag_ids),
        direct_artist_proper_and_hierarchy_accepted_seed_count=len(
            direct_ids & accepted_hierarchy_ids
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": frontier_sha256(base)})
