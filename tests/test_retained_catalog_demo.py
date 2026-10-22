"""Public-source demonstration preserves coverage, identity and frozen acoustic boundaries."""

import math
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

from opennoise.pipeline import catalog_demo as demo

ROOT = Path(__file__).resolve().parents[1]


class RetainedCatalogDemoTests(unittest.TestCase):
    temporary: ClassVar[tempfile.TemporaryDirectory[str]]
    output: ClassVar[Path]
    result: ClassVar[dict[str, Any]]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        (ROOT / ".cache/test-tmp").mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache/test-tmp")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name) / "demo"
        cls.result = demo.build(ROOT, cls.output)

    def test_public_replay_preserves_distinct_coverage_and_identities(self) -> None:
        data = demo.read(self.output / "site/pipeline.json")
        self.assertEqual(
            data["counts"],
            {
                "artists": 440,
                "catalog_artists": 433,
                "artists_with_direct_genres": 78,
                "recordings": 1086,
                "core_recordings": 1031,
                "acoustic_artists": 17,
                "acoustic_nominations": 100,
                "descriptor_recordings": 55,
                "compatible_recordings": 34,
                "compatible_artists": 13,
                "supported_query_recordings": 11,
                "supported_query_artists": 6,
                "genres": 151,
            },
        )
        self.assertEqual(len(data["columns"]), 178)
        self.assertEqual(len(data["features"]), 100)
        self.assertEqual(len(data["source_edges"]), 290)
        self.assertEqual(len(data["acoustic_edges"]), 28)
        artists = {a["id"]: a for a in data["artists"]}
        self.assertEqual(len(artists), 440)
        self.assertEqual(sum(a["position"] is not None for a in artists.values()), 72)
        for edge in data["source_edges"]:
            left, right = (artists[edge[k]] for k in ("source", "target"))
            self.assertEqual(edge["genres"], sorted(set(left["genres"]) & set(right["genres"])))
        for artist in artists.values():
            for recording in artist["recordings"]:
                self.assertIn(artist["id"], data["recordings"][recording]["artists"])
        for edge in data["acoustic_edges"]:
            for observation in edge["observations"]:
                self.assertIn(
                    edge["source"],
                    data["recordings"][observation["query_recording_mbid"]]["artists"],
                )
                self.assertIn(
                    edge["target"],
                    data["recordings"][observation["candidate_recording_mbid"]]["artists"],
                )
                self.assertEqual(observation["contract_sha256"], edge["contract"])
                self.assertEqual(observation["heldout_fold"], edge["fold"])
        self.assertEqual(
            demo.digest(self.output / "acoustic-replay/manifest.json"),
            demo.ACOUSTIC_OUTPUT_PIN,
        )

    def test_receipt_binds_export_and_standalone_has_no_external_assets(self) -> None:
        site = self.output / "site"
        receipt = demo.read(site / "receipt.json")
        for relative, expected in receipt["files"].items():
            self.assertEqual(demo.digest(site / relative), expected)
        self.assertFalse(receipt["perceptual_similarity_validated"])
        self.assertFalse(receipt["audio_playback_verified"])
        self.assertFalse(receipt["private_annotations_or_benchmark_inputs"])
        html = (site / "OpenNoise.html").read_text()
        self.assertEqual(html.count('<script type="module">'), 1)
        self.assertNotIn('<script type="module" src=', html)
        self.assertNotIn('<link rel="stylesheet"', html)
        self.assertIn("globalThis.OPENNOISE_LOCAL_FILES=", html)
        self.assertEqual(self.result["standalone_sha256"], demo.digest(site / "OpenNoise.html"))

    def test_output_rejects_existing_outside_and_symlink_paths(self) -> None:
        for path in (self.output, ROOT / "dist-demo-forbidden"):
            with self.assertRaisesRegex(ValueError, "fresh and under"):
                demo.build(ROOT, path)
        link = Path(self.temporary.name) / "link"
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            demo.build(ROOT, link / "new")

    def test_graph_drawing_does_not_place_unknown_relationships(self) -> None:
        ids = ["a", "b", "c"]
        edges = [{"source": "a", "target": "b"}]
        actual = demo.positions(ids, edges)
        self.assertEqual(set(actual), {"a", "b"})
        self.assertEqual(actual, demo.positions(list(reversed(ids)), edges))
        self.assertTrue(all(math.isfinite(v) for p in actual.values() for v in p))
        self.assertEqual(set(demo.positions(ids, edges, place_unlinked=True)), set(ids))


if __name__ == "__main__":
    unittest.main()
