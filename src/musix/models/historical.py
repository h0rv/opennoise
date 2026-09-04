"""Strict, provenance-first contracts for the bounded historical Every Noise lens."""

from typing import Literal

from pydantic import AnyHttpUrl, Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.types import Sha256

type HistoricalStage = Literal["H1", "H2", "H3", "H4", "H5", "H6"]
type CoverageState = Literal["complete", "partial", "missing"]
type HistoricalRelationMethod = Literal[
    "artist_overlap",
    "audio_similarity",
    "historical_unspecified",
]


class HistoricalArtifact(FrozenModel):
    """Identify one immutable, local-only historical source artifact."""

    source_id: str = Field(min_length=1, max_length=200)
    snapshot: str = Field(min_length=1, max_length=300)
    source_url: AnyHttpUrl
    content_sha256: Sha256
    byte_size: int = Field(gt=0)
    expected_genres: int = Field(gt=0, le=20_000)
    rights_classification: Literal["user_authorized_local"] = "user_authorized_local"
    local_only: Literal[True] = True


class HistoricalCoordinate(FrozenModel):
    """One observed legacy display position, not an inferred embedding."""

    x_px: FiniteFloat = Field(ge=0.0, le=2_000.0)
    y_px: FiniteFloat = Field(ge=0.0, le=30_000.0)
    color_hex: str = Field(pattern=r"^#[0-9a-f]{6}$")
    font_size_percent: int = Field(ge=100, le=200)
    coordinate_kind: Literal["legacy_display_coordinate"] = "legacy_display_coordinate"


class HistoricalRepresentative(FrozenModel):
    """One map-row representative. It deliberately contains no preview URL or media bytes."""

    artist_name: str = Field(min_length=1, max_length=500)
    track_title: str = Field(min_length=1, max_length=500)
    recording_provider: Literal["spotify"] = "spotify"
    recording_source_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")
    safe_external_url: AnyHttpUrl
    source_genre_page_url: AnyHttpUrl | None = None
    legacy_preview_state: Literal["absent", "disabled_legacy"]
    legacy_preview_url_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def require_preview_hash_only_when_present(self) -> "HistoricalRepresentative":
        """Keep only a hash for disabled legacy previews."""
        if (self.legacy_preview_state == "disabled_legacy") != (
            self.legacy_preview_url_sha256 is not None
        ):
            raise ValueError("legacy preview state and hash are inconsistent")
        return self


class HistoricalGenre(FrozenModel):
    """One dated map row exactly as retained by the verified source artifact."""

    external_id: str = Field(min_length=1, max_length=200)
    source_item_id: str = Field(min_length=1, max_length=100)
    source_order: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=500)
    slug: str = Field(min_length=1, max_length=500)
    coordinate: HistoricalCoordinate
    representative: HistoricalRepresentative | None = None


class HistoricalRelation(FrozenModel):
    """One observed relation from a retained page, never a coordinate-derived guess."""

    source_external_id: str = Field(min_length=1, max_length=200)
    target_external_id: str | None = Field(default=None, min_length=1, max_length=200)
    target_name: str = Field(min_length=1, max_length=500)
    method: HistoricalRelationMethod
    source_rank: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def reject_self_relation_when_resolved(self) -> "HistoricalRelation":
        """Reject a resolved link to the same genre."""
        if self.source_external_id == self.target_external_id:
            raise ValueError("historical relation cannot target itself")
        return self


class HistoricalQuarantine(FrozenModel):
    """One safely retained parser rejection with source position and provenance."""

    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: Sha256
    source_record_number: int = Field(gt=0)
    source_record_id: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)


class HistoricalCoverage(FrozenModel):
    """Declare exactly what one historical stage can and cannot reproduce."""

    stage: HistoricalStage
    state: CoverageState
    retained_record_count: int = Field(ge=0)
    quarantined_record_count: int = Field(default=0, ge=0)
    expected_record_count: int | None = Field(default=None, ge=0)
    retained_fields: tuple[str, ...] = Field(default=(), max_length=64)
    missing_fields: tuple[str, ...] = Field(default=(), max_length=64)
    accounting_note: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def require_explicit_missing_accounting(self) -> "HistoricalCoverage":
        """Require every unavailable surface to state its missing fields."""
        if self.state == "complete" and self.missing_fields:
            raise ValueError("complete coverage cannot declare missing fields")
        if self.state != "complete" and not self.missing_fields:
            raise ValueError("partial or missing coverage requires missing fields")
        if (
            self.expected_record_count is not None
            and self.retained_record_count + self.quarantined_record_count
            > self.expected_record_count
        ):
            raise ValueError("retained and quarantined record counts exceed expected record count")
        return self


class HistoricalAdapterCheckpoint(FrozenModel):
    """Portable state needed to resume a future bounded historical adapter."""

    contract_key: str = Field(min_length=1, max_length=200)
    source_sha256: Sha256 | None = None
    cursor: str | None = Field(default=None, max_length=2_000)
    accepted_records: int = Field(default=0, ge=0)
    quarantined_records: int = Field(default=0, ge=0)
    complete: bool = False


class HistoricalAdapterContract(FrozenModel):
    """A no-fetch contract for a missing historical surface and its future resume state."""

    stage: Literal["H3", "H4", "H5", "H6"]
    contract_key: str = Field(min_length=1, max_length=200)
    adapter_key: str = Field(min_length=1, max_length=200)
    input_kind: Literal["archived_html", "archived_list", "derived_projection"]
    source_requirement: str = Field(min_length=1, max_length=2_000)
    output_observations: tuple[str, ...] = Field(min_length=1, max_length=32)
    checkpoint: HistoricalAdapterCheckpoint
    enabled: bool = False

    @model_validator(mode="after")
    def require_matching_checkpoint_key(self) -> "HistoricalAdapterContract":
        """Bind a reusable checkpoint to exactly one adapter contract."""
        if self.contract_key != self.checkpoint.contract_key:
            raise ValueError("adapter contract and checkpoint keys must match")
        if self.enabled and self.checkpoint.source_sha256 is None:
            raise ValueError("an enabled adapter needs a verified source hash")
        return self


class HistoricalCompatibilityManifest(FrozenModel):
    """A complete, bounded compatibility artifact for the retained historical data."""

    revision: Literal["historical-compatibility-v1"] = "historical-compatibility-v1"
    artifact: HistoricalArtifact
    genres: tuple[HistoricalGenre, ...] = Field(min_length=1, max_length=20_000)
    relations: tuple[HistoricalRelation, ...] = Field(default=(), max_length=500_000)
    quarantine: tuple[HistoricalQuarantine, ...] = Field(default=(), max_length=20_000)
    coverage: tuple[HistoricalCoverage, ...] = Field(min_length=6, max_length=6)
    adapter_contracts: tuple[HistoricalAdapterContract, ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def require_complete_accounting(self) -> "HistoricalCompatibilityManifest":
        """Require a full verified map and exactly one record for every stage."""
        genre_ids = [genre.external_id for genre in self.genres]
        if len(genre_ids) != len(set(genre_ids)):
            raise ValueError("historical genre external IDs must be unique")
        item_ids = [genre.source_item_id for genre in self.genres]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("historical source item IDs must be unique")
        if len(self.genres) != self.artifact.expected_genres:
            raise ValueError("historical genre count does not match verified source expectation")
        stages = tuple(item.stage for item in self.coverage)
        if set(stages) != {"H1", "H2", "H3", "H4", "H5", "H6"}:
            raise ValueError("coverage must account for H1 through H6 exactly once")
        contract_stages = tuple(item.stage for item in self.adapter_contracts)
        if set(contract_stages) != {"H3", "H4", "H5", "H6"}:
            raise ValueError("adapter contracts must cover H3 through H6 exactly once")
        known = set(genre_ids)
        if any(relation.source_external_id not in known for relation in self.relations):
            raise ValueError("historical relations require a retained source genre")
        if any(
            relation.target_external_id is not None and relation.target_external_id not in known
            for relation in self.relations
        ):
            raise ValueError("resolved historical relations require retained target genres")
        if any(
            item.source_id != self.artifact.source_id
            or item.source_sha256 != self.artifact.content_sha256
            for item in self.quarantine
        ):
            raise ValueError("historical quarantine needs matching source provenance")
        return self


class PublicComparisonGenre(FrozenModel):
    """The small independent public-model projection required for comparison."""

    genre_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    x: FiniteFloat | None = None
    y: FiniteFloat | None = None

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> "PublicComparisonGenre":
        """Keep optional public coordinates atomic."""
        if (self.x is None) != (self.y is None):
            raise ValueError("public comparison coordinates must be supplied as a pair")
        return self


class PublicComparisonRelation(FrozenModel):
    """One independently produced public relationship for overlap measurement."""

    source_genre_id: str = Field(min_length=1, max_length=200)
    target_genre_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def reject_self_relation(self) -> "PublicComparisonRelation":
        """Reject an invalid public self relation."""
        if self.source_genre_id == self.target_genre_id:
            raise ValueError("public comparison relations cannot be self relations")
        return self


class PublicComparisonModel(FrozenModel):
    """A typed independent public model projection, separate from historical inputs."""

    revision: str = Field(min_length=1, max_length=200)
    output_sha256: Sha256
    genres: tuple[PublicComparisonGenre, ...] = Field(min_length=1, max_length=20_000)
    relations: tuple[PublicComparisonRelation, ...] = Field(default=(), max_length=500_000)

    @model_validator(mode="after")
    def require_references(self) -> "PublicComparisonModel":
        """Ensure public relationships are resolvable inside this projection."""
        genre_ids = {genre.genre_id for genre in self.genres}
        if len(genre_ids) != len(self.genres):
            raise ValueError("public comparison genre IDs must be unique")
        if any(
            relation.source_genre_id not in genre_ids or relation.target_genre_id not in genre_ids
            for relation in self.relations
        ):
            raise ValueError("public comparison relation endpoints need genres")
        return self


class HistoricalGeometryComparison(FrozenModel):
    """Coverage and aligned coordinate diagnostics, with no recovery claim."""

    matched_name_count: int = Field(ge=0)
    legacy_genre_count: int = Field(ge=0)
    public_genre_count: int = Field(ge=0)
    aligned_coordinate_count: int = Field(ge=0)
    root_mean_square_error: FiniteFloat | None = Field(default=None, ge=0.0)
    coordinate_comparison_state: Literal["compared", "insufficient_overlap"]
    exact_historical_recovery_claimed: Literal[False] = False


class HistoricalRelationshipComparison(FrozenModel):
    """Observed-only relationship overlap; unavailable is an honest result."""

    observed_historical_relations: int = Field(ge=0)
    comparable_historical_relations: int = Field(ge=0)
    overlapping_public_relations: int = Field(ge=0)
    comparison_state: Literal["compared", "unavailable"]

    @model_validator(mode="after")
    def require_consistent_relationship_state(self) -> "HistoricalRelationshipComparison":
        """Prevent unavailable comparisons from carrying synthetic overlap counts."""
        if self.comparison_state == "unavailable" and self.comparable_historical_relations:
            raise ValueError("unavailable relationship comparison cannot have comparable relations")
        if self.overlapping_public_relations > self.comparable_historical_relations:
            raise ValueError("relationship overlap exceeds comparable relations")
        return self


class HistoricalCompatibilityReport(FrozenModel):
    """Reproducible quality report for one historical and public-model pair."""

    revision: Literal["historical-compatibility-report-v1"] = "historical-compatibility-report-v1"
    historical_source_sha256: Sha256
    public_model_output_sha256: Sha256
    coverage: tuple[HistoricalCoverage, ...] = Field(min_length=6, max_length=6)
    geometry: HistoricalGeometryComparison
    relationships: HistoricalRelationshipComparison
