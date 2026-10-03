"""Recording view fixtures are synthetic metadata, never musical judgments."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch
from uuid import UUID

import zstandard

from opennoise.serving.metadata import recording_catalog_export as catalog
from opennoise.serving.metadata.recovered_recording_catalog import page_binding, project_page
from opennoise.serving.metadata.selected_recording_catalog import canonical_json

ARTIST = "00000000-0000-0000-0000-000000000001"
ZERO = "00000000-0000-0000-0000-000000000002"
CHECK_MEMORY = catalog._check_memory  # noqa: SLF001 - exercise the production resource guard independently.


class CatalogExportTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        # Metadata fixtures run in the shared test harness, not a bounded build process.
        guard = patch.object(catalog, "_check_memory", return_value=1)
        guard.start()
        self.addCleanup(guard.stop)

    def test_production_memory_ceiling_is_not_raised(self) -> None:
        with (
            patch.object(catalog, "_peak_bytes", return_value=40_000_000),
            self.assertRaises(ValueError),
        ):
            CHECK_MEMORY()

    def fixture(self, root: Path) -> Path:
        source = root / "source"
        source.mkdir()
        (source / "custody").mkdir()
        (source / "selection.json").write_bytes(
            canonical_json(
                {
                    "roster_sha256": "synthetic",
                    "artists": [
                        {"artist_mbid": ARTIST, "name": "Fixture"},
                        {"artist_mbid": ZERO, "name": "Empty fixture"},
                    ],
                }
            )
        )
        (source / "pre-http-freeze.json").write_text("{}")
        summaries = [
            {
                "artist_mbid": identity,
                "returned_nonprobe_rows": count,
                "baseline_advertised_count": count,
                "unique_exact_credited_recordings": count,
                "status": "observed_window_complete",
                "atomic_snapshot": False,
                "musical_relevance": "not_assessed",
            }
            for identity, count in [(ARTIST, 501), (ZERO, 0)]
        ]
        (source / "artists.json").write_bytes(canonical_json(summaries))
        with (source / "request-ledger.jsonl").open("wb") as ledger:
            for sequence, offset in enumerate(range(0, 501, 100)):
                request = {
                    "artist_mbid": ARTIST,
                    "baseline_count": 501,
                    "offset": offset,
                    "stage": "initial" if offset == 0 else "continuation",
                    "url": "https://musicbrainz.org/ws/2/recording?fixture",
                }
                rows = [
                    {
                        "id": str(UUID(int=100 + row)),
                        "title": f"Fixture {row}",
                        "length": 1234,
                        "artist-credit": [{"artist": {"id": ARTIST, "name": "Fixture"}}],
                    }
                    for row in range(offset, min(offset + 100, 501))
                ]
                body = canonical_json(
                    {"recording-count": 501, "recording-offset": offset, "recordings": rows}
                )
                compressed = zstandard.ZstdCompressor().compress(body)
                relative = f"custody/{sequence}.zst"
                (source / relative).write_bytes(compressed)
                capture = {
                    "request": request,
                    "outcome": "native_core_page",
                    "fetched_at": "2026-01-01T00:00:00+00:00",
                    "custody": {
                        "path": relative,
                        "decoded_bytes": len(body),
                        "decoded_sha256": hashlib.sha256(body).hexdigest(),
                    },
                    "projection": page_binding(project_page(body, request)),
                }
                ledger.write(
                    canonical_json({"event": "outcome", "sequence": sequence, "capture": capture})
                    + b"\n"
                )
        return source

    def reseal(self, output: Path) -> None:
        receipt = json.loads((output / "receipt.json").read_bytes())
        receipt["files"] = catalog._inventory(output)  # noqa: SLF001 - attacker rehashes every output, not just a byte mutation.
        (output / "receipt.json").write_bytes(canonical_json(receipt))

    def test_complete_pagination_zero_count_and_native_row_replay(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(catalog, "verify_source", return_value={"verified": True}),
        ):
            root = Path(temporary)
            source = self.fixture(root)
            output = root / "view"
            result = catalog.export_catalog(source, root, output)
            self.assertEqual(result["rows"], 501)
            index = json.loads((output / "index.json").read_bytes())
            self.assertEqual([p["count"] for p in index["artists"][0]["pages"]], [500, 1])
            self.assertEqual(index["artists"][1]["pages"], [])
            self.assertEqual(catalog.replay_catalog(source, root, output)["rows"], 501)
            with self.assertRaises(FileExistsError):
                catalog.export_catalog(source, root, output)

    def test_self_rehashed_fact_and_scope_changes_are_rejected(self) -> None:  # noqa: C901 - eleven distinct adversarial protocol mutations.
        for mutation in [
            "title",
            "scope",
            "denominator",
            "name",
            "source",
            "license",
            "extra",
            "drop_zero",
            "page_count",
            "page_identity",
            "implementation",
        ]:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary,
                patch.object(catalog, "verify_source", return_value={"verified": True}),
            ):
                root = Path(temporary)
                source = self.fixture(root)
                output = root / "view"
                catalog.export_catalog(source, root, output)
                relative = (
                    f"artists/{ARTIST}/0000.json"
                    if mutation in {"title", "source"}
                    else f"artists/{ARTIST}/0001.json"
                    if mutation == "page_identity"
                    else "index.json"
                )
                path = output / relative
                value = json.loads(path.read_bytes())
                if mutation == "title":
                    value["recordings"][0]["title"] = "Different metadata"
                elif mutation == "source":
                    value["sources"]["0"]["page_sha256"] = "0" * 64
                elif mutation == "scope":
                    value["scope"]["representative_judgments"] = 1
                elif mutation == "name":
                    value["artists"][0]["name"] = "Name-based merge"
                elif mutation == "denominator":
                    value["counts"]["baseline_per_artist_count_sum"] = 500
                elif mutation == "license":
                    value["license"] = "CC-BY-4.0"
                elif mutation == "extra":
                    (output / "unreferenced.json").write_text("{}")
                elif mutation == "drop_zero":
                    value["artists"].pop()
                elif mutation == "page_count":
                    value["artists"][0]["pages"][0]["count"] = 499
                elif mutation == "page_identity":
                    value["page"] = True
                else:
                    (output / "implementation.py").write_text("# Different implementation\n")
                path.write_bytes(canonical_json(value))
                self.reseal(output)
                with self.assertRaises(ValueError):
                    catalog.replay_catalog(source, root, output)

    def test_native_identity_mismatch_rejected_without_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self.fixture(Path(temporary))
            body_path = source / "custody/0.zst"
            body = zstandard.ZstdDecompressor().decompress(body_path.read_bytes())
            payload = json.loads(body)
            payload["recordings"][0]["artist-credit"][0]["artist"]["id"] = ZERO
            altered = canonical_json(payload)
            body_path.write_bytes(zstandard.ZstdCompressor().compress(altered))
            ledger_path = source / "request-ledger.jsonl"
            events = [json.loads(line) for line in ledger_path.read_bytes().splitlines()]
            changed = events[0]["capture"]
            changed["custody"]["decoded_bytes"] = len(altered)
            changed["custody"]["decoded_sha256"] = hashlib.sha256(altered).hexdigest()
            changed["projection"] = page_binding(project_page(altered, changed["request"]))
            ledger_path.write_bytes(b"".join(canonical_json(event) + b"\n" for event in events))
            with self.assertRaises(ValueError):
                list(catalog._observations(source))  # noqa: SLF001 - direct native-credit guard, without mocked fixture source admission.


if __name__ == "__main__":
    unittest.main()
