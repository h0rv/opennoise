"""Reject unsafe artist projections and keep catalog promotion independent."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.pipeline import artist_network as network

A = "00000000-0000-4000-8000-000000000001"
B = "00000000-0000-4000-8000-000000000002"


class ArtistNetworkContracts(unittest.TestCase):
    def test_projection_rejects_private_fields_and_invalid_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / network.SNAPSHOT
            path.parent.mkdir(parents=True)
            valid = {
                "revision": "fixture",
                "artists": [{"id": A, "name": "Alpha"}, {"id": B, "name": "Beta"}],
                "pairs": [[A, B, 20]],
                "layouts": {},
                "source": {},
            }
            contract = {"counts": {"artists": 2, "observed_undirected_pairs": 1}}
            path.write_bytes(gzip.compress(json.dumps(valid).encode()))
            self.assertEqual(network.read_snapshot(root, contract), valid)
            for key, value in [
                ("lyrics", "private"),
                ("listens", []),
                ("pairs", [[A, A, 20]]),
                ("artists", [{"id": A, "name": "Alpha"}, {"id": A, "name": "Duplicate"}]),
            ]:
                with self.subTest(key=key):
                    changed = copy.deepcopy(valid)
                    changed[key] = value
                    path.write_bytes(gzip.compress(json.dumps(changed).encode()))
                    with self.assertRaises(ValueError):
                        network.read_snapshot(root, contract)

    def test_missing_or_modified_source_never_builds(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / network.CONTRACT
            path.parent.mkdir(parents=True)
            body = b'{"snapshot_sha256":"not-present","snapshot_bytes":0}'
            path.write_bytes(body)
            with patch.object(network, "CONTRACT_SHA256", hashlib.sha256(body).hexdigest()):
                with self.assertRaisesRegex(ValueError, "source differs"):
                    network.inputs(root)
                path.write_bytes(body + b" ")
                with self.assertRaisesRegex(ValueError, "source differs"):
                    network.inputs(root)

    def test_layout_rejects_unknown_repeated_and_nonfinite_points(self) -> None:
        point = {"id": A, "x": 100, "y": 100, "size": 16, "width": 100}
        network.validate_layout([point], {A})
        for rows in [
            [point, point],
            [{**point, "id": B}],
            [{**point, "x": float("nan")}],
            [{**point, "size": 1}],
        ]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                network.validate_layout(rows, {A})

    def test_secondary_promotion_binds_its_json_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = {"artist-network/catalog.json": {"sha256": "example", "bytes": 10}}
            digest = hashlib.sha256(
                (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
            ).hexdigest()
            approval = {"counts": {"artists": 2}, "data_files": 1, "data_inventory_sha256": digest}
            path = root / network.PROMOTION
            path.parent.mkdir(parents=True)
            body = json.dumps(approval).encode()
            path.write_bytes(body)
            manifest = {"counts": {"artists": 2}, "input_contract_sha256": network.CONTRACT_SHA256}
            with patch.object(network, "PROMOTION_SHA256", hashlib.sha256(body).hexdigest()):
                network.authorize(root, manifest, data)
                with self.assertRaisesRegex(ValueError, "differs"):
                    network.authorize(root, manifest, {**data, "artist-network/extra.json": {}})
