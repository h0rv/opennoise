"""Coverage for the exclusive, source-custody proper-genre anchor projection."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_proper_genre_anchor_projection import (
    DirectProperGenreAnchorProjectionError,
    build_direct_proper_genre_anchor_projection,
    verify_direct_proper_genre_anchor_projection,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    build_portable_direct_proper_genre_custody,
)
from scripts.build_musicbrainz_direct_proper_genre_anchor_projection import _prepare_output

_A = "11111111-1111-4111-8111-111111111111"
_B = "22222222-2222-4222-8222-222222222222"
_C = "33333333-3333-4333-8333-333333333333"
_GENRE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class DirectProperGenreAnchorProjectionTests(unittest.TestCase):
    def _inputs(self, root: Path) -> tuple[Path, Path, Path, Path]:
        source = root / "source.json"
        reconciliation = root / "reconciliation.json"
        layout = root / "layout.json"
        receipt = root / "receipt.json"
        claims = [
            ("item2945", _A),
            ("item0", _A),
            ("item2946", _B),
            ("item1", _B),
            ("item2", _B),
            ("item2947", _C),
        ]
        source.write_text(
            json.dumps(
                {
                    "evidence": [
                        {
                            "seed_source_item_id": seed,
                            "seed_name": seed,
                            "artist_id": artist,
                            "facet": "genre",
                            "match_kind": "exact",
                            "target_identity": _GENRE,
                            "target_name": seed,
                            "target_namespace": "musicbrainz_genre_id",
                            "source_record_id": f"musicbrainz:artist:{artist}",
                            "source_record_sha256": hashlib.sha256(seed.encode()).hexdigest(),
                            "evidence_ref": f"source:{seed}",
                        }
                        for seed, artist in claims
                    ],
                    "output_sha256": "b" * 64,
                }
            )
        )
        reconciliation.write_text(
            json.dumps(
                {
                    "dispositions": [
                        {
                            "source_item_id": seed,
                            "musicbrainz_identities": [
                                {"namespace": "musicbrainz_genre_id", "identifier": _GENRE}
                            ],
                        }
                        for seed, _ in claims
                    ],
                    "output_sha256": "c" * 64,
                }
            )
        )
        layout.write_text(
            json.dumps(
                {
                    "coordinates": [
                        {"seed_id": f"item{index}", "x": index, "y": -index}
                        for index in range(2945)
                    ],
                    "unplaced": [
                        {"seed_id": f"item{index}", "reason": "fixture"}
                        for index in range(2945, 6291)
                    ],
                    "output_sha256": "d" * 64,
                }
            )
        )
        store = root / "objects"
        build_portable_direct_proper_genre_custody(
            seed_target=source,
            seed_target_byte_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            seed_target_output_sha256="b" * 64,
            reconciliation=reconciliation,
            object_store=store,
            receipt_output=receipt,
        )
        return receipt, store, layout, source

    def test_projects_only_one_exclusive_positioned_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt, store, layout, _ = self._inputs(Path(temporary))
            result = build_direct_proper_genre_anchor_projection(
                custody_receipt_path=receipt, custody_object_store=store, layout_path=layout
            )
            self.assertEqual(result.proper_genre_frontier_seed_count, 3)
            self.assertEqual(
                [(item.unplaced_seed_id, item.positioned_seed_id) for item in result.proposals],
                [("item2945", "item0")],
            )
            self.assertEqual(
                [(item.unplaced_seed_id, item.reason) for item in result.abstentions],
                [
                    ("item2946", "multiple_positioned_anchor_seeds"),
                    ("item2947", "no_positioned_artist_overlap"),
                ],
            )
            self.assertFalse(result.layout_coordinates_read)
            self.assertFalse(result.public_export_authorized)
            verify_direct_proper_genre_anchor_projection(result)

    def test_rejects_a_mutated_projection_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt, store, layout, _ = self._inputs(Path(temporary))
            result = build_direct_proper_genre_anchor_projection(
                custody_receipt_path=receipt, custody_object_store=store, layout_path=layout
            )
            with self.assertRaises(DirectProperGenreAnchorProjectionError):
                verify_direct_proper_genre_anchor_projection(
                    result.model_copy(update={"output_sha256": "0" * 64})
                )

    def test_cli_output_refuses_public_or_existing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public_path = root / "dist" / "review.json"
            with self.assertRaisesRegex(ValueError, "local .cache"):
                _prepare_output(public_path, cache_root=root / ".cache")
            cache = root / ".cache"
            cache.mkdir()
            existing = cache / "existing.json"
            existing.write_text("already here")
            with self.assertRaises(FileExistsError):
                _prepare_output(existing, cache_root=cache)
