"""Test the deploy-only static Pages custody gate."""

from __future__ import annotations

import argparse
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from opennoise.common import sha256_hex
from opennoise.deployment.public_discovery_promotion import (
    PublicDiscoveryPromotionReceipt,
    public_discovery_promotion_sha256,
)
from scripts.certify_static_pages import (
    _SEALED_DATABASE,
    _SEALED_DATABASE_SHA256,
    _SEALED_LAYOUT,
    _SEALED_LAYOUT_SHA256,
    _SEALED_OUTPUT,
    _replay_public_discovery_v2_promotion,
    _verify_sealed_deploy_inputs,
)

if TYPE_CHECKING:
    from opennoise.ml.semantic_layout.contracts import SemanticLayoutArtifact


class SealedDeployTests(unittest.TestCase):
    """The deployment entry point must not accept locally selected inputs."""

    def _arguments(self, **changes: Path) -> argparse.Namespace:
        arguments = {
            "semantic_layout": _SEALED_LAYOUT,
            "discovery_database": _SEALED_DATABASE,
            "output": _SEALED_OUTPUT,
        }
        arguments.update(changes)
        return argparse.Namespace(**arguments)

    def test_accepts_only_hash_pinned_canonical_inputs(self) -> None:
        arguments = self._arguments()

        def pinned_hash(path: Path) -> tuple[str, int]:
            if path == arguments.semantic_layout:
                return _SEALED_LAYOUT_SHA256, 1
            return _SEALED_DATABASE_SHA256, 1

        with patch.dict(os.environ, {}, clear=True):
            _verify_sealed_deploy_inputs(arguments, file_hasher=pinned_hash)

    def test_rejects_environment_input_override_before_hashing(self) -> None:
        arguments = self._arguments()
        with (
            patch.dict(os.environ, {"OPENNOISE_PAGES_OUTPUT": "candidate"}, clear=True),
            self.assertRaisesRegex(RuntimeError, "environment overrides"),
        ):
            _verify_sealed_deploy_inputs(arguments)

    def test_rejects_noncanonical_output(self) -> None:
        arguments = self._arguments(output=Path("candidate"))
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "requires output"),
        ):
            _verify_sealed_deploy_inputs(arguments)

    def test_rejects_tampered_canonical_bytes(self) -> None:
        arguments = self._arguments()
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(RuntimeError, "semantic layout SHA-256"),
        ):
            _verify_sealed_deploy_inputs(arguments, file_hasher=lambda _path: ("0" * 64, 1))


class PublicDiscoveryV2ReplayTests(unittest.TestCase):
    """The optional receipt path rebuilds only from the sealed primary inputs."""

    def test_missing_receipt_fails_closed(self) -> None:
        with (
            patch(
                "scripts.certify_static_pages._PUBLIC_DISCOVERY_V2_PROMOTION_RECEIPT",
                Path("missing"),
            ),
            self.assertRaisesRegex(RuntimeError, "receipt is missing"),
        ):
            _replay_public_discovery_v2_promotion(
                semantic_layout=Path("layout"), database=Path("database"), artifact=_artifact()
            )

    def test_malformed_receipt_fails_closed(self) -> None:
        artifact = _artifact()
        with TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "promotion.json"
            receipt.write_text("not json", encoding="utf-8")
            with (
                patch(
                    "scripts.certify_static_pages._PUBLIC_DISCOVERY_V2_PROMOTION_RECEIPT", receipt
                ),
                self.assertRaisesRegex(RuntimeError, "promotion replay failed"),
            ):
                _replay_public_discovery_v2_promotion(
                    semantic_layout=Path("layout"), database=Path("database"), artifact=artifact
                )

    def test_receipt_directory_does_not_fall_back_to_v1(self) -> None:
        artifact = _artifact()
        with TemporaryDirectory() as temporary:
            receipt_directory = Path(temporary)
            with (
                patch(
                    "scripts.certify_static_pages._PUBLIC_DISCOVERY_V2_PROMOTION_RECEIPT",
                    receipt_directory,
                ),
                self.assertRaisesRegex(RuntimeError, "not a regular file"),
            ):
                _replay_public_discovery_v2_promotion(
                    semantic_layout=Path("layout"), database=Path("database"), artifact=artifact
                )

    def test_qid_map_pin_drift_fails_closed_before_writing_intermediate(self) -> None:
        base_bytes = b"rebuilt-v1"
        receipt = _promotion_receipt(base_sha256=sha256_hex(base_bytes))
        artifact = _artifact(receipt.input_pins.sealed_layout.logical_sha256)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "promotion.json"
            path.write_text(receipt.model_dump_json(), encoding="utf-8")
            wrong_qid_map = SimpleNamespace(output_sha256="9" * 64)
            with (
                patch("scripts.certify_static_pages._PUBLIC_DISCOVERY_V2_PROMOTION_RECEIPT", path),
                patch(
                    "scripts.certify_static_pages.sha256_file",
                    side_effect=[
                        (receipt.input_pins.sealed_layout.file_sha256, 1),
                        (receipt.input_pins.public_database_sha256, 1),
                    ],
                ),
                patch(
                    "scripts.certify_static_pages.static_discovery_v1_bytes_from_layout",
                    return_value=base_bytes,
                ),
                patch(
                    "scripts.certify_static_pages.build_public_qid_seed_map",
                    return_value=wrong_qid_map,
                ),
                patch("scripts.certify_static_pages.write_public_qid_seed_map") as write_qid_map,
                self.assertRaisesRegex(RuntimeError, "promotion replay failed"),
            ):
                _replay_public_discovery_v2_promotion(
                    semantic_layout=Path("layout"), database=Path("database"), artifact=artifact
                )
            write_qid_map.assert_not_called()

    def test_replays_only_sealed_inputs_and_checks_each_intermediate_pin(self) -> None:
        base_bytes = b"rebuilt-v1"
        receipt = _promotion_receipt(base_sha256=sha256_hex(base_bytes))
        artifact = _artifact(receipt.input_pins.sealed_layout.logical_sha256)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "promotion.json"
            path.write_text(receipt.model_dump_json(), encoding="utf-8")
            qid_map = SimpleNamespace(output_sha256=receipt.input_pins.public_qid_seed_map_sha256)
            bridge = SimpleNamespace(
                selection_sha256=receipt.input_pins.sealed_qid_direct_bridge_selection_sha256,
                output_sha256=receipt.input_pins.sealed_qid_direct_bridge_sha256,
            )
            sidecar = SimpleNamespace(
                output_sha256=receipt.input_pins.sealed_qid_additive_static_discovery_sha256
            )
            candidate = SimpleNamespace(
                output_sha256=receipt.input_pins.merged_public_direct_discovery_sha256
            )
            with (
                patch("scripts.certify_static_pages._PUBLIC_DISCOVERY_V2_PROMOTION_RECEIPT", path),
                patch(
                    "scripts.certify_static_pages.sha256_file",
                    side_effect=[
                        (receipt.input_pins.sealed_layout.file_sha256, 1),
                        (receipt.input_pins.public_database_sha256, 1),
                    ],
                ),
                patch(
                    "scripts.certify_static_pages.static_discovery_v1_bytes_from_layout",
                    return_value=base_bytes,
                ) as rebuild_v1,
                patch(
                    "scripts.certify_static_pages.build_public_qid_seed_map", return_value=qid_map
                ),
                patch("scripts.certify_static_pages.write_public_qid_seed_map") as write_qid_map,
                patch(
                    "scripts.certify_static_pages.build_sealed_qid_direct_bridge",
                    return_value=bridge,
                ),
                patch(
                    "scripts.certify_static_pages.build_sealed_qid_additive_static_discovery",
                    return_value=sidecar,
                ),
                patch(
                    "scripts.certify_static_pages.build_merged_public_direct_discovery_candidate",
                    return_value=candidate,
                ),
            ):
                self.assertEqual(
                    _replay_public_discovery_v2_promotion(
                        semantic_layout=Path("layout"), database=Path("database"), artifact=artifact
                    ),
                    (candidate, receipt),
                )
            rebuild_v1.assert_called_once_with(
                semantic_layout_path=Path("layout"), database=Path("database")
            )
            write_qid_map.assert_called_once()


def _promotion_receipt(*, base_sha256: str) -> PublicDiscoveryPromotionReceipt:
    draft = PublicDiscoveryPromotionReceipt.model_validate(
        {
            "input_pins": {
                "sealed_layout": {"file_sha256": "a" * 64, "logical_sha256": "b" * 64},
                "public_database_sha256": "c" * 64,
                "base_static_discovery_sha256": base_sha256,
                "public_qid_seed_map_sha256": "d" * 64,
                "sealed_qid_direct_bridge_selection_sha256": "e" * 64,
                "sealed_qid_direct_bridge_sha256": "f" * 64,
                "sealed_qid_additive_static_discovery_sha256": "1" * 64,
                "merged_public_direct_discovery_sha256": "2" * 64,
                "semantic_atlas_sha256": "3" * 64,
            },
            "public_payload": {
                "logical_sha256": "4" * 64,
                "file_sha256": "5" * 64,
                "byte_count": 1,
            },
            "output_sha256": "6" * 64,
        }
    )
    return draft.model_copy(update={"output_sha256": public_discovery_promotion_sha256(draft)})


def _artifact(output_sha256: str = "b" * 64) -> SemanticLayoutArtifact:
    return cast("SemanticLayoutArtifact", SimpleNamespace(output_sha256=output_sha256))
