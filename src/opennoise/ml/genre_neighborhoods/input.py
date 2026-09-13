"""Fail-closed startup certification for the two sealed construction inputs."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from opennoise.common import sha256_file
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)

from .contracts import (
    CertifiedInputs,
    GenreNeighborhoodError,
    GenreNeighborhoodInputs,
    InputBinding,
)


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def certify_inputs(inputs: GenreNeighborhoodInputs) -> CertifiedInputs:
    """Verify receipt bytes and logical IDs before reading either SQLite file."""
    try:
        graph = EvidenceGraphProjectionArtifact.model_validate_json(
            inputs.graph_receipt.read_bytes()
        )
        verify_evidence_graph_projection(graph)
        colisten = load_colisten_overlay(inputs.colisten_receipt)
        certify_colisten_overlay_sources(CoListenOverlaySources(inputs.colisten_database, colisten))
    except (OSError, ValueError) as error:
        raise GenreNeighborhoodError("sealed graph or co-listen sidecar is invalid") from error
    if sha256_file(inputs.graph_database) != (graph.database_sha256, graph.database_bytes):
        raise GenreNeighborhoodError("graph database does not bind graph receipt")
    if colisten.graph_receipt_output_sha256 != graph.output_sha256:
        raise GenreNeighborhoodError("co-listen sidecar binds a different graph receipt")
    with closing(_readonly(inputs.graph_database)) as database:
        if database.execute(
            "SELECT count(*) FROM identity WHERE namespace = 'stable_seed'"
        ).fetchone() != (6291,):
            raise GenreNeighborhoodError("graph does not contain the complete stable seed universe")
    bindings = (
        _binding("graph_database", inputs.graph_database, graph.output_sha256),
        _binding("graph_receipt", inputs.graph_receipt, graph.output_sha256),
        _binding("colisten_database", inputs.colisten_database, colisten.output_sha256),
        _binding("colisten_receipt", inputs.colisten_receipt, colisten.output_sha256),
    )
    return CertifiedInputs(bindings, graph.output_sha256, colisten.output_sha256)


def _binding(role: str, path: Path, logical_sha256: str) -> InputBinding:
    digest, size = sha256_file(path)
    return InputBinding(
        role=role, byte_sha256=digest, byte_count=size, logical_sha256=logical_sha256
    )
