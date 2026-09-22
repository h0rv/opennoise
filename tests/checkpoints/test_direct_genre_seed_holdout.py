"""Boundaries for direct-candidate versus H3 positive-only evaluation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.checkpoints.direct_genre_seed_holdout import build_direct_genre_seed_holdout
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
    receipt_sha256,
)

_SHA = "a" * 64
_ARTIST = "123e4567-e89b-12d3-a456-426614174000"


class DirectGenreSeedHoldoutTests(unittest.TestCase):
    """The evaluator preserves exact identity and positive-only abstentions."""

    def test_exact_seed_join_accounts_for_novel_and_abstained_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            receipt, object_store = _custody(directory, ("item1", "item2", "item3"))
            public = _write(
                directory / "public.json", {"genres": [{"node_id": "item1"}, {"node_id": "item4"}]}
            )
            historical = _write(
                directory / "historical.json",
                {
                    "nodes": [
                        {"genre_id": "enao-legacy:item1", "membership_count": 1},
                        {"genre_id": "enao-legacy:item2", "membership_count": 2},
                        {"genre_id": "enao-legacy:item3", "membership_count": 0},
                    ]
                },
            )
            report = build_direct_genre_seed_holdout(
                custody_receipt_path=receipt,
                custody_object_store=object_store,
                public_static_discovery_path=public,
                historical_semantic_path=historical,
            )
        self.assertEqual(
            report["seed_sets"],
            {
                "direct_reconciliation_safe_seed_count": 3,
                "current_public_seed_count": 2,
                "shared_direct_and_public_seed_count": 1,
                "direct_outside_current_public_seed_count": 2,
                "current_public_only_seed_count": 1,
            },
        )
        coverage = report["novel_direct_historical_identity_smoke"]
        if not isinstance(coverage, dict):
            self.fail("holdout report must contain an identity-smoke object")
        self.assertEqual(coverage["observed_positive_seed_count"], 1)
        self.assertEqual(coverage["zero_membership_abstention_count"], 1)
        self.assertEqual(coverage["unknown_historical_identity_abstention_count"], 0)
        self.assertFalse(coverage["quality_inference_supported"])
        self.assertFalse(report["precision_or_negative_metrics_computed"])

    def test_historical_prefix_is_required_for_identity_safe_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            receipt, object_store = _custody(directory, ("item1",))
            public = _write(directory / "public.json", {"genres": []})
            historical = _write(
                directory / "historical.json",
                {"nodes": [{"genre_id": "item1", "membership_count": 1}]},
            )
            with self.assertRaisesRegex(ValueError, "retained seed prefix"):
                build_direct_genre_seed_holdout(
                    custody_receipt_path=receipt,
                    custody_object_store=object_store,
                    public_static_discovery_path=public,
                    historical_semantic_path=historical,
                )

    def test_negative_historical_membership_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            receipt, object_store = _custody(directory, ("item1",))
            public = _write(directory / "public.json", {"genres": []})
            historical = _write(
                directory / "historical.json",
                {"nodes": [{"genre_id": "enao-legacy:item1", "membership_count": -1}]},
            )
            with self.assertRaisesRegex(ValueError, "nonnegative integer"):
                build_direct_genre_seed_holdout(
                    custody_receipt_path=receipt,
                    custody_object_store=object_store,
                    public_static_discovery_path=public,
                    historical_semantic_path=historical,
                )


def _custody(directory: Path, seed_ids: tuple[str, ...]) -> tuple[Path, Path]:
    claims = [
        DirectProperGenreClaim(
            seed_id=seed_id,
            artist_mbid=_ARTIST,
            musicbrainz_genre_id="22222222-2222-4222-8222-222222222222",
            source_record_id=f"musicbrainz:artist:{_ARTIST}",
            source_record_sha256=_SHA,
            source_evidence_ref=f"fixture:{seed_id}",
        )
        for seed_id in seed_ids
    ]
    stream = b"".join(
        json.dumps(claim.model_dump(mode="json"), separators=(",", ":"), sort_keys=True).encode()
        + b"\n"
        for claim in claims
    )
    object_store = directory / "objects"
    digest = hashlib.sha256(stream).hexdigest()
    compressed = zstandard.ZstdCompressor(level=1).compress(stream)
    object_sha = hashlib.sha256(compressed).hexdigest()
    key = f"musicbrainz-direct-proper-genre-custody/sha256/{object_sha}.jsonl.zst"
    object_path = object_store / key
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(compressed)
    base = DirectProperGenreCustodyReceipt(
        source_seed_target_byte_sha256=_SHA,
        source_seed_target_output_sha256=_SHA,
        reconciliation_byte_sha256=_SHA,
        reconciliation_output_sha256=_SHA,
        claims_object_key=key,
        claims_object_sha256=object_sha,
        claims_object_byte_size=len(compressed),
        claims_uncompressed_sha256=digest,
        claim_count=len(claims),
        seed_count=len(seed_ids),
        artist_mbid_count=1,
        source_record_sha256_count=1,
        output_sha256="0" * 64,
    )
    receipt = base.model_copy(update={"output_sha256": receipt_sha256(base)})
    receipt_path = directory / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    return receipt_path, object_store


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path
