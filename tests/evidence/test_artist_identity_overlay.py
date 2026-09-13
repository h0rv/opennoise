"""Behavioral tests for the immutable evidence-graph artist-name sidecar."""

from __future__ import annotations

import shutil
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.common import sha256_file
from opennoise.evidence.artist_identity_overlay import (
    ArtistIdentityOverlayArtifact,
    ArtistIdentityOverlayError,
    ArtistIdentityOverlayInputs,
    ArtistIdentityOverlaySources,
    OverlayInput,
    artist_identity_for,
    artist_identity_overlay_sha256,
    build_artist_identity_overlay,
    certified_artist_identity_for,
    certify_artist_identity_overlay_sources,
    certify_genre_artist_evidence_sources,
    genre_artist_evidence_for,
    verify_artist_identity_overlay,
    write_artist_identity_overlay,
)
from opennoise.evidence.graph_projection import (
    ArtifactInput,
    EvidenceGraphProjectionArtifact,
    artifact_sha256,
)
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    ArtistMetadataCounters,
    ArtistMetadataSettings,
    artist_metadata_artifact_sha256,
)

_ARTIST_A = "00000000-0000-4000-8000-000000000001"
_ARTIST_B = "00000000-0000-4000-8000-000000000002"
_ARTIST_C = "00000000-0000-4000-8000-000000000003"


class ArtistIdentityOverlayTests(unittest.TestCase):
    def test_complete_overlay_preserves_source_bytes_and_exposes_exact_lookup(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "graph.sqlite"
            metadata = root / "metadata.sqlite"
            _graph_database(graph)
            _metadata_database(metadata)
            graph_receipt = _graph_receipt(graph)
            metadata_receipt = _metadata_receipt(metadata)
            graph_receipt_path = root / "graph.receipt.json"
            metadata_receipt_path = root / "metadata.receipt.json"
            graph_receipt_path.write_bytes(graph_receipt.model_dump_json().encode())
            metadata_receipt_path.write_bytes(metadata_receipt.model_dump_json().encode())
            graph_before = graph.read_bytes()
            metadata_before = metadata.read_bytes()

            artifact = build_artist_identity_overlay(
                ArtistIdentityOverlayInputs(
                    graph_database=graph,
                    graph_receipt=graph_receipt_path,
                    metadata_database=metadata,
                    metadata_receipt=metadata_receipt_path,
                    output_database=root / "overlay.sqlite",
                )
            )
            relocated = root / "relocated"
            relocated.mkdir()
            for source in (graph, metadata, graph_receipt_path, metadata_receipt_path):
                shutil.copyfile(source, relocated / source.name)
            relocated_artifact = build_artist_identity_overlay(
                ArtistIdentityOverlayInputs(
                    graph_database=relocated / graph.name,
                    graph_receipt=relocated / graph_receipt_path.name,
                    metadata_database=relocated / metadata.name,
                    metadata_receipt=relocated / metadata_receipt_path.name,
                    output_database=relocated / "overlay.sqlite",
                )
            )
            sources = ArtistIdentityOverlaySources(root / "overlay.sqlite", artifact)
            certified = certify_artist_identity_overlay_sources(sources)
            observed = certified_artist_identity_for(certified, _ARTIST_A)
            ambiguous = artist_identity_for(sources, _ARTIST_B)
            absent = artist_identity_for(sources, _ARTIST_C)
            genre_sources = certify_genre_artist_evidence_sources(graph, certified)
            evidence = genre_artist_evidence_for(genre_sources, "seed-a", limit=10)

            self.assertEqual(graph.read_bytes(), graph_before)
            self.assertEqual(metadata.read_bytes(), metadata_before)
            self.assertEqual(artifact.artist_identity_count, 3)
            self.assertEqual(artifact.canonical_name_count, 1)
            self.assertEqual(artifact.ambiguous_name_count, 1)
            self.assertEqual(artifact.metadata_missing_count, 1)
            self.assertEqual(relocated_artifact, artifact)
            self.assertEqual(observed.canonical_name if observed else None, "Canonical A")
            self.assertEqual(observed.representative_release_group_id if observed else None, "rg-a")
            self.assertEqual(ambiguous.name_status if ambiguous else None, "ambiguous_name")
            self.assertEqual(absent.name_status if absent else None, "metadata_missing")
            self.assertIsNone(certified_artist_identity_for(certified, "not-an-artist"))
            self.assertEqual(evidence.total_artist_count, 3)
            self.assertEqual(evidence.total_unnamed_artist_count, 2)
            self.assertEqual(evidence.returned_artist_count, 3)
            self.assertEqual(evidence.returned_unnamed_artist_count, 2)
            self.assertEqual(evidence.artists[0].artist.canonical_name, "Canonical A")
            self.assertEqual(evidence.artists[1].artist.name_status, "ambiguous_name")
            self.assertEqual(evidence.artists[2].artist.name_status, "metadata_missing")
            self.assertEqual(evidence.artists[0].membership_claim_count, 2)
            self.assertIsNone(evidence.artists[0].evidence_weight)

    def test_tampered_receipt_is_rejected_and_serialization_replays(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = _overlay_artifact()
            verify_artist_identity_overlay(artifact)
            with self.assertRaises(ArtistIdentityOverlayError):
                verify_artist_identity_overlay(
                    artifact.model_copy(update={"output_sha256": "0" * 64})
                )
            receipt = root / "overlay.receipt.json"
            write_artist_identity_overlay(receipt, artifact)
            self.assertEqual(
                ArtistIdentityOverlayArtifact.model_validate_json(receipt.read_bytes()), artifact
            )


def _graph_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as database:
        database.executescript(
            """PRAGMA foreign_keys=ON;
CREATE TABLE identity(namespace TEXT NOT NULL, identifier TEXT NOT NULL,
PRIMARY KEY(namespace, identifier)) WITHOUT ROWID;
CREATE TABLE claim(
subject_namespace TEXT NOT NULL, subject_identifier TEXT NOT NULL,
predicate TEXT NOT NULL, object_namespace TEXT NOT NULL, object_identifier TEXT NOT NULL,
evidence_kind TEXT NOT NULL, source TEXT NOT NULL, facet TEXT NOT NULL,
provenance_ref TEXT NOT NULL, release_group_id TEXT NOT NULL);"""
        )
        database.executemany(
            "INSERT INTO identity(namespace, identifier) VALUES ('musicbrainz_artist', ?)",
            ((_ARTIST_A,), (_ARTIST_B,), (_ARTIST_C,)),
        )
        database.executemany(
            """INSERT INTO claim(
                   subject_namespace, subject_identifier, predicate, object_namespace,
                   object_identifier, evidence_kind, source, facet, provenance_ref,
                   release_group_id
                   ) VALUES ('musicbrainz_artist', ?, 'artist_membership',
                         'stable_seed', 'seed-a', ?, 'musicbrainz', 'genre', ?, ?)""",
            (
                (_ARTIST_A, "artist_direct", "proof-a", "rg-a"),
                (_ARTIST_A, "release_group_support", "proof-a-support", "rg-a-support"),
                (_ARTIST_B, "release_group_support", "proof-b", "rg-b"),
                (_ARTIST_C, "release_group_support", "proof-c", "rg-c"),
            ),
        )
        database.commit()


def _metadata_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as database:
        database.executescript(
            """CREATE TABLE artist_summary(
artist_mbid TEXT PRIMARY KEY NOT NULL, canonical_name TEXT) WITHOUT ROWID;
CREATE TABLE canonical_name_variant(
artist_mbid TEXT NOT NULL, canonical_name TEXT NOT NULL,
representative_release_group_id TEXT NOT NULL,
representative_record_ordinal INTEGER NOT NULL,
representative_record_sha256 TEXT NOT NULL,
PRIMARY KEY(artist_mbid, canonical_name)) WITHOUT ROWID;"""
        )
        database.executemany(
            "INSERT INTO artist_summary(artist_mbid, canonical_name) VALUES (?, ?)",
            ((_ARTIST_A, "Canonical A"), (_ARTIST_B, None)),
        )
        database.execute(
            """INSERT INTO canonical_name_variant(
                   artist_mbid, canonical_name, representative_release_group_id,
                   representative_record_ordinal, representative_record_sha256
               ) VALUES (?, ?, ?, ?, ?)""",
            (_ARTIST_A, "Canonical A", "rg-a", 7, "a" * 64),
        )
        database.commit()


def _graph_receipt(database: Path) -> EvidenceGraphProjectionArtifact:
    digest, size = sha256_file(database)
    inputs = tuple(
        ArtifactInput(
            role=f"input-{index}",
            path=f"input-{index}",
            byte_sha256="a" * 64,
            byte_count=1,
            logical_sha256="b" * 64,
        )
        for index in range(8)
    )
    base = EvidenceGraphProjectionArtifact(
        inputs=inputs,
        database_sha256=digest,
        database_bytes=size,
        identity_count=6291,
        total_identity_count=6291,
        claim_count=0,
        abstention_count=0,
        factual_relation_count=0,
        candidate_relation_score_count=0,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": artifact_sha256(base)})


def _metadata_receipt(database: Path) -> ArtistMetadataArtifact:
    digest, size = sha256_file(database)
    base = ArtistMetadataArtifact(
        source_archive_sha256="c" * 64,
        source_archive_bytes=1,
        source_snapshot="fixture",
        evidence_output_sha256="d" * 64,
        evidence_database_sha256="e" * 64,
        evidence_database_bytes=1,
        metadata_database_sha256=digest,
        metadata_database_bytes=size,
        target_artist_count=3,
        observed_artist_count=2,
        conflicting_artist_count=1,
        counters=ArtistMetadataCounters(
            records_seen=1, records_parsed=1, rejected_records=0, target_credit_observations=1
        ),
        settings=ArtistMetadataSettings(),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": artist_metadata_artifact_sha256(base)})


def _overlay_artifact() -> ArtistIdentityOverlayArtifact:
    inputs = tuple(
        OverlayInput(
            role=role,
            locator=role,
            byte_sha256="f" * 64,
            byte_count=1,
            logical_sha256="a" * 64,
        )
        for role in sorted(
            {
                "evidence_graph_database",
                "evidence_graph_receipt",
                "musicbrainz_artist_metadata_database",
                "musicbrainz_artist_metadata_receipt",
            }
        )
    )
    base = ArtistIdentityOverlayArtifact(
        inputs=inputs,
        database_sha256="b" * 64,
        database_bytes=1,
        artist_identity_count=3,
        canonical_name_count=1,
        metadata_missing_count=1,
        ambiguous_name_count=1,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": artist_identity_overlay_sha256(base)})


if __name__ == "__main__":
    unittest.main()
