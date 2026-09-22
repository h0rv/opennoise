"""Tests for the custody-only direct discovery delta report."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import zstandard

from opennoise.checkpoints.musicbrainz_direct_discovery_delta import (
    DirectDiscoveryDeltaError,
    build_musicbrainz_direct_discovery_delta,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
    receipt_sha256,
)

_SHA = "a" * 64
_ARTISTS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
)


class MusicBrainzDirectDiscoveryDeltaTests(unittest.TestCase):
    """The report stays custody-bound and verifies the current assets."""

    def test_reports_exact_seed_delta_and_name_abstention(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            receipt, object_store = _custody(directory)
            static, manifest, atlas = _certified_site(directory)
            report = build_musicbrainz_direct_discovery_delta(
                custody_receipt_path=receipt,
                custody_object_store=object_store,
                static_discovery_path=static,
                certified_manifest_path=manifest,
                certified_layout_path=atlas,
            )

        self.assertFalse(report["public_export_authorized"])
        self.assertFalse(report["release_gate"])
        self.assertEqual(
            report["seed_sets"],
            {
                "direct_seed_count": 4,
                "current_static_discovery_seed_count": 344,
                "shared_seed_count": 2,
                "candidate_only_seed_count": 2,
            },
        )
        self.assertEqual(
            report["candidate_only_placement"],
            {"placed_seed_count": 1, "unplaced_seed_count": 1},
        )
        evidence = report["evidence_counts"]
        self.assertIsInstance(evidence, dict)
        candidate = _mapping(_mapping(evidence)["candidate_only"])
        self.assertEqual(candidate["observation_count"], 3)
        self.assertEqual(candidate["distinct_seed_artist_pair_count"], 2)
        self.assertEqual(_mapping(report["name_display_coverage"])["status"], "abstained")
        self.assertEqual(
            _mapping(report["review_projection"])["static_ui_json_size_estimate"], "abstained"
        )

    def test_rejects_asset_that_no_longer_matches_manifest(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            receipt, object_store = _custody(directory)
            static, manifest, atlas = _certified_site(directory)
            static.write_bytes(static.read_bytes() + b" ")
            with self.assertRaisesRegex(DirectDiscoveryDeltaError, "certified manifest"):
                build_musicbrainz_direct_discovery_delta(
                    custody_receipt_path=receipt,
                    custody_object_store=object_store,
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                )

    def test_rejects_mutated_custody_object_before_reporting(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            receipt, object_store = _custody(directory)
            static, manifest, atlas = _certified_site(directory)
            object_path = next(object_store.rglob("*.jsonl.zst"))
            object_path.write_bytes(object_path.read_bytes() + b"mutated")
            with self.assertRaisesRegex(DirectDiscoveryDeltaError, "custody"):
                build_musicbrainz_direct_discovery_delta(
                    custody_receipt_path=receipt,
                    custody_object_store=object_store,
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                )

    def test_rejects_atlas_that_no_longer_matches_manifest(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            receipt, object_store = _custody(directory)
            static, manifest, atlas = _certified_site(directory)
            atlas.write_bytes(atlas.read_bytes() + b" ")
            with self.assertRaisesRegex(DirectDiscoveryDeltaError, "semantic_atlas"):
                build_musicbrainz_direct_discovery_delta(
                    custody_receipt_path=receipt,
                    custody_object_store=object_store,
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                )


def _custody(directory: Path) -> tuple[Path, Path]:
    claims = tuple(
        DirectProperGenreClaim(
            seed_id=seed_id,
            artist_mbid=artist_mbid,
            musicbrainz_genre_id="99999999-9999-4999-8999-999999999999",
            source_record_id=f"musicbrainz:artist:{artist_mbid}",
            source_record_sha256=_SHA,
            source_evidence_ref=f"fixture:{index}",
        )
        for index, (seed_id, artist_mbid) in enumerate(
            (
                ("item1", _ARTISTS[0]),
                ("item2", _ARTISTS[1]),
                ("item345", _ARTISTS[2]),
                ("item346", _ARTISTS[3]),
                ("item346", _ARTISTS[3]),
            )
        )
    )
    stream = b"".join(
        json.dumps(claim.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
        for claim in claims
    )
    object_store = directory / "objects"
    compressed = zstandard.ZstdCompressor(level=1).compress(stream)
    object_sha = hashlib.sha256(compressed).hexdigest()
    key = f"musicbrainz-direct-proper-genre-custody/sha256/{object_sha}.jsonl.zst"
    object_path = object_store / key
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(compressed)
    draft = DirectProperGenreCustodyReceipt(
        source_seed_target_byte_sha256=_SHA,
        source_seed_target_output_sha256=_SHA,
        reconciliation_byte_sha256=_SHA,
        reconciliation_output_sha256=_SHA,
        claims_object_key=key,
        claims_object_sha256=object_sha,
        claims_object_byte_size=len(compressed),
        claims_uncompressed_sha256=hashlib.sha256(stream).hexdigest(),
        claim_count=len(claims),
        seed_count=4,
        artist_mbid_count=4,
        source_record_sha256_count=1,
        output_sha256="0" * 64,
    )
    receipt = draft.model_copy(update={"output_sha256": receipt_sha256(draft)})
    receipt_path = directory / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
    return receipt_path, object_store


def _certified_site(directory: Path) -> tuple[Path, Path, Path]:
    site = directory / "site"
    assets = site / "assets"
    assets.mkdir(parents=True)
    static = assets / "static.json"
    atlas = assets / "atlas.json"
    static.write_text(
        json.dumps({"genres": [{"node_id": f"item{index}"} for index in range(1, 345)]}),
        encoding="utf-8",
    )
    atlas.write_text(
        json.dumps({"nodes": [{"id": f"item{index}"} for index in range(1, 346)]}),
        encoding="utf-8",
    )
    manifest = site / "opennoise-static-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "assets": {
                    "static_discovery": {
                        "path": "assets/static.json",
                        "sha256": hashlib.sha256(static.read_bytes()).hexdigest(),
                    },
                    "semantic_atlas": {
                        "path": "assets/atlas.json",
                        "sha256": hashlib.sha256(atlas.read_bytes()).hexdigest(),
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return static, manifest, atlas


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return {str(key): item for key, item in value.items()}
