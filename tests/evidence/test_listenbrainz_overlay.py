"""Contract tests for the separate receipt-bound ListenBrainz sidecars."""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.common import canonical_json, sha256_file
from opennoise.evidence.graph_projection import (
    ArtifactInput,
    EvidenceGraphProjectionArtifact,
    artifact_sha256,
    write_evidence_graph_projection,
)
from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlayInputs,
    CoListenOverlaySources,
    DerivedReviewOverlayInputs,
    DerivedReviewOverlaySources,
    ListenBrainzOverlayError,
    build_colisten_overlay,
    build_derived_review_overlay,
    certify_colisten_overlay_sources,
    certify_derived_review_overlay_sources,
    colistens_for_artist,
    derived_reviews_for_seed,
    write_colisten_overlay,
    write_derived_review_overlay,
)
from opennoise.ingest.listenbrainz.propagation import (
    ListenBrainzPropagationReceipt,
    ListenBrainzPropagationSettings,
    PropagationCandidate,
    PropagationCoverage,
    PropagationInputFingerprint,
    PropagationPath,
)
from opennoise.storage import ObjectKey, ObjectWrite

_ARTIST_A = "00000000-0000-4000-8000-000000000001"
_ARTIST_B = "00000000-0000-4000-8000-000000000002"
_ARTIST_MISSING = "00000000-0000-4000-8000-000000000003"
_QUALIFIED_SHA = "a" * 64
_PROPAGATION_LOGICAL = "b" * 64


class ListenBrainzOverlayTests(unittest.TestCase):
    def test_sidecars_partition_all_inputs_and_preserve_bounded_query_provenance(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, graph_receipt = _graph(root)
            propagation, propagation_receipt = _propagation(root)
            qualified = _qualified_listenbrainz(root)
            qualified_sha, _ = sha256_file(qualified)
            review_database = root / "review.sqlite"
            review = build_derived_review_overlay(
                DerivedReviewOverlayInputs(
                    graph,
                    graph_receipt,
                    propagation,
                    propagation_receipt,
                    review_database,
                )
            )
            review_receipt = root / "review.receipt.json"
            write_derived_review_overlay(review_receipt, review)
            colisten_database = root / "colisten.sqlite"
            colisten = build_colisten_overlay(
                CoListenOverlayInputs(
                    graph,
                    graph_receipt,
                    qualified,
                    qualified_sha,
                    colisten_database,
                )
            )
            colisten_receipt = root / "colisten.receipt.json"
            write_colisten_overlay(colisten_receipt, colisten)

            self.assertEqual(review.coverage.source_candidate_count, 4)
            self.assertEqual(review.coverage.retained_candidate_count, 1)
            self.assertEqual(review.coverage.abstained_artist_not_in_graph_count, 1)
            self.assertEqual(review.coverage.rejected_stable_seed_not_in_graph_count, 1)
            self.assertEqual(review.coverage.rejected_invalid_identifier_count, 1)
            self.assertFalse(review.coverage.factual_memberships_written)
            self.assertEqual(colisten.coverage.source_row_count, 5)
            self.assertEqual(colisten.coverage.retained_relation_count, 1)
            self.assertEqual(colisten.coverage.abstained_endpoint_not_in_graph_count, 1)
            self.assertEqual(colisten.coverage.rejected_below_privacy_threshold_count, 1)
            self.assertEqual(colisten.coverage.rejected_noncanonical_endpoint_count, 2)
            self.assertFalse(colisten.coverage.inferred_artist_similarity_written)

            review_sources = certify_derived_review_overlay_sources(
                DerivedReviewOverlaySources(review_database, review)
            )
            review_page = derived_reviews_for_seed(review_sources, "item1", limit=1)
            self.assertEqual(review_page.total_candidate_count, 1)
            self.assertEqual(review_page.candidates[0].artist_mbid, _ARTIST_A)
            self.assertEqual(len(review_page.candidates[0].paths), 1)
            self.assertIn(
                _PROPAGATION_LOGICAL, review_page.candidates[0].propagation_provenance_ref
            )

            colisten_sources = certify_colisten_overlay_sources(
                CoListenOverlaySources(colisten_database, colisten)
            )
            colisten_page = colistens_for_artist(colisten_sources, _ARTIST_A, limit=1)
            self.assertEqual(colisten_page.total_relation_count, 1)
            self.assertEqual(colisten_page.relations[0].neighbor_artist_mbid, _ARTIST_B)
            self.assertEqual(colisten_page.relations[0].distinct_user_count, 5)
            self.assertEqual(colisten_page.relations[0].window_start, 10)
            self.assertTrue(colisten_page.relations[0].source_binding.endswith(qualified_sha))

    def test_propagation_receipt_and_artifact_bytes_are_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, graph_receipt = _graph(root)
            propagation, propagation_receipt = _propagation(root)
            tampered = root / "tampered-propagation.json"
            tampered.write_bytes(propagation.read_bytes() + b"\n")
            with self.assertRaisesRegex(ListenBrainzOverlayError, "does not match its receipt"):
                build_derived_review_overlay(
                    DerivedReviewOverlayInputs(
                        graph,
                        graph_receipt,
                        tampered,
                        propagation_receipt,
                        root / "review.sqlite",
                    )
                )

    def test_sidecars_reject_unbounded_queries_and_tampered_database_bytes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, graph_receipt = _graph(root)
            propagation, propagation_receipt = _propagation(root)
            review_database = root / "review.sqlite"
            review = build_derived_review_overlay(
                DerivedReviewOverlayInputs(
                    graph,
                    graph_receipt,
                    propagation,
                    propagation_receipt,
                    review_database,
                )
            )
            source = certify_derived_review_overlay_sources(
                DerivedReviewOverlaySources(review_database, review)
            )
            with self.assertRaisesRegex(ListenBrainzOverlayError, "between 1 and 1000"):
                derived_reviews_for_seed(source, "item1", limit=1_001)
            with closing(sqlite3.connect(review_database)) as database, database:
                database.execute("UPDATE review_candidate SET score = .4")
            with self.assertRaisesRegex(ListenBrainzOverlayError, "does not match receipt"):
                certify_derived_review_overlay_sources(
                    DerivedReviewOverlaySources(review_database, review)
                )

    def test_fresh_sidecars_replay_with_identical_bytes_and_logical_hashes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, graph_receipt = _graph(root)
            propagation, propagation_receipt = _propagation(root)
            qualified = _qualified_listenbrainz(root)
            qualified_sha, _ = sha256_file(qualified)
            first_review = root / "first-review.sqlite"
            second_review = root / "second-review.sqlite"
            first_review_artifact = build_derived_review_overlay(
                DerivedReviewOverlayInputs(
                    graph, graph_receipt, propagation, propagation_receipt, first_review
                )
            )
            second_review_artifact = build_derived_review_overlay(
                DerivedReviewOverlayInputs(
                    graph, graph_receipt, propagation, propagation_receipt, second_review
                )
            )
            first_colisten = root / "first-colisten.sqlite"
            second_colisten = root / "second-colisten.sqlite"
            first_colisten_artifact = build_colisten_overlay(
                CoListenOverlayInputs(
                    graph, graph_receipt, qualified, qualified_sha, first_colisten
                )
            )
            second_colisten_artifact = build_colisten_overlay(
                CoListenOverlayInputs(
                    graph, graph_receipt, qualified, qualified_sha, second_colisten
                )
            )

            self.assertEqual(first_review_artifact, second_review_artifact)
            self.assertEqual(first_colisten_artifact, second_colisten_artifact)
            self.assertEqual(sha256_file(first_review), sha256_file(second_review))
            self.assertEqual(sha256_file(first_colisten), sha256_file(second_colisten))


def _graph(root: Path) -> tuple[Path, Path]:
    database = root / "graph.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """CREATE TABLE identity(
                   namespace TEXT NOT NULL, identifier TEXT NOT NULL, label TEXT,
                   disposition TEXT NOT NULL, PRIMARY KEY(namespace, identifier)
               ) WITHOUT ROWID"""
        )
        connection.executemany(
            "INSERT INTO identity VALUES ('stable_seed', ?, ?, 'source_entity')",
            ((f"item{ordinal}", f"genre {ordinal}") for ordinal in range(1, 6_292)),
        )
        connection.executemany(
            "INSERT INTO identity VALUES ('musicbrainz_artist', ?, NULL, 'source_entity')",
            ((_ARTIST_A,), (_ARTIST_B,)),
        )
    database_sha, database_bytes = sha256_file(database)
    inputs = tuple(
        ArtifactInput(
            role=f"fixture_{ordinal}",
            path=f"fixture_{ordinal}",
            byte_sha256=f"{ordinal:x}".zfill(64),
            byte_count=1,
            logical_sha256=f"{ordinal:x}".zfill(64),
        )
        for ordinal in range(8)
    )
    base = EvidenceGraphProjectionArtifact(
        inputs=inputs,
        database_sha256=database_sha,
        database_bytes=database_bytes,
        identity_count=6_291,
        total_identity_count=6_293,
        claim_count=0,
        abstention_count=0,
        factual_relation_count=0,
        candidate_relation_score_count=0,
        output_sha256="0" * 64,
    )
    receipt = base.model_copy(update={"output_sha256": artifact_sha256(base)})
    path = root / "graph.receipt.json"
    write_evidence_graph_projection(path, receipt)
    return database, path


def _propagation(root: Path) -> tuple[Path, Path]:
    candidates = (
        _candidate(_ARTIST_A, "legacy:item1"),
        _candidate(_ARTIST_MISSING, "legacy:item1"),
        _candidate(_ARTIST_A, "legacy:item9999"),
        _candidate(_ARTIST_A, "legacy:legacy:item1"),
    )
    coverage = PropagationCoverage(
        uniquely_matched_name_universe_genre_count=0,
        ambiguous_name_universe_genre_count=0,
        direct_anchor_count=0,
        direct_anchor_artist_count=0,
        direct_anchor_genre_count=0,
        musicbrainz_only_anchor_count=0,
        wikidata_only_anchor_count=0,
        musicbrainz_wikidata_overlap_anchor_count=0,
        input_artist_pair_count=0,
        support_eligible_artist_pair_count=0,
        hub_capped_artist_count=0,
        hub_capped_artist_pair_count=0,
        retained_artist_pair_count=0,
        seed_anchor_capped_count=0,
        propagation_visit_count=0,
        candidate_count_before_genre_cap=4,
        candidate_count=4,
        candidate_artist_count=2,
        candidate_genre_count=2,
        incremental_name_universe_genre_count=2,
    )
    artifact_payload = {
        "membership_semantics": "derived_review_evidence_not_factual_membership",
        "output_sha256": _PROPAGATION_LOGICAL,
        "coverage": coverage.model_dump(mode="json"),
        "settings": ListenBrainzPropagationSettings().model_dump(mode="json"),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    artifact_path = root / "propagation.json"
    artifact_path.write_bytes(canonical_json(artifact_payload))
    artifact_sha, artifact_bytes = sha256_file(artifact_path)
    receipt = ListenBrainzPropagationReceipt(
        artifact=ObjectWrite(
            key=ObjectKey(value="fixture/propagation.json"),
            sha256=artifact_sha,
            byte_size=artifact_bytes,
            reused=False,
        ),
        artifact_sha256=artifact_sha,
        logical_output_sha256=_PROPAGATION_LOGICAL,
        inputs=PropagationInputFingerprint(
            catalog_database_sha256=_QUALIFIED_SHA,
            listenbrainz_database_sha256=_QUALIFIED_SHA,
            name_universe_source_sha256="c" * 64,
            musicbrainz_seed_target_output_sha256="d" * 64,
            musicbrainz_seed_target_file_sha256="e" * 64,
            public_input_sha256="f" * 64,
        ),
    )
    receipt_path = root / "propagation.receipt.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    return artifact_path, receipt_path


def _candidate(artist_mbid: str, genre_id: str) -> PropagationCandidate:
    return PropagationCandidate(
        artist_id=f"musicbrainz:artist:{artist_mbid}",
        genre_id=genre_id,
        genre_rank=1,
        score=1.0,
        paths=(
            PropagationPath(
                seed_artist_id=f"musicbrainz:artist:{_ARTIST_B}",
                direct_facets=("musicbrainz_genre",),
                direct_evidence_refs=("musicbrainz:fixture",),
                listener_day_support=5,
                supporting_windows=1,
                co_listen_evidence_refs=("listenbrainz:fixture",),
                normalized_edge_weight=0.5,
            ),
        ),
    )


def _qualified_listenbrainz(root: Path) -> Path:
    database = root / "qualified.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """CREATE TABLE artist_co_listen_evidence(
                   left_artist_source_id TEXT NOT NULL,
                   right_artist_source_id TEXT NOT NULL,
                   window_start INTEGER NOT NULL,
                   window_end INTEGER NOT NULL,
                   distinct_user_count INTEGER NOT NULL,
                   evidence_fingerprint TEXT NOT NULL
               )"""
        )
        a = f"musicbrainz:artist:{_ARTIST_A}"
        b = f"musicbrainz:artist:{_ARTIST_B}"
        missing = f"musicbrainz:artist:{_ARTIST_MISSING}"
        connection.executemany(
            "INSERT INTO artist_co_listen_evidence VALUES (?, ?, ?, ?, ?, ?)",
            (
                (a, b, 10, 11, 5, "1" * 64),
                (a, missing, 20, 21, 5, "2" * 64),
                (a, b, 30, 31, 4, "3" * 64),
                (b, a, 40, 41, 5, "4" * 64),
                (
                    a,
                    "musicbrainz:artist:gggggggg-gggg-4ggg-8ggg-gggggggggggg",
                    50,
                    51,
                    5,
                    "5" * 64,
                ),
            ),
        )
    return database


if __name__ == "__main__":
    unittest.main()
