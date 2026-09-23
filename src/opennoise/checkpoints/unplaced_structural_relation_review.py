"""Create a local packet for reviewing unplaced genre relation proposals.

The packet combines hierarchy candidates with co-listen context.  Neither
input supplies a coordinate or an accepted placement.  Co-listen rows remain
non-structural context and cannot be used as factual relation evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final, Literal

from pydantic import ConfigDict, Field, model_validator

from opennoise.analysis.musicbrainz_unplaced_colisten_edges import (
    MusicBrainzUnplacedCoListenReport,
)
from opennoise.models import FrozenModel
from opennoise.taxonomy.structure.hierarchy_candidates import (
    GenreHierarchyCandidateArtifact,
)
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "unplaced-structural-relation-review-v1"
_PROJECT_CACHE_ROOT: Final = Path(__file__).resolve().parents[3] / ".cache"
_HIERARCHY_FILE_SHA256: Final = "b702d6e78d5f94c04dd4adfef4314ed02538b92a6042140ee8a35768ae712a8a"
_HIERARCHY_LOGICAL_SHA256: Final = (
    "fc224da42842cdd0a4a9b5628d015cf83d60266b609857dcdff96abe01f7f02a"
)
_COLISTEN_FILE_SHA256: Final = "7261dbfdcfce25c596eca2af3137e4649318dbe6ee9ca92b99b41345c24d8431"
_COLISTEN_LOGICAL_SHA256: Final = "284e1e43d224a24934b92ba3a4f44f39d463dc1041a4093e082f4d3ff6f9cc24"
_LAYOUT_FILE_SHA256: Final = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_LAYOUT_LOGICAL_SHA256: Final = "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"


class UnplacedStructuralRelationReviewError(ValueError):
    """The review packet inputs do not form a safe local-only boundary."""


class _LayoutRow(FrozenModel):
    seed_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class _LayoutArtifact(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    output_sha256: Sha256
    coordinates: tuple[_LayoutRow, ...]
    unplaced: tuple[_LayoutRow, ...]


class ReviewInputPin(FrozenModel):
    """File and logical identities for one immutable packet input."""

    file_sha256: Sha256
    logical_sha256: Sha256


class StructuralRelationReviewRow(FrozenModel):
    """One reviewer-facing relation row that remains an explicit abstention."""

    category: Literal["hierarchy_review_candidate", "colisten_context_only"]
    reason: str = Field(min_length=1)
    child_seed_id: str = Field(min_length=1)
    child_name: str = Field(min_length=1)
    child_state: Literal["unplaced"] = "unplaced"
    parent_seed_id: str = Field(min_length=1)
    parent_name: str = Field(min_length=1)
    parent_state: Literal["placed", "unplaced"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    factual_structural_evidence: Literal[False] = False
    placement_abstention: Literal["no_supported_structural_relation"] = (
        "no_supported_structural_relation"
    )

    @model_validator(mode="after")
    def require_distinct_endpoints(self) -> StructuralRelationReviewRow:
        """Reject a relation that names the same seed at both endpoints."""
        if self.child_seed_id == self.parent_seed_id:
            raise ValueError("review rows cannot have identical endpoints")
        return self


class UnplacedStructuralRelationReviewCoverage(FrozenModel):
    """Counts that keep names, rows, and sources separately visible."""

    layout_unplaced_seed_count: int = Field(ge=1)
    hierarchy_review_seed_count: int = Field(ge=0)
    hierarchy_review_row_count: int = Field(ge=0)
    colisten_review_seed_count: int = Field(ge=0)
    colisten_review_row_count: int = Field(ge=0)
    total_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_row_partition(self) -> UnplacedStructuralRelationReviewCoverage:
        """Require category counts to account for every packet row."""
        if self.total_row_count != self.hierarchy_review_row_count + self.colisten_review_row_count:
            raise ValueError("review rows do not partition by input category")
        return self


class UnplacedStructuralRelationReviewPacket(FrozenModel):
    """Hash-bound local-only material for a music-domain review decision."""

    revision: Literal["unplaced-structural-relation-review-v1"] = _REVISION
    local_only: Literal[True] = True
    create_only: Literal[True] = True
    coordinate_values_read: Literal[False] = False
    placed_seed_identifiers_read: Literal[True] = True
    historical_inputs_used: Literal[False] = False
    serving_allowed: Literal[False] = False
    export_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    placement_asserted: Literal[False] = False
    hierarchy_input: ReviewInputPin
    colisten_input: ReviewInputPin
    layout_input: ReviewInputPin
    coverage: UnplacedStructuralRelationReviewCoverage
    rows: tuple[StructuralRelationReviewRow, ...] = Field(max_length=100_000)
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_replayable_rows(self) -> UnplacedStructuralRelationReviewPacket:
        """Require stable rows and the packet's self-hash."""
        if len(self.rows) != self.coverage.total_row_count:
            raise ValueError("review row count does not match coverage")
        keys = tuple(
            (row.category, row.child_seed_id, row.parent_seed_id, row.reason) for row in self.rows
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("review rows must be sorted and unique")
        if self.output_sha256 != unplaced_structural_relation_review_sha256(self):
            raise ValueError("review packet logical hash does not replay")
        return self


def unplaced_structural_relation_review_sha256(
    packet: UnplacedStructuralRelationReviewPacket,
) -> Sha256:
    """Return the logical packet hash without its self-reference."""
    payload = packet.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def build_unplaced_structural_relation_review_packet(
    *, hierarchy_path: Path, colisten_path: Path, layout_path: Path
) -> UnplacedStructuralRelationReviewPacket:
    """Read verified inputs and return rows for unplaced child seeds only."""
    hierarchy_bytes = hierarchy_path.read_bytes()
    colisten_bytes = colisten_path.read_bytes()
    layout_bytes = layout_path.read_bytes()
    try:
        hierarchy = GenreHierarchyCandidateArtifact.model_validate_json(hierarchy_bytes)
        colisten = MusicBrainzUnplacedCoListenReport.model_validate_json(colisten_bytes)
        layout = _LayoutArtifact.model_validate_json(layout_bytes)
    except (OSError, ValueError) as error:
        raise UnplacedStructuralRelationReviewError("review packet input is invalid") from error
    _require_pinned_inputs(
        hierarchy_input=(hierarchy_bytes, hierarchy.output_sha256),
        colisten_input=(colisten_bytes, colisten.output_sha256),
        layout_input=(layout_bytes, layout.output_sha256),
        colisten_layout_sha256=colisten.layout_sha256,
    )
    placed, unplaced = _layout_states(layout)
    hierarchy_rows = _hierarchy_rows(hierarchy, placed=placed, unplaced=unplaced)
    colisten_rows = _colisten_rows(colisten, placed=placed, unplaced=unplaced)
    rows = tuple(sorted((*hierarchy_rows, *colisten_rows), key=_row_key))
    coverage = UnplacedStructuralRelationReviewCoverage(
        layout_unplaced_seed_count=len(unplaced),
        hierarchy_review_seed_count=len({row.child_seed_id for row in hierarchy_rows}),
        hierarchy_review_row_count=len(hierarchy_rows),
        colisten_review_seed_count=len({row.child_seed_id for row in colisten_rows}),
        colisten_review_row_count=len(colisten_rows),
        total_row_count=len(rows),
    )
    draft = UnplacedStructuralRelationReviewPacket.model_construct(
        hierarchy_input=_pin(hierarchy_bytes, hierarchy.output_sha256),
        colisten_input=_pin(colisten_bytes, colisten.output_sha256),
        layout_input=_pin(layout_bytes, layout.output_sha256),
        coverage=coverage,
        rows=rows,
        output_sha256="0" * 64,
    )
    return UnplacedStructuralRelationReviewPacket(
        **draft.model_dump(mode="python", exclude={"output_sha256"}),
        output_sha256=unplaced_structural_relation_review_sha256(draft),
    )


def write_unplaced_structural_relation_review_packet(
    output: Path, packet: UnplacedStructuralRelationReviewPacket
) -> None:
    """Write one packet below `.cache` without replacing an existing file."""
    cache_root = _PROJECT_CACHE_ROOT.resolve()
    if not output.resolve(strict=False).is_relative_to(cache_root):
        raise UnplacedStructuralRelationReviewError(
            "review packet output must be below the project .cache root"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.resolve(strict=False).is_relative_to(cache_root):
        raise UnplacedStructuralRelationReviewError(
            "review packet output parent resolves outside the project .cache root"
        )
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise UnplacedStructuralRelationReviewError(
            "review packet output already exists"
        ) from error
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(packet.model_dump_json(indent=2).encode())
        stream.write(b"\n")


def _pin(payload: bytes, logical_sha256: Sha256) -> ReviewInputPin:
    return ReviewInputPin(
        file_sha256=hashlib.sha256(payload).hexdigest(), logical_sha256=logical_sha256
    )


def _require_pinned_inputs(
    *,
    hierarchy_input: tuple[bytes, Sha256],
    colisten_input: tuple[bytes, Sha256],
    layout_input: tuple[bytes, Sha256],
    colisten_layout_sha256: Sha256,
) -> None:
    """Require the known retained artifacts before creating a review packet."""
    actual = (
        hashlib.sha256(hierarchy_input[0]).hexdigest(),
        hierarchy_input[1],
        hashlib.sha256(colisten_input[0]).hexdigest(),
        colisten_input[1],
        hashlib.sha256(layout_input[0]).hexdigest(),
        layout_input[1],
    )
    expected = (
        _HIERARCHY_FILE_SHA256,
        _HIERARCHY_LOGICAL_SHA256,
        _COLISTEN_FILE_SHA256,
        _COLISTEN_LOGICAL_SHA256,
        _LAYOUT_FILE_SHA256,
        _LAYOUT_LOGICAL_SHA256,
    )
    if actual != expected:
        raise UnplacedStructuralRelationReviewError(
            "review packet inputs do not match retained pins"
        )
    if colisten_layout_sha256 != _LAYOUT_FILE_SHA256:
        raise UnplacedStructuralRelationReviewError(
            "co-listen report is not bound to the retained layout bytes"
        )


def _layout_states(
    layout: _LayoutArtifact,
) -> tuple[dict[str, _LayoutRow], dict[str, _LayoutRow]]:
    placed = {row.seed_id: row for row in layout.coordinates}
    unplaced = {row.seed_id: row for row in layout.unplaced}
    if not placed or not unplaced or placed.keys() & unplaced.keys():
        raise UnplacedStructuralRelationReviewError(
            "layout placement states are incomplete or overlap"
        )
    return placed, unplaced


def _hierarchy_rows(
    hierarchy: GenreHierarchyCandidateArtifact,
    *,
    placed: dict[str, _LayoutRow],
    unplaced: dict[str, _LayoutRow],
) -> tuple[StructuralRelationReviewRow, ...]:
    rows: list[StructuralRelationReviewRow] = []
    for candidate in hierarchy.candidates:
        if candidate.status != "review" or candidate.child_genre_id not in unplaced:
            continue
        parent = placed.get(candidate.parent_genre_id) or unplaced.get(candidate.parent_genre_id)
        if parent is None:
            raise UnplacedStructuralRelationReviewError(
                "hierarchy review edge has unknown layout endpoint"
            )
        rows.append(
            StructuralRelationReviewRow(
                category="hierarchy_review_candidate",
                reason=candidate.reason,
                child_seed_id=candidate.child_genre_id,
                child_name=unplaced[candidate.child_genre_id].name,
                parent_seed_id=candidate.parent_genre_id,
                parent_name=parent.name,
                parent_state="placed" if candidate.parent_genre_id in placed else "unplaced",
                source_refs=candidate.evidence_refs,
            )
        )
    return tuple(rows)


def _colisten_rows(
    colisten: MusicBrainzUnplacedCoListenReport,
    *,
    placed: dict[str, _LayoutRow],
    unplaced: dict[str, _LayoutRow],
) -> tuple[StructuralRelationReviewRow, ...]:
    refs = (
        f"musicbrainz-unplaced-colisten-report:{colisten.output_sha256}",
        f"musicbrainz-source-tags:{colisten.source_tag_artifact_sha256}",
        f"lastfm-aggregate:{colisten.lastfm_artifact_sha256}",
    )
    rows: list[StructuralRelationReviewRow] = []
    for proposal in colisten.proposals:
        child = unplaced.get(proposal.unplaced_seed_id)
        parent = placed.get(proposal.placed_seed_id)
        if child is None or parent is None:
            raise UnplacedStructuralRelationReviewError(
                "co-listen proposal does not retain unplaced-to-placed endpoints"
            )
        rows.append(
            StructuralRelationReviewRow(
                category="colisten_context_only",
                reason="co_listen_context_is_not_factual_structural_evidence",
                child_seed_id=proposal.unplaced_seed_id,
                child_name=child.name,
                parent_seed_id=proposal.placed_seed_id,
                parent_name=parent.name,
                parent_state="placed",
                source_refs=refs,
            )
        )
    return tuple(rows)


def _row_key(row: StructuralRelationReviewRow) -> tuple[str, str, str, str]:
    return (row.category, row.child_seed_id, row.parent_seed_id, row.reason)
