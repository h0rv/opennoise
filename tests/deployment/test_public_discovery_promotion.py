"""Hermetic contracts for the future public static-discovery v2 receipt."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidSeedMapInputs,
    build_public_qid_seed_map,
    write_public_qid_seed_map,
)
from opennoise.checkpoints.sealed_qid_direct_bridge import (
    SealedQidDirectBridgeInputs,
    build_sealed_qid_direct_bridge,
)
from opennoise.common import sha256_hex
from opennoise.deployment.merged_public_direct_discovery import (
    build_merged_public_direct_discovery_candidate,
)
from opennoise.deployment.public_direct_static_discovery import (
    build_sealed_qid_additive_static_discovery,
)
from opennoise.deployment.public_discovery_promotion import (
    PublicDiscoveryPromotionError,
    PublicDiscoveryPromotionReceipt,
    public_discovery_promotion_sha256,
    verify_public_discovery_promotion,
)
from opennoise.deployment.public_static_discovery_v2 import (
    adapt_public_static_discovery_v2,
    public_static_discovery_v2_json,
)
from tests._pinned_v1_discovery import pinned_v1_discovery_path

_LAYOUT_FILE_SHA256 = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_LAYOUT_LOGICAL_SHA256 = "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"
_DATABASE_SHA256 = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_BASE_SHA256 = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_QID_MAP_SHA256 = "dd5cf7cf33898a76c1e85e95351e25e7303933f4524e2776097c20fd0d73a449"
_BRIDGE_SELECTION_SHA256 = "a6e24b756236abf94416c129d442dd7b7fd5592eb27e2fe742c4c7ece30c1b4a"
_BRIDGE_SHA256 = "c488223b34afcd59596072d4623e3190cfff1941cfdccb4da3e286e7ccebef5b"
_SIDECAR_SHA256 = "dfc4c74915ddc72df831a350d3fd420c9b14ff24c1f99e3758b6cdbb8257da73"
_MERGED_SHA256 = "9ee2a464de74e0b681ea347163fda94afa6eb28e3189a4fa4e6d0ee3d708232b"
_ATLAS_SHA256 = "730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac"
_PAYLOAD_LOGICAL_SHA256 = "c117658577413e8047503486077e3b50ebe31056340a9025897fa8645c716c22"
_PAYLOAD_FILE_SHA256 = "4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c"
_PAYLOAD_BYTE_COUNT = 2_865_604
_BASE = pinned_v1_discovery_path()
_ATLAS = Path(
    "dist/assets/semantic-atlas.730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac.json"
)
_DATABASE = Path("data/public.sqlite")
_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
_SEALED_INPUTS = (_BASE, _ATLAS, _DATABASE, _LAYOUT)


def _receipt(
    *, payload_file_sha256: str | None = None, payload_byte_count: int = _PAYLOAD_BYTE_COUNT
) -> PublicDiscoveryPromotionReceipt:
    draft = PublicDiscoveryPromotionReceipt.model_validate(
        {
            "input_pins": {
                "sealed_layout": {
                    "file_sha256": _LAYOUT_FILE_SHA256,
                    "logical_sha256": _LAYOUT_LOGICAL_SHA256,
                },
                "public_database_sha256": _DATABASE_SHA256,
                "base_static_discovery_sha256": _BASE_SHA256,
                "public_qid_seed_map_sha256": _QID_MAP_SHA256,
                "sealed_qid_direct_bridge_selection_sha256": _BRIDGE_SELECTION_SHA256,
                "sealed_qid_direct_bridge_sha256": _BRIDGE_SHA256,
                "sealed_qid_additive_static_discovery_sha256": _SIDECAR_SHA256,
                "merged_public_direct_discovery_sha256": _MERGED_SHA256,
                "semantic_atlas_sha256": _ATLAS_SHA256,
            },
            "public_payload": {
                "logical_sha256": _PAYLOAD_LOGICAL_SHA256,
                "file_sha256": payload_file_sha256 or _PAYLOAD_FILE_SHA256,
                "byte_count": payload_byte_count,
            },
            "output_sha256": _PAYLOAD_LOGICAL_SHA256,
        }
    )
    return draft.model_copy(update={"output_sha256": public_discovery_promotion_sha256(draft)})


class PublicDiscoveryPromotionTests(unittest.TestCase):
    """Receipt parsing is self-hashed and verification consumes v2 bytes once."""

    def test_receipt_replays_its_self_hash_and_fixed_coverage(self) -> None:
        receipt = _receipt()
        self.assertEqual(receipt.output_sha256, public_discovery_promotion_sha256(receipt))
        self.assertEqual(receipt.coverage.genre_count, 344)
        self.assertEqual(receipt.coverage.qid_position_genre_count, 84)

    def test_receipt_rejects_placeholder_pin(self) -> None:
        values = _receipt().model_dump(mode="json")
        values["input_pins"]["public_database_sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            PublicDiscoveryPromotionReceipt.model_validate(values)

    def test_receipt_rejects_unreviewed_field(self) -> None:
        values = _receipt().model_dump(mode="json")
        values["unreviewed_input"] = "candidate-path"
        with self.assertRaises(ValidationError):
            PublicDiscoveryPromotionReceipt.model_validate(values)

    def test_verifier_rejects_file_hash_before_parsing_payload(self) -> None:
        receipt = _receipt()
        with (
            patch(
                "opennoise.deployment.public_discovery_promotion.PublicStaticDiscoveryV2Payload.model_validate_json"
            ) as parse,
            self.assertRaisesRegex(PublicDiscoveryPromotionError, "file SHA-256"),
        ):
            verify_public_discovery_promotion(receipt, b"not-the-receipt-file")
        parse.assert_not_called()

    def test_verifier_parses_once_then_replays_the_bound_chain(self) -> None:
        payload_bytes = b"payload"
        file_receipt = _receipt(
            payload_file_sha256=sha256_hex(payload_bytes), payload_byte_count=len(payload_bytes)
        )
        genres = tuple(
            SimpleNamespace(binding="exact_casefolded_label", node_id=f"item{index}")
            for index in range(1, 261)
        ) + tuple(
            SimpleNamespace(binding="one_to_one_qid_position_binding", node_id=f"item{index}")
            for index in range(261, 345)
        )
        payload = SimpleNamespace(
            revision="static-direct-discovery-v2",
            output_sha256=file_receipt.public_payload.logical_sha256,
            genres=genres,
            artists=tuple(SimpleNamespace() for _ in range(1126)),
            coverage=SimpleNamespace(bound_direct_observation_count=3859),
            input_chain=SimpleNamespace(
                public_database_sha256=file_receipt.input_pins.public_database_sha256,
                base_static_discovery_sha256=file_receipt.input_pins.base_static_discovery_sha256,
                sealed_qid_additive_static_discovery_sha256=(
                    file_receipt.input_pins.sealed_qid_additive_static_discovery_sha256
                ),
                sealed_qid_direct_bridge_sha256=(
                    file_receipt.input_pins.sealed_qid_direct_bridge_sha256
                ),
                merged_public_direct_discovery_sha256=(
                    file_receipt.input_pins.merged_public_direct_discovery_sha256
                ),
                semantic_atlas_sha256=file_receipt.input_pins.semantic_atlas_sha256,
            ),
            source=SimpleNamespace(database_sha256=file_receipt.input_pins.public_database_sha256),
        )
        with (
            patch(
                "opennoise.deployment.public_discovery_promotion.PublicStaticDiscoveryV2Payload.model_validate_json",
                return_value=payload,
            ) as parse,
            patch(
                "opennoise.deployment.public_discovery_promotion.verify_public_static_discovery_v2_payload"
            ) as verify_payload,
            patch(
                "opennoise.deployment.public_discovery_promotion.public_static_discovery_v2_sha256",
                return_value=file_receipt.public_payload.logical_sha256,
            ),
        ):
            self.assertIs(verify_public_discovery_promotion(file_receipt, payload_bytes), payload)
        parse.assert_called_once_with(payload_bytes)
        verify_payload.assert_called_once()

    @unittest.skipUnless(
        all(path.is_file() for path in _SEALED_INPUTS),
        "requires the sealed local public inputs",
    )
    def test_pinned_chain_replays_the_recorded_public_v2_bytes(self) -> None:
        """Exercise the receipt against real rebuilt bytes, not a tracked receipt file."""
        with TemporaryDirectory() as temporary:
            qid_map_path = Path(temporary) / "qid-map.json"
            qid_map = build_public_qid_seed_map(
                PublicQidSeedMapInputs(public_database=_DATABASE, canonical_layout=_LAYOUT)
            )
            write_public_qid_seed_map(qid_map, qid_map_path)
            bridge = build_sealed_qid_direct_bridge(
                SealedQidDirectBridgeInputs(
                    public_qid_seed_map=qid_map_path,
                    public_database=_DATABASE,
                    base_static_discovery=_BASE,
                )
            )
            sidecar = build_sealed_qid_additive_static_discovery(
                database=_DATABASE, base_static_discovery=_BASE, bridge=bridge
            )
            candidate = build_merged_public_direct_discovery_candidate(
                base_static_discovery=_BASE, additive=sidecar
            )
            payload = adapt_public_static_discovery_v2(candidate=candidate, semantic_atlas=_ATLAS)
        payload_bytes = public_static_discovery_v2_json(payload)
        self.assertEqual(payload.output_sha256, _PAYLOAD_LOGICAL_SHA256)
        self.assertEqual(sha256_hex(payload_bytes), _PAYLOAD_FILE_SHA256)
        self.assertEqual(len(payload_bytes), _PAYLOAD_BYTE_COUNT)
        receipt = _receipt(
            payload_file_sha256=sha256_hex(payload_bytes), payload_byte_count=len(payload_bytes)
        )
        self.assertEqual(verify_public_discovery_promotion(receipt, payload_bytes), payload)


if __name__ == "__main__":
    unittest.main()
