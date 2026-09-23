from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opennoise.checkpoints.names_only_construction_boundary import (
    NamesOnlyConstructionBoundaryError,
    NamesOnlyConstructionBoundaryProof,
    names_only_construction_boundary_sha256,
    verify_name_projection_records,
    verify_names_only_construction_boundary_proof,
)
from opennoise.taxonomy.seeds.universe import load_seed_input


def _proof() -> NamesOnlyConstructionBoundaryProof:
    base = NamesOnlyConstructionBoundaryProof(
        source_content_sha256="a" * 64,
        name_projection_sha256="b" * 64,
        peer_index_sha256="c" * 64,
        semantic_layout_sha256="d" * 64,
        semantic_layout_logical_sha256="e" * 64,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": names_only_construction_boundary_sha256(base)})


class NamesOnlyConstructionBoundaryProofTests(unittest.TestCase):
    def test_proof_replays(self) -> None:
        verify_names_only_construction_boundary_proof(_proof())

    def test_changed_proof_does_not_replay(self) -> None:
        proof = _proof().model_copy(update={"peer_index_sha256": "f" * 64})
        with self.assertRaises(NamesOnlyConstructionBoundaryError):
            verify_names_only_construction_boundary_proof(proof)

    def test_historical_non_name_changes_cannot_change_the_verified_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "plain.json"
            altered = root / "altered.json"
            self._write_seed(plain, historical_value="first")
            self._write_seed(altered, historical_value="second")
            first = load_seed_input(plain)
            second = load_seed_input(altered)
        self.assertEqual(first, second)
        peer_rows = {
            item.source_item_id: (item.source_external_id, item.name) for item in first.names
        }
        layout_rows = {item.source_item_id: ("", item.name) for item in first.names}
        verify_name_projection_records(first, peer_rows, layout_rows)
        layout_rows["item1"] = ("", "changed name")
        with self.assertRaises(NamesOnlyConstructionBoundaryError):
            verify_name_projection_records(first, peer_rows, layout_rows)

    def _write_seed(self, path: Path, *, historical_value: str) -> None:
        document = {
            "artifact": {
                "source_id": "enao_quint_legacy_map_2025",
                "content_sha256": "a" * 64,
            },
            "genres": [
                {
                    "source_item_id": f"item{index}",
                    "external_id": f"enao-legacy:item{index}",
                    "name": f"Genre {index}",
                    "coordinate": {"x": historical_value, "y": index},
                    "artist_memberships": [historical_value],
                    "historical_neighbors": [f"genre:{historical_value}"],
                    "rank": index,
                    "sample": {"artist": historical_value},
                }
                for index in range(1, 6_292)
            ],
        }
        path.write_text(json.dumps(document), encoding="utf-8")
