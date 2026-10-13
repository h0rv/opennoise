"""Synthetic v3 policy and independent numerical replay; no authentic-audio claims."""

# ruff: noqa: SLF001, PLR2004 -- explicit independent replay and synthetic fixture identities.
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.common import canonical_json
from opennoise.ml import fma_playable_neighbors as shared
from opennoise.ml import fma_reconstructed_neighbors as m


class ReconstructedNeighborsTests(unittest.TestCase):
    def test_independent_replay_component_diversity_and_abstentions(self) -> None:
        model = {
            "center": np.zeros(2),
            "scale": np.ones(2),
            "active_columns": np.ones(2, dtype=bool),
        }
        roles = {
            i: {"artist_known": i != 11, "component_id": 2 if i in (2, 3) else i}
            for i in range(1, 13)
        }
        features = {i: np.array([i / 2, 0]) for i in range(1, 10)}
        features[12] = np.array([np.nan, 0])
        rows = shared.rank_playable(list(roles), roles, features, model)
        m._direct_replay(list(roles), roles, features, model, rows)
        self.assertNotIn(3, rows[0]["neighbor_ids"])
        self.assertEqual(rows[9]["reason"], "missing_feature_row")
        self.assertEqual(rows[10]["reason"], "unresolved_artist")
        self.assertEqual(rows[11]["reason"], "outside_training_support")
        wrong = copy.deepcopy(rows)
        wrong[0]["neighbor_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "squared-difference"):
            m._direct_replay(list(roles), roles, features, model, wrong)

    def test_v3_closed_pack_freeze_build_replay_and_policy_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            digest = "a" * 64
            binding = {"sha256": digest, "bytes": 1}
            frozen: dict[str, Any] = {
                "policy": m.POLICY,
                "audio_manifest": binding,
                "roster": [1, 2, 3],
                "components": {"1": 1, "2": 2, "3": 3},
                "model_sha256": digest,
                "roles_sha256": digest,
                "feature_receipt": binding,
                "features": {
                    "features.float32": {**binding, "sha256": shared.FEATURE_SHA},
                    "track_ids.uint32": {**binding, "sha256": shared.ID_SHA},
                },
            }
            roles = [{"track_id": i, "artist_known": True, "component_id": i} for i in (1, 2, 3)]
            loaded = (
                roles,
                np.array([1, 2, 3]),
                np.array([[0.0], [1.0], [-1.0]]),
                {
                    "center": np.zeros(1),
                    "scale": np.ones(1),
                    "active_columns": np.ones(1, dtype=bool),
                },
            )
            declaration, output = root / "declaration.json", root / "result"
            inputs = (root, root, root, root, root)
            with patch.object(m, "_protocol", return_value=(frozen, loaded)):
                m.freeze_protocol(*inputs, declaration)
                result = m.build(*inputs, declaration, output)
                self.assertEqual(result["revision"], m.REVISION)
                self.assertEqual(result["rows"][0]["neighbor_ids"], [2, 3])
                self.assertEqual(m.replay(*inputs, output), result)
                wrong_frozen = copy.deepcopy(frozen)
                wrong_frozen["features"]["features.float32"]["sha256"] = "b" * 64
                wrong_result = copy.deepcopy(result)
                wrong_result["provenance"]["features_sha256"] = "b" * 64
                body = canonical_json(wrong_frozen)
                wrong_result["provenance"]["declaration_sha256"] = hashlib.sha256(body).hexdigest()
                (output / "declaration.json").write_bytes(body)
                (output / "manifest.json").write_bytes(canonical_json(wrong_result))
                rebound = {
                    "revision": m.REVISION,
                    "files": {
                        filename: {
                            "sha256": hashlib.sha256((output / filename).read_bytes()).hexdigest(),
                            "bytes": (output / filename).stat().st_size,
                        }
                        for filename in ("manifest.json", "declaration.json")
                    },
                }
                (output / "receipt.json").write_bytes(canonical_json(rebound))
                with self.assertRaisesRegex(ValueError, "array pin differs"):
                    shared.validate_playable_neighbors(output)

                changed = copy.deepcopy(frozen)
                changed["policy"] = shared.POLICY
                declaration.write_bytes(canonical_json(changed))
                with self.assertRaisesRegex(ValueError, "declaration differs"):
                    m.derive(*inputs, declaration)
                with self.assertRaises(FileExistsError):
                    m.build(*inputs, declaration, output)
            self.assertEqual(shared.POLICY["revision"], "fma-playable-component-neighbors-v2")
            self.assertIn("inner-fit", shared.POLICY["normalization"])
            self.assertIn("original-training", m.POLICY["normalization"])

    def test_rehashed_wrong_arrays_do_not_pass_known_restored_pins(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            files = {}
            for filename in ("features.float32", "track_ids.uint32"):
                body = b"coherently rewritten synthetic bytes"
                (root / filename).write_bytes(body)
                files[filename] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            (root / "projection-receipt.json").write_text(json.dumps({"files": files}))
            with self.assertRaisesRegex(ValueError, "array pin differs"):
                m.verify_feature_pins(root)
