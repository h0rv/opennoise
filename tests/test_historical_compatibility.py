import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, ValidationError

from musix.historical_compatibility import (
    coverage_quality_report,
    evaluate_historical_compatibility,
    publish_historical_compatibility,
)
from musix.models.historical import (
    HistoricalAdapterCheckpoint,
    HistoricalAdapterContract,
    HistoricalArtifact,
    HistoricalCompatibilityManifest,
    HistoricalCoordinate,
    HistoricalCoverage,
    HistoricalGenre,
    HistoricalMembershipProjection,
    HistoricalQuarantine,
    HistoricalRelation,
    HistoricalRepresentative,
    HistoricalStage,
    PublicComparisonGenre,
    PublicComparisonModel,
    PublicComparisonRelation,
)
from musix.storage import LocalObjectStore

SHA = "a" * 64
PUBLIC_SHA = "b" * 64


def adapter_contract(stage: Literal["H3", "H4", "H5", "H6"]) -> HistoricalAdapterContract:
    """Build one deliberately disabled future source contract."""
    key = f"fixture-{stage.casefold()}"
    return HistoricalAdapterContract(
        stage=stage,
        contract_key=key,
        adapter_key="fixture-adapter",
        input_kind="archived_html",
        source_requirement="A verified fixture source is required.",
        output_observations=("fixture-observation",),
        checkpoint=HistoricalAdapterCheckpoint(contract_key=key),
    )


def coverage(
    stage: HistoricalStage,
    state: Literal["complete", "partial", "missing"],
    retained: int,
    missing: tuple[str, ...] = (),
) -> HistoricalCoverage:
    """Build explicit fixture coverage rows."""
    return HistoricalCoverage(
        stage=stage,
        state=state,
        retained_record_count=retained,
        expected_record_count=retained if state == "complete" else None,
        retained_fields=("fixture",) if retained else (),
        missing_fields=missing,
        accounting_note=f"{stage} fixture accounting.",
    )


def manifest(*, relations: tuple[HistoricalRelation, ...] = ()) -> HistoricalCompatibilityManifest:
    """Build a one-row, fully accounted historical fixture."""
    genre = HistoricalGenre(
        external_id="enao-legacy:item1",
        source_item_id="item1",
        source_order=1,
        name="Example Genre",
        slug="example-genre",
        coordinate=HistoricalCoordinate(
            x_px=10.0, y_px=20.0, color_hex="#123abc", font_size_percent=100
        ),
        representative=HistoricalRepresentative(
            artist_name="Example Artist",
            track_title="Example Track",
            recording_source_id="1V6gIisPpYqgFeWbMLI0bA",
            safe_external_url=AnyHttpUrl("https://open.spotify.com/track/1V6gIisPpYqgFeWbMLI0bA"),
            legacy_preview_state="absent",
        ),
    )
    return HistoricalCompatibilityManifest(
        artifact=HistoricalArtifact(
            source_id="fixture-source",
            snapshot="fixture-snapshot",
            source_url=AnyHttpUrl("https://example.invalid/fixture.html"),
            content_sha256=SHA,
            byte_size=1,
            expected_genres=1,
        ),
        genres=(genre,),
        relations=relations,
        coverage=(
            coverage("H1", "complete", 1),
            coverage("H2", "complete", 1),
            coverage("H3", "partial", 1, ("genre pages",)),
            coverage("H4", "missing", 0, ("artist pages",)),
            coverage("H5", "missing", 0, ("playlists",)),
            coverage("H6", "partial", 1, ("full discovery path",)),
        ),
        adapter_contracts=tuple(adapter_contract(stage) for stage in ("H3", "H4", "H5", "H6")),
    )


class HistoricalCompatibilityTests(unittest.TestCase):
    def test_sealed_h3_projection_updates_coverage_without_exporting_memberships(self) -> None:
        projection = HistoricalMembershipProjection(
            source_id="fixture-h3",
            source_sha256="c" * 64,
            source_manifest_sha256="d" * 64,
            source_revision_date="2024-11-16",
            source_genre_row_count=2,
            source_membership_count=3,
            stored_membership_count=2,
            quarantined_membership_count=1,
            matched_h2_genre_count=1,
            unmatched_source_genre_count=1,
            h2_genre_count=1,
            distinct_source_artist_count=2,
            policy_key=f"historical-membership:local-display:{'c' * 64}",
        )
        value = manifest().model_copy(
            update={
                "h3_membership": projection,
                "coverage": tuple(
                    coverage_item.model_copy(
                        update={
                            "state": "partial",
                            "retained_record_count": 2,
                            "expected_record_count": 3,
                            "retained_fields": ("source-scoped genre-to-artist membership",),
                            "missing_fields": ("full verified H2 name coverage",),
                        }
                    )
                    if coverage_item.stage == "H3"
                    else coverage_item
                    for coverage_item in manifest().coverage
                ),
                "adapter_contracts": tuple(
                    contract.model_copy(
                        update={
                            "enabled": True,
                            "checkpoint": HistoricalAdapterCheckpoint(
                                contract_key=contract.contract_key,
                                source_sha256=projection.source_sha256,
                            ),
                        }
                    )
                    if contract.stage == "H3"
                    else contract
                    for contract in manifest().adapter_contracts
                ),
            }
        )
        value = HistoricalCompatibilityManifest.model_validate(value.model_dump())
        rendered = value.h3_membership.model_dump_json() if value.h3_membership else ""
        self.assertIn("stored_membership_count", rendered)
        self.assertNotIn("preview_url", rendered)
        self.assertNotIn("sample_song", rendered)
        self.assertNotIn("track_id", rendered)

    def test_manifest_rejects_partial_map_count(self) -> None:
        value = manifest().model_dump(mode="json")
        value["artifact"]["expected_genres"] = 2
        with self.assertRaises(ValidationError):
            HistoricalCompatibilityManifest.model_validate(value)

    def test_preview_hash_is_not_a_preview_url(self) -> None:
        serialized = manifest().model_dump_json()
        self.assertNotIn("mp3-preview", serialized)
        self.assertIn(
            "disabled_legacy",
            HistoricalRepresentative(
                artist_name="A",
                track_title="T",
                recording_source_id="1V6gIisPpYqgFeWbMLI0bA",
                safe_external_url=AnyHttpUrl(
                    "https://open.spotify.com/track/1V6gIisPpYqgFeWbMLI0bA"
                ),
                legacy_preview_state="disabled_legacy",
                legacy_preview_url_sha256=SHA,
            ).model_dump_json(),
        )

    def test_quarantine_requires_matching_source_provenance(self) -> None:
        value = manifest().model_dump(mode="json")
        value["quarantine"] = [
            HistoricalQuarantine(
                source_id="different-source",
                source_sha256=SHA,
                source_record_number=1,
                reason="fixture rejection",
            ).model_dump(mode="json")
        ]
        with self.assertRaises(ValidationError):
            HistoricalCompatibilityManifest.model_validate_json(json.dumps(value))

    def test_evaluator_reports_insufficient_geometry_and_unavailable_relations(self) -> None:
        public = PublicComparisonModel(
            revision="public-graph-v2",
            output_sha256=PUBLIC_SHA,
            genres=(PublicComparisonGenre(genre_id="Q1", name="Example Genre", x=0.2, y=0.4),),
        )
        report = evaluate_historical_compatibility(manifest(), public)
        self.assertEqual(report.geometry.matched_name_count, 1)
        self.assertEqual(report.geometry.coordinate_comparison_state, "insufficient_overlap")
        self.assertEqual(report.relationships.comparison_state, "unavailable")
        self.assertFalse(report.geometry.exact_historical_recovery_claimed)

    def test_evaluator_only_compares_observed_relations(self) -> None:
        second = HistoricalGenre(
            external_id="enao-legacy:item2",
            source_item_id="item2",
            source_order=2,
            name="Other Genre",
            slug="other-genre",
            coordinate=HistoricalCoordinate(
                x_px=20.0, y_px=20.0, color_hex="#123abc", font_size_percent=100
            ),
        )
        value = manifest().model_dump(mode="json")
        value["artifact"]["expected_genres"] = 2
        value["genres"].append(second.model_dump(mode="json"))
        value["coverage"][1]["retained_record_count"] = 2
        value["coverage"][1]["expected_record_count"] = 2
        value["relations"] = [
            HistoricalRelation(
                source_external_id="enao-legacy:item1",
                target_external_id="enao-legacy:item2",
                target_name="Other Genre",
                method="artist_overlap",
            ).model_dump(mode="json")
        ]
        historical = HistoricalCompatibilityManifest.model_validate_json(json.dumps(value))
        public = PublicComparisonModel(
            revision="public-graph-v2",
            output_sha256=PUBLIC_SHA,
            genres=(
                PublicComparisonGenre(genre_id="Q1", name="Example Genre", x=0.0, y=0.0),
                PublicComparisonGenre(genre_id="Q2", name="Other Genre", x=1.0, y=0.0),
            ),
            relations=(PublicComparisonRelation(source_genre_id="Q1", target_genre_id="Q2"),),
        )
        report = evaluate_historical_compatibility(historical, public)
        self.assertEqual(report.geometry.coordinate_comparison_state, "compared")
        self.assertEqual(report.relationships.comparable_historical_relations, 1)
        self.assertEqual(report.relationships.overlapping_public_relations, 1)

    def test_publication_uses_object_store_and_append_only_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = publish_historical_compatibility(
                manifest=manifest(),
                output_path=root / "historical.json",
                store=LocalObjectStore(root / "objects"),
                database_path=root / "catalog.sqlite",
            )
            self.assertEqual(
                result.artifact_sha256,
                hashlib.sha256((root / "historical.json").read_bytes()).hexdigest(),
            )
            self.assertTrue((root / "objects" / result.object_write.key.value).is_file())
            report = coverage_quality_report(manifest())
            self.assertEqual(report["genre_count"], 1)
            self.assertEqual(
                report["coverage_state_counts"], {"complete": 2, "missing": 2, "partial": 2}
            )
            with (
                self.assertRaises(sqlite3.IntegrityError),
                sqlite3.connect(root / "catalog.sqlite") as connection,
            ):
                connection.execute("UPDATE historical_compatibility_runs SET source_id = 'changed'")

    def test_coverage_is_json_serializable(self) -> None:
        payload = json.loads(manifest().model_dump_json())
        self.assertEqual(payload["revision"], "historical-compatibility-v1")


if __name__ == "__main__":
    unittest.main()
