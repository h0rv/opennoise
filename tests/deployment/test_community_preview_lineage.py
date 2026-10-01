"""Prevent partial provenance manifests from validating consumed preview data."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

from opennoise.common import sha256_file
from opennoise.deployment.community_preview import (
    require_assignment_source_bindings,
    validate_membership,
    verify_boundaries,
    verify_feature_lineage,
)

_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_MODEL_FILES = (
    "communities.json",
    "assignments.jsonl",
    "topic-centroids.npz",
    "topic-feature-identities.json",
)
_REQUIRED_FEATURE_BINDINGS = (
    "artist_name_enrichment_receipt",
    "candidate_catalog_database",
    "candidate_catalog_receipt",
    "direct_genre_claim_object",
    "direct_genre_receipt",
    "genre_labels",
    "open_artist_features",
    "open_artist_features_receipt",
    "open_artist_source_manifest",
)


def _model_report() -> dict[str, Any]:
    return {
        "files": {name: {} for name in _REQUIRED_MODEL_FILES},
        "historical_inputs_used": False,
        "artist_names_used_for_construction": False,
        "native_genre_memberships_added": 0,
    }


class CommunityPreviewLineageTests(unittest.TestCase):
    def test_every_consumed_model_artifact_requires_a_binding(self) -> None:
        source = {"files": {"index.html": {}, "data.json": {}}}
        verify_boundaries(source, _model_report())
        for missing in _REQUIRED_MODEL_FILES:
            with self.subTest(missing=missing):
                report = _model_report()
                del report["files"][missing]
                with self.assertRaisesRegex(ValueError, "model artifact lacks receipt binding"):
                    verify_boundaries(source, report)

    def test_source_overview_requires_both_consumed_bindings(self) -> None:
        for missing in ("index.html", "data.json"):
            with self.subTest(missing=missing):
                source = {"files": {"index.html": {}, "data.json": {}}}
                del source["files"][missing]
                with self.assertRaisesRegex(ValueError, "source overview lacks receipt binding"):
                    verify_boundaries(source, _model_report())

    def test_every_consumed_source_artist_shard_requires_a_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary)
            (model / "assignments.jsonl").write_text(
                json.dumps({"artist_mbid": "aaa00000-0000-4000-8000-000000000000"})
                + "\n"
                + json.dumps({"artist_mbid": "bbb00000-0000-4000-8000-000000000000"})
                + "\n",
                encoding="utf-8",
            )
            source = {"files": {"artists/aaa.json": {}, "artists/bbb.json": {}}}
            require_assignment_source_bindings(model, source)
            del source["files"]["artists/bbb.json"]

            with self.assertRaisesRegex(ValueError, "artist source lacks receipt binding"):
                require_assignment_source_bindings(model, source)

    def test_source_only_model_construction_boundaries_are_required(self) -> None:
        source = {"files": {"index.html": {}, "data.json": {}}}
        for field, value in (
            ("historical_inputs_used", True),
            ("artist_names_used_for_construction", True),
            ("native_genre_memberships_added", 1),
        ):
            with self.subTest(field=field):
                report = _model_report()
                report[field] = value
                with self.assertRaisesRegex(ValueError, "source-only construction boundary"):
                    verify_boundaries(source, report)


class CommunityPreviewFeatureLineageTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="community-lineage-test-", dir=cache)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.features = self.directory / "features.jsonl"
        self.features.write_text('{"artist_mbid":"fixture","features":[]}\n', encoding="utf-8")
        self.input = self.directory / "source.json"
        self.input.write_text('{"source":"metadata"}\n', encoding="utf-8")
        self.receipt: dict[str, Any] = {
            "scope": "local_noncommercial_research",
            "public_export_authorized": False,
            "audio_inputs_used": False,
            "historical_assignments_read": False,
            "feature_sha256": sha256_file(self.features)[0],
            "inputs": {
                name: {
                    "path": self.input.relative_to(_ROOT).as_posix(),
                    "sha256": sha256_file(self.input)[0],
                }
                for name in _REQUIRED_FEATURE_BINDINGS
            },
        }
        self.write_receipt()

    def write_receipt(self) -> None:
        (self.directory / "receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_verified_feature_bytes_and_source_inputs_are_accepted(self) -> None:
        self.assertEqual(verify_feature_lineage(self.features), self.receipt)

    def test_feature_mutation_is_rejected(self) -> None:
        self.features.write_text('{"artist_mbid":"different","features":[]}\n', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "mismatched feature lineage"):
            verify_feature_lineage(self.features)

    def test_source_input_mutation_is_rejected(self) -> None:
        self.input.write_text('{"source":"changed"}\n', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source byte binding differs"):
            verify_feature_lineage(self.features)

    def test_audio_historical_and_public_export_exclusions_are_required(self) -> None:
        for field in (
            "audio_inputs_used",
            "historical_assignments_read",
            "public_export_authorized",
        ):
            with self.subTest(field=field):
                self.receipt[field] = True
                self.write_receipt()
                with self.assertRaisesRegex(ValueError, "mismatched feature lineage"):
                    verify_feature_lineage(self.features)
                self.receipt[field] = False

    def test_symlinked_source_input_is_rejected(self) -> None:
        link = self.directory / "linked.json"
        link.symlink_to(self.input)
        self.receipt["inputs"]["open_artist_features"]["path"] = link.relative_to(_ROOT).as_posix()
        self.write_receipt()

        with self.assertRaisesRegex(ValueError, "source escapes repository"):
            verify_feature_lineage(self.features)

    def test_source_input_outside_repository_is_rejected(self) -> None:
        self.receipt["inputs"]["open_artist_features"]["path"] = "../outside-source.json"
        self.write_receipt()

        with self.assertRaisesRegex(ValueError, "source escapes repository"):
            verify_feature_lineage(self.features)

    def test_every_mandatory_feature_source_binding_is_required(self) -> None:
        for missing in _REQUIRED_FEATURE_BINDINGS:
            with self.subTest(missing=missing):
                binding = self.receipt["inputs"].pop(missing)
                self.write_receipt()
                with self.assertRaisesRegex(ValueError, "omits mandatory source bindings"):
                    verify_feature_lineage(self.features)
                self.receipt["inputs"][missing] = binding

    def test_empty_feature_source_binding_manifest_is_rejected(self) -> None:
        self.receipt["inputs"] = {}
        self.write_receipt()

        with self.assertRaisesRegex(ValueError, "omits mandatory source bindings"):
            verify_feature_lineage(self.features)


class CommunityPreviewMembershipBoundaryTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.communities = {
            "broad": {"level": "broad", "parent_id": None},
            "sub": {"level": "sub", "parent_id": "broad"},
            "micro": {"level": "micro", "parent_id": "sub"},
        }
        self.membership: dict[str, Any] = {
            "community_id": "micro",
            "level": "micro",
            "role": "inferred_community_membership",
            "score": 0.4,
        }
        self.assigned = set(self.communities)

    def test_known_inferred_membership_with_ancestry_is_accepted(self) -> None:
        validate_membership(self.membership, self.assigned, self.communities)

    def test_unknown_community_is_rejected(self) -> None:
        self.membership["community_id"] = "unknown"

        with self.assertRaisesRegex(ValueError, "unknown community assignment"):
            validate_membership(self.membership, self.assigned, self.communities)

    def test_role_and_level_cannot_copy_a_source_claim_or_parent_resolution(self) -> None:
        for field, value in (("role", "direct_source_observation"), ("level", "broad")):
            with self.subTest(field=field):
                changed = dict(self.membership, **{field: value})
                with self.assertRaisesRegex(ValueError, "role or level differs"):
                    validate_membership(changed, self.assigned, self.communities)

    def test_invalid_affinities_are_rejected(self) -> None:
        for score in (False, "0.4", float("nan"), float("inf"), -0.01, 1.01):
            with self.subTest(score=score):
                changed = dict(self.membership, score=score)
                with self.assertRaisesRegex(ValueError, "invalid membership affinity"):
                    validate_membership(changed, self.assigned, self.communities)

    def test_finer_membership_requires_its_direct_ancestor_assignment(self) -> None:
        with self.assertRaisesRegex(ValueError, "membership lacks its ancestor"):
            validate_membership(self.membership, {"broad", "micro"}, self.communities)
