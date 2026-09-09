"""One-command bootstrap for the pinned Every Noise genre map."""

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from musix.adapters.everynoise import (
    AdaptationResult,
    adapt_quint_historical_representatives,
    adapt_quint_html,
    store_verified_bytes,
)
from musix.db import Database
from musix.genre_discovery import DiscoveryImportSummary, import_historical_representatives
from musix.ingest.ingest import ImportOptions, ImportSummary, import_jsonl

LAYOUT_KEY = "default"
SOURCE_NAME = "Every Noise legacy genre map"


class BootstrapSummary(BaseModel):
    """Validated result of the complete local demo bootstrap."""

    model_config = ConfigDict(frozen=True, strict=True)

    import_summary: ImportSummary
    map_points: int
    discovery: DiscoveryImportSummary
    source_sha256: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _publish_layout(
    database_path: Path,
    adaptation: AdaptationResult,
) -> int:
    database = Database(database_path)
    with database.connect() as connection, connection:
        source_row = connection.execute(
            "SELECT id, default_policy_id FROM data_sources WHERE source_key = ?",
            (adaptation.source.source_id,),
        ).fetchone()
        if source_row is None:
            raise RuntimeError("Every Noise source was not normalized")
        source_id = int(source_row[0])
        policy_id = int(source_row[1])
        connection.execute(
            """INSERT OR IGNORE INTO layout_runs
               (layout_key, revision, algorithm_key, algorithm_revision, parameters_json,
                input_fingerprint, status, policy_id, completed_at)
               VALUES (?, 1, 'source_coordinates', ?, '{}', ?, 'complete', ?, ?)""",
            (
                LAYOUT_KEY,
                adaptation.source.snapshot,
                adaptation.source.sha256,
                policy_id,
                _now(),
            ),
        )
        run_row = connection.execute(
            "SELECT id FROM layout_runs WHERE layout_key = ? AND revision = 1", (LAYOUT_KEY,)
        ).fetchone()
        if run_row is None:
            raise RuntimeError("layout run registration failed")
        run_id = int(run_row[0])
        identifier_type_row = connection.execute(
            "SELECT id FROM identifier_types WHERE type_key = 'source_id'"
        ).fetchone()
        if identifier_type_row is None:
            raise RuntimeError("source identifier type is missing")
        identifier_type_id = int(identifier_type_row[0])
        entity_rows = connection.execute(
            """SELECT identifier.normalized_value, identifier.entity_id
               FROM entity_identifiers AS identifier
               JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
               WHERE provenance.source_id = ? AND identifier.identifier_type_id = ?""",
            (source_id, identifier_type_id),
        ).fetchall()
        entity_ids = {str(row[0]): int(row[1]) for row in entity_rows}
        missing = [
            item.catalog.external_id
            for item in adaptation.records
            if item.catalog.external_id not in entity_ids
        ]
        if missing:
            raise RuntimeError(f"genres were not normalized: {len(missing)}")
        connection.executemany(
            """INSERT OR IGNORE INTO layout_points
               (layout_run_id, entity_id, x, y, display_weight, color_hex, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, '{}')""",
            (
                (
                    run_id,
                    entity_ids[item.catalog.external_id],
                    float(item.layout.x_px),
                    float(item.layout.y_px),
                    float(item.layout.font_size_percent or 100) / 100.0,
                    item.layout.color_hex,
                )
                for item in adaptation.records
            ),
        )
        connection.execute(
            """INSERT INTO current_layouts (layout_key, layout_run_id)
               VALUES (?, ?)
               ON CONFLICT(layout_key) DO UPDATE SET layout_run_id = excluded.layout_run_id,
                   selected_at = excluded.selected_at""",
            (LAYOUT_KEY, run_id),
        )
        count_row = connection.execute(
            "SELECT count(*) FROM layout_points WHERE layout_run_id = ?", (run_id,)
        ).fetchone()
        if count_row is None:
            raise RuntimeError("layout count failed")
        return int(count_row[0])


async def bootstrap_everynoise(
    *,
    database_path: Path,
    vault_path: Path,
    source_path: Path,
) -> BootstrapSummary:
    """Adapt, normalize, and publish one verified Every Noise snapshot."""
    raw = await asyncio.to_thread(source_path.read_bytes)
    adaptation = await asyncio.to_thread(adapt_quint_html, raw)
    await asyncio.to_thread(
        store_verified_bytes,
        raw,
        adaptation.source,
        vault_path / "raw" / "sha256",
    )
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as temporary:
        temporary.write(adaptation.catalog_jsonl())
        temporary.flush()
        import_summary = await import_jsonl(
            ImportOptions(
                input_path=Path(temporary.name),
                database_path=database_path,
                vault_path=vault_path / "normalized" / "sha256",
                source_key=adaptation.source.source_id,
                source_name=SOURCE_NAME,
            )
        )
    map_points = await asyncio.to_thread(_publish_layout, database_path, adaptation)
    historical = await asyncio.to_thread(adapt_quint_historical_representatives, raw)
    discovery = await asyncio.to_thread(
        import_historical_representatives,
        database_path,
        historical,
    )
    return BootstrapSummary(
        import_summary=import_summary,
        map_points=map_points,
        discovery=discovery,
        source_sha256=adaptation.source.sha256,
    )
