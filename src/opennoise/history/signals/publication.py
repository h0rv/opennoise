"""Seal an H3-only historical signal map for explicit local opt-in serving."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.models.historical_signal import (
    HistoricalSignalArtifact,
    HistoricalSignalPublicationArtifact,
    HistoricalSignalPublicationQuality,
    HistoricalSignalPublicationReceipt,
)
from opennoise.storage import ObjectKey, ObjectStore

if TYPE_CHECKING:
    from opennoise.models.historical import HistoricalCompatibilityReceipt
    from opennoise.storage import ObjectWrite


class HistoricalSignalPublicationError(ValueError):
    """Reject an unsafe or incomplete historical-map publication."""


def _canonical_sha256(value: HistoricalSignalPublicationArtifact) -> str:
    payload = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True).encode()
    ).hexdigest()


def build_historical_signal_publication(
    signal: HistoricalSignalArtifact,
    compatibility: HistoricalCompatibilityReceipt,
) -> HistoricalSignalPublicationArtifact:
    """Parse the two sealed inputs into one complete, non-default local map."""
    handoff = compatibility.full_map_production_input
    membership = compatibility.h3_membership
    if handoff is None or membership is None:
        raise HistoricalSignalPublicationError(
            "historical map publication requires the sealed H3 handoff"
        )
    if not handoff.enabled or handoff.membership_exported:
        raise HistoricalSignalPublicationError(
            "historical map handoff is not local-only H3 evidence"
        )
    if handoff.independent_layout_mode != "reconstruct_from_safe_graph":
        raise HistoricalSignalPublicationError(
            "historical map must use the safe H3 graph layout mode"
        )
    if signal.inputs.h2_artifact_sha256 != compatibility.h2_source_sha256:
        raise HistoricalSignalPublicationError(
            "signal H2 provenance does not match the compatibility receipt"
        )
    if signal.inputs.h3_artifact_sha256 != membership.source_sha256:
        raise HistoricalSignalPublicationError(
            "signal H3 provenance does not match the compatibility receipt"
        )
    if signal.inputs.membership_count != handoff.membership_edge_count:
        raise HistoricalSignalPublicationError(
            "signal membership count does not match the H3 handoff"
        )
    final_lod = signal.progressive_lods[-1]
    final_tile_node_count = sum(
        len(tile.node_ids) for tile in signal.tiles if tile.level == final_lod.level
    )
    return HistoricalSignalPublicationArtifact(
        source_signal_artifact_sha256=signal.quality.artifact_sha256,
        h2_artifact_sha256=signal.inputs.h2_artifact_sha256,
        h3_artifact_sha256=signal.inputs.h3_artifact_sha256,
        h3_database_sha256=signal.inputs.h3_database_sha256,
        h3_policy_key=membership.policy_key,
        map=signal,
        quality=HistoricalSignalPublicationQuality(
            node_count=len(signal.nodes),
            final_lod_node_count=final_lod.node_count,
            final_lod_tile_node_count=final_tile_node_count,
            h3_membership_count=signal.inputs.membership_count,
            h3_member_genre_count=signal.inputs.mapped_membership_genre_count,
            h2_oracle_evaluation_node_count=signal.coordinate_evaluation.compared_node_count,
        ),
    )


def write_historical_signal_publication(
    artifact: HistoricalSignalPublicationArtifact, output_path: Path
) -> tuple[str, int]:
    """Write canonical JSON atomically and return its content identity."""
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def publish_historical_signal_publication(
    artifact: HistoricalSignalPublicationArtifact,
    *,
    output_path: Path,
    store: ObjectStore,
) -> tuple[HistoricalSignalPublicationReceipt, ObjectWrite]:
    """Store one immutable local artifact and issue a receipt that cannot promote it."""
    first_hash = _canonical_sha256(artifact)
    second_hash = _canonical_sha256(artifact)
    if first_hash != second_hash:
        raise HistoricalSignalPublicationError("historical map publication is not deterministic")
    artifact_sha256, artifact_size = write_historical_signal_publication(artifact, output_path)
    key = ObjectKey(
        value=(
            f"historical-signal-map/{artifact.source_signal_artifact_sha256}/{artifact_sha256}.json"
        )
    )
    object_write = store.push(output_path, key)
    if object_write.sha256 != artifact_sha256 or object_write.byte_size != artifact_size:
        raise HistoricalSignalPublicationError(
            "object store write does not match local publication"
        )
    return (
        HistoricalSignalPublicationReceipt(
            artifact_sha256=artifact_sha256,
            artifact_byte_size=artifact_size,
            object_key=key.value,
            source_signal_artifact_sha256=artifact.source_signal_artifact_sha256,
            h2_artifact_sha256=artifact.h2_artifact_sha256,
            h3_artifact_sha256=artifact.h3_artifact_sha256,
            h3_database_sha256=artifact.h3_database_sha256,
            h3_policy_key=artifact.h3_policy_key,
        ),
        object_write,
    )
