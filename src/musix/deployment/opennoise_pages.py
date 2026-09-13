"""Stage one sealed production map for a later static OpenNoise Pages render.

This module deliberately owns only the reproducible data boundary. The
presentation is supplied by the separately reviewed static UI export, so this
module cannot introduce a second map layout or product copy.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from musix.models import FrozenModel
from musix.models.production import ProductionMapArtifact

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "opennoise-pages-static-staging-v1"
_STAGED_ARTIFACT_NAME: Final = "production-map-v1.json"


class OpenNoisePagesExportError(ValueError):
    """The requested static-release input is unavailable or not publishable."""


class OpenNoisePagesArtifactBinding(FrozenModel):
    """Exact identity of the single semantic production-map input."""

    revision: Literal["production-map-v1"] = "production-map-v1"
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapped_node_count: int = Field(ge=1)
    similarity_edge_count: int = Field(ge=0)
    taxonomy_edge_count: int = Field(ge=0)
    unplaced_count: int = Field(ge=0)


class OpenNoisePagesExportManifest(FrozenModel):
    """Deterministic receipt for data staged for the reviewed static renderer."""

    revision: Literal["opennoise-pages-static-staging-v1"] = _REVISION
    artifact: OpenNoisePagesArtifactBinding
    explicit_backend_api_available: Literal[False] = False
    staged_artifact_relative_path: Literal["assets/production-map-v1.json"] = (
        "assets/production-map-v1.json"
    )
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OpenNoisePagesExportInputs:
    """One verified map and a new or empty directory for its static staging area."""

    production_map_path: Path
    output_directory: Path


def export_opennoise_pages(inputs: OpenNoisePagesExportInputs) -> OpenNoisePagesExportManifest:
    """Stage a verified semantic map without generating a competing UI surface."""
    if inputs.output_directory.exists() and any(inputs.output_directory.iterdir()):
        raise OpenNoisePagesExportError("static Pages output directory must be empty")
    _, binding = _load_production_map(inputs.production_map_path)
    inputs.output_directory.mkdir(parents=True, exist_ok=True)
    assets = inputs.output_directory / "assets"
    assets.mkdir()
    shutil.copyfile(inputs.production_map_path, assets / _STAGED_ARTIFACT_NAME)
    base = OpenNoisePagesExportManifest(artifact=binding, output_sha256="0" * 64)
    manifest = base.model_copy(update={"output_sha256": _manifest_sha256(base)})
    write_atomic_bytes(
        inputs.output_directory / "opennoise-static-staging-manifest.json",
        manifest.model_dump_json(indent=2).encode() + b"\n",
    )
    return manifest


def _load_production_map(
    path: Path,
) -> tuple[ProductionMapArtifact, OpenNoisePagesArtifactBinding]:
    try:
        artifact = ProductionMapArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise OpenNoisePagesExportError("invalid sealed production map artifact") from error
    if not artifact.export_allowed:
        raise OpenNoisePagesExportError("production map artifact is not export allowed")
    byte_sha256, byte_count = sha256_file(path)
    return artifact, OpenNoisePagesArtifactBinding(
        byte_sha256=byte_sha256,
        byte_count=byte_count,
        logical_sha256=artifact.output_sha256,
        mapped_node_count=len(artifact.nodes),
        similarity_edge_count=sum(edge.kind == "similarity" for edge in artifact.edges),
        taxonomy_edge_count=sum(edge.kind == "taxonomy" for edge in artifact.edges),
        unplaced_count=len(artifact.unplaced),
    )


def _manifest_sha256(manifest: OpenNoisePagesExportManifest) -> str:
    return sha256_hex(canonical_json(manifest.model_dump(mode="json", exclude={"output_sha256"})))
