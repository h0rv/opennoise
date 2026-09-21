"""Test the deploy-only static Pages custody gate."""

from __future__ import annotations

import argparse
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.certify_static_pages import (
    _SEALED_DATABASE,
    _SEALED_DATABASE_SHA256,
    _SEALED_LAYOUT,
    _SEALED_LAYOUT_SHA256,
    _SEALED_OUTPUT,
    _verify_sealed_deploy_inputs,
)


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
