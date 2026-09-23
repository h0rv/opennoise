"""Tests for the local pending MusicBrainz static policy-review input."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from opennoise.checkpoints.musicbrainz_direct_local_static_candidate import (
    LocalCandidateShard,
    LocalMusicBrainzStaticCandidateManifest,
    local_candidate_manifest_sha256,
)
from opennoise.checkpoints.musicbrainz_direct_static_policy_review import (
    MusicBrainzDirectStaticPolicyReviewError,
    build_musicbrainz_direct_static_policy_review_input,
    write_musicbrainz_direct_static_policy_review_input,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

_DIRECT_OUTPUT_SHA = "a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9"
_SEED_IDS = tuple(f"item{index:03d}" for index in range(412))


class MusicBrainzDirectStaticPolicyReviewTests(unittest.TestCase):
    """Keep the policy input pending and tied to its exact local candidate."""

    def test_returns_pending_input_with_exact_candidate_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            direct_path = directory / "direct.json"
            candidate_path = directory / "candidate.json"
            self._write_direct(direct_path)
            candidate = self._candidate()
            candidate_path.write_bytes(candidate.model_dump_json().encode())

            with self._pins(candidate.output_sha256, candidate_path):
                review = build_musicbrainz_direct_static_policy_review_input(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_object_store=self._object_store(),
                    local_candidate_manifest_path=candidate_path,
                )

        self.assertEqual(review.review_decision, "pending")
        self.assertEqual(review.placed_candidate_seed_ids, _SEED_IDS)
        self.assertEqual(
            review.proposed_public_source_wording,
            "MusicBrainz proper-genre observation on this artist record.",
        )
        self.assertEqual(
            review.required_quality_report_fields,
            (
                "source_coverage",
                "duplicate_count",
                "exclusion_count",
                "ambiguous_name_rejection_count",
                "per_genre_row_counts",
                "manually_sampled_public_source_links",
            ),
        )
        self.assertFalse(review.public_export_authorized)
        self.assertFalse(review.serving_authorized)

    def test_writes_review_once_without_replacing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            direct_path = directory / "direct.json"
            candidate_path = directory / "candidate.json"
            output_path = directory / "review.json"
            self._write_direct(direct_path)
            candidate = self._candidate()
            candidate_path.write_bytes(candidate.model_dump_json().encode())

            with self._pins(candidate.output_sha256, candidate_path):
                review = build_musicbrainz_direct_static_policy_review_input(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_object_store=self._object_store(),
                    local_candidate_manifest_path=candidate_path,
                )
                output_sha256 = write_musicbrainz_direct_static_policy_review_input(
                    output_path, review
                )
                actual_output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
                with self.assertRaisesRegex(MusicBrainzDirectStaticPolicyReviewError, "exists"):
                    write_musicbrainz_direct_static_policy_review_input(output_path, review)

        self.assertEqual(output_sha256, actual_output_sha256)

    def test_rejects_candidate_with_a_different_direct_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            direct_path = directory / "direct.json"
            candidate_path = directory / "candidate.json"
            self._write_direct(direct_path)
            candidate = self._candidate(direct_custody_output_sha256="c" * 64)
            candidate_path.write_bytes(candidate.model_dump_json().encode())

            with (
                self._pins(candidate.output_sha256, candidate_path),
                self.assertRaisesRegex(
                    MusicBrainzDirectStaticPolicyReviewError, "different direct custody"
                ),
            ):
                build_musicbrainz_direct_static_policy_review_input(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_object_store=self._object_store(),
                    local_candidate_manifest_path=candidate_path,
                )

    def test_rejects_candidate_that_does_not_have_412_seed_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            direct_path = directory / "direct.json"
            candidate_path = directory / "candidate.json"
            self._write_direct(direct_path)
            candidate = self._candidate(seed_ids=_SEED_IDS[:-1])
            candidate_path.write_bytes(candidate.model_dump_json().encode())

            with (
                self._pins(candidate.output_sha256, candidate_path),
                self.assertRaisesRegex(
                    MusicBrainzDirectStaticPolicyReviewError, "local candidate manifest is invalid"
                ),
            ):
                build_musicbrainz_direct_static_policy_review_input(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_object_store=self._object_store(),
                    local_candidate_manifest_path=candidate_path,
                )

    @staticmethod
    def _pins(candidate_output_sha256: str, candidate_path: Path) -> AbstractContextManager[object]:
        return patch.multiple(
            "opennoise.checkpoints.musicbrainz_direct_static_policy_review",
            _PINNED_DIRECT_CUSTODY_RECEIPT_OUTPUT_SHA256=_DIRECT_OUTPUT_SHA,
            _PINNED_LOCAL_CANDIDATE_MANIFEST_OUTPUT_SHA256=candidate_output_sha256,
            _PINNED_DIRECT_CUSTODY_RECEIPT_BYTE_SHA256=hashlib.sha256(
                Path(
                    "config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json"
                ).read_bytes()
            ).hexdigest(),
            _PINNED_LOCAL_CANDIDATE_MANIFEST_BYTE_SHA256=hashlib.sha256(
                candidate_path.read_bytes()
            ).hexdigest(),
        )

    @staticmethod
    def _write_direct(path: Path) -> None:
        fixture = Path("config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json")
        path.write_bytes(fixture.read_bytes())

    @staticmethod
    def _object_store() -> Path:
        return Path("data/release/musicbrainz-direct-proper-genre-custody-v1/objects")

    @staticmethod
    def _candidate(
        *,
        direct_custody_output_sha256: str = _DIRECT_OUTPUT_SHA,
        seed_ids: tuple[str, ...] = _SEED_IDS,
    ) -> LocalMusicBrainzStaticCandidateManifest:
        shards = tuple(
            LocalCandidateShard(
                seed_id=seed_id,
                ordinal=0,
                path="genres/" + f"{index:064x}" + "/0000." + "1" * 64 + ".jsonl",
                row_count=1,
                sha256="1" * 64,
                byte_count=1,
            )
            for index, seed_id in enumerate(seed_ids)
        )
        unsealed = LocalMusicBrainzStaticCandidateManifest(
            direct_custody_receipt_sha256="2" * 64,
            direct_custody_output_sha256=direct_custody_output_sha256,
            direct_claims_object_sha256="3" * 64,
            canonical_name_receipt_sha256="4" * 64,
            canonical_name_object_sha256="5" * 64,
            recovered_name_receipt_sha256="6" * 64,
            recovered_name_object_sha256="7" * 64,
            certified_static_discovery_sha256="8" * 64,
            certified_semantic_atlas_sha256="9" * 64,
            placed_candidate_seed_ids=_SEED_IDS,
            membership_count=len(_SEED_IDS),
            shards=shards
            if seed_ids == _SEED_IDS
            else tuple(
                LocalCandidateShard(
                    seed_id=seed_id,
                    ordinal=0,
                    path="genres/" + f"{index:064x}" + "/0000." + "1" * 64 + ".jsonl",
                    row_count=1,
                    sha256="1" * 64,
                    byte_count=1,
                )
                for index, seed_id in enumerate(_SEED_IDS)
            ),
            output_sha256="0" * 64,
            public_export_authorized=False,
            serving_authorized=False,
            membership_claims_authorized=False,
            release_gate=False,
        )
        output_sha = local_candidate_manifest_sha256(unsealed)
        updates: dict[str, object] = {"output_sha256": output_sha}
        if seed_ids != _SEED_IDS:
            updates["placed_candidate_seed_ids"] = seed_ids
        return unsealed.model_copy(update=updates)
