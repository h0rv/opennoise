"""Build and publish a bounded historical compatibility manifest from retained HTML."""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

from musix.adapters.everynoise import (
    NEROYUKI_H3_SOURCE,
    QUINT_SOURCE,
    adapt_historical_genre_artist_map,
    adapt_quint_html,
)
from musix.db import Database
from musix.genre_discovery import (
    import_historical_genre_memberships,
    query_displayable_historical_genre_memberships,
)
from musix.history.historical_compatibility import (
    build_historical_compatibility,
    compatibility_receipt,
    coverage_quality_report,
    publish_historical_compatibility,
    write_compatibility_receipt,
)
from musix.ingest import ImportOptions, import_jsonl_sync
from musix.models.historical import HistoricalH3SourceManifest, HistoricalMembershipProjection
from musix.storage import LocalObjectStore


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, required=True, help="Verified retained Every Noise HTML"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/historical/historical-compatibility-v1.json"),
    )
    parser.add_argument("--h3-source", type=Path)
    parser.add_argument(
        "--h3-manifest",
        type=Path,
        default=Path("config/historical_sources/neroyuki_h3_20241116.json"),
    )
    parser.add_argument("--enable-local-display", action="store_true")
    parser.add_argument("--database", type=Path, default=Path("data/musix.sqlite"))
    parser.add_argument("--object-store", type=Path, default=Path("data/objects"))
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("data/historical/historical-compatibility-v1.receipt.json"),
    )
    return parser.parse_args()


def _h3_projection(
    *,
    source_path: Path,
    manifest_path: Path,
    database_path: Path,
    h2_genre_count: int,
) -> HistoricalMembershipProjection:
    """Verify, store, and measure an explicit local-display H3 projection."""
    manifest_bytes = manifest_path.read_bytes()
    source_manifest = HistoricalH3SourceManifest.model_validate_json(manifest_bytes)
    raw = source_path.read_bytes()
    adaptation = adapt_historical_genre_artist_map(
        raw,
        NEROYUKI_H3_SOURCE,
        source_revision_date="2024-11-16",
    )
    source = adaptation.source
    if (
        source_manifest.source_id != source.source_id
        or source_manifest.full_sha256 != source.sha256
        or source_manifest.full_byte_size != source.expected_bytes
        or source_manifest.adapter != source.adapter
    ):
        raise ValueError("H3 source manifest does not match the sealed source contract")
    if (
        source_manifest.coverage.source_genre_rows != source.expected_records
        or source_manifest.coverage.source_distinct_genres
        != len({record.genre_name.casefold() for record in adaptation.records})
        or source_manifest.coverage.source_artist_memberships != adaptation.source_membership_count
    ):
        raise ValueError("H3 source manifest coverage does not match the sealed source bytes")
    imported = import_historical_genre_memberships(
        database_path,
        adaptation,
        enable_local_display=True,
    )
    visible = query_displayable_historical_genre_memberships(
        database_path,
        source_sha256=source.sha256,
        policy_key=imported.policy_key,
    )
    if (
        visible.genre_memberships != imported.genre_memberships
        or visible.matched_genres != imported.matched_genres
        or visible.distinct_source_artists != imported.distinct_source_artists
    ):
        raise RuntimeError("H3 display query does not match the sealed local projection")
    return HistoricalMembershipProjection(
        source_id=source.source_id,
        source_sha256=source.sha256,
        source_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        source_revision_date="2024-11-16",
        source_genre_row_count=source.expected_records,
        source_membership_count=imported.source_membership_count,
        stored_membership_count=visible.genre_memberships,
        quarantined_membership_count=imported.quarantined_membership_count,
        matched_h2_genre_count=visible.matched_genres,
        unmatched_source_genre_count=imported.unmatched_genres,
        h2_genre_count=h2_genre_count,
        distinct_source_artist_count=visible.distinct_source_artists,
        policy_key=imported.policy_key,
    )


def _normalized_h2_genre_count(database_path: Path) -> int:
    """Count only H2 genres normalized from the sealed base map source key."""
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            """SELECT count(DISTINCT genre.id)
               FROM genres AS genre
               JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
               JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
               JOIN data_sources AS source ON source.id = provenance.source_id
               WHERE source.source_key = ?""",
            (QUINT_SOURCE.source_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("H2 normalized genre count failed")
    return int(row[0])


def _normalize_h2_catalog(raw: bytes, database_path: Path) -> None:
    """Normalize the verified H2 map before its H3 rows can be matched to it."""
    adaptation = adapt_quint_html(raw)
    if len(adaptation.records) != QUINT_SOURCE.expected_records:
        raise RuntimeError("sealed H2 map did not expose every expected genre")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=database_path.parent) as temporary_directory:
        catalog_path = Path(temporary_directory) / "h2-catalog.jsonl"
        catalog_path.write_bytes(adaptation.catalog_jsonl())
        import_jsonl_sync(
            ImportOptions(
                input_path=catalog_path,
                database_path=database_path,
                vault_path=database_path.parent / "vault",
                source_key=QUINT_SOURCE.source_id,
                source_name="Every Noise legacy H2 map",
            )
        )
    normalized_genres = _normalized_h2_genre_count(database_path)
    if normalized_genres != QUINT_SOURCE.expected_records:
        raise RuntimeError(
            f"normalized H2 map has {normalized_genres} genres; "
            f"expected {QUINT_SOURCE.expected_records}"
        )


def _require_complete_h2_manifest(genre_count: int) -> None:
    """Reject H3 publication unless the compatibility build retained every H2 row."""
    if genre_count != QUINT_SOURCE.expected_records:
        raise RuntimeError("historical compatibility H2 map is incomplete")


def _require_h3_arguments(*, enable_local_display: bool, source_path: Path | None) -> None:
    """Reject an accidental publication-mode toggle without its sealed H3 input."""
    if enable_local_display != (source_path is not None):
        raise ValueError("--enable-local-display requires exactly one --h3-source")


def main() -> int:
    """Publish a complete H1/H2 compatibility snapshot and explicit H3-H6 gaps."""
    arguments = _arguments()
    try:
        _require_h3_arguments(
            enable_local_display=arguments.enable_local_display,
            source_path=arguments.h3_source,
        )
        source_bytes = arguments.source.read_bytes()
        _normalize_h2_catalog(source_bytes, arguments.database)
        base_manifest = build_historical_compatibility(source_bytes)
        _require_complete_h2_manifest(len(base_manifest.genres))
        h3_membership = (
            _h3_projection(
                source_path=arguments.h3_source,
                manifest_path=arguments.h3_manifest,
                database_path=arguments.database,
                h2_genre_count=len(base_manifest.genres),
            )
            if arguments.enable_local_display and arguments.h3_source is not None
            else None
        )
        manifest = build_historical_compatibility(
            arguments.source.read_bytes(), h3_membership=h3_membership
        )
        summary = publish_historical_compatibility(
            manifest=manifest,
            output_path=arguments.output,
            store=LocalObjectStore(arguments.object_store),
            database_path=arguments.database,
        )
        receipt = compatibility_receipt(manifest, summary)
        write_compatibility_receipt(receipt, arguments.receipt)
    except (OSError, ValueError, RuntimeError) as error:
        sys.stderr.write(f"historical compatibility build failed: {error}\n")
        return 2
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    sys.stdout.write(f"{coverage_quality_report(manifest)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
