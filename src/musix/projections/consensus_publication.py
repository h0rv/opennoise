"""Publish a sealed consensus semantic projection without serving or UI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from musix.models import FrozenModel
from musix.projections.consensus_semantic import (
    ConsensusSemanticProjection,
    verify_consensus_semantic_projection,
)

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "consensus-semantic-projection-publication-v1"


class ConsensusSemanticPublicationError(ValueError):
    """A projection cannot be published under the source-neutral contract."""


class ConsensusSemanticPublicationBinding(FrozenModel):
    """Byte and logical identity of the only publication input."""

    role: Literal["consensus_semantic_projection"] = "consensus_semantic_projection"
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConsensusSemanticPublication(FrozenModel):
    """A UI-agnostic envelope around one replay-verified local-only projection."""

    revision: Literal["consensus-semantic-projection-publication-v1"] = _REVISION
    scope: Literal["local_research_non_production"] = "local_research_non_production"
    historical_inputs_used_for_construction: Literal[False] = False
    source_projection: ConsensusSemanticPublicationBinding
    projection: ConsensusSemanticProjection
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ConsensusSemanticPublicationInputs:
    """The one sealed artifact accepted by the standalone publisher."""

    projection_path: Path


def consensus_semantic_publication_sha256(publication: ConsensusSemanticPublication) -> str:
    """Return the canonical logical hash for one publication envelope."""
    return sha256_hex(
        canonical_json(publication.model_dump(mode="json", exclude={"output_sha256"}))
    )


def build_consensus_semantic_publication(
    inputs: ConsensusSemanticPublicationInputs,
) -> ConsensusSemanticPublication:
    """Wrap one verified projection while binding its exact bytes and logical hash."""
    projection, binding = _load_projection(inputs.projection_path)
    base = ConsensusSemanticPublication(
        source_projection=binding,
        projection=projection,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": consensus_semantic_publication_sha256(base)})


def verify_consensus_semantic_publication(publication: ConsensusSemanticPublication) -> None:
    """Fail closed if the envelope or its nested source-neutral projection changes."""
    if publication.output_sha256 != consensus_semantic_publication_sha256(publication):
        raise ConsensusSemanticPublicationError(
            "consensus semantic publication hash does not replay"
        )
    verify_consensus_semantic_projection(publication.projection)
    if publication.source_projection.logical_sha256 != publication.projection.output_sha256:
        raise ConsensusSemanticPublicationError(
            "publication logical binding does not match nested projection"
        )


def write_consensus_semantic_publication(
    path: Path, publication: ConsensusSemanticPublication
) -> None:
    """Write a verified adapter artifact without registering it with any UI route."""
    verify_consensus_semantic_publication(publication)
    write_atomic_bytes(path, publication.model_dump_json(indent=2).encode() + b"\n")


def _load_projection(
    path: Path,
) -> tuple[ConsensusSemanticProjection, ConsensusSemanticPublicationBinding]:
    raw = path.read_bytes()
    try:
        projection = ConsensusSemanticProjection.model_validate_json(raw)
        verify_consensus_semantic_projection(projection)
    except (OSError, ValueError) as error:
        raise ConsensusSemanticPublicationError("invalid consensus semantic projection") from error
    digest, size = sha256_file(path)
    return projection, ConsensusSemanticPublicationBinding(
        byte_sha256=digest,
        byte_count=size,
        logical_sha256=projection.output_sha256,
    )
