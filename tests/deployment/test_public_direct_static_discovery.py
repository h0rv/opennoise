"""Contracts for the local sealed-QID additive discovery sidecar."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, override

from pydantic import ValidationError

from opennoise.checkpoints.sealed_qid_direct_bridge import (
    BridgeEvidence,
    SealedQidDirectBridge,
    SealedQidDirectCoverage,
    SealedQidDirectMembership,
)
from opennoise.deployment.public_direct_static_discovery import (
    AdditiveCoverage,
    PublicDirectStaticDiscoveryExportError,
    _additions,
    _Observation,
    build_sealed_qid_additive_static_discovery,
)
from opennoise.deployment.static_discovery import (
    StaticDiscoveryGenrePayload,
    StaticDiscoveryPayload,
)
from tests._pinned_v1_discovery import pinned_v1_discovery_path

_PINNED_INPUTS = (
    Path("data/public.sqlite"),
    Path(".cache/semantic-map-layout-v3/artifact.json"),
    pinned_v1_discovery_path(),
)
_PINNED_INPUTS_AVAILABLE = all(path.is_file() for path in _PINNED_INPUTS)


class PublicDirectStaticDiscoveryTests(unittest.TestCase):
    """The sidecar is QID-bound and preserves the sealed base boundary."""

    _temporary: ClassVar[tempfile.TemporaryDirectory[str] | None] = None
    _bridge: ClassVar[SealedQidDirectBridge]
    _bridge_path: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        """Build the sealed receipts once for the pinned replay cases."""
        if not _PINNED_INPUTS_AVAILABLE:
            return
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        qid_map = root / "qid-map.json"
        bridge = root / "bridge.json"
        subprocess.run(  # noqa: S603 - fixed local Python and repository scripts.
            [sys.executable, "scripts/build_public_qid_seed_map.py", "--output", str(qid_map)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(  # noqa: S603 - fixed local Python and repository scripts.
            [
                sys.executable,
                "scripts/build_sealed_qid_direct_bridge.py",
                "--public-qid-seed-map",
                str(qid_map),
                "--base-static-discovery",
                str(pinned_v1_discovery_path()),
                "--output",
                str(bridge),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        cls._bridge = SealedQidDirectBridge.model_validate_json(bridge.read_bytes())
        cls._bridge_path = bridge

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        """Remove temporary pinned receipts."""
        if cls._temporary is not None:
            cls._temporary.cleanup()

    def test_coverage_rejects_count_drift(self) -> None:
        with self.assertRaisesRegex(ValidationError, "coverage drifted"):
            AdditiveCoverage(
                added_direct_observation_count=959,
                added_membership_count=861,
                added_genre_count=84,
            )

    def test_hermetic_addition_keeps_qid_binding_and_rejects_conflict(self) -> None:
        membership = SealedQidDirectMembership(
            catalog_genre_id=9,
            genre_qid="Q9",
            seed_id="item9",
            artist_catalog_id=7,
            artist_name="Artist",
            artist_musicbrainz_id="12345678-1234-1234-1234-123456789abc",
            artist_wikidata_id="Q7",
            evidence=(
                BridgeEvidence(
                    evidence_id=3,
                    source_key="wikidata",
                    source_record_id="Qartist",
                    source_name="Wikidata",
                    policy_key="cc0",
                    policy_version=1,
                    provenance_id=2,
                ),
            ),
        )
        bridge = SealedQidDirectBridge(
            public_qid_seed_map_sha256="1" * 64,
            public_database_sha256="2" * 64,
            base_static_discovery_sha256="3" * 64,
            selection_sha256="4" * 64,
            memberships=(membership,),
            coverage=SealedQidDirectCoverage(
                positioned_genre_count=1,
                grouped_membership_count=1,
                direct_observation_count=1,
                artist_count=1,
                net_new_artist_count=1,
            ),
            output_sha256="5" * 64,
        )
        base = StaticDiscoveryPayload(
            revision="static-direct-discovery-v1",
            availability="ready",
            genres=(
                StaticDiscoveryGenrePayload(
                    node_id="item1",
                    catalog_genre_id=1,
                    catalog_genre_name="Base",
                    binding="exact_casefolded_label",
                    artist_ids=("artist:1",),
                ),
            ),
        )
        observation = _Observation(3, 7, "Artist", 9, "Added", "wikidata", "Qartist", 2)
        genres, artists = _additions(bridge, {3: observation}, base)
        self.assertEqual(genres[0].genre_qid, "Q9")
        self.assertEqual(artists[0].artist_id, "artist:7")
        with self.assertRaisesRegex(PublicDirectStaticDiscoveryExportError, "conflicts"):
            _additions(bridge, {3: replace(observation, source_key="forged")}, base)

    def test_sidecar_does_not_import_the_retired_bridge(self) -> None:
        source = Path("src/opennoise/deployment/public_direct_static_discovery.py").read_text()
        self.assertIn("sealed_qid_direct_bridge", source)
        self.assertNotIn("public_direct_production_bridge", source)
        self.assertNotIn("seed-reconciliation", source)

    @unittest.skipUnless(_PINNED_INPUTS_AVAILABLE, "requires pinned local public inputs")
    def test_real_pinned_replay_and_tampered_bridge_fail_closed(self) -> None:
        payload = build_sealed_qid_additive_static_discovery(
            database=Path("data/public.sqlite"),
            base_static_discovery=pinned_v1_discovery_path(),
            bridge=self._bridge,
        )
        self.assertEqual(
            payload.output_sha256,
            "dfc4c74915ddc72df831a350d3fd420c9b14ff24c1f99e3758b6cdbb8257da73",
        )
        self.assertEqual((len(payload.base.genres), len(payload.genres)), (260, 84))
        self.assertEqual(sum(len(item.memberships) for item in payload.artists), 862)
        with self.assertRaisesRegex(
            PublicDirectStaticDiscoveryExportError, "selection or self-hash"
        ):
            build_sealed_qid_additive_static_discovery(
                database=Path("data/public.sqlite"),
                base_static_discovery=pinned_v1_discovery_path(),
                bridge=self._bridge.model_copy(update={"output_sha256": "0" * 64}),
            )

    @unittest.skipUnless(_PINNED_INPUTS_AVAILABLE, "requires pinned local public inputs")
    def test_cli_refuses_existing_output(self) -> None:
        temporary = self._temporary
        if temporary is None:
            raise RuntimeError("pinned replay fixture was not initialized")
        output = Path(temporary.name) / "existing-sidecar.json"
        output.write_bytes(b"original\n")
        result = subprocess.run(  # noqa: S603 - fixed local Python and repository CLI.
            [
                sys.executable,
                "scripts/export_public_direct_additive_static_discovery.py",
                "--public-database",
                "data/public.sqlite",
                "--base-static-discovery",
                str(pinned_v1_discovery_path()),
                "--bridge-receipt",
                str(self._bridge_path),
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b"original\n")


if __name__ == "__main__":
    unittest.main()
