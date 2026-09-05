"""Verify and export the selected public-model metadata representatives without re-ranking them."""

import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from musix.ml.repository import PublicInputLoadSettings, _metadata_candidates
from musix.models import FrozenModel
from musix.types import Sha256

type ReleaseMetadataKind = Literal["release_group", "recording"]
_RELEASE_KINDS: tuple[ReleaseMetadataKind, ...] = ("release_group", "recording")
_EVIDENCE_REFS_ADAPTER: TypeAdapter[tuple[str, ...]] = TypeAdapter(tuple[str, ...])


class MetadataRepresentativeSettings(FrozenModel):
    """Bound canonical candidate loading while auditing one selected public-model run."""

    max_metadata_candidates: int = Field(default=100_000, gt=0, le=1_000_000)


DEFAULT_METADATA_REPRESENTATIVE_SETTINGS = MetadataRepresentativeSettings()


class RepresentativeRunProvenance(FrozenModel):
    """Expose the already-published model run rather than creating a competing release ranking."""

    model_run_id: int = Field(gt=0)
    output_sha256: Sha256
    input_provenance_ids: tuple[int, ...]


class MetadataRepresentativeItem(FrozenModel):
    """A selected metadata example, not a claim of quintessential quality or popularity."""

    genre_id: str = Field(min_length=1)
    entity_kind: ReleaseMetadataKind
    entity_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    rank: int = Field(gt=0)
    direct_evidence_value: float = Field(gt=0.0)
    source_count: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    classification: Literal["metadata_example"] = "metadata_example"
    explanation: str = (
        "Selected by the published public model from direct metadata evidence. This is a metadata "
        "example, not evidence of popularity, quality, audience consensus, or influence."
    )
    missing_features: tuple[str, ...] = (
        "audio",
        "previews",
        "media_assets",
        "edition_rows",
        "catalog_track_rows",
        "popularity",
        "listener_consensus",
        "influence",
    )


class MetadataRepresentativeArtifact(FrozenModel):
    """Versioned export of existing selections with provenance and gap declarations."""

    method_key: Literal["selected_public_metadata_representatives"] = (
        "selected_public_metadata_representatives"
    )
    method_version: Literal["1"] = "1"
    run: RepresentativeRunProvenance
    items: tuple[MetadataRepresentativeItem, ...]
    recording_semantics: str = (
        "MusicBrainz recordings are the track-level metadata proxy in this MVP; the catalog has no "
        "track rows and this export does not infer a recording-to-release relationship."
    )

    @model_validator(mode="after")
    def require_contiguous_ranks(self) -> "MetadataRepresentativeArtifact":
        """Require the public selection to remain rank-complete per genre and metadata kind."""
        ranks: dict[tuple[str, ReleaseMetadataKind], list[int]] = {}
        for item in self.items:
            ranks.setdefault((item.genre_id, item.entity_kind), []).append(item.rank)
        if any(sorted(values) != list(range(1, len(values) + 1)) for values in ranks.values()):
            raise ValueError("selected metadata representative ranks must be contiguous")
        return self


class _PublishedRepresentativeRow(FrozenModel):
    """Parse one selected SQLite representative before matching it to a canonical candidate."""

    entity_kind: ReleaseMetadataKind
    genre_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    rank: int = Field(gt=0)
    direct_evidence_value: float = Field(gt=0.0)
    source_count: int = Field(gt=0)
    evidence_refs_json: str = Field(min_length=2)

    def evidence_refs(self) -> tuple[str, ...]:
        """Parse the persisted explainability reference array once at the SQLite boundary."""
        references = _EVIDENCE_REFS_ADAPTER.validate_json(self.evidence_refs_json)
        if not references:
            raise ValueError("published representative evidence references must not be empty")
        return references


def _selected_run(connection: sqlite3.Connection) -> RepresentativeRunProvenance:
    """Read the selected public model and its persisted input provenance."""
    row = connection.execute(
        """
        SELECT run.id, run.output_sha256
        FROM current_public_models AS current
        JOIN servable_public_model_runs AS run ON run.id = current.model_run_id
        WHERE current.model_key = 'public-graph'
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("no displayable selected public model run")
    provenance_rows = connection.execute(
        """
        SELECT provenance_id FROM public_model_input_provenance
        WHERE model_run_id = ? ORDER BY provenance_id
        """,
        (int(row[0]),),
    ).fetchall()
    return RepresentativeRunProvenance(
        model_run_id=int(row[0]),
        output_sha256=str(row[1]),
        input_provenance_ids=tuple(int(provenance[0]) for provenance in provenance_rows),
    )


def _selected_rows(connection: sqlite3.Connection) -> tuple[_PublishedRepresentativeRow, ...]:
    """Read only published release-group and recording selections, in stable order."""
    rows = connection.execute(
        """
        SELECT representative.entity_kind, COALESCE(
                   (SELECT 'wikidata:genre:' || identifier.normalized_value
                    FROM entity_identifiers AS identifier
                    WHERE identifier.entity_id = representative.genre_id
                      AND identifier.namespace = 'wikidata'
                    ORDER BY identifier.id LIMIT 1),
                   (SELECT 'musicbrainz:genre:' || identifier.normalized_value
                    FROM entity_identifiers AS identifier
                    WHERE identifier.entity_id = representative.genre_id
                      AND identifier.namespace = 'musicbrainz'
                    ORDER BY identifier.id LIMIT 1)
               ) AS genre_id,
               representative.source_entity_ref AS entity_id, representative.display_name,
               representative.rank, representative.direct_evidence_value,
               representative.source_count,
               representative.evidence_refs_json
        FROM displayable_public_genre_representatives AS representative
        WHERE representative.entity_kind IN ('release_group', 'recording')
        ORDER BY representative.entity_kind, genre_id, representative.rank,
                 representative.source_entity_ref
        """
    ).fetchall()
    return tuple(_PublishedRepresentativeRow.model_validate(dict(row)) for row in rows)


def metadata_representatives(
    database: Path,
    settings: MetadataRepresentativeSettings = DEFAULT_METADATA_REPRESENTATIVE_SETTINGS,
) -> MetadataRepresentativeArtifact:
    """Export selected examples after proving each remains in the canonical candidate loader."""
    absolute = database.resolve(strict=True)
    with sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        run = _selected_run(connection)
        candidates = _metadata_candidates(
            connection,
            PublicInputLoadSettings(max_metadata_candidates=settings.max_metadata_candidates),
        )
        selected = _selected_rows(connection)
    candidate_index = {
        (candidate.entity_kind, candidate.genre_id, candidate.entity_id): candidate
        for candidate in candidates
        if candidate.entity_kind in _RELEASE_KINDS
    }
    items: list[MetadataRepresentativeItem] = []
    for row in selected:
        candidate = candidate_index.get((row.entity_kind, row.genre_id, row.entity_id))
        if candidate is None:
            raise RuntimeError(
                "published metadata representative is absent from the canonical candidate loader: "
                f"{row.entity_kind}/{row.genre_id}/{row.entity_id}"
            )
        evidence_refs = row.evidence_refs()
        if candidate.evidence_refs != evidence_refs:
            raise RuntimeError(
                "published metadata representative evidence differs from its candidate"
            )
        items.append(
            MetadataRepresentativeItem(
                genre_id=row.genre_id,
                entity_kind=row.entity_kind,
                entity_id=row.entity_id,
                display_name=row.display_name,
                rank=row.rank,
                direct_evidence_value=row.direct_evidence_value,
                source_count=row.source_count,
                evidence_refs=evidence_refs,
            )
        )
    return MetadataRepresentativeArtifact(run=run, items=tuple(items))
