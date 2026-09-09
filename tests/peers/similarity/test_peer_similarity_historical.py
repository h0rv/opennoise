"""Tests for evaluation isolation and deterministic historical peer scoring."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import override

from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.peers.similarity.peer_similarity import PeerSimilaritySettings, build_peer_similarity
from musix.peers.similarity.peer_similarity_historical import (
    HistoricalPeerSettings,
    evaluate_peer_similarity_historical,
    historical_peer_report_sha256,
    publish_historical_peer_evaluation,
    verify_historical_peer_report,
)
from musix.storage import LocalObjectStore


class HistoricalPeerEvaluationTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.public_input = PublicModelInput(
            artifacts=(
                PublicArtifact(
                    source="musicbrainz",
                    snapshot="test",
                    artifact_key="artists",
                    content_sha256="a" * 64,
                    export_allowed=True,
                ),
            ),
            genres=(
                GenreIdentity(genre_id="g-a", name="Genre A", evidence_refs=("seed:a",)),
                GenreIdentity(genre_id="g-b", name="Genre B", evidence_refs=("seed:b",)),
                GenreIdentity(genre_id="g-c", name="Genre C", evidence_refs=("seed:c",)),
            ),
            direct_memberships=(
                DirectMembershipEvidence(
                    artist_id="a1",
                    genre_id="g-a",
                    facet="musicbrainz_tag",
                    value=1.0,
                    evidence_ref="mb:a1",
                ),
                DirectMembershipEvidence(
                    artist_id="a2",
                    genre_id="g-a",
                    facet="musicbrainz_tag",
                    value=1.0,
                    evidence_ref="mb:a2",
                ),
                DirectMembershipEvidence(
                    artist_id="a2",
                    genre_id="g-b",
                    facet="musicbrainz_tag",
                    value=1.0,
                    evidence_ref="mb:a2b",
                ),
                DirectMembershipEvidence(
                    artist_id="a3",
                    genre_id="g-b",
                    facet="musicbrainz_tag",
                    value=1.0,
                    evidence_ref="mb:a3",
                ),
                DirectMembershipEvidence(
                    artist_id="a4",
                    genre_id="g-c",
                    facet="musicbrainz_tag",
                    value=1.0,
                    evidence_ref="mb:a4",
                ),
            ),
        )
        self.candidate_settings = PeerSimilaritySettings(
            minimum_shared_artists=1,
            direct_component_weight=1.0,
            aggregate_component_weight=0.0,
            maximum_neighbors=2,
        )
        self.candidate = build_peer_similarity(
            self.public_input,
            self.candidate_settings,
        )
        self.candidate_path = self.root / "candidate.json"
        self.input_path = self.root / "public-input.json"
        self.candidate_path.write_bytes(self.candidate.model_dump_json().encode())
        self.input_path.write_bytes(self.public_input.model_dump_json().encode())
        self.public_db = self.root / "public.sqlite"
        with closing(sqlite3.connect(self.public_db)) as connection:
            connection.executescript(
                """
                CREATE TABLE entity_identifiers (
                    normalized_value TEXT, identifier_type_id INTEGER, entity_id INTEGER
                );
                CREATE TABLE identifier_types (id INTEGER, type_key TEXT);
                CREATE TABLE entity_names (
                    entity_id INTEGER, name TEXT, name_kind TEXT,
                    is_preferred INTEGER, language_tag TEXT
                );
                INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id');
                INSERT INTO entity_identifiers VALUES
                    ('a1', 1, 1), ('a2', 1, 2), ('a3', 1, 3), ('a4', 1, 4);
                INSERT INTO entity_names VALUES
                    (1, 'Artist One', 'primary', 1, 'en'),
                    (2, 'Artist Two', 'primary', 1, 'en'),
                    (3, 'Artist Three', 'primary', 1, 'en'),
                    (4, 'Artist Four', 'primary', 1, 'en');
                """
            )
        self.historical_db = self.root / "historical.sqlite"
        with closing(sqlite3.connect(self.historical_db)) as connection:
            connection.executescript(
                """
                CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE historical_genre_artist_observations (
                    id INTEGER PRIMARY KEY,
                    genre_id INTEGER NOT NULL,
                    source_artist_name TEXT NOT NULL,
                    source_local_rank INTEGER
                );
                INSERT INTO genres VALUES (1, 'Genre A'), (2, 'Genre B'), (3, 'Genre C');
                INSERT INTO historical_genre_artist_observations VALUES
                    (1, 1, 'Artist One', 1), (2, 1, 'Artist Two', 2),
                    (3, 2, 'Artist Two', 1), (4, 2, 'Artist Three', 2),
                    (5, 3, 'Artist Four', 1);
                """
            )

    @override
    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_overlap_beats_uniform_null_and_is_replayable(self) -> None:
        report = evaluate_peer_similarity_historical(
            self.candidate_path,
            self.input_path,
            self.public_db,
            self.historical_db,
            candidate_settings=self.candidate_settings,
            settings=HistoricalPeerSettings(k=2),
        )
        self.assertEqual(report.matched_genre_count, 3)
        self.assertEqual(report.micro_overlap_count, 2)
        self.assertGreater(
            report.micro_candidate_recall_at_k or 0.0,
            report.micro_null_recall_at_k or 0.0,
        )
        self.assertEqual(report.historical_inputs_used_for_construction, False)
        self.assertEqual(report.construction_excluded_historical_data, True)
        self.assertEqual(report.report_sha256, historical_peer_report_sha256(report))
        verify_historical_peer_report(report)
        report_path = self.root / "evaluation-report.json"
        report_path.write_text(report.model_dump_json(), encoding="utf-8")
        receipt = publish_historical_peer_evaluation(
            report_path, report, LocalObjectStore(self.root / "objects")
        )
        self.assertEqual(receipt.report.sha256, receipt.report_sha256)
        self.assertTrue(
            receipt.report.key.value.startswith("evaluation/genre-peer-similarity-historical/")
        )

    def test_ambiguous_name_is_excluded_from_crosswalk(self) -> None:
        with closing(sqlite3.connect(self.public_db)) as connection, connection:
            connection.execute("INSERT INTO entity_identifiers VALUES ('other', 1, 5)")
            connection.execute(
                "INSERT INTO entity_names VALUES (5, 'Artist Two', 'primary', 1, 'en')"
            )
        report = evaluate_peer_similarity_historical(
            self.candidate_path,
            self.input_path,
            self.public_db,
            self.historical_db,
            candidate_settings=self.candidate_settings,
        )
        self.assertEqual(report.ambiguous_artist_name_count, 1)
        self.assertEqual(report.micro_overlap_count, 0)

    def test_tampered_report_fails_closed(self) -> None:
        report = evaluate_peer_similarity_historical(
            self.candidate_path,
            self.input_path,
            self.public_db,
            self.historical_db,
            candidate_settings=self.candidate_settings,
        )
        tampered = report.model_copy(update={"micro_overlap_count": report.micro_overlap_count + 1})
        with self.assertRaises(ValueError):
            verify_historical_peer_report(tampered)

    def test_sealed_json_hash_survives_numeric_model_normalization(self) -> None:
        payload = json.loads(self.candidate_path.read_text(encoding="utf-8"))
        payload["candidates"][0]["aggregate_score"] = 0
        without_hash = {key: value for key, value in payload.items() if key != "output_sha256"}
        payload["output_sha256"] = hashlib.sha256(
            json.dumps(
                without_hash,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.candidate_path.write_text(json.dumps(payload), encoding="utf-8")
        report = evaluate_peer_similarity_historical(
            self.candidate_path,
            self.input_path,
            self.public_db,
            self.historical_db,
            candidate_settings=self.candidate_settings,
        )
        self.assertEqual(report.candidate_output_sha256, payload["output_sha256"])

    def test_history_is_not_accepted_as_public_input(self) -> None:
        public = self.public_input.model_dump(mode="json")
        public["artifacts"].append(
            {
                "source": "wikidata",
                "snapshot": "historical",
                "artifact_key": "h3",
                "content_sha256": "b" * 64,
                "export_allowed": True,
            }
        )
        self.input_path.write_text(json.dumps(public))
        with self.assertRaises(ValueError):
            evaluate_peer_similarity_historical(
                self.candidate_path,
                self.input_path,
                self.public_db,
                self.historical_db,
                candidate_settings=self.candidate_settings,
            )


if __name__ == "__main__":
    unittest.main()
