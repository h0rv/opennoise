"""Direct source taxonomy export, namespaces, missingness and byte custody."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.deployment.source_genres import export_source_genres
from opennoise.pipeline.portable_foundation import project_portable_foundation

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/examples/open-genre-taxonomy"


class SourceGenresTests(unittest.TestCase):
    def test_all_direct_relations_and_artist_claims_preserve_source_scope(self) -> None:
        source = json.loads((PACK / "projection.json").read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            files = {}
            manifest = export_source_genres(PACK, output, files, foundation_root=ROOT)
            index = json.loads((output / manifest["index"]).read_bytes())
            self.assertEqual(len(index["genres"]), 1000)
            self.assertEqual(
                index["genres"],
                sorted(index["genres"], key=lambda row: (row[1].casefold(), int(row[0][1:]))),
            )
            self.assertEqual({row[0] for row in index["genres"] if row[2]}, {"Q3071", "Q704073"})
            details = {}
            for shard in range(index["detail_shards"]):
                payload = json.loads((output / f"source-genres/{shard}.json").read_bytes())
                self.assertEqual(payload["shard"], shard)
                self.assertTrue(all(int(qid[1:]) % 10 == shard for qid in payload["genres"]))
                details.update(payload["genres"])
            self.assertEqual(set(details), set(source["selected_qids"]))
            expected = {
                (row["genre_qid"], row["value_qid"])
                for row in source["claims"]
                if row["property_id"] == "P279"
            }
            actual = {(qid, parent[0]) for qid, row in details.items() for parent in row["parents"]}
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 1542)
            for child, row in details.items():
                for parent, _name, selected in row["parents"]:
                    self.assertEqual(selected, parent in details)
                    if selected:
                        self.assertIn(child, details[parent]["children"])
            artists = json.loads((output / "source-genres/artists.json").read_bytes())["artists"]
            expected_artists = {
                (artist["artist_mbid"], qid)
                for artist in project_portable_foundation(ROOT)["artists"]
                for qid in artist["direct_genres"]
                if qid in details
            }
            actual_artists = {
                (mbid, qid) for qid, row in details.items() for mbid in row["artists"]
            }
            self.assertEqual(actual_artists, expected_artists)
            self.assertEqual(len(actual_artists), 233)
            self.assertEqual(len(artists), 78)
            for artist in artists.values():
                self.assertEqual(
                    set(artist["direct_genres"]), {row["genre_qid"] for row in artist["claims"]}
                )
                self.assertTrue(all(row["property_id"] == "P136" for row in artist["claims"]))
            self.assertEqual(index["artist_memberships"], 233)
            self.assertFalse(index["cross_source_equivalence"])
            self.assertTrue(index["selection_possibly_truncated"])
            self.assertEqual(index["source_receipt_sha256"], sha256_file(PACK / "receipt.json")[0])
            for relative, binding in files.items():
                self.assertEqual(
                    sha256_file(output / relative), (binding["sha256"], binding["bytes"])
                )
                self.assertLessEqual(binding["bytes"], 200_000)

    def test_taxonomy_only_deterministic_and_never_assumes_artist_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first", Path(temporary) / "second"
            a, b = {}, {}
            self.assertEqual(
                export_source_genres(PACK, first, a), export_source_genres(PACK, second, b)
            )
            self.assertEqual(a, b)
            index = json.loads((first / "source-genres/index.json").read_bytes())
            self.assertEqual(index["artist_memberships"], 0)
            self.assertEqual(index["counts"]["artists"], 0)
            self.assertEqual(
                json.loads((first / "source-genres/artists.json").read_bytes()), {"artists": {}}
            )

    def test_modified_source_fails_before_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack, output = Path(temporary) / "pack", Path(temporary) / "output"
            shutil.copytree(PACK, pack)
            with (pack / "projection.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaises(ValueError):
                export_source_genres(pack, output, {})
            self.assertFalse(output.exists())

    def test_shard_limit_checked_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with (
                patch("opennoise.deployment.source_genres.MAX_SHARD_BYTES", 1),
                self.assertRaisesRegex(ValueError, "200 KB"),
            ):
                export_source_genres(PACK, output, {})
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
