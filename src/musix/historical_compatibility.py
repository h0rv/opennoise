"""Build, publish, and evaluate the bounded historical compatibility artifact."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from musix.adapters.everynoise import (
    AdaptationResult,
    HistoricalAdaptationResult,
    HistoricalRepresentativeRecord,
    adapt_quint_historical_representatives,
    adapt_quint_html,
)
from musix.db import Database
from musix.models.historical import (
    HistoricalAdapterCheckpoint,
    HistoricalAdapterContract,
    HistoricalArtifact,
    HistoricalCompatibilityManifest,
    HistoricalCompatibilityReceipt,
    HistoricalCompatibilityReport,
    HistoricalCoordinate,
    HistoricalCoverage,
    HistoricalGenre,
    HistoricalGeometryComparison,
    HistoricalMembershipProjection,
    HistoricalQuarantine,
    HistoricalRelationshipComparison,
    HistoricalRepresentative,
    PublicComparisonGenre,
    PublicComparisonModel,
    PublicComparisonRelation,
)
from musix.models.modeling import PublicModelArtifact
from musix.models.production import ProductionMapArtifact
from musix.reconstruction import (
    HistoricalGenrePoint,
    ReconstructionPoint,
    align_to_historical_points,
)
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

HISTORICAL_COMPATIBILITY_REVISION = "historical-compatibility-v1"
HISTORICAL_REPORT_REVISION = "historical-compatibility-report-v1"
MINIMUM_ALIGNMENT_POINTS = 2
type AdapterSpecification = tuple[
    Literal["H3", "H4", "H5", "H6"],
    str,
    str,
    Literal["archived_html", "archived_json", "archived_list", "derived_projection"],
    str,
    tuple[str, ...],
]


class HistoricalPublicationSummary(BaseModel):
    """Identify immutable file, object-store, and SQLite publication results."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_byte_size: int = Field(gt=0)
    object_write: ObjectWrite
    sqlite_run_id: int = Field(gt=0)


def _normalized_name(value: str) -> str:
    """Use an exact, Unicode-normalized name key rather than fuzzy identity resolution."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _representative(record: HistoricalRepresentativeRecord) -> HistoricalRepresentative:
    """Project the adapter's media-safe representative record into the published model."""
    # The adapter result is already verified and typed. Keeping this projection
    # local makes the published artifact intentionally smaller than raw HTML.
    return HistoricalRepresentative(
        artist_name=record.artist_name,
        track_title=record.track_title,
        recording_source_id=record.recording_source_id,
        safe_external_url=record.safe_external_url,
        source_genre_page_url=record.source_genre_page_url,
        legacy_preview_state="disabled_legacy" if record.legacy_preview_present else "absent",
        legacy_preview_url_sha256=record.legacy_preview_url_sha256,
    )


def _coverage(
    adaptation: AdaptationResult,
    representatives: HistoricalAdaptationResult,
    h3_membership: HistoricalMembershipProjection | None,
) -> tuple[HistoricalCoverage, ...]:
    """Account for source availability without treating absent archive pages as facts."""
    source_count = adaptation.source.expected_records
    return (
        HistoricalCoverage(
            stage="H1",
            state="complete",
            retained_record_count=1,
            expected_record_count=1,
            retained_fields=("source URL", "snapshot", "SHA-256", "byte size", "rights policy"),
            accounting_note="One verified, local-only pinned HTML artifact is retained.",
        ),
        HistoricalCoverage(
            stage="H2",
            state="complete",
            retained_record_count=len(adaptation.records),
            expected_record_count=source_count,
            retained_fields=(
                "source item ID",
                "name",
                "source order",
                "x/y display coordinates",
                "color",
                "font size",
            ),
            accounting_note="All verified map rows are retained as legacy display observations.",
        ),
        _h3_coverage(adaptation, representatives, h3_membership),
        HistoricalCoverage(
            stage="H4",
            state="partial" if h3_membership is not None else "missing",
            retained_record_count=h3_membership.stored_membership_count if h3_membership else 0,
            retained_fields=("derived exact artist-to-genre index",) if h3_membership else (),
            missing_fields=(
                "artist-page capture",
                "artist-page genre list",
                "artist-page recording list",
                "historical related-artist links",
            ),
            accounting_note=(
                f"A derived_partial inverse index has {h3_membership.stored_membership_count} "
                "exact source-scoped artist-to-genre rows; it is not artist-page evidence. "
                f"{h3_membership.quarantined_membership_count} duplicate or malformed source "
                "rows were quarantined."
                if h3_membership
                else "No verified archived artist-page artifact is retained for this build."
            ),
        ),
        HistoricalCoverage(
            stage="H5",
            state="missing",
            retained_record_count=0,
            missing_fields=("rank lists", "playlist identifiers", "playlist track order"),
            accounting_note=(
                "No verified historical list or playlist artifact is retained for this build."
            ),
        ),
        HistoricalCoverage(
            stage="H6",
            state="partial",
            retained_record_count=len(adaptation.records),
            retained_fields=("map geometry", "map labels", "dated map-row representatives"),
            missing_fields=(
                "genre-page discovery paths",
                "artist-page discovery paths",
                "playlist views",
            ),
            accounting_note=(
                "The compatibility view reproduces retained map output only; unavailable pages "
                "stay unavailable."
            ),
        ),
    )


def _h3_coverage(
    adaptation: AdaptationResult,
    representatives: HistoricalAdaptationResult,
    h3_membership: HistoricalMembershipProjection | None,
) -> HistoricalCoverage:
    """Account for H3 from measured sealed source coverage, never assumed completeness."""
    if h3_membership is None:
        representative_count = len(representatives.records)
        return HistoricalCoverage(
            stage="H3",
            state="partial" if representative_count else "missing",
            retained_record_count=representative_count,
            quarantined_record_count=len(representatives.quarantine),
            expected_record_count=adaptation.source.expected_records,
            retained_fields=("one map-row representative artist and track",)
            if representative_count
            else (),
            missing_fields=(
                "genre-page artist membership lists",
                "artist page positions",
                "related-genre blocks",
                "genre-page capture dates",
            ),
            accounting_note=(
                f"{representative_count} map-row representatives are retained; "
                f"{len(representatives.quarantine)} source rows are quarantined for this field. "
                "No archived genre artist-page corpus was provided. Representative absence is "
                "never negative membership."
            ),
        )
    complete = (
        h3_membership.matched_h2_genre_count == h3_membership.h2_genre_count
        and h3_membership.stored_membership_count == h3_membership.source_membership_count
        and h3_membership.unmatched_source_genre_count == 0
    )
    return HistoricalCoverage(
        stage="H3",
        state="complete" if complete else "partial",
        retained_record_count=h3_membership.stored_membership_count,
        expected_record_count=h3_membership.source_membership_count,
        retained_fields=("source-scoped genre-to-artist membership",),
        missing_fields=()
        if complete
        else (
            "full verified H2 name coverage",
            "artist page positions",
            "related-genre blocks",
            "genre-page capture dates",
        ),
        accounting_note=(
            f"{h3_membership.stored_membership_count} H3 memberships across "
            f"{h3_membership.matched_h2_genre_count} of {h3_membership.h2_genre_count} "
            "retained H2 genre names are stored under an explicit local-display policy. "
            "The sealed source is an observed membership projection, not evidence of missing "
            "members or a complete historical page corpus."
        ),
    )


def _adapter_contracts(
    h3_membership: HistoricalMembershipProjection | None,
) -> tuple[HistoricalAdapterContract, ...]:
    """Declare bounded resume points without authorizing a fetch or scrape."""
    specifications: tuple[AdapterSpecification, ...] = (
        (
            "H3",
            "historical-genre-pages-v1",
            "enao_historical_genre_page_html_v1",
            "archived_html",
            (
                "A verified local/archived genre-page HTML manifest with capture URL, timestamp, "
                "hash, and rights decision."
            ),
            ("genre_page_member", "artist_local_position", "historical_related_genre"),
        ),
        (
            "H4",
            "historical-artist-pages-v1",
            "enao_historical_artist_page_html_v1",
            "archived_html",
            (
                "A verified local/archived artist-page HTML manifest with capture URL, timestamp, "
                "hash, and rights decision."
            ),
            ("artist_page_genre", "artist_page_recording", "artist_page_external_link"),
        ),
        (
            "H5",
            "historical-lists-playlists-v1",
            "enao_historical_list_or_playlist_v1",
            "archived_list",
            (
                "A verified local/archived list or playlist metadata manifest; audio and playlist "
                "media are excluded."
            ),
            (
                "historical_rank",
                "historical_playlist_identifier",
                "historical_playlist_track_order",
            ),
        ),
        (
            "H6",
            "historical-compatibility-projection-v1",
            "historical_compatibility_projection_v1",
            "derived_projection",
            (
                "Verified H1-H5 publication manifests; this local projection resumes only after "
                "those inputs are sealed."
            ),
            ("compatibility_surface", "coverage_accounting", "provenance_link"),
        ),
    )
    contracts = tuple(
        HistoricalAdapterContract(
            stage=stage,
            contract_key=contract_key,
            adapter_key=adapter_key,
            input_kind=input_kind,
            source_requirement=source_requirement,
            output_observations=observations,
            checkpoint=HistoricalAdapterCheckpoint(contract_key=contract_key),
        )
        for (
            stage,
            contract_key,
            adapter_key,
            input_kind,
            source_requirement,
            observations,
        ) in specifications
    )
    if h3_membership is None:
        return contracts
    h3_contract = contracts[0].model_copy(
        update={
            "adapter_key": "enao_genre_artist_map_v1",
            "input_kind": "archived_json",
            "source_requirement": "Sealed local H3 JSON source and matching manifest hash.",
            "output_observations": ("genre_page_member",),
            "checkpoint": HistoricalAdapterCheckpoint(
                contract_key=contracts[0].contract_key,
                source_sha256=h3_membership.source_sha256,
                accepted_records=h3_membership.stored_membership_count,
                complete=(
                    h3_membership.matched_h2_genre_count == h3_membership.h2_genre_count
                    and h3_membership.stored_membership_count
                    == h3_membership.source_membership_count
                    and h3_membership.unmatched_source_genre_count == 0
                ),
            ),
            "enabled": True,
        }
    )
    return (h3_contract, *contracts[1:])


def build_historical_compatibility(
    raw: bytes,
    *,
    h3_membership: HistoricalMembershipProjection | None = None,
) -> HistoricalCompatibilityManifest:
    """Build a fail-closed full map compatibility artifact from verified retained bytes."""
    adaptation = adapt_quint_html(raw)
    representatives = adapt_quint_historical_representatives(raw)
    if adaptation.quarantine:
        raise ValueError("historical map rows were quarantined; refusing partial compatibility map")
    if len(adaptation.records) != adaptation.source.expected_records:
        raise ValueError("historical map does not contain every verified source row")
    representatives_by_genre = {
        record.genre_external_id: _representative(record) for record in representatives.records
    }
    genres = tuple(
        HistoricalGenre(
            external_id=record.catalog.external_id,
            source_item_id=record.catalog.identifiers[0].value,
            source_order=index,
            name=record.catalog.name,
            slug=record.catalog.slug,
            coordinate=HistoricalCoordinate(
                x_px=float(record.layout.x_px),
                y_px=float(record.layout.y_px),
                color_hex=record.layout.color_hex,
                font_size_percent=record.layout.font_size_percent or 100,
            ),
            representative=representatives_by_genre.get(record.catalog.external_id),
        )
        for index, record in enumerate(adaptation.records, start=1)
    )
    source = adaptation.source
    return HistoricalCompatibilityManifest(
        artifact=HistoricalArtifact(
            source_id=source.source_id,
            snapshot=source.snapshot,
            source_url=source.url,
            content_sha256=source.sha256,
            byte_size=source.expected_bytes,
            expected_genres=source.expected_records,
        ),
        genres=genres,
        quarantine=tuple(
            HistoricalQuarantine(
                source_id=item.source_id,
                source_sha256=source.sha256,
                source_record_number=item.record_number,
                source_record_id=item.source_record_id,
                reason=item.reason,
            )
            for item in representatives.quarantine
        ),
        coverage=_coverage(adaptation, representatives, h3_membership),
        adapter_contracts=_adapter_contracts(h3_membership),
        h3_membership=h3_membership,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    """Atomically publish JSON without leaving partial compatibility artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_historical_compatibility(
    manifest: HistoricalCompatibilityManifest,
    output_path: Path,
) -> tuple[str, int]:
    """Serialize one deterministic compatibility manifest to an atomic JSON file."""
    payload = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    _atomic_write(output_path, payload)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def publish_historical_compatibility(
    *,
    manifest: HistoricalCompatibilityManifest,
    output_path: Path,
    store: ObjectStore,
    database_path: Path,
) -> HistoricalPublicationSummary:
    """Publish immutable JSON to the object store and coverage rows to SQLite."""
    artifact_sha256, artifact_byte_size = write_historical_compatibility(manifest, output_path)
    object_write = store.push(
        output_path,
        ObjectKey(
            value=f"historical-compatibility/{manifest.artifact.content_sha256}/{artifact_sha256}.json"
        ),
    )
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection, connection:
        connection.execute(
            """INSERT OR IGNORE INTO historical_compatibility_runs
               (revision, source_id, source_sha256, manifest_sha256, object_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                manifest.revision,
                manifest.artifact.source_id,
                manifest.artifact.content_sha256,
                artifact_sha256,
                object_write.key.value,
                _now(),
            ),
        )
        row = connection.execute(
            """SELECT id FROM historical_compatibility_runs
               WHERE source_sha256 = ? AND manifest_sha256 = ?""",
            (manifest.artifact.content_sha256, artifact_sha256),
        ).fetchone()
        if row is None:
            raise RuntimeError("historical compatibility SQLite publication failed")
        run_id = int(row[0])
        connection.executemany(
            """INSERT OR IGNORE INTO historical_compatibility_coverage
               (run_id, stage, state, retained_record_count, expected_record_count,
                quarantined_record_count, retained_fields_json, missing_fields_json,
                accounting_note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    run_id,
                    coverage.stage,
                    coverage.state,
                    coverage.retained_record_count,
                    coverage.expected_record_count,
                    coverage.quarantined_record_count,
                    json.dumps(coverage.retained_fields, separators=(",", ":")),
                    json.dumps(coverage.missing_fields, separators=(",", ":")),
                    coverage.accounting_note,
                )
                for coverage in manifest.coverage
            ),
        )
    return HistoricalPublicationSummary(
        artifact_sha256=artifact_sha256,
        artifact_byte_size=artifact_byte_size,
        object_write=object_write,
        sqlite_run_id=run_id,
    )


def compatibility_receipt(
    manifest: HistoricalCompatibilityManifest,
    publication: HistoricalPublicationSummary,
) -> HistoricalCompatibilityReceipt:
    """Create a compact receipt that links the published artifact to its local H3 projection."""
    return HistoricalCompatibilityReceipt(
        artifact_sha256=publication.artifact_sha256,
        artifact_byte_size=publication.artifact_byte_size,
        object_key=publication.object_write.key.value,
        sqlite_run_id=publication.sqlite_run_id,
        h2_source_sha256=manifest.artifact.content_sha256,
        h3_membership=manifest.h3_membership,
    )


def write_compatibility_receipt(
    receipt: HistoricalCompatibilityReceipt,
    output_path: Path,
) -> None:
    """Atomically write the small receipt that links H2, H3, object storage, and SQLite."""
    _atomic_write(output_path, (receipt.model_dump_json(indent=2) + "\n").encode())


def _comparison_from_public_artifact(artifact: PublicModelArtifact) -> PublicComparisonModel:
    coordinates = {point.genre_id: point for point in artifact.coordinates}
    return PublicComparisonModel(
        revision=artifact.revision,
        output_sha256=artifact.output_sha256,
        genres=tuple(
            PublicComparisonGenre(
                genre_id=genre.genre_id,
                name=genre.name,
                x=coordinates[genre.genre_id].x if genre.genre_id in coordinates else None,
                y=coordinates[genre.genre_id].y if genre.genre_id in coordinates else None,
            )
            for genre in artifact.genres
        ),
        relations=tuple(
            PublicComparisonRelation(
                source_genre_id=neighbor.genre_id,
                target_genre_id=neighbor.neighbor_genre_id,
            )
            for neighbor in artifact.neighbors
        ),
    )


def _comparison_from_production_artifact(artifact: ProductionMapArtifact) -> PublicComparisonModel:
    return PublicComparisonModel(
        revision=artifact.revision,
        output_sha256=artifact.output_sha256,
        genres=tuple(
            PublicComparisonGenre(genre_id=node.genre_id, name=node.name, x=node.x, y=node.y)
            for node in artifact.nodes
        ),
        relations=tuple(
            PublicComparisonRelation(
                source_genre_id=edge.source_genre_id,
                target_genre_id=edge.target_genre_id,
            )
            for edge in artifact.edges
        ),
    )


def load_public_comparison(path: Path) -> PublicComparisonModel:
    """Load either supported independent public model artifact with strict validation."""
    payload_text = path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    revision = payload.get("revision") if isinstance(payload, dict) else None
    if revision == "public-graph-v2":
        return _comparison_from_public_artifact(
            PublicModelArtifact.model_validate_json(payload_text)
        )
    if revision == "production-map-v1":
        return _comparison_from_production_artifact(
            ProductionMapArtifact.model_validate_json(payload_text)
        )
    raise ValueError("public comparison requires a public-graph-v2 or production-map-v1 artifact")


def _unique_name_index(items: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """Return only unique exact normalized names; ambiguities remain intentionally unmatched."""
    candidates: dict[str, list[str]] = defaultdict(list)
    for identifier, name in items:
        candidates[_normalized_name(name)].append(identifier)
    return {
        name: identifiers[0] for name, identifiers in candidates.items() if len(identifiers) == 1
    }


def evaluate_historical_compatibility(
    manifest: HistoricalCompatibilityManifest,
    public: PublicComparisonModel,
) -> HistoricalCompatibilityReport:
    """Compare retained observations to independent public output without inventing links."""
    legacy_by_name = _unique_name_index(
        tuple((genre.external_id, genre.name) for genre in manifest.genres)
    )
    public_by_name = _unique_name_index(
        tuple((genre.genre_id, genre.name) for genre in public.genres)
    )
    matched = tuple(
        (legacy_id, public_by_name[name])
        for name, legacy_id in legacy_by_name.items()
        if name in public_by_name
    )
    legacy_by_id = {genre.external_id: genre for genre in manifest.genres}
    public_by_id = {genre.genre_id: genre for genre in public.genres}
    candidate_points: list[ReconstructionPoint] = []
    historical_points: list[HistoricalGenrePoint] = []
    for legacy_id, public_id in matched:
        public_genre = public_by_id[public_id]
        if public_genre.x is None or public_genre.y is None:
            continue
        legacy = legacy_by_id[legacy_id]
        candidate_points.append(
            ReconstructionPoint(genre_id=legacy_id, x=public_genre.x, y=public_genre.y)
        )
        historical_points.append(
            HistoricalGenrePoint(
                genre_id=legacy_id,
                x=legacy.coordinate.x_px,
                y=legacy.coordinate.y_px,
                evidence_ref=f"sha256:{manifest.artifact.content_sha256}",
            )
        )
    if len(candidate_points) >= MINIMUM_ALIGNMENT_POINTS:
        alignment = align_to_historical_points(tuple(candidate_points), tuple(historical_points))
        geometry = HistoricalGeometryComparison(
            matched_name_count=len(matched),
            legacy_genre_count=len(manifest.genres),
            public_genre_count=len(public.genres),
            aligned_coordinate_count=len(candidate_points),
            root_mean_square_error=alignment.root_mean_square_error,
            coordinate_comparison_state="compared",
        )
    else:
        geometry = HistoricalGeometryComparison(
            matched_name_count=len(matched),
            legacy_genre_count=len(manifest.genres),
            public_genre_count=len(public.genres),
            aligned_coordinate_count=len(candidate_points),
            coordinate_comparison_state="insufficient_overlap",
        )
    legacy_to_public = dict(matched)
    public_relations = {(item.source_genre_id, item.target_genre_id) for item in public.relations}
    comparable = [
        relation
        for relation in manifest.relations
        if relation.target_external_id is not None
        and relation.source_external_id in legacy_to_public
        and relation.target_external_id in legacy_to_public
    ]
    relationship = HistoricalRelationshipComparison(
        observed_historical_relations=len(manifest.relations),
        comparable_historical_relations=len(comparable),
        overlapping_public_relations=sum(
            (
                legacy_to_public[relation.source_external_id],
                legacy_to_public[relation.target_external_id],
            )
            in public_relations
            for relation in comparable
            if relation.target_external_id is not None
        ),
        comparison_state="compared" if comparable else "unavailable",
    )
    return HistoricalCompatibilityReport(
        historical_source_sha256=manifest.artifact.content_sha256,
        public_model_output_sha256=public.output_sha256,
        coverage=manifest.coverage,
        geometry=geometry,
        relationships=relationship,
    )


def coverage_quality_report(manifest: HistoricalCompatibilityManifest) -> dict[str, object]:
    """Return a compact deterministic report usable without an independent model artifact."""
    state_counts = Counter(item.state for item in manifest.coverage)
    return {
        "revision": HISTORICAL_REPORT_REVISION,
        "historical_source_sha256": manifest.artifact.content_sha256,
        "genre_count": len(manifest.genres),
        "representative_count": sum(item.representative is not None for item in manifest.genres),
        "representative_quarantine_count": next(
            item.quarantined_record_count for item in manifest.coverage if item.stage == "H3"
        ),
        "representative_quarantine_reasons": dict(
            sorted(Counter(item.reason for item in manifest.quarantine).items())
        ),
        "relation_count": len(manifest.relations),
        "h3_membership": (
            manifest.h3_membership.model_dump(mode="json")
            if manifest.h3_membership is not None
            else None
        ),
        "coverage_state_counts": dict(sorted(state_counts.items())),
        "missing_adapter_contracts": [
            {
                "stage": item.stage,
                "contract_key": item.contract_key,
                "enabled": item.enabled,
                "source_requirement": item.source_requirement,
            }
            for item in manifest.adapter_contracts
        ],
    }
