"""Receipt-bound, streaming input adapters for hierarchy fusion."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

import ijson
from pydantic import Field

from opennoise.common import sha256_file
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.ml.full_graph_signal import (
    FullGraphSignalArtifact,
    FullGraphSignalReceipt,
    verify_full_graph_signal,
)
from opennoise.models import FrozenModel
from opennoise.taxonomy.relations.expansion import (
    TaxonomyRelationExpansionArtifact,
    taxonomy_relation_expansion_output_sha256,
)
from opennoise.taxonomy.seeds.reconciliation import SeedReconciliationArtifact
from opennoise.taxonomy.structure.hierarchy_candidates import (
    GenreHierarchyCandidatePublicationReceipt,
)

from .contracts import EdgeProvenance, HierarchyFusionError, SourceBinding

_SEED_COUNT = 6_291
_PUBLIC_CANDIDATE_COUNT = 66_132

if TYPE_CHECKING:
    from pathlib import Path


class _PublicCandidateComponent(FrozenModel):
    normalized_value: float = Field(ge=0.0, le=1.0)
    # This source stores its optional references as JSON arrays.  They are not
    # retained in the compact fusion representation, but validating their real
    # wire shape keeps the streaming adapter strict without rejecting the
    # sealed corpus.
    evidence_refs: list[str] = Field(default_factory=list)


class _PublicCandidateComponents(FrozenModel):
    lexical_head_review_prior: _PublicCandidateComponent
    artist_set_containment: _PublicCandidateComponent
    child_artist_count: int = Field(ge=0)
    parent_artist_count: int = Field(ge=0)
    shared_artist_count: int = Field(ge=0)


class _PublicCandidate(FrozenModel):
    child_genre_id: str = Field(min_length=1)
    parent_genre_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    components: _PublicCandidateComponents


class _PublicCandidateCoverage(FrozenModel):
    seed_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class HierarchyFusionInputs:
    """Eight construction-only inputs, including receipts for large artifacts."""

    reconciliation: Path
    evidence_graph_database: Path
    evidence_graph_receipt: Path
    factual_taxonomy: Path
    public_candidate_corpus: Path
    public_candidate_receipt: Path
    full_graph_signal: Path
    full_graph_signal_receipt: Path


@dataclass(frozen=True, slots=True)
class LoadedHierarchyFusionInputs:
    """Validated compact view of source artifacts; the public corpus streams once."""

    seed_names: dict[str, str]
    factual: dict[tuple[str, str], tuple[EdgeProvenance, ...]]
    public_candidate_corpus: dict[tuple[str, str], tuple[EdgeProvenance, ...]]
    full_graph: dict[tuple[str, str], tuple[EdgeProvenance, ...]]
    unknown_reasons: dict[str, tuple[str, ...]]
    bindings: tuple[
        SourceBinding,
        SourceBinding,
        SourceBinding,
        SourceBinding,
        SourceBinding,
        SourceBinding,
        SourceBinding,
        SourceBinding,
    ]


def _binding(role: str, path: Path, logical_sha256: str | None = None) -> SourceBinding:
    digest, size = sha256_file(path)
    return SourceBinding(
        role=role,
        locator=f"{role}:{path.name}",
        sha256=digest,
        byte_count=size,
        logical_sha256=logical_sha256,
    )


def _load_reconciliation(path: Path) -> tuple[dict[str, str], SourceBinding]:
    try:
        artifact = SeedReconciliationArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise HierarchyFusionError("seed reconciliation is invalid") from error
    names = {row.source_item_id: row.seed_name for row in artifact.dispositions}
    if artifact.seed_count != _SEED_COUNT or len(names) != _SEED_COUNT:
        raise HierarchyFusionError("seed reconciliation does not cover 6,291 unique stable seeds")
    return names, _binding("seed_reconciliation", path, artifact.output_sha256)


def _load_factual(
    path: Path, seed_names: dict[str, str]
) -> tuple[dict[tuple[str, str], tuple[EdgeProvenance, ...]], SourceBinding]:
    try:
        artifact = TaxonomyRelationExpansionArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise HierarchyFusionError("exact taxonomy artifact is invalid") from error
    if taxonomy_relation_expansion_output_sha256(artifact) != artifact.output_sha256:
        raise HierarchyFusionError("exact taxonomy artifact hash does not replay")
    output: dict[tuple[str, str], list[EdgeProvenance]] = defaultdict(list)
    for edge in artifact.edges:
        if edge.disposition != "accepted_factual":
            continue
        if edge.child_seed_id not in seed_names or edge.parent_seed_id not in seed_names:
            raise HierarchyFusionError("exact taxonomy edge is outside the stable seed universe")
        output[(edge.child_seed_id, edge.parent_seed_id)].extend(
            EdgeProvenance(
                source_role="wikidata_p279",
                source_ref=f"{artifact.output_sha256}:{source.observation_id}",
                score=1.0,
                lexical_score=0.0,
                artist_containment_score=0.0,
                shared_artist_count=0,
                child_artist_count=0,
                parent_artist_count=0,
            )
            for source in edge.factual_evidence
        )
    if (
        artifact.coverage.seed_count != _SEED_COUNT
        or len(output) != artifact.coverage.accepted_factual_edge_count
    ):
        raise HierarchyFusionError("exact taxonomy factual edge accounting does not replay")
    return (
        {
            key: tuple(sorted(value, key=lambda item: item.source_ref))
            for key, value in output.items()
        },
        _binding("wikidata_p279", path, artifact.output_sha256),
    )


def _load_graph_hierarchy(
    database_path: Path,
    receipt_path: Path,
    seed_names: dict[str, str],
    factual: dict[tuple[str, str], tuple[EdgeProvenance, ...]],
) -> tuple[dict[str, tuple[str, ...]], SourceBinding, SourceBinding]:
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(receipt_path.read_bytes())
        verify_evidence_graph_projection(receipt)
    except (OSError, ValueError) as error:
        raise HierarchyFusionError("evidence graph receipt is invalid") from error
    database_sha, database_size = sha256_file(database_path)
    if (database_sha, database_size) != (receipt.database_sha256, receipt.database_bytes):
        raise HierarchyFusionError("evidence graph database does not bind receipt")
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(database_uri, uri=True)) as database:
            if database.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise HierarchyFusionError("evidence graph integrity check failed")
            rows = tuple(
                database.execute(
                    "SELECT child_identifier, parent_identifier FROM factual_relation "
                    "WHERE source = 'wikidata' AND relation_kind = 'wikidata_p279_subclass_of' "
                    "AND child_namespace = 'stable_seed' AND parent_namespace = 'stable_seed'"
                )
            )
            unknown_rows = tuple(
                database.execute(
                    "SELECT identifier, reason FROM abstention WHERE namespace = 'stable_seed' "
                    "AND reason IN ('no_factual_hierarchy', 'no_review_hierarchy', "
                    "'hierarchy_candidate_abstained') ORDER BY identifier, reason"
                )
            )
    except sqlite3.Error as error:
        raise HierarchyFusionError("evidence graph hierarchy query failed") from error
    graph_facts = {(str(child), str(parent)) for child, parent in rows}
    if graph_facts != set(factual):
        raise HierarchyFusionError("graph and exact taxonomy factual P279 edges differ")
    unknown: dict[str, list[str]] = defaultdict(list)
    for seed_id, reason in unknown_rows:
        if str(seed_id) not in seed_names:
            raise HierarchyFusionError("evidence graph abstention is outside stable seeds")
        unknown[str(seed_id)].append(str(reason))
    return (
        {seed_id: tuple(reasons) for seed_id, reasons in unknown.items()},
        _binding("evidence_graph_database", database_path, receipt.output_sha256),
        _binding("evidence_graph_receipt", receipt_path, receipt.output_sha256),
    )


def _load_public_candidate_receipt(
    corpus_path: Path, receipt_path: Path
) -> GenreHierarchyCandidatePublicationReceipt:
    """Verify the compact receipt before reading the large source-neutral corpus."""
    try:
        receipt = GenreHierarchyCandidatePublicationReceipt.model_validate_json(
            receipt_path.read_bytes()
        )
    except (OSError, ValueError) as error:
        raise HierarchyFusionError("public hierarchy candidate receipt is invalid") from error
    corpus_sha, corpus_size = sha256_file(corpus_path)
    if (
        (corpus_sha, corpus_size) != (receipt.artifact_sha256, receipt.artifact.byte_size)
        or receipt.artifact.sha256 != receipt.artifact_sha256
        or receipt.historical_data_used_for_construction
    ):
        raise HierarchyFusionError("public hierarchy candidate receipt does not bind corpus bytes")
    return receipt


def _public_candidate_manifest(
    corpus_path: Path, receipt: GenreHierarchyCandidatePublicationReceipt
) -> tuple[_PublicCandidateCoverage, str, bool]:
    """Read top-level construction metadata without materializing candidate rows."""
    try:
        with corpus_path.open("rb") as stream:
            coverage = _PublicCandidateCoverage.model_validate(
                next(ijson.items(stream, "coverage"))
            )
        with corpus_path.open("rb") as stream:
            logical_output_sha256 = str(next(ijson.items(stream, "output_sha256")))
        with corpus_path.open("rb") as stream:
            historical_construction = bool(
                next(ijson.items(stream, "historical_data_used_for_construction"))
            )
    except (OSError, StopIteration, ValueError) as error:
        raise HierarchyFusionError("public hierarchy candidate manifest is invalid") from error
    if (
        coverage.seed_count != _SEED_COUNT
        or coverage.candidate_count != _PUBLIC_CANDIDATE_COUNT
        or logical_output_sha256 != receipt.logical_output_sha256
        or historical_construction
    ):
        raise HierarchyFusionError(
            "public hierarchy candidate manifest does not meet source-neutral bounds"
        )
    return coverage, logical_output_sha256, historical_construction


def _stream_public_candidate_rows(
    corpus_path: Path, seed_names: dict[str, str], maximum: int
) -> dict[tuple[str, str], tuple[EdgeProvenance, ...]]:
    """Stream and compact rows to the score/provenance fields fusion actually consumes."""
    output: dict[tuple[str, str], list[EdgeProvenance]] = defaultdict(list)
    count = 0
    try:
        with corpus_path.open("rb") as stream:
            for index, raw in enumerate(ijson.items(stream, "candidates.item")):
                row = _PublicCandidate.model_validate(raw)
                count += 1
                if count > maximum:
                    raise HierarchyFusionError("public hierarchy candidate bound exceeded")
                if row.child_genre_id not in seed_names or row.parent_genre_id not in seed_names:
                    raise HierarchyFusionError("public hierarchy candidate is outside stable seeds")
                components = row.components
                output[(row.child_genre_id, row.parent_genre_id)].append(
                    EdgeProvenance(
                        source_role="public_candidate_corpus",
                        source_ref=f"candidate-index:{index}",
                        score=row.score,
                        lexical_score=components.lexical_head_review_prior.normalized_value,
                        artist_containment_score=components.artist_set_containment.normalized_value,
                        shared_artist_count=components.shared_artist_count,
                        child_artist_count=components.child_artist_count,
                        parent_artist_count=components.parent_artist_count,
                    )
                )
    except (OSError, ValueError) as error:
        if isinstance(error, HierarchyFusionError):
            raise
        raise HierarchyFusionError("public hierarchy candidate stream is invalid") from error
    if count == 0:
        raise HierarchyFusionError("public hierarchy candidate stream is empty")
    if count != _PUBLIC_CANDIDATE_COUNT:
        raise HierarchyFusionError("public hierarchy candidate count is not the sealed 66,132")
    return {key: tuple(value) for key, value in output.items()}


def _load_public_candidate_corpus(
    corpus_path: Path,
    receipt_path: Path,
    seed_names: dict[str, str],
    maximum: int,
) -> tuple[dict[tuple[str, str], tuple[EdgeProvenance, ...]], SourceBinding, SourceBinding]:
    """Stream the 683MB candidate corpus instead of loading its evidence lists in RAM."""
    receipt = _load_public_candidate_receipt(corpus_path, receipt_path)
    _public_candidate_manifest(corpus_path, receipt)
    output = _stream_public_candidate_rows(corpus_path, seed_names, maximum)
    return (
        output,
        _binding("public_candidate_corpus", corpus_path, receipt.logical_output_sha256),
        _binding("public_candidate_receipt", receipt_path, receipt.logical_output_sha256),
    )


def _load_full_graph(
    path: Path, receipt_path: Path, seed_names: dict[str, str]
) -> tuple[dict[tuple[str, str], tuple[EdgeProvenance, ...]], SourceBinding, SourceBinding]:
    try:
        artifact = FullGraphSignalArtifact.model_validate_json(path.read_bytes())
        receipt = FullGraphSignalReceipt.model_validate_json(receipt_path.read_bytes())
        verify_full_graph_signal(artifact)
    except (OSError, ValueError) as error:
        raise HierarchyFusionError("full graph signal artifact is invalid") from error
    artifact_sha, artifact_size = sha256_file(path)
    if (
        receipt.artifact_sha256 != artifact_sha
        or receipt.artifact_byte_count != artifact_size
        or receipt.logical_output_sha256 != artifact.output_sha256
    ):
        raise HierarchyFusionError("full graph signal receipt does not bind artifact bytes")
    result: dict[tuple[str, str], list[EdgeProvenance]] = defaultdict(list)
    for index, row in enumerate(artifact.containment_candidates):
        if row.child_seed_id not in seed_names or row.parent_seed_id not in seed_names:
            raise HierarchyFusionError("full graph containment candidate is outside stable seeds")
        result[(row.child_seed_id, row.parent_seed_id)].append(
            EdgeProvenance(
                source_role="full_graph_containment",
                source_ref=f"{artifact.output_sha256}:containment:{index}",
                score=row.containment_score,
                lexical_score=0.0,
                artist_containment_score=row.containment_score,
                shared_artist_count=row.shared_artist_count,
                child_artist_count=row.child_artist_count,
                parent_artist_count=row.parent_artist_count,
            )
        )
    return (
        {key: tuple(value) for key, value in result.items()},
        _binding("full_graph_containment", path, artifact.output_sha256),
        _binding("full_graph_containment_receipt", receipt_path, artifact.output_sha256),
    )


def load_hierarchy_fusion_inputs(
    inputs: HierarchyFusionInputs, *, maximum_public_candidate_rows: int
) -> LoadedHierarchyFusionInputs:
    """Load only source-neutral inputs and bind every byte payload."""
    seed_names, reconciliation = _load_reconciliation(inputs.reconciliation)
    factual, factual_binding = _load_factual(inputs.factual_taxonomy, seed_names)
    unknown_reasons, graph_database_binding, graph_receipt_binding = _load_graph_hierarchy(
        inputs.evidence_graph_database,
        inputs.evidence_graph_receipt,
        seed_names,
        factual,
    )
    public_candidate_corpus, corpus_binding, corpus_receipt_binding = _load_public_candidate_corpus(
        inputs.public_candidate_corpus,
        inputs.public_candidate_receipt,
        seed_names,
        maximum_public_candidate_rows,
    )
    full_graph, full_graph_binding, full_graph_receipt_binding = _load_full_graph(
        inputs.full_graph_signal, inputs.full_graph_signal_receipt, seed_names
    )
    return LoadedHierarchyFusionInputs(
        seed_names=seed_names,
        factual=factual,
        public_candidate_corpus=public_candidate_corpus,
        full_graph=full_graph,
        unknown_reasons=unknown_reasons,
        bindings=(
            reconciliation,
            graph_database_binding,
            graph_receipt_binding,
            factual_binding,
            corpus_binding,
            corpus_receipt_binding,
            full_graph_binding,
            full_graph_receipt_binding,
        ),
    )
