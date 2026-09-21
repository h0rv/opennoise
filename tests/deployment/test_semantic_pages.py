"""Integration contract for the static semantic-atlas publication path."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidSeedMapInputs,
    build_public_qid_seed_map,
    write_public_qid_seed_map,
)
from opennoise.checkpoints.sealed_qid_direct_bridge import (
    SealedQidDirectBridgeInputs,
    build_sealed_qid_direct_bridge,
)
from opennoise.common import sha256_file, sha256_hex
from opennoise.deployment import semantic_pages
from opennoise.deployment.merged_public_direct_discovery import (
    build_merged_public_direct_discovery_candidate,
)
from opennoise.deployment.public_direct_static_discovery import (
    build_sealed_qid_additive_static_discovery,
)
from opennoise.deployment.public_discovery_promotion import (
    PublicDiscoveryPromotionReceipt,
    public_discovery_promotion_sha256,
)
from opennoise.deployment.public_static_discovery_v2 import (
    adapt_public_static_discovery_v2,
    public_static_discovery_v2_json,
)
from opennoise.deployment.semantic_pages import (
    SemanticPagesExportError,
    SemanticPagesExportInputs,
    StaticLabelPayload,
    _label_reveal_scale,
    _overlap_scale_interval,
    _PublicIdMapper,
    _spread_static_label_reveals,
    export_semantic_pages,
)
from tests._pinned_v1_discovery import pinned_v1_discovery_path

LAYOUT = Path(".cache/semantic-map-layout-v2/artifact.json")
V3_LAYOUT = Path(".cache/semantic-map-layout-v3/artifact.json")
PUBLIC_DATABASE = Path("data/public.sqlite")
BASE_DISCOVERY = pinned_v1_discovery_path()
STATIC_ROOT = Path(__file__).resolve().parents[2] / "src" / "opennoise" / "static"
REFERENCE_FIT_SCALE = 900.0
BASELINE_LABEL_COUNT = 4
LABEL_BOX_HEIGHT = 22.0


def _v2_candidate_and_receipt(atlas: Path):  # noqa: ANN202
    with tempfile.TemporaryDirectory() as temporary:
        qid_map_path = Path(temporary) / "qid-map.json"
        qid_map = build_public_qid_seed_map(
            PublicQidSeedMapInputs(public_database=PUBLIC_DATABASE, canonical_layout=V3_LAYOUT)
        )
        write_public_qid_seed_map(qid_map, qid_map_path)
        bridge = build_sealed_qid_direct_bridge(
            SealedQidDirectBridgeInputs(
                public_qid_seed_map=qid_map_path,
                public_database=PUBLIC_DATABASE,
                base_static_discovery=BASE_DISCOVERY,
            )
        )
        additive = build_sealed_qid_additive_static_discovery(
            database=PUBLIC_DATABASE,
            base_static_discovery=BASE_DISCOVERY,
            bridge=bridge,
        )
        candidate = build_merged_public_direct_discovery_candidate(
            base_static_discovery=BASE_DISCOVERY, additive=additive
        )
        payload = adapt_public_static_discovery_v2(candidate=candidate, semantic_atlas=atlas)
        payload_bytes = public_static_discovery_v2_json(payload)
        layout_sha256, _ = sha256_file(V3_LAYOUT)
        layout = semantic_pages.SemanticLayoutArtifact.model_validate_json(V3_LAYOUT.read_bytes())
        draft = PublicDiscoveryPromotionReceipt.model_validate(
            {
                "input_pins": {
                    "sealed_layout": {
                        "file_sha256": layout_sha256,
                        "logical_sha256": layout.output_sha256,
                    },
                    "public_database_sha256": candidate.public_database_sha256,
                    "base_static_discovery_sha256": candidate.base_static_discovery_sha256,
                    "public_qid_seed_map_sha256": qid_map.output_sha256,
                    "sealed_qid_direct_bridge_selection_sha256": bridge.selection_sha256,
                    "sealed_qid_direct_bridge_sha256": bridge.output_sha256,
                    "sealed_qid_additive_static_discovery_sha256": (
                        candidate.sealed_qid_additive_static_discovery_sha256
                    ),
                    "merged_public_direct_discovery_sha256": candidate.output_sha256,
                    "semantic_atlas_sha256": payload.input_chain.semantic_atlas_sha256,
                },
                "public_payload": {
                    "logical_sha256": payload.output_sha256,
                    "file_sha256": sha256_hex(payload_bytes),
                    "byte_count": len(payload_bytes),
                },
                "output_sha256": "0" * 64,
            }
        )
        receipt = draft.model_copy(
            update={"output_sha256": public_discovery_promotion_sha256(draft)}
        )
        return candidate, receipt, payload_bytes


def _assert_public_payload(test: unittest.TestCase, payload: dict[str, object]) -> None:  # noqa: C901, PLR0915
    public_bytes = json.dumps(payload, sort_keys=True)
    test.assertNotIn("legacy:", public_bytes)
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    node_ids: set[str] = set()
    for node in nodes:
        assert isinstance(node, dict)
        node_id = node["id"]
        assert isinstance(node_id, str)
        test.assertNotIn(":", node_id)
        node_ids.add(node_id)
    test.assertEqual(len(node_ids), len(nodes))
    test.assertTrue(all(node_id for node_id in node_ids))
    edges = payload["edges"]
    assert isinstance(edges, list)
    for edge in edges:
        assert isinstance(edge, dict)
        test.assertIn(edge["source"], node_ids)
        test.assertIn(edge["target"], node_ids)
        test.assertNotIn(":", edge["source"])
        test.assertNotIn(":", edge["target"])
    for node in nodes:
        assert isinstance(node, dict)
        for field in ("display_parent_id", "hierarchy_root_id"):
            if node[field] is not None:
                test.assertIn(node[field], node_ids)
                test.assertNotIn(":", node[field])
    labels = payload["labels"]
    assert isinstance(labels, list)
    for level in labels:
        assert isinstance(level, dict)
        test.assertTrue(set(level["ids"]).issubset(node_ids))
        test.assertTrue(all(":" not in node_id for node_id in level["ids"]))
    aliases = payload["aliases"]
    assert isinstance(aliases, list)
    for alias in aliases:
        assert isinstance(alias, dict)
        test.assertIn(alias["target"], node_ids)
        test.assertNotIn(":", alias["target"])
    browse_landmarks = payload["browse_landmarks"]
    assert isinstance(browse_landmarks, list)
    for landmark in browse_landmarks:
        assert isinstance(landmark, dict)
        test.assertIn(landmark["root_id"], node_ids)
        test.assertTrue(set(landmark["member_ids"]).issubset(node_ids))
        test.assertNotIn(":", landmark["root_id"])
        test.assertTrue(all(":" not in node_id for node_id in landmark["member_ids"]))
    label_atlas = payload["label_atlas"]
    assert isinstance(label_atlas, list)
    test.assertEqual(len(label_atlas), len(nodes))
    label_ids = set()
    for label in label_atlas:
        assert isinstance(label, dict)
        label_ids.add(label["id"])
        test.assertIn(label["id"], node_ids)
        test.assertEqual(label["side"], "right")
        for field in ("offset_x", "offset_y", "width_px", "height_px", "reveal_scale"):
            test.assertIsInstance(label[field], (int, float))
        test.assertGreaterEqual(label["width_px"], 16)
        test.assertGreaterEqual(label["reveal_scale"], 0)
    test.assertEqual(label_ids, node_ids)


class PublicIdMapperTests(unittest.TestCase):
    def test_public_id_mapper_is_deterministic_and_rejects_collisions(self) -> None:
        mapper = _PublicIdMapper.from_ids(("item1", "item887"))
        self.assertEqual(mapper.public("item887"), "item887")
        with self.assertRaises(SemanticPagesExportError):
            _PublicIdMapper.from_ids(("item1", "archive:item1"))

    def test_public_id_mapper_checks_the_full_seed_cardinality(self) -> None:
        ids = tuple(f"item{number}" for number in range(1, 6292))
        mapper = _PublicIdMapper.from_ids(ids)
        self.assertEqual(mapper.public("item6291"), "item6291")
        with self.assertRaises(SemanticPagesExportError):
            _PublicIdMapper.from_ids((*ids, "archive:item1"))


class PublicDiscoveryV2InputTests(unittest.TestCase):
    """The optional v2 path never accepts an unpaired promotion authority."""

    def test_v2_candidate_and_receipt_must_be_supplied_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            with self.assertRaisesRegex(SemanticPagesExportError, "supplied together"):
                export_semantic_pages(
                    SemanticPagesExportInputs(
                        Path("missing-layout.json"),
                        output,
                        public_discovery_v2_candidate=MagicMock(),
                    )
                )
            with self.assertRaisesRegex(SemanticPagesExportError, "supplied together"):
                export_semantic_pages(
                    SemanticPagesExportInputs(
                        Path("missing-layout.json"),
                        output,
                        public_discovery_v2_promotion_receipt=MagicMock(),
                    )
                )


@unittest.skipUnless(
    all(path.is_file() for path in (V3_LAYOUT, PUBLIC_DATABASE, BASE_DISCOVERY)),
    "requires pinned public v2 inputs",
)
class PublicDiscoveryV2ExportTests(unittest.TestCase):
    """The optional export writes only a receipt-verified v2 discovery asset."""

    def test_pinned_candidate_and_receipt_export_v2_after_atlas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed_output = root / "seed"
            seed_manifest = export_semantic_pages(SemanticPagesExportInputs(V3_LAYOUT, seed_output))
            seed_assets = seed_manifest["assets"]
            assert isinstance(seed_assets, dict)
            seed_atlas = seed_assets["semantic_atlas"]
            assert isinstance(seed_atlas, dict)
            candidate, receipt, expected_bytes = _v2_candidate_and_receipt(
                seed_output / str(seed_atlas["path"])
            )

            output = root / "v2"
            manifest = export_semantic_pages(
                SemanticPagesExportInputs(
                    V3_LAYOUT,
                    output,
                    public_discovery_v2_candidate=candidate,
                    public_discovery_v2_promotion_receipt=receipt,
                )
            )

            discovery = manifest["discovery"]
            assets = manifest["assets"]
            assert isinstance(discovery, dict)
            assert isinstance(assets, dict)
            discovery_asset = assets["static_discovery"]
            assert isinstance(discovery_asset, dict)
            self.assertEqual(discovery["revision"], "static-direct-discovery-v2")
            self.assertEqual(discovery["promotion_receipt_sha256"], receipt.output_sha256)
            payload = discovery["payload"]
            assert isinstance(payload, dict)
            self.assertEqual(payload["logical_sha256"], receipt.public_payload.logical_sha256)
            self.assertEqual(payload["file_sha256"], receipt.public_payload.file_sha256)
            self.assertEqual(payload["byte_count"], receipt.public_payload.byte_count)
            self.assertEqual((output / str(discovery_asset["path"])).read_bytes(), expected_bytes)


class StaticLabelAtlasTests(unittest.TestCase):
    def test_fixed_label_reveal_is_deterministic_and_clear_forever(self) -> None:
        root = StaticLabelPayload(
            id="root",
            side="right",
            offset_x=12,
            offset_y=5,
            width_px=42,
            priority=0,
            reveal_scale=0,
        )
        candidate = StaticLabelPayload(
            id="child",
            side="right",
            offset_x=12,
            offset_y=5,
            width_px=54,
            priority=1,
            reveal_scale=900,
        )
        reveal = _label_reveal_scale(candidate, 0.001, 0, ((0, 0, root),), 900)
        repeat = _label_reveal_scale(candidate, 0.001, 0, ((0, 0, root),), 900)
        self.assertEqual(reveal, repeat)
        self.assertGreaterEqual(reveal, 900)
        for scale in (reveal, reveal * 2, reveal * 100):
            left = (12, 5 - LABEL_BOX_HEIGHT, 12 + 42, 5)
            right = (
                0.001 * scale + 12,
                0.001 * scale + 5 - LABEL_BOX_HEIGHT,
                0.001 * scale + 12 + 54,
                0.001 * scale + 5,
            )
            self.assertTrue(
                left[2] <= right[0]
                or right[2] <= left[0]
                or left[3] <= right[1]
                or right[3] <= left[1]
            )

    def test_prior_label_is_checked_even_when_its_tier_reveals_later(self) -> None:
        prior = StaticLabelPayload(
            id="prior",
            side="right",
            offset_x=12.0,
            offset_y=5.0,
            width_px=42.0,
            priority=0,
            reveal_scale=1_500.0,
        )
        candidate = StaticLabelPayload(
            id="candidate",
            side="right",
            offset_x=12.0,
            offset_y=5.0,
            width_px=54.0,
            priority=1,
            reveal_scale=900.0,
        )
        # The boxes overlap from zero through roughly 1,680.  A later-tier
        # prior is therefore active for the final part of that interval.
        reveal = _label_reveal_scale(candidate, 0.025, 0.0, ((0.0, 0.0, prior),), 900.0)
        self.assertGreater(reveal, prior.reveal_scale)

    def test_coincident_right_labels_are_rejected_without_a_duplicate_lane(self) -> None:
        prior = StaticLabelPayload(
            id="prior",
            side="right",
            offset_x=12.0,
            offset_y=5.0,
            width_px=42.0,
            priority=0,
            reveal_scale=0.0,
        )
        candidate = StaticLabelPayload(
            id="candidate",
            side="right",
            offset_x=12.0,
            offset_y=5.0,
            width_px=54.0,
            priority=1,
            reveal_scale=900.0,
        )
        with self.assertRaisesRegex(SemanticPagesExportError, "coincident static label"):
            _label_reveal_scale(candidate, 0.0, 0.0, ((0.0, 0.0, prior),), 900.0)

    def test_admission_spread_delays_without_dropping_or_advancing_labels(self) -> None:
        labels = [
            StaticLabelPayload(
                id=f"item{index}",
                side="right",
                offset_x=12.0,
                offset_y=5.0,
                width_px=42.0,
                priority=index,
                reveal_scale=0.0 if index < BASELINE_LABEL_COUNT else 1_000.0,
            )
            for index in range(10)
        ]
        spread = _spread_static_label_reveals(labels)
        self.assertEqual({label.id for label in spread}, {label.id for label in labels})
        self.assertTrue(
            all(
                after.reveal_scale >= before.reveal_scale
                for before, after in zip(labels, spread, strict=True)
            ),
        )
        admitted = BASELINE_LABEL_COUNT
        for scale in sorted(
            {label.reveal_scale for label in spread if label.reveal_scale > REFERENCE_FIT_SCALE}
        ):
            next_admitted = sum(label.reveal_scale <= scale for label in spread)
            self.assertLessEqual(next_admitted, admitted + max(1, math.floor(admitted * 0.5)))
            admitted = next_admitted


@unittest.skipUnless(LAYOUT.is_file(), "semantic-layout integration artifact is not provisioned")
class SemanticPagesExportTests(unittest.TestCase):
    """The release exporter must retain the canonical renderer payload, not the SVG fallback."""

    def test_exports_full_semantic_atlas_and_static_edge_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            manifest = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, output))
            binding = manifest["semantic_layout"]
            assert isinstance(binding, dict)
            self.assertEqual(binding["total_seed_count"], 6291)
            self.assertEqual(binding["placed_node_count"], 2945)
            self.assertEqual(binding["unplaced_node_count"], 3346)
            self.assertEqual(binding["overview_region_count"], 24)
            self.assertEqual(binding["structural_edge_count"], 34937)
            release_assets = manifest["assets"]
            assert isinstance(release_assets, dict)
            atlas_entry = release_assets["semantic_atlas"]
            assert isinstance(atlas_entry, dict)
            atlas_path = output / str(atlas_entry["path"])
            payload = json.loads(atlas_path.read_text())
            self.assertEqual(len(payload["nodes"]), 2945)
            self.assertEqual(len(payload["edges"]), 34937)
            _assert_public_payload(self, payload)
            self._assert_static_labels_do_not_collide_at_any_admitted_scale(payload)
            index = (output / "index.html").read_text()
            self.assertIn('id="semantic-map"', index)
            self.assertIn('data-discovery-url="assets/', index)
            self.assertIn('id="search-results"', index)
            self.assertIn("Search genres and artists", index)
            self.assertIn('placeholder="Search genres or artists"', index)
            self.assertFalse((output / "assets" / "production-map-v1.json").exists())
            self.assertFalse((output / "assets" / "app.css").exists())
            self.assertFalse((output / "assets" / "map-atlas.mjs").exists())
            self.assertFalse((output / "assets" / "map-renderer.js").exists())
            self.assertFalse((output / "assets" / "semantic-atlas.json").exists())
            for stale_path in (
                "assets/app.css",
                "assets/map-atlas.mjs",
                "assets/map-renderer.js",
                "assets/semantic-atlas.json",
            ):
                self.assertNotIn(stale_path, index)
            for entry in release_assets.values():
                assert isinstance(entry, dict)
                path = output / str(entry["path"])
                self.assertTrue(path.is_file())
                self.assertEqual(
                    entry["sha256"], semantic_pages.sha256(path.read_bytes()).hexdigest()
                )
            app_entry = release_assets["app_css"]
            renderer_entry = release_assets["map_renderer_module"]
            atlas_module_entry = release_assets["map_atlas_module"]
            assert isinstance(app_entry, dict)
            assert isinstance(renderer_entry, dict)
            assert isinstance(atlas_module_entry, dict)
            self.assertIn(str(app_entry["path"]), index)
            self.assertIn(str(renderer_entry["path"]), index)
            self.assertIn(str(atlas_entry["path"]), index)
            renderer_text = (output / str(renderer_entry["path"])).read_text()
            self.assertIn(Path(str(atlas_module_entry["path"])).name, renderer_text)
            self.assertNotIn("./map-atlas.mjs", renderer_text)

    def _assert_static_labels_do_not_collide_at_any_admitted_scale(
        self, payload: dict[str, object]
    ) -> None:
        """Certify every pair over the full finite delivery scale range."""
        nodes = payload["nodes"]
        labels = payload["label_atlas"]
        maximum_scale = payload["maximum_scale"]
        assert isinstance(nodes, list)
        assert isinstance(labels, list)
        assert isinstance(maximum_scale, float)
        self.assertTrue(math.isfinite(maximum_scale))
        self.assertGreaterEqual(maximum_scale, 900.0)
        self.assertGreaterEqual(
            maximum_scale,
            max(float(label["reveal_scale"]) for label in labels),
        )
        by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
        for index, candidate in enumerate(labels):
            assert isinstance(candidate, dict)
            candidate_node = by_id[candidate["id"]]
            for prior in labels[:index]:
                assert isinstance(prior, dict)
                prior_node = by_id[prior["id"]]
                x_interval = _overlap_scale_interval(
                    float(candidate_node["x"]) - float(prior_node["x"]),
                    float(candidate["offset_x"]) - float(prior["offset_x"]),
                    -float(candidate["width_px"]),
                    float(prior["width_px"]),
                )
                y_interval = _overlap_scale_interval(
                    float(candidate_node["y"]) - float(prior_node["y"]),
                    float(candidate["offset_y"]) - float(prior["offset_y"]),
                    -float(candidate["height_px"]),
                    float(prior["height_px"]),
                )
                if x_interval is None or y_interval is None:
                    continue
                active_from = max(
                    x_interval[0],
                    y_interval[0],
                    float(candidate["reveal_scale"]),
                    float(prior["reveal_scale"]),
                )
                active_until = min(x_interval[1], y_interval[1], maximum_scale)
                self.assertLessEqual(
                    active_until,
                    active_from,
                    f"static labels {candidate['id']} and {prior['id']} overlap in delivery range",
                )
        self.assertTrue(
            all(float(label["reveal_scale"]) <= maximum_scale for label in labels),
            "the finite camera cap must admit the certified deepest label",
        )
        admitted = sum(float(label["reveal_scale"]) <= REFERENCE_FIT_SCALE for label in labels)
        for scale in sorted(
            {
                float(label["reveal_scale"])
                for label in labels
                if float(label["reveal_scale"]) > REFERENCE_FIT_SCALE
            }
        ):
            next_admitted = sum(float(label["reveal_scale"]) <= scale for label in labels)
            self.assertLessEqual(next_admitted, admitted + max(1, math.floor(admitted * 0.5)))
            admitted = next_admitted

    def test_changed_static_bytes_get_a_new_immutable_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            static = root / "static"
            shutil.copytree(STATIC_ROOT, static)
            with patch.object(semantic_pages, "_STATIC_ROOT", static):
                first = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, root / "first"))
                (static / "app.css").write_text("/* changed */\n", encoding="utf-8")
                second = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, root / "second"))
            first_assets = first["assets"]
            second_assets = second["assets"]
            assert isinstance(first_assets, dict)
            assert isinstance(second_assets, dict)
            first_css = first_assets["app_css"]
            second_css = second_assets["app_css"]
            assert isinstance(first_css, dict)
            assert isinstance(second_css, dict)
            self.assertNotEqual(first_css["path"], second_css["path"])

    def test_release_browse_paths_remain_presentation_only(self) -> None:
        """The current release has a rock browse path; IDM has no display parent."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            manifest = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, output))
            assets = manifest["assets"]
            assert isinstance(assets, dict)
            atlas = assets["semantic_atlas"]
            assert isinstance(atlas, dict)
            payload = json.loads((output / str(atlas["path"])).read_text())
        by_name = {node["name"].casefold(): node for node in payload["nodes"]}
        self.assertEqual(by_name["modern rock"]["display_parent_id"], by_name["rock"]["id"])
        # The released source has no electronic→IDM display parent, so the UI
        # must not manufacture that browse-path presentation link.
        self.assertIsNone(by_name["intelligent dance music"]["display_parent_id"])

        rock = by_name["rock"]
        rock_region = next(
            region for region in payload["browse_landmarks"] if region["root_id"] == rock["id"]
        )
        self.assertGreaterEqual(rock_region["member_count"], 4)
        self.assertEqual(rock_region["member_count"], len(rock_region["member_ids"]))
        by_id = {node["id"]: node for node in payload["nodes"]}
        landmark_ids = [region["root_id"] for region in payload["browse_landmarks"]]
        self.assertIn(rock["id"], landmark_ids)
        # Landmark IDs are L0 nodes, so they persist through every cumulative
        # semantic level rather than being a separate overview-only set.
        for level in range(4):
            self.assertTrue(all(by_id[node_id]["lod"] <= level for node_id in landmark_ids))


if __name__ == "__main__":
    unittest.main()
