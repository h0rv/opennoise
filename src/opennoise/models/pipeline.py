"""Strict shared pipeline limits and adapter result records."""

from pydantic import BaseModel, ConfigDict, Field

from opennoise.models.catalog import CatalogProjection
from opennoise.types import Sha256


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class SourceLimits(_FrozenModel):
    """Bound compressed bytes, expansion, records, lines, and runtime."""

    max_archive_bytes: int = Field(default=4 * 1024 * 1024 * 1024, gt=0)
    max_member_bytes: int = Field(default=32 * 1024 * 1024 * 1024, gt=0)
    max_record_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    max_records: int = Field(default=10_000_000, gt=0)
    max_decompression_ratio: float = Field(default=64.0, gt=0)
    timeout_seconds: float = Field(default=6 * 60 * 60, gt=0)


class ParsedSourceRecord(_FrozenModel):
    """Carry an accepted boundary record and exact-byte identity to the pipeline."""

    ordinal: int = Field(ge=0)
    exact_sha256: Sha256
    byte_length: int = Field(ge=0)
    projection: CatalogProjection


class RejectedSourceRecord(_FrozenModel):
    """Carry one rejected boundary record without its potentially unsafe payload."""

    ordinal: int = Field(ge=0)
    exact_sha256: Sha256
    byte_length: int = Field(ge=0)
    reason: str = Field(min_length=1)


type SourceRecord = ParsedSourceRecord | RejectedSourceRecord
