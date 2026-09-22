"""Strict ListenBrainz source-boundary models."""

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.models.sources import DownloadSource
from opennoise.types import Sha256


class _ListenBrainzBoundaryModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class ListenMbidMapping(_ListenBrainzBoundaryModel):
    """Parse server-resolved MusicBrainz artist identifiers when present."""

    artist_mbids: tuple[str, ...] = ()


class ListenAdditionalInfo(_ListenBrainzBoundaryModel):
    """Parse MusicBrainz identifiers carried by the official listen dump."""

    artist_mbids: tuple[str, ...] = ()


class ListenTrackMetadata(_ListenBrainzBoundaryModel):
    """Discard submitted names and retain only source-qualified identifiers."""

    mbid_mapping: ListenMbidMapping | None = None
    additional_info: ListenAdditionalInfo | None = None


class ListenBrainzListen(_ListenBrainzBoundaryModel):
    """Parse the minimum official JSON listen shape used by aggregation."""

    listened_at: int = Field(
        validation_alias=AliasChoices("timestamp", "listened_at"),
        ge=0,
    )
    user_id: int = Field(ge=0)
    track_metadata: ListenTrackMetadata


class ListenBrainzAggregationConfig(BaseModel):
    """Choose explicit fixed windows, privacy floor, ordering, and state limits."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    ordering: Literal["newest_first", "unordered_bounded"] = "unordered_bounded"
    window_seconds: int = Field(default=86_400, gt=0)
    minimum_distinct_users: int = Field(default=2, gt=0)
    max_users_per_window: int = Field(default=2_000_000, gt=0)
    max_artists_per_user_window: int = Field(default=1_000, gt=1)
    max_distinct_artists: int = Field(default=5_000_000, gt=1)
    max_pairs_per_window: int = Field(default=10_000_000, gt=0)
    max_listen_members: int = Field(default=16, gt=0)
    max_active_windows: int = Field(default=20_000, gt=0)
    max_total_user_windows: int = Field(default=5_000_000, gt=0)
    minimum_window_start: int | None = Field(default=None, ge=0)
    maximum_window_start: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_complete_window_selection(self) -> "ListenBrainzAggregationConfig":
        """Require an ordered, aligned pair of optional event-time bounds."""
        bounds = (self.minimum_window_start, self.maximum_window_start)
        if (bounds[0] is None) != (bounds[1] is None):
            raise ValueError("event-time window bounds must be set together")
        if bounds[0] is None or bounds[1] is None:
            return self
        if bounds[0] > bounds[1]:
            raise ValueError("minimum_window_start cannot exceed maximum_window_start")
        if bounds[0] % self.window_seconds or bounds[1] % self.window_seconds:
            raise ValueError("event-time window bounds must align to window_seconds")
        return self


class JointListenArtifact(_ListenBrainzBoundaryModel):
    """Bind one verified increment to its strict corpus order."""

    source: DownloadSource
    path: Path
    sequence: int = Field(ge=0)
    snapshot_date: date


class ListenBrainzCompletionInput(_ListenBrainzBoundaryModel):
    """One content-addressed daily input in a future completion identity."""

    source_key: str = Field(min_length=1, max_length=300)
    snapshot_ref: str = Field(min_length=1, max_length=600)
    artifact_sha256: Sha256
    byte_size: int = Field(ge=0)
    sequence: int = Field(ge=0)


class ListenBrainzSemanticCompletionReceipt(_ListenBrainzBoundaryModel):
    """Deterministic identity for a completed fixed-window aggregation.

    This deliberately excludes executable-byte identity and process measurements.
    Those facts remain available in :class:`ListenBrainzRuntimeTelemetryReceipt`
    without making a semantic replay depend on import paths or machine load.
    """

    revision: Literal["listenbrainz-semantic-completion-v1"] = "listenbrainz-semantic-completion-v1"
    aggregation_version: str = Field(min_length=1)
    configuration: ListenBrainzAggregationConfig
    configuration_sha256: Sha256
    inputs: tuple[ListenBrainzCompletionInput, ...] = Field(min_length=7, max_length=14)
    listens_seen: int = Field(ge=0)
    listens_with_artist_mbid: int = Field(ge=0)
    distinct_artists: int = Field(ge=0)
    user_windows: int = Field(ge=0)
    candidate_pairs: int = Field(ge=0)
    emitted_pairs: int = Field(ge=0)
    quarantined_records: int = Field(ge=0)
    minimum_listened_at: int | None = Field(default=None, ge=0)
    maximum_listened_at: int | None = Field(default=None, ge=0)
    semantic_identity_sha256: Sha256

    @model_validator(mode="after")
    def check_identity(self) -> "ListenBrainzSemanticCompletionReceipt":
        """Reject a receipt whose deterministic identity does not replay."""
        if (
            self.configuration_sha256
            != hashlib.sha256(self.configuration.model_dump_json().encode()).hexdigest()
        ):
            raise ValueError("completion receipt configuration hash does not replay")
        sequences = tuple(item.sequence for item in self.inputs)
        if sequences != tuple(range(sequences[0], sequences[0] + len(sequences))):
            raise ValueError("completion receipt inputs must be contiguous and ordered")
        if len({item.artifact_sha256 for item in self.inputs}) != len(self.inputs):
            raise ValueError("completion receipt inputs must have unique artifact hashes")
        expected = sha256_hex(
            canonical_json(self.model_dump(mode="json", exclude={"semantic_identity_sha256"}))
        )
        if self.semantic_identity_sha256 != expected:
            raise ValueError("completion semantic identity does not replay")
        return self


class ListenBrainzRuntimeTelemetryReceipt(_ListenBrainzBoundaryModel):
    """Auditable non-semantic execution facts for one completion identity."""

    revision: Literal["listenbrainz-runtime-telemetry-v1"] = "listenbrainz-runtime-telemetry-v1"
    semantic_identity_sha256: Sha256
    adapter_key: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    adapter_build_sha256: Sha256
    elapsed_ms: int = Field(ge=0)
    peak_rss_bytes: int = Field(ge=0)
    telemetry_sha256: Sha256

    @model_validator(mode="after")
    def check_identity(self) -> "ListenBrainzRuntimeTelemetryReceipt":
        """Reject a telemetry record that cannot be independently rehashed."""
        expected = sha256_hex(
            canonical_json(self.model_dump(mode="json", exclude={"telemetry_sha256"}))
        )
        if self.telemetry_sha256 != expected:
            raise ValueError("completion runtime telemetry does not replay")
        return self


class ListenBrainzCompletionReceipt(_ListenBrainzBoundaryModel):
    """Bind one deterministic completion identity to separately auditable telemetry."""

    revision: Literal["listenbrainz-completion-receipt-v1"] = "listenbrainz-completion-receipt-v1"
    semantic: ListenBrainzSemanticCompletionReceipt
    runtime: ListenBrainzRuntimeTelemetryReceipt

    @model_validator(mode="after")
    def check_binding(self) -> "ListenBrainzCompletionReceipt":
        """Ensure the runtime record belongs to this semantic completion."""
        if self.runtime.semantic_identity_sha256 != self.semantic.semantic_identity_sha256:
            raise ValueError("completion runtime telemetry binds another semantic identity")
        return self
