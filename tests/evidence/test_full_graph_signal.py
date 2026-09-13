from __future__ import annotations

import sqlite3
import tempfile
import unittest
from array import array
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.checkpoints.source_neutral_certification import (
    HierarchyCertification,
    InputBinding,
    MembershipCertification,
    PeerCertification,
    SourceNeutralCheckpointCertification,
    certification_sha256,
)
from opennoise.common import sha256_file
from opennoise.evidence.full_graph_signal import (
    ChannelPairCounts,
    FullGraphSignalInputs,
    FullGraphSignalSettings,
    _containment_candidates,
    _cooccurrence,
    _csr,
    _evaluate_membership,
    _heldout_by_artist,
    _load_pairs,
    _PairData,
    _peer_recovery,
    _trim_rows,
    build_full_graph_signal,
    verify_full_graph_signal,
)
from opennoise.evidence.graph_projection import (
    ArtifactInput,
    EvidenceGraphProjectionArtifact,
    artifact_sha256,
)


class FullGraphSignalTests(unittest.TestCase):
    def _inputs(self, directory: Path) -> FullGraphSignalInputs:
        database = directory / "graph.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript(
                """
                CREATE TABLE identity(namespace TEXT NOT NULL, identifier TEXT NOT NULL,
                    label TEXT, disposition TEXT NOT NULL, PRIMARY KEY(namespace, identifier));
                CREATE TABLE claim(subject_namespace TEXT NOT NULL,
                    subject_identifier TEXT NOT NULL,
                    predicate TEXT NOT NULL, object_namespace TEXT NOT NULL,
                    object_identifier TEXT NOT NULL, evidence_kind TEXT NOT NULL,
                    source TEXT NOT NULL, facet TEXT NOT NULL, provenance_ref TEXT NOT NULL,
                    release_group_id TEXT NOT NULL);
                """
            )
            connection.executemany(
                "INSERT INTO identity VALUES ('stable_seed', ?, ?, 'fixture')",
                ((f"seed-{index}", f"Seed {index}") for index in range(6291)),
            )
            pairs = (
                ("artist-a", "seed-1", "artist_direct", ""),
                ("artist-a", "seed-1", "release_group_support", "release-1"),
                ("artist-a", "seed-2", "release_group_support", "release-2"),
                ("artist-a", "seed-3", "release_group_support", "release-3"),
                ("artist-b", "seed-1", "artist_direct", ""),
                ("artist-b", "seed-2", "release_group_support", "release-4"),
                ("artist-b", "seed-3", "reviewed_alias_context", ""),
                ("artist-c", "seed-1", "release_group_support", "release-5"),
                ("artist-c", "seed-2", "release_group_support", "release-6"),
                ("artist-d", "seed-2", "release_group_support", "release-7"),
                ("artist-d", "seed-3", "release_group_support", "release-8"),
            )
            connection.executemany(
                "INSERT INTO claim VALUES ('musicbrainz_artist', ?, 'artist_membership',"
                "'stable_seed', ?, ?, 'fixture', 'tag', ?, ?)",
                (
                    (artist, seed, kind, f"ref:{artist}:{seed}:{kind}", release)
                    for artist, seed, kind, release in pairs
                ),
            )
            connection.commit()
        database_sha, database_size = sha256_file(database)
        graph_inputs = tuple(
            ArtifactInput(
                role=f"input-{index}",
                path=f"fixture-{index}",
                byte_sha256=f"{index:x}".zfill(64),
                byte_count=1,
                logical_sha256=f"{index + 8:x}".zfill(64),
            )
            for index in range(8)
        )
        receipt_base = EvidenceGraphProjectionArtifact(
            inputs=graph_inputs,
            database_sha256=database_sha,
            database_bytes=database_size,
            identity_count=6291,
            total_identity_count=6291,
            claim_count=len(pairs),
            abstention_count=0,
            factual_relation_count=0,
            candidate_relation_score_count=0,
            output_sha256="0" * 64,
        )
        receipt = receipt_base.model_copy(update={"output_sha256": artifact_sha256(receipt_base)})
        receipt_path = directory / "graph-receipt.json"
        receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
        certificate_base = SourceNeutralCheckpointCertification(
            inputs=(
                InputBinding(
                    role="evidence_graph_database",
                    bytes_sha256=database_sha,
                    byte_count=database_size,
                    logical_sha256=database_sha,
                ),
                InputBinding(
                    role="evidence_graph_receipt",
                    bytes_sha256="a" * 64,
                    byte_count=1,
                    logical_sha256=receipt.output_sha256,
                ),
                InputBinding(role="fixture-a", bytes_sha256="b" * 64, byte_count=1),
                InputBinding(role="fixture-b", bytes_sha256="c" * 64, byte_count=1),
            ),
            graph_explicit_abstention_row_count=0,
            membership=MembershipCertification(
                certified_observed_seed_count=3, certified_unknown_seed_count=6288
            ),
            peers=PeerCertification(
                certified_stable_pair_count=0, eligible_seed_count=0, explicit_abstention_count=6291
            ),
            hierarchy=HierarchyCertification(
                accepted_factual_edge_count=0,
                factual_endpoint_seed_count=0,
                factual_isolated_seed_count=6291,
            ),
            output_sha256="0" * 64,
        )
        certificate = certificate_base.model_copy(
            update={"output_sha256": certification_sha256(certificate_base)}
        )
        certificate_path = directory / "certificate.json"
        certificate_path.write_text(certificate.model_dump_json(), encoding="utf-8")
        return FullGraphSignalInputs(
            graph_database=database,
            graph_receipt=receipt_path,
            construction_certificate=certificate_path,
            cache_directory=directory / "cache",
        )

    def test_streams_complete_pairs_and_reuses_verified_pair_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            inputs = self._inputs(Path(raw_directory))
            settings = FullGraphSignalSettings(
                split_seed=1,
                heldout_fraction=0.4,
                maximum_evaluation_artists=100,
                maximum_genre_neighbors=10,
            )
            first = build_full_graph_signal(inputs, settings)
            verify_full_graph_signal(first)
            self.assertEqual(first.pair_split.unique_pair_count, 10)
            self.assertEqual(first.pair_split.claims_streamed, 11)
            self.assertEqual(first.pair_split.source_channel_pairs.artist_direct, 2)
            self.assertFalse(first.pair_split.historical_inputs_read)
            self.assertTrue(all(not Path(row.path).is_absolute() for row in first.matrix_caches))
            pair_data = _load_pairs(inputs.graph_database, settings)
            heldout = _heldout_by_artist(pair_data)
            self.assertTrue(heldout)
            for artist, seed in zip(pair_data.heldout_rows, pair_data.heldout_columns, strict=True):
                self.assertNotIn(
                    int(seed),
                    {
                        pair_data.columns[index]
                        for index, row in enumerate(pair_data.rows)
                        if row == artist
                    },
                )
            with patch(
                "opennoise.evidence.full_graph_signal._load_pairs", side_effect=AssertionError
            ):
                second = build_full_graph_signal(inputs, settings)
            self.assertEqual(first.output_sha256, second.output_sha256)

    def test_tampered_cache_and_certificate_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            inputs = self._inputs(Path(raw_directory))
            artifact = build_full_graph_signal(
                inputs,
                FullGraphSignalSettings(
                    split_seed=1,
                    heldout_fraction=0.4,
                    maximum_evaluation_artists=100,
                    maximum_genre_neighbors=10,
                ),
            )
            matrix = inputs.cache_directory / artifact.matrix_caches[0].path
            matrix.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "cache"):
                build_full_graph_signal(
                    inputs,
                    FullGraphSignalSettings(
                        split_seed=1,
                        heldout_fraction=0.4,
                        maximum_evaluation_artists=100,
                        maximum_genre_neighbors=10,
                    ),
                )

    def test_score_ordering_and_cold_abstention_are_explicit(self) -> None:
        settings = FullGraphSignalSettings(
            maximum_evaluation_artists=100,
            maximum_genre_neighbors=10,
        )
        untrimmed = _csr(
            rows=array("I", [0, 0, 0]),
            columns=array("I", [1, 2, 3]),
            values=array("f", [0.9, 0.9, 0.1]),
            shape=(4, 4),
        )
        trimmed = _trim_rows(untrimmed, 2)
        self.assertEqual(trimmed.indices.tolist(), [1, 2])
        self.assertTrue(np.allclose(trimmed.data, [0.9, 0.9]))

        train = _csr(
            rows=array("I", [0, 1]),
            columns=array("I", [0, 1]),
            values=array("f", [1.0, 1.0]),
            shape=(2, 6291),
        )
        neighbors = _csr(
            rows=array("I", [0]),
            columns=array("I", [1]),
            values=array("f", [1.0]),
            shape=(6291, 6291),
        )
        evaluation = _evaluate_membership(
            "binary_jaccard_all_open", train, neighbors, {0: {1, 2}}, settings
        )
        self.assertEqual(evaluation.anchored.heldout_pair_count, 1)
        self.assertEqual(evaluation.anchored.scoreable_pair_count, 1)
        self.assertEqual(evaluation.anchored.recall_at_1, 1.0)
        self.assertEqual(evaluation.split_cold.heldout_pair_count, 1)
        self.assertEqual(evaluation.split_cold.scoreable_pair_count, 0)
        self.assertEqual(evaluation.split_cold.abstained_pair_count, 1)
        self.assertEqual(evaluation.split_cold.recall_at_10, 0.0)

        peer_neighbors = _csr(
            rows=array("I", [0] * 11),
            columns=array("I", list(range(1, 12))),
            values=array("f", [0.1] * 10 + [0.9]),
            shape=(6291, 6291),
        )
        peer = _peer_recovery(peer_neighbors, {0: {0, 11}}, settings)
        self.assertEqual(peer.heldout_open_peer_pair_count, 1)
        self.assertEqual(peer.recall_at_10, 1.0)

    def test_cooccurrence_bound_and_review_only_overlapping_containment(self) -> None:
        settings = FullGraphSignalSettings(
            maximum_genres_per_artist_for_cooccurrence=32,
            minimum_containment_child_support=3,
            minimum_containment_score=1.0,
        )
        dense_rows = array("I", (row for row in range(11) for _ in range(11)))
        dense_columns = array("I", (column for _ in range(11) for column in range(11)))
        dense_values = array("f", (1.0 for _ in range(121)))
        with self.assertRaisesRegex(ValueError, "cooccurrence bound"):
            _cooccurrence(
                _csr(dense_rows, dense_columns, dense_values, (11, 6291)),
                settings.model_copy(update={"maximum_cooccurrence_nnz": 100}),
            )

        binary = _csr(
            rows=array("I", [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3]),
            columns=array("I", [0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1]),
            values=array("f", [1.0] * 11),
            shape=(4, 6291),
        )
        pair_data = _PairData(
            rows=array("I"),
            columns=array("I"),
            full_weights=array("f"),
            direct_weights=array("f"),
            support_weights=array("f"),
            heldout_rows=array("I"),
            heldout_columns=array("I"),
            artist_ids=(),
            seed_ids=tuple(f"seed-{i}" for i in range(6291)),
            claims_streamed=0,
            channel_pairs=ChannelPairCounts(
                artist_direct=0, release_group_support=0, reviewed_alias_context=0
            ),
        )
        candidates, coverage = _containment_candidates(
            binary, _cooccurrence(binary, settings), pair_data, settings
        )
        self.assertEqual(
            {(item.parent_seed_id, item.child_seed_id) for item in candidates},
            {("seed-0", "seed-2"), ("seed-1", "seed-2")},
        )
        self.assertEqual(coverage.overlapping_parent_child_count, 1)
        self.assertTrue(all(item.disposition == "review_candidate" for item in candidates))
        self.assertFalse(coverage.inferred_as_factual)
