"""Research supplements must remain distinct from native observation and provenance."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.common import canonical_json, sha256_file
from opennoise.pipeline.full_input_assembly import public_genres
from opennoise.pipeline.full_input_foundation import _compare_artist_detail, _entity_rows
from opennoise.pipeline.full_input_research import source_completion, verify_research_files


class FullInputResearchTests(unittest.TestCase):
    def test_compact_replay_checks_every_native_entity_field(self) -> None:
        native = {
            "artist_mbid": "exact",
            "labels": {"ja": {"value": "東京"}},
            "claims": {"P17": [{"rank": "normal", "references_retained_in_raw": True}]},
        }
        expected = {
            "artist_mbid": "exact",
            "direct_genres": ["Q1"],
            "_native_entity_evidence_sha256": hashlib.sha256(canonical_json(native)).hexdigest(),
        }
        actual = {"artist_mbid": "exact", "direct_genres": ["Q1"], "native_entity_evidence": native}
        _compare_artist_detail(actual, expected)
        native["claims"]["P17"][0]["rank"] = "preferred"
        with self.assertRaisesRegex(ValueError, "native entity fields"):
            _compare_artist_detail(actual, expected)
        self.assertIn("_native_entity_evidence_sha256", expected)

    def test_streamed_entity_rows_preserve_literal_nested_json(self) -> None:
        rows = [
            {
                "artist_mbid": "literal",
                "labels": {"ja": {"value": "東京"}},
                "claims": {
                    "P136": [
                        {
                            "datavalue": {"value": {"id": "Q1"}},
                            "rank": "normal",
                            "qualifiers": {"P1": [1, 2.5, None]},
                        }
                    ]
                },
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "projection.json"
            path.write_bytes(
                canonical_json({"artists": rows, "context_entities": {}, "license": "CC0-1.0"})
            )
            self.assertEqual(list(_entity_rows(path)), rows)

    def test_lean_index_keeps_exact_counts_and_complete_cohort_routes(self) -> None:
        native = [{"genre_id": "Q1", "name": "native label", "artist_mbids": ["a", "b"]}]
        self.assertEqual(
            public_genres(native),
            [
                {
                    "genre_id": "Q1",
                    "name": "native label",
                    "artist_count": 2,
                    "cohort_path": "genres/Q1.json",
                }
            ],
        )
        self.assertEqual(native[0]["artist_mbids"], ["a", "b"])

    def _pack(self, directory: Path, *, probability: float | None, seed: str) -> None:
        row = {
            "artist_mbid": "00000000-0000-0000-0000-000000000001",
            "namespace": "experimental-source-completion-v1",
            "default_promotion": False,
            "observed_genre_qids": [seed],
            "abstention": None,
            "proposals": [
                {
                    "genre_qid": "Q2",
                    "musical_membership_probability": probability,
                    "proposal_probability": None,
                }
            ],
        }
        (directory / "artist-proposals.jsonl.zst").write_bytes(
            zstandard.ZstdCompressor().compress(canonical_json(row) + b"\n")
        )
        (directory / "report.json").write_bytes(
            canonical_json(
                {"source_license": "CC0-1.0", "artist_replay": {"receipt_sha256": "native-source"}}
            )
        )
        receipt = {"revision": "wikidata-artist-completion-v1", "files": {}}
        for filename in ("report.json", "artist-proposals.jsonl.zst"):
            digest, size = sha256_file(directory / filename)
            receipt["files"][filename] = {"sha256": digest, "bytes": size}
        (directory / "receipt.json").write_bytes(canonical_json(receipt))

    def test_self_rehashed_musical_probability_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._pack(directory, probability=0.8, seed="Q1")
            artists = {"00000000-0000-0000-0000-000000000001": {"direct_genres": ["Q1"]}}
            with self.assertRaisesRegex(ValueError, "invents"):
                source_completion(directory, artists, "native-source")
            self.assertNotIn("source_completion_proposals", next(iter(artists.values())))

    def test_self_rehashed_unobserved_seed_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._pack(directory, probability=None, seed="Q3")
            artists = {"00000000-0000-0000-0000-000000000001": {"direct_genres": ["Q1"]}}
            with self.assertRaisesRegex(ValueError, "not observed"):
                source_completion(directory, artists, "native-source")

    def test_provenance_change_and_uninventoried_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._pack(directory, probability=None, seed="Q1")
            artists = {"00000000-0000-0000-0000-000000000001": {"direct_genres": ["Q1"]}}
            with self.assertRaisesRegex(ValueError, "does not bind"):
                source_completion(directory, artists, "different-native-source")
            (directory / "extra.json").write_text(json.dumps({}))
            with self.assertRaisesRegex(ValueError, "closed file"):
                verify_research_files(directory, "artist_source_completion")
