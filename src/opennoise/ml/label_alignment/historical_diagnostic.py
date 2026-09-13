"""Post-seal historical membership/peer coverage diagnostic.

This module is deliberately separate from construction. It reads a sealed
alignment artifact first, then uses only historical node IDs, membership
counts, and peer endpoints to describe held-out coverage strata. Coordinates,
communities, and historical labels are never accessed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_durable_bytes
from opennoise.ml.label_alignment.contracts import ColdLabelAlignmentArtifact, InputBinding
from opennoise.ml.label_alignment.pipeline import verify_cold_label_alignment
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path


class HistoricalDiagnosticError(ValueError):
    """Historical data cannot be safely used as an after-the-fact diagnostic."""


class HistoricalDiagnosticPartition(FrozenModel):
    """Historical-signal availability in one already-sealed alignment partition."""

    seed_count: int = Field(ge=0)
    membership_positive_seed_count: int = Field(ge=0)
    peer_endpoint_seed_count: int = Field(ge=0)


class HistoricalDiagnosticArtifact(FrozenModel):
    """Receipt-bound, post-construction diagnostic with no coordinate values."""

    revision: Literal["cold-label-alignment-historical-diagnostic-v1"] = (
        "cold-label-alignment-historical-diagnostic-v1"
    )
    inputs: tuple[InputBinding, InputBinding]
    alignment_logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_seed_count: int = Field(ge=0)
    accepted: HistoricalDiagnosticPartition
    review: HistoricalDiagnosticPartition
    abstentions: HistoricalDiagnosticPartition
    historical_inputs_used_for_construction: Literal[False] = False
    coordinates_accessed: Literal[False] = False
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoricalDiagnosticReceipt(FrozenModel):
    """Content-addressed receipt for the terminal diagnostic artifact."""

    revision: Literal["cold-label-alignment-historical-diagnostic-receipt-v1"] = (
        "cold-label-alignment-historical-diagnostic-receipt-v1"
    )
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_key: str = Field(min_length=1)


def historical_diagnostic_sha256(artifact: HistoricalDiagnosticArtifact) -> str:
    """Compute the content hash without the self-reference."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def build_historical_diagnostic(
    alignment_path: Path, historical_semantic_path: Path
) -> HistoricalDiagnosticArtifact:
    """Describe historical signal availability after the alignment is sealed."""
    try:
        alignment = ColdLabelAlignmentArtifact.model_validate_json(alignment_path.read_bytes())
        verify_cold_label_alignment(alignment)
        historical = json.loads(historical_semantic_path.read_bytes())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise HistoricalDiagnosticError(
            "historical diagnostic inputs are not sealed JSON artifacts"
        ) from error
    if not isinstance(historical, dict):
        raise HistoricalDiagnosticError("historical semantic artifact must be an object")
    membership_positive, peer_endpoints, historical_seed_count = _historical_sets(historical)
    alignment_sha, alignment_size = sha256_file(alignment_path)
    historical_sha, historical_size = sha256_file(historical_semantic_path)
    base = HistoricalDiagnosticArtifact(
        inputs=(
            InputBinding(
                role="sealed_cold_label_alignment_artifact",
                byte_sha256=alignment_sha,
                byte_count=alignment_size,
                logical_sha256=alignment.output_sha256,
            ),
            InputBinding(
                role="historical_membership_peer_diagnostic",
                byte_sha256=historical_sha,
                byte_count=historical_size,
            ),
        ),
        alignment_logical_output_sha256=alignment.output_sha256,
        historical_seed_count=historical_seed_count,
        accepted=_partition(
            {candidate.source_item_id for candidate in alignment.accepted},
            membership_positive,
            peer_endpoints,
        ),
        review=_partition(
            {candidate.source_item_id for candidate in alignment.review},
            membership_positive,
            peer_endpoints,
        ),
        abstentions=_partition(
            {candidate.source_item_id for candidate in alignment.abstentions},
            membership_positive,
            peer_endpoints,
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": historical_diagnostic_sha256(base)})


def write_historical_diagnostic(
    artifact: HistoricalDiagnosticArtifact, output_root: Path
) -> tuple[HistoricalDiagnosticReceipt, Path, Path]:
    """Publish a terminal diagnostic under durable content-addressed custody."""
    if historical_diagnostic_sha256(artifact) != artifact.output_sha256:
        raise HistoricalDiagnosticError("historical diagnostic hash does not replay")
    directory = output_root / "sha256"
    directory.mkdir(parents=True, exist_ok=True)
    artifact_path = directory / f"{artifact.output_sha256}.json"
    payload = canonical_json(artifact.model_dump(mode="json")) + b"\n"
    write_durable_bytes(artifact_path, payload)
    receipt = HistoricalDiagnosticReceipt(
        artifact_sha256=sha256_hex(payload),
        artifact_byte_count=len(payload),
        logical_output_sha256=artifact.output_sha256,
        object_key=f"cold-label-alignment-historical-diagnostic/v1/sha256/{artifact.output_sha256}.json",
    )
    receipt_path = directory / f"{artifact.output_sha256}.receipt.json"
    write_durable_bytes(receipt_path, canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return receipt, artifact_path, receipt_path


def _historical_sets(payload: dict[str, object]) -> tuple[set[str], set[str], int]:
    nodes = payload.get("nodes")
    neighbors = payload.get("neighbors")
    if not isinstance(nodes, list) or not isinstance(neighbors, list):
        raise HistoricalDiagnosticError("historical artifact lacks nodes or neighbors")
    membership_positive: set[str] = set()
    historical_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        source_id = _source_id(node.get("genre_id"))
        membership_count = node.get("membership_count")
        if source_id is None:
            continue
        historical_ids.add(source_id)
        if (
            isinstance(membership_count, int)
            and not isinstance(membership_count, bool)
            and membership_count > 0
        ):
            membership_positive.add(source_id)
    peer_endpoints: set[str] = set()
    for neighbor in neighbors:
        if not isinstance(neighbor, dict):
            continue
        for key in ("genre_id", "neighbor_genre_id"):
            source_id = _source_id(neighbor.get(key))
            if source_id is not None:
                peer_endpoints.add(source_id)
    return membership_positive, peer_endpoints, len(historical_ids)


def _source_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("enao-legacy:"):
        return None
    source_id = value.removeprefix("enao-legacy:")
    return source_id if source_id and ":" not in source_id else None


def _partition(
    identifiers: set[str], membership_positive: set[str], peer_endpoints: set[str]
) -> HistoricalDiagnosticPartition:
    return HistoricalDiagnosticPartition(
        seed_count=len(identifiers),
        membership_positive_seed_count=len(identifiers & membership_positive),
        peer_endpoint_seed_count=len(identifiers & peer_endpoints),
    )
