import json
import sqlite3
import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.serving.local.v3_map_overlay import (
    V3MapOverlayError,
    V3MapOverlayInputs,
    build_local_v3_map_overlay_audit,
)

_V3_ROOT = Path("/tmp/phase3-historical-v3-20260921")  # noqa: S108 - retained read-only input.


class V3MapOverlayTests(unittest.TestCase):
    @unittest.skipUnless(
        all(
            path.is_file()
            for path in (
                _V3_ROOT / "receipt.json",
                _V3_ROOT / "model.json",
                _V3_ROOT / "serving.sqlite",
                Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
                Path(".cache/semantic-map-layout-v3/artifact.json"),
            )
        ),
        "retained local Phase 3 v3 inputs are unavailable",
    )
    def test_retained_local_inputs_replay_the_bounded_bridge_without_writes(self) -> None:
        inputs = V3MapOverlayInputs(
            v3_receipt=_V3_ROOT / "receipt.json",
            v3_model=_V3_ROOT / "model.json",
            v3_serving_database=_V3_ROOT / "serving.sqlite",
            reconciliation=Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
            canonical_layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
        )
        input_paths = (
            inputs.v3_receipt,
            inputs.v3_model,
            inputs.v3_serving_database,
            inputs.reconciliation,
            inputs.canonical_layout,
        )
        before = {path: _file_sha256(path) for path in input_paths}
        audit = build_local_v3_map_overlay_audit(inputs)
        after = {path: _file_sha256(path) for path in input_paths}

        self.assertEqual(before, after)
        self.assertEqual(
            audit.coverage.model_dump(),
            {
                "v3_genre_count": 603,
                "reconciliation_candidate_genre_count": 415,
                "unique_candidate_genre_count": 347,
                "unique_non_ambiguous_genre_count": 314,
                "positioned_link_count": 305,
                "canonical_seed_count": 6291,
                "canonical_placed_count": 2945,
                "canonical_unplaced_count": 3346,
            },
        )
        self.assertFalse(audit.export_allowed)
        self.assertFalse(audit.static_output_written)
        self.assertFalse(audit.artist_integration_included)

    @unittest.skipUnless((_V3_ROOT / "receipt.json").is_file(), "retained v3 receipt unavailable")
    def test_rejects_a_byte_modified_copy_of_the_pinned_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            altered = Path(temporary) / "receipt.json"
            altered.write_bytes((_V3_ROOT / "receipt.json").read_bytes() + b"\n")
            inputs = V3MapOverlayInputs(
                v3_receipt=altered,
                v3_model=_V3_ROOT / "model.json",
                v3_serving_database=_V3_ROOT / "serving.sqlite",
                reconciliation=Path(".cache/seed-reconciliation/v3/seed-reconciliation.json"),
                canonical_layout=Path(".cache/semantic-map-layout-v3/artifact.json"),
            )
            with self.assertRaisesRegex(V3MapOverlayError, "receipt file hash is not"):
                build_local_v3_map_overlay_audit(inputs)

    def test_rejects_an_invalid_receipt_before_reading_other_inputs(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _inputs(root)
            with self.assertRaisesRegex(V3MapOverlayError, "receipt file hash is not"):
                build_local_v3_map_overlay_audit(inputs)

    def test_is_explicitly_read_only_and_has_no_output_path(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = _inputs(root)
            with self.assertRaisesRegex(V3MapOverlayError, "receipt file hash is not"):
                build_local_v3_map_overlay_audit(inputs)
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                [
                    "layout.json",
                    "model.json",
                    "receipt.json",
                    "reconciliation.json",
                    "serving.sqlite",
                ],
            )


def _inputs(root: Path) -> V3MapOverlayInputs:
    # Focus these tests on fail-closed boundaries. The adapter never receives
    # an output path, so even malformed input cannot create an artifact.
    receipt = root / "receipt.json"
    model = root / "model.json"
    database = root / "serving.sqlite"
    reconciliation = root / "reconciliation.json"
    layout = root / "layout.json"
    model.write_text(
        json.dumps(
            {
                "revision": "public-graph-v2",
                "input_sha256": "1" * 64,
                "settings_sha256": "2" * 64,
                "output_sha256": "3" * 64,
            }
        )
    )
    with sqlite3.connect(database) as db:
        db.execute("pragma user_version = 12")
        db.execute("create table public_genre_names (source_genre_ref text not null)")
        db.execute("insert into public_genre_names values ('wikidata:genre:Q1')")
    # The receipt is intentionally malformed, so the adapter fails before
    # opening the model, database, reconciliation, or layout.
    receipt.write_text("{}")
    reconciliation.write_text("{}")
    layout.write_text(
        json.dumps(
            {
                "stable_seed_count": 6291,
                "coordinates": [],
                "unplaced": [{"seed_id": f"item-{index}"} for index in range(6291)],
                "output_sha256": "4" * 64,
            }
        )
    )
    return V3MapOverlayInputs(
        v3_receipt=receipt,
        v3_model=model,
        v3_serving_database=database,
        reconciliation=reconciliation,
        canonical_layout=layout,
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
