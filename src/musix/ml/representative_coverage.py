"""Read bounded, provenance-preserving coverage for public representatives."""

import sqlite3
from collections import Counter
from pathlib import Path

from pydantic import Field

from musix.ml.repository import PublicInputLoadSettings, _metadata_candidates
from musix.models import FrozenModel
from musix.models.modeling import MetadataCandidate, MetadataKind

_KINDS: tuple[MetadataKind, ...] = ("artist", "release_group", "recording")


class RepresentativeCoverageSettings(FrozenModel):
    """Bound candidate loading when auditing a stored public catalog."""

    max_metadata_candidates: int = Field(default=100_000, gt=0, le=1_000_000)


DEFAULT_REPRESENTATIVE_COVERAGE_SETTINGS = RepresentativeCoverageSettings()


class RepresentativeKindCoverage(FrozenModel):
    """Describe source eligibility and selected output for one metadata kind."""

    entity_kind: MetadataKind
    candidate_pairs: int = Field(ge=0)
    candidate_entities: int = Field(ge=0)
    candidate_genres: int = Field(ge=0)
    candidate_zero_coverage_genres: int = Field(ge=0)
    published_items: int = Field(ge=0)
    published_genres: int = Field(ge=0)
    published_zero_coverage_genres: int = Field(ge=0)


class RepresentativeCoverageReport(FrozenModel):
    """Make public metadata gaps reviewable without emitting catalog content."""

    modelable_genres: int = Field(ge=0)
    selected_model_output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_method: str = "public_metadata_candidate_v1"
    published_method: str = "selected_displayable_public_representative_v1"
    by_kind: tuple[RepresentativeKindCoverage, ...] = Field(min_length=3, max_length=3)


def _coverage(
    *,
    modelable_genres: int,
    candidates: tuple[MetadataCandidate, ...],
    published: tuple[tuple[MetadataKind, str, int], ...],
    output_sha256: str | None,
) -> RepresentativeCoverageReport:
    """Summarize already-filtered candidates and selected rows deterministically."""
    candidate_pairs = Counter(item.entity_kind for item in candidates)
    candidate_entities = {
        kind: {item.entity_id for item in candidates if item.entity_kind == kind} for kind in _KINDS
    }
    candidate_genres = {
        kind: {item.genre_id for item in candidates if item.entity_kind == kind} for kind in _KINDS
    }
    published_items = Counter(kind for kind, _genre_id, _rank in published)
    published_genres = {
        kind: {genre_id for item_kind, genre_id, _rank in published if item_kind == kind}
        for kind in _KINDS
    }
    return RepresentativeCoverageReport(
        modelable_genres=modelable_genres,
        selected_model_output_sha256=output_sha256,
        by_kind=tuple(
            RepresentativeKindCoverage(
                entity_kind=kind,
                candidate_pairs=candidate_pairs[kind],
                candidate_entities=len(candidate_entities[kind]),
                candidate_genres=len(candidate_genres[kind]),
                candidate_zero_coverage_genres=modelable_genres - len(candidate_genres[kind]),
                published_items=published_items[kind],
                published_genres=len(published_genres[kind]),
                published_zero_coverage_genres=modelable_genres - len(published_genres[kind]),
            )
            for kind in _KINDS
        ),
    )


def representative_coverage(
    database: Path,
    settings: RepresentativeCoverageSettings = DEFAULT_REPRESENTATIVE_COVERAGE_SETTINGS,
) -> RepresentativeCoverageReport:
    """Read one immutable SQLite snapshot without fetching or writing any media."""
    absolute = database.resolve(strict=True)
    with sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        candidate_settings = PublicInputLoadSettings(
            max_metadata_candidates=settings.max_metadata_candidates
        )
        candidates = _metadata_candidates(connection, candidate_settings)
        modelable = connection.execute("SELECT count(*) FROM modelable_music_genres").fetchone()
        output = connection.execute(
            """SELECT run.output_sha256
               FROM current_public_models AS current
               JOIN servable_public_model_runs AS run ON run.id = current.model_run_id
               WHERE current.model_key = 'public-graph'"""
        ).fetchone()
        rows = connection.execute(
            """SELECT entity_kind, genre_id, rank
               FROM displayable_public_genre_representatives
               ORDER BY entity_kind, genre_id, rank, source_entity_ref"""
        ).fetchall()
    if modelable is None:
        raise RuntimeError("modelable genre coverage query returned no row")
    published: list[tuple[MetadataKind, str, int]] = []
    for row in rows:
        kind = str(row[0])
        if kind not in _KINDS:
            raise RuntimeError(f"unexpected public representative kind: {kind}")
        published.append((kind, str(row[1]), int(row[2])))
    return _coverage(
        modelable_genres=int(modelable[0]),
        candidates=candidates,
        published=tuple(published),
        output_sha256=None if output is None else str(output[0]),
    )
