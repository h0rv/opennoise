"""Check that the semantic layout uses the retained Every Noise name projection only."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.common import sha256_file, sha256_json
from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)
from opennoise.models import FrozenModel
from opennoise.taxonomy.seeds.universe import SeedInput, load_seed_input

if TYPE_CHECKING:
    from pathlib import Path

_EVERY_NOISE_SOURCE_ID = "enao_quint_legacy_map_2025"
_SEED_COUNT = 6_291


class NamesOnlyConstructionBoundaryError(ValueError):
    """Raise when a name projection and a layout input do not agree."""


class NamesOnlyConstructionBoundaryProof(FrozenModel):
    """A local receipt that names and stable identities agree across one layout boundary.

    The receipt does not prove which fields an upstream peer-edge producer read.
    """

    revision: Literal["names-only-construction-boundary-v1"] = "names-only-construction-boundary-v1"
    source_id: Literal["enao_quint_legacy_map_2025"] = _EVERY_NOISE_SOURCE_ID
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    name_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    peer_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_layout_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_count: Literal[6291] = _SEED_COUNT
    checker_read_fields: Literal["source_item_id,source_external_id,name"] = (
        "source_item_id,source_external_id,name"
    )
    peer_index_matches_name_projection: Literal[True] = True
    layout_matches_name_projection: Literal[True] = True
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def names_only_construction_boundary_sha256(proof: NamesOnlyConstructionBoundaryProof) -> str:
    """Return the logical proof hash without its self-hash."""
    return sha256_json(proof.model_dump(mode="json", exclude={"output_sha256"}))


def verify_names_only_construction_boundary(
    *, seed_artifact: Path, peer_index: Path, semantic_layout: Path
) -> NamesOnlyConstructionBoundaryProof:
    """Check the current layout seed inventory against the typed name projection.

    This checker reads the raw Every Noise artifact only through ``load_seed_input``.
    That parser returns stable item IDs, external IDs, and names. The checker reads
    only the same IDs and names from the peer index and semantic layout.

    The check proves identity consistency at the peer-index and layout boundary.
    It does not prove which fields an upstream peer-edge producer read.
    """
    seed = load_seed_input(seed_artifact)
    if seed.source_id != _EVERY_NOISE_SOURCE_ID:
        raise NamesOnlyConstructionBoundaryError(
            "seed artifact is not the pinned Every Noise H2 source"
        )
    peer_rows = _peer_seed_rows(peer_index)
    layout, layout_sha256 = _semantic_layout(semantic_layout)
    verify_name_projection_records(seed, peer_rows, _layout_seed_rows(layout))
    base = NamesOnlyConstructionBoundaryProof(
        source_content_sha256=seed.source_content_sha256,
        name_projection_sha256=seed.artifact_sha256,
        peer_index_sha256=sha256_file(peer_index)[0],
        semantic_layout_sha256=layout_sha256,
        semantic_layout_logical_sha256=layout.output_sha256,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": names_only_construction_boundary_sha256(base)})


def verify_names_only_construction_boundary_proof(
    proof: NamesOnlyConstructionBoundaryProof,
) -> None:
    """Reject a changed or incomplete names-only boundary proof."""
    if proof.output_sha256 != names_only_construction_boundary_sha256(proof):
        raise NamesOnlyConstructionBoundaryError(
            "names-only construction boundary proof does not replay"
        )


def _peer_seed_rows(path: Path) -> dict[str, tuple[str, str]]:
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            rows = tuple(
                (str(item_id), str(external_id), str(name))
                for item_id, external_id, name in db.execute(
                    "SELECT source_item_id, source_external_id, seed_name FROM seed"
                )
            )
    except sqlite3.Error as error:
        raise NamesOnlyConstructionBoundaryError(
            "peer index cannot provide its seed projection"
        ) from error
    return _seed_rows_by_id(rows, source="peer index")


def _semantic_layout(path: Path) -> tuple[SemanticLayoutArtifact, str]:
    try:
        layout = SemanticLayoutArtifact.model_validate_json(path.read_bytes())
        verify_semantic_map_layout(layout)
    except (OSError, ValueError) as error:
        raise NamesOnlyConstructionBoundaryError("semantic layout is invalid") from error
    return layout, sha256_file(path)[0]


def _layout_seed_rows(layout: SemanticLayoutArtifact) -> dict[str, tuple[str, str]]:
    rows = tuple((item.seed_id, item.name) for item in (*layout.coordinates, *layout.unplaced))
    if len(rows) != _SEED_COUNT:
        raise NamesOnlyConstructionBoundaryError(
            "semantic layout does not contain the complete seed inventory"
        )
    result = {item_id: ("", name) for item_id, name in rows}
    if len(result) != len(rows):
        raise NamesOnlyConstructionBoundaryError("semantic layout repeats a seed identity")
    return result


def _seed_rows_by_id(
    rows: tuple[tuple[str, str, str], ...], *, source: str
) -> dict[str, tuple[str, str]]:
    result = {item_id: (external_id, name) for item_id, external_id, name in rows}
    if len(result) != _SEED_COUNT or len(result) != len(rows):
        raise NamesOnlyConstructionBoundaryError(
            f"{source} does not contain exactly {_SEED_COUNT} seeds"
        )
    return result


def verify_name_projection_records(
    seed: SeedInput,
    peer_rows: dict[str, tuple[str, str]],
    layout_rows: dict[str, tuple[str, str]],
) -> None:
    """Require peer and layout identities to equal one typed name projection."""
    projected = _seed_rows_by_id(
        tuple((item.source_item_id, item.source_external_id, item.name) for item in seed.names),
        source="Every Noise name projection",
    )
    if peer_rows != projected:
        raise NamesOnlyConstructionBoundaryError(
            "peer index seed identities or names differ from projection"
        )
    if {item_id: name for item_id, (_external_id, name) in layout_rows.items()} != {
        item_id: name for item_id, (_external_id, name) in projected.items()
    }:
        raise NamesOnlyConstructionBoundaryError(
            "semantic layout seed identities or names differ from projection"
        )
