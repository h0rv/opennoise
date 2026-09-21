"""Guard the local merged-candidate CLI's intentionally narrow surface."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidSeedMapInputs,
    build_public_qid_seed_map,
    write_public_qid_seed_map,
)
from opennoise.checkpoints.sealed_qid_direct_bridge import (
    SealedQidDirectBridgeInputs,
    build_sealed_qid_direct_bridge,
)
from opennoise.deployment.public_direct_static_discovery import (
    build_sealed_qid_additive_static_discovery,
    sealed_qid_additive_static_discovery_json,
)
from scripts.export_merged_public_direct_discovery import main

_BASE = Path(
    "dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json"
)
_DATABASE = Path("data/public.sqlite")
_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
_PINNED_INPUTS = (_BASE, _DATABASE, _LAYOUT)


def _additive_bytes() -> bytes:
    with TemporaryDirectory() as temporary:
        qid_map_path = Path(temporary) / "qid-map.json"
        qid_map = build_public_qid_seed_map(
            PublicQidSeedMapInputs(
                public_database=_DATABASE,
                canonical_layout=_LAYOUT,
            )
        )
        write_public_qid_seed_map(qid_map, qid_map_path)
        bridge = build_sealed_qid_direct_bridge(
            SealedQidDirectBridgeInputs(
                public_qid_seed_map=qid_map_path,
                public_database=_DATABASE,
                base_static_discovery=_BASE,
            )
        )
        additive = build_sealed_qid_additive_static_discovery(
            database=_DATABASE,
            base_static_discovery=_BASE,
            bridge=bridge,
        )
        return sealed_qid_additive_static_discovery_json(additive)


class ExportMergedPublicDirectDiscoveryTests(unittest.TestCase):
    """The script creates a fresh local file but has no export or deployment path."""

    def test_script_uses_no_replace_receipt_writer_only(self) -> None:
        source = Path("scripts/export_merged_public_direct_discovery.py").read_text()
        self.assertIn("_write_fresh_candidate", source)
        self.assertIn("build_merged_public_direct_discovery_candidate", source)
        self.assertNotIn("semantic_pages", source)
        self.assertNotIn("wrangler", source)
        self.assertNotIn("dist/", source)
        self.assertNotIn("public_direct_production_bridge", source)

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "requires the pinned local public inputs",
    )
    def test_existing_output_is_not_replaced(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            additive = root / "additive.json"
            output = root / "merged.json"
            additive.write_bytes(_additive_bytes())
            arguments = [
                "export_merged_public_direct_discovery.py",
                "--base-static-discovery",
                str(_BASE),
                "--additive-sidecar",
                str(additive),
                "--output",
                str(output),
            ]
            with patch("sys.argv", arguments):
                self.assertEqual(main(), 0)
            original = output.read_bytes()
            with patch("sys.argv", arguments), self.assertRaises(FileExistsError):
                main()
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
