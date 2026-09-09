from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple
from unittest.mock import patch

from musix.local_reviewed_alias_context_store import (
    LocalReviewedAliasContextStore,
    LocalReviewedAliasContextStoreError,
)
from musix.ingest.musicbrainz_model_adapter import MusicBrainzModelAdapterReport
from musix.ingest.musicbrainz_reviewed_alias_context import (
    ReviewedAliasCombinedModelReceipt,
    ReviewedAliasContextArtifact,
    ReviewedAliasContextMembership,
)
from musix.routes import _union_observed_artists, _union_observed_seeds
from musix.taxonomy.seed_reconciliation import SeedReconciliationArtifact, SeedReconciliationDisposition

_ARTIST = "00000000-0000-4000-8000-000000000001"
_PEER_SHA = "201a5061c2bcd0b71e7d6ac867e8a42d76b3c8cfed0318d88752cfbae12853eb"


class _Artist(NamedTuple):
    artist_mbid: str


class _Seed(NamedTuple):
    source_item_id: str


class LocalReviewedAliasContextStoreTests(unittest.TestCase):
    def test_observed_artist_union_deduplicates_five_overlaps_to_685(self) -> None:
        direct = tuple(_Artist(f"artist-{number}") for number in range(7))
        context = tuple(_Artist(f"artist-{number}") for number in range(2, 685))

        observed = _union_observed_artists(direct, context)

        self.assertEqual(len(context), 683)
        self.assertEqual(len(observed), 685)
        self.assertEqual(observed[:7], direct)

    def test_empty_overlay_keeps_the_direct_artist_baseline_and_reverse_seed(self) -> None:
        direct_artists = (_Artist(_ARTIST),)
        direct_seeds = (_Seed("item887"),)

        self.assertEqual(_union_observed_artists(direct_artists, ()), direct_artists)
        self.assertEqual(_union_observed_seeds(direct_seeds, ()), direct_seeds)
        self.assertEqual(
            _union_observed_seeds(direct_seeds, (_Seed("item887"), _Seed("item2"))),
            (_Seed("item887"), _Seed("item2")),
        )

    def test_startup_verifies_once_and_preserves_context_provenance(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_path = root / "artifact.json"
            receipt_path = root / "receipt.json"
            artifact_path.write_text("{}", encoding="utf-8")
            receipt_path.write_text("{}", encoding="utf-8")
            peer_index = _peer_index(root / "peers.sqlite", _PEER_SHA)
            store = _store(artifact_path, receipt_path, peer_index)
            with (
                patch(
                    "musix.local_reviewed_alias_context_store.ReviewedAliasContextArtifact.model_validate_json",
                    return_value=_artifact(),
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.ReviewedAliasCombinedModelReceipt.model_validate_json",
                    return_value=_receipt(),
                ),
                patch(
                    "musix.local_reviewed_alias_context_store."
                    "verify_reviewed_alias_context_artifact"
                ) as verify_artifact,
                patch(
                    "musix.local_reviewed_alias_context_store."
                    "verify_reviewed_alias_combined_model_receipt"
                ) as verify_receipt,
            ):
                store.start()
                artists = store.artist_rows("item887")
                seeds = store.seed_rows(_ARTIST)

        self.assertTrue(store.configured)
        self.assertEqual(verify_artifact.call_count, 1)
        self.assertEqual(verify_receipt.call_count, 1)
        self.assertEqual(artists[0].artist_mbid, _ARTIST)
        self.assertEqual(artists[0].source_record_id, "record:1")
        self.assertEqual(seeds[0].source_item_id, "item887")
        self.assertEqual(seeds[0].name, "intelligent dance music")
        self.assertEqual(seeds[0].contextual_evidence_ref, "context:1")

    def test_startup_rejects_an_invalid_receipt_binding(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_path = root / "artifact.json"
            receipt_path = root / "receipt.json"
            artifact_path.write_text("{}", encoding="utf-8")
            receipt_path.write_text("{}", encoding="utf-8")
            store = _store(
                artifact_path, receipt_path, _peer_index(root / "peers.sqlite", _PEER_SHA)
            )
            wrong = _receipt().model_copy(update={"reviewed_alias_context_output_sha256": "b" * 64})
            with (
                patch(
                    "musix.local_reviewed_alias_context_store.ReviewedAliasContextArtifact.model_validate_json",
                    return_value=_artifact(),
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.ReviewedAliasCombinedModelReceipt.model_validate_json",
                    return_value=wrong,
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.verify_reviewed_alias_context_artifact"
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.verify_reviewed_alias_combined_model_receipt"
                ),
                self.assertRaisesRegex(LocalReviewedAliasContextStoreError, "binding is invalid"),
            ):
                store.start()

    def test_startup_rejects_a_peer_index_from_a_different_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_path = root / "artifact.json"
            receipt_path = root / "receipt.json"
            artifact_path.write_text("{}", encoding="utf-8")
            receipt_path.write_text("{}", encoding="utf-8")
            store = _store(
                artifact_path, receipt_path, _peer_index(root / "peers.sqlite", "a" * 64)
            )
            with (
                patch(
                    "musix.local_reviewed_alias_context_store.ReviewedAliasContextArtifact.model_validate_json",
                    return_value=_artifact(),
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.ReviewedAliasCombinedModelReceipt.model_validate_json",
                    return_value=_receipt(),
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.verify_reviewed_alias_context_artifact"
                ),
                patch(
                    "musix.local_reviewed_alias_context_store.verify_reviewed_alias_combined_model_receipt"
                ),
                self.assertRaisesRegex(LocalReviewedAliasContextStoreError, "does not match"),
            ):
                store.start()


def _store(
    artifact_path: Path, receipt_path: Path, peer_index_path: Path
) -> LocalReviewedAliasContextStore:
    return LocalReviewedAliasContextStore(
        artifact_path,
        receipt_path,
        peer_index_path,
        _adapter_report(),
        _reconciliation(),
    )


def _artifact() -> ReviewedAliasContextArtifact:
    membership = ReviewedAliasContextMembership.model_construct(
        seed_source_item_id="item887",
        artist_id=_ARTIST,
        source_record_id="record:1",
        contextual_evidence_ref="context:1",
        approval_ref="reviewed:idm-v1",
    )
    return ReviewedAliasContextArtifact.model_construct(
        output_sha256="a" * 64,
        baseline_output_sha256="c" * 64,
        memberships=(membership,),
    )


def _receipt() -> ReviewedAliasCombinedModelReceipt:
    return ReviewedAliasCombinedModelReceipt.model_construct(
        reviewed_alias_context_output_sha256="a" * 64,
        baseline_seed_target_output_sha256="c" * 64,
    )


def _adapter_report() -> MusicBrainzModelAdapterReport:
    return MusicBrainzModelAdapterReport.model_construct(seed_target_output_sha256="c" * 64)


def _reconciliation() -> SeedReconciliationArtifact:
    row = SeedReconciliationDisposition.model_construct(
        source_item_id="item887", seed_name="intelligent dance music"
    )
    return SeedReconciliationArtifact.model_construct(dispositions=(row,))


def _peer_index(path: Path, artifact_sha256: str) -> Path:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            (("artifact_output_sha256", artifact_sha256),),
        )
    return path
