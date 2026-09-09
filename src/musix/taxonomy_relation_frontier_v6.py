"""Compact v6 frontier wrapper over sealed v5 evidence and a factual hierarchy overlay."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from musix.common import sha256_file, sha256_json
from musix.evidence_frontier import (
    AllSeedEvidenceFrontierArtifact,
    EvidenceFrontierCoverage,
    EvidenceFrontierReceipt,
)
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy_relation_hierarchy_overlay import (
    TaxonomyRelationHierarchyOverlay,
    TaxonomyRelationHierarchyOverlayReceipt,
)
from musix.types import Sha256  # noqa: TC001

_REVISION = "all-seed-evidence-frontier-v6-taxonomy-overlay"
_SEED_COUNT = 6_291


class TaxonomyRelationFrontierSeedSupport(FrozenModel):
    """Direct factual relation support contributed by the compact overlay."""

    source_item_id: str = Field(min_length=1, max_length=200)
    factual_parent_count: int = Field(ge=0)
    factual_child_count: int = Field(ge=0)
    factual_relation_edge_count: int = Field(ge=0)

    @model_validator(mode="after")
    def partition_edge_incidence(self) -> TaxonomyRelationFrontierSeedSupport:
        """Require outgoing and incoming factual incidences to form one total."""
        if self.factual_relation_edge_count != self.factual_parent_count + self.factual_child_count:
            raise ValueError(
                "per-seed factual relation incidence must partition parents and children"
            )
        return self


class TaxonomyRelationFrontierV6(FrozenModel):
    """Small v6 wrapper; v5 remains authoritative for MB/WD/LB/peer evidence."""

    revision: Literal["all-seed-evidence-frontier-v6-taxonomy-overlay"] = _REVISION
    base_v5_logical_output_sha256: Sha256
    base_v5_receipt_sha256: Sha256
    base_v5_object_key: ObjectKey
    base_v5_object_sha256: Sha256
    base_v5_object_byte_size: int = Field(ge=1)
    preserved_v5_coverage: EvidenceFrontierCoverage
    preserved_v5_coverage_sha256: Sha256
    hierarchy_overlay_logical_output_sha256: Sha256
    hierarchy_overlay_receipt_sha256: Sha256
    hierarchy_overlay_object_key: ObjectKey
    hierarchy_overlay_object_sha256: Sha256
    hierarchy_overlay_object_byte_size: int = Field(ge=1)
    hierarchy_base_candidate_count: int = Field(ge=0)
    hierarchy_base_accepted_count: int = Field(ge=0)
    hierarchy_union_candidate_count: int = Field(ge=0)
    hierarchy_union_accepted_count: int = Field(ge=0)
    hierarchy_net_new_accepted_count: int = Field(ge=0)
    hierarchy_isolated_seed_reduction: int = Field(ge=0)
    support_rows: tuple[TaxonomyRelationFrontierSeedSupport, ...] = Field(
        min_length=_SEED_COUNT, max_length=_SEED_COUNT
    )
    output_sha256: Sha256

    @model_validator(mode="after")
    def complete_monotonic_wrapper(self) -> TaxonomyRelationFrontierV6:
        """Bind complete support coverage and non-decreasing hierarchy counts."""
        ids = tuple(row.source_item_id for row in self.support_rows)
        if ids != tuple(sorted(ids)) or len(set(ids)) != _SEED_COUNT:
            raise ValueError("v6 factual support must cover every v5 seed once in sorted order")
        if self.preserved_v5_coverage_sha256 != sha256_json(
            self.preserved_v5_coverage.model_dump(mode="json")
        ):
            raise ValueError("v6 preserved v5 coverage hash does not replay")
        if self.hierarchy_union_candidate_count < self.hierarchy_base_candidate_count:
            raise ValueError("v6 hierarchy union cannot remove base candidate pairs")
        if self.hierarchy_union_accepted_count < self.hierarchy_base_accepted_count:
            raise ValueError("v6 hierarchy union cannot remove accepted base pairs")
        if self.hierarchy_union_candidate_count != (
            self.hierarchy_base_candidate_count + self.hierarchy_net_new_accepted_count
        ):
            raise ValueError("v6 hierarchy candidate union must be monotonic and exact")
        if (
            sha256_json(self.model_dump(mode="json", exclude={"output_sha256"}))
            != self.output_sha256
        ):
            raise ValueError("v6 compact frontier logical hash does not replay")
        return self


class TaxonomyRelationFrontierV6Receipt(FrozenModel):
    """Immutable object-store receipt for a compact v6 frontier wrapper."""

    artifact: ObjectWrite
    artifact_sha256: Sha256
    logical_output_sha256: Sha256


@dataclass(frozen=True)
class FrontierV6Inputs:
    """All explicitly trusted immutable inputs required for v6 construction."""

    v5_path: Path
    v5_receipt: EvidenceFrontierReceipt
    v5_receipt_sha256: Sha256
    expected_v5_receipt_sha256: Sha256
    v5_object_store: ObjectStore
    overlay_path: Path
    overlay_receipt: TaxonomyRelationHierarchyOverlayReceipt
    overlay_receipt_sha256: Sha256
    expected_overlay_receipt_sha256: Sha256
    overlay_object_store: ObjectStore


def _verify_inputs(
    inputs: FrontierV6Inputs,
) -> tuple[AllSeedEvidenceFrontierArtifact, TaxonomyRelationHierarchyOverlay]:
    if inputs.v5_receipt_sha256 != inputs.expected_v5_receipt_sha256:
        raise ValueError("v5 receipt does not match its explicit trust root")
    if inputs.overlay_receipt_sha256 != inputs.expected_overlay_receipt_sha256:
        raise ValueError("overlay receipt does not match its explicit trust root")
    if inputs.v5_receipt.artifact_sha256 != sha256_file(inputs.v5_path)[0]:
        raise ValueError("v5 local bytes do not match receipt")
    v5_meta = inputs.v5_object_store.inspect(ObjectKey(value=inputs.v5_receipt.object_key))
    if (
        v5_meta.sha256 != inputs.v5_receipt.artifact_sha256
        or v5_meta.byte_size != inputs.v5_receipt.artifact_byte_size
    ):
        raise ValueError("v5 object does not match receipt")
    if inputs.overlay_receipt.artifact_sha256 != sha256_file(inputs.overlay_path)[0]:
        raise ValueError("overlay local bytes do not match receipt")
    overlay_meta = inputs.overlay_object_store.inspect(inputs.overlay_receipt.artifact.key)
    if (
        overlay_meta.sha256 != inputs.overlay_receipt.artifact_sha256
        or overlay_meta.byte_size != inputs.overlay_receipt.artifact.byte_size
    ):
        raise ValueError("overlay object does not match receipt")
    v5 = AllSeedEvidenceFrontierArtifact.model_validate_json(inputs.v5_path.read_bytes())
    if v5.output_sha256 != inputs.v5_receipt.logical_output_sha256:
        raise ValueError("v5 logical output does not match receipt")
    overlay = TaxonomyRelationHierarchyOverlay.model_validate_json(inputs.overlay_path.read_bytes())
    if overlay.output_sha256 != inputs.overlay_receipt.logical_output_sha256:
        raise ValueError("overlay logical output does not match receipt")
    return v5, overlay


def build_taxonomy_relation_frontier_v6(inputs: FrontierV6Inputs) -> TaxonomyRelationFrontierV6:
    """Bind v5 intact and project only compact direct relation support per seed."""
    v5, overlay = _verify_inputs(inputs)
    parents: dict[str, int] = {row.source_item_id: 0 for row in v5.rows}
    children: dict[str, int] = {row.source_item_id: 0 for row in v5.rows}
    for edge in overlay.edges:
        if edge.child_genre_id not in parents or edge.parent_genre_id not in parents:
            raise ValueError("overlay edge is outside the sealed v5 seed universe")
        parents[edge.child_genre_id] += 1
        children[edge.parent_genre_id] += 1
    rows = tuple(
        TaxonomyRelationFrontierSeedSupport(
            source_item_id=seed_id,
            factual_parent_count=parents[seed_id],
            factual_child_count=children[seed_id],
            factual_relation_edge_count=parents[seed_id] + children[seed_id],
        )
        for seed_id in sorted(parents)
    )
    payload: dict[str, Any] = {
        "base_v5_logical_output_sha256": v5.output_sha256,
        "base_v5_receipt_sha256": inputs.v5_receipt_sha256,
        "base_v5_object_key": ObjectKey(value=inputs.v5_receipt.object_key),
        "base_v5_object_sha256": inputs.v5_receipt.artifact_sha256,
        "base_v5_object_byte_size": inputs.v5_receipt.artifact_byte_size,
        "preserved_v5_coverage": v5.coverage,
        "preserved_v5_coverage_sha256": sha256_json(v5.coverage.model_dump(mode="json")),
        "hierarchy_overlay_logical_output_sha256": overlay.output_sha256,
        "hierarchy_overlay_receipt_sha256": inputs.overlay_receipt_sha256,
        "hierarchy_overlay_object_key": inputs.overlay_receipt.artifact.key,
        "hierarchy_overlay_object_sha256": inputs.overlay_receipt.artifact_sha256,
        "hierarchy_overlay_object_byte_size": inputs.overlay_receipt.artifact.byte_size,
        "hierarchy_base_candidate_count": overlay.base_candidate_count,
        "hierarchy_base_accepted_count": overlay.base_accepted_count,
        "hierarchy_union_candidate_count": overlay.union_candidate_count,
        "hierarchy_union_accepted_count": overlay.union_accepted_count,
        "hierarchy_net_new_accepted_count": overlay.net_new_accepted_count,
        "hierarchy_isolated_seed_reduction": overlay.isolated_seed_reduction,
        "support_rows": rows,
        "output_sha256": "0" * 64,
    }
    provisional = TaxonomyRelationFrontierV6.model_construct(**payload)
    payload["output_sha256"] = sha256_json(
        provisional.model_dump(mode="json", exclude={"output_sha256"})
    )
    return TaxonomyRelationFrontierV6.model_validate(payload)


def publish_taxonomy_relation_frontier_v6(
    artifact: TaxonomyRelationFrontierV6, *, output: Path, store: ObjectStore
) -> TaxonomyRelationFrontierV6Receipt:
    """Atomically publish a compact receipt-rooted v6 wrapper."""
    payload = (artifact.model_dump_json(indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    write = store.push(
        output,
        ObjectKey(value=f"all-seed-evidence-frontier-v6/sha256/{artifact.output_sha256}.json"),
    )
    if write.sha256 != artifact_sha or write.byte_size != len(payload):
        raise ValueError("v6 object-store publication does not match bytes")
    return TaxonomyRelationFrontierV6Receipt(
        artifact=write, artifact_sha256=artifact_sha, logical_output_sha256=artifact.output_sha256
    )
