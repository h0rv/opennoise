"""Tests for the exact-MBID local direct-name frontier join."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import zstandard

from opennoise.checkpoints.musicbrainz_direct_name_join_frontier import (
    DirectNameJoinFrontierError,
    build_musicbrainz_direct_name_join_frontier,
)
from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    DirectArtistNameRecoveryReceipt,
    DirectArtistNameRecoveryRow,
)
from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    receipt_sha256 as recovery_receipt_sha256,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    CanonicalArtistName,
    DirectCanonicalArtistNameCustodyReceipt,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    receipt_sha256 as name_receipt_sha256,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    receipt_sha256 as direct_receipt_sha256,
)

_SHA = "a" * 64
_ARTISTS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
)


class MusicBrainzDirectNameJoinFrontierTests(unittest.TestCase):
    """Only identical UUID MBIDs join a direct pair to a name fact."""

    def test_reports_named_and_unnamed_distinct_pairs_by_exact_mbid(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            direct_path, direct_store, name_path, name_store = _custodies(directory)
            static, manifest, atlas = _certified_site(directory)
            report = build_musicbrainz_direct_name_join_frontier(
                direct_custody_receipt_path=direct_path,
                direct_custody_receipt_sha256=_sha256(direct_path),
                direct_object_store=direct_store,
                name_custody_receipt_path=name_path,
                name_custody_receipt_sha256=_sha256(name_path),
                name_object_store=name_store,
                static_discovery_path=static,
                certified_manifest_path=manifest,
                certified_layout_path=atlas,
            )

        self.assertFalse(report.public_export_authorized)
        self.assertFalse(report.serving_authorized)
        self.assertEqual(report.candidate_only_seed_count, 2)
        self.assertEqual(report.candidate_only_direct_artist_pair_count, 2)
        self.assertEqual(report.candidate_only_named_direct_artist_pair_count, 1)
        self.assertEqual(report.candidate_only_unnamed_direct_artist_pair_count, 1)
        self.assertEqual(report.candidate_only_exact_display_coverage, 0.5)
        self.assertEqual(
            tuple(
                (
                    row.seed_id,
                    row.direct_artist_pair_count,
                    row.named_direct_artist_pair_count,
                    row.unnamed_direct_artist_pair_count,
                )
                for row in report.candidate_only_per_seed
            ),
            (("item345", 1, 1, 0), ("item346", 1, 0, 1)),
        )
        payload = report.proposed_static_payload
        self.assertEqual(payload["status"], "derived_local_estimate")
        self.assertFalse(payload["public_asset_written"])
        self.assertEqual(payload["row_count"], 1)

    def test_rejects_substituted_receipt_before_streaming(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            direct_path, direct_store, name_path, name_store = _custodies(directory)
            static, manifest, atlas = _certified_site(directory)
            with self.assertRaisesRegex(DirectNameJoinFrontierError, "expected SHA-256"):
                build_musicbrainz_direct_name_join_frontier(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_receipt_sha256="b" * 64,
                    direct_object_store=direct_store,
                    name_custody_receipt_path=name_path,
                    name_custody_receipt_sha256=_sha256(name_path),
                    name_object_store=name_store,
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                )

    def test_unions_verified_unique_recovery_names_by_exact_mbid(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            direct_path, direct_store, name_path, name_store = _custodies(directory)
            recovery_path, recovery_store = _recovery(directory, direct_path, name_path)
            recovery_receipt_sha256 = _sha256(recovery_path)
            static, manifest, atlas = _certified_site(directory)
            report = build_musicbrainz_direct_name_join_frontier(
                direct_custody_receipt_path=direct_path,
                direct_custody_receipt_sha256=_sha256(direct_path),
                direct_object_store=direct_store,
                name_custody_receipt_path=name_path,
                name_custody_receipt_sha256=_sha256(name_path),
                name_object_store=name_store,
                static_discovery_path=static,
                certified_manifest_path=manifest,
                certified_layout_path=atlas,
                recovery_receipt_path=recovery_path,
                recovery_receipt_sha256=recovery_receipt_sha256,
                recovery_object_store=recovery_store,
            )

        self.assertFalse(report.public_export_authorized)
        self.assertFalse(report.serving_authorized)
        self.assertFalse(report.membership_claims_authorized)
        self.assertFalse(report.release_gate)
        self.assertEqual(report.candidate_only_named_direct_artist_pair_count, 2)
        self.assertEqual(report.candidate_only_unnamed_direct_artist_pair_count, 0)
        self.assertEqual(report.candidate_only_exact_display_coverage, 1.0)
        self.assertEqual(report.proposed_static_payload["row_count"], 2)
        self.assertEqual(report.inputs["recovery_receipt_byte_sha256"], recovery_receipt_sha256)
        self.assertIn("recovery_receipt_output_sha256", report.inputs)
        self.assertIn("recovery_object_sha256", report.inputs)

    def test_rejects_recovery_bound_to_another_name_custody_cohort(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            direct_path, direct_store, name_path, name_store = _custodies(directory)
            recovery_path, recovery_store = _recovery(
                directory, direct_path, name_path, bound_name_receipt_sha256="b" * 64
            )
            static, manifest, atlas = _certified_site(directory)
            with self.assertRaisesRegex(
                DirectNameJoinFrontierError, "different direct or canonical"
            ):
                build_musicbrainz_direct_name_join_frontier(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_receipt_sha256=_sha256(direct_path),
                    direct_object_store=direct_store,
                    name_custody_receipt_path=name_path,
                    name_custody_receipt_sha256=_sha256(name_path),
                    name_object_store=name_store,
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                    recovery_receipt_path=recovery_path,
                    recovery_receipt_sha256=_sha256(recovery_path),
                    recovery_object_store=recovery_store,
                )

    def test_rejects_partial_optional_recovery_input(self) -> None:
        with TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            direct_path, direct_store, name_path, name_store = _custodies(directory)
            static, manifest, atlas = _certified_site(directory)
            with self.assertRaisesRegex(DirectNameJoinFrontierError, "supplied together"):
                build_musicbrainz_direct_name_join_frontier(
                    direct_custody_receipt_path=direct_path,
                    direct_custody_receipt_sha256=_sha256(direct_path),
                    direct_object_store=direct_store,
                    name_custody_receipt_path=name_path,
                    name_custody_receipt_sha256=_sha256(name_path),
                    name_object_store=name_store,
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                    recovery_receipt_path=directory / "recovery.json",
                )


def _custodies(directory: Path) -> tuple[Path, Path, Path, Path]:
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
                ("item345", _ARTISTS[2]),  # exact name match
                ("item346", _ARTISTS[3]),  # missing name
                ("item346", _ARTISTS[3]),  # another source observation, same pair
            )
        )
    )
    stream = _jsonl(claim.model_dump(mode="json") for claim in claims)
    direct_store = directory / "direct-objects"
    direct_object = _write_object(
        direct_store, "musicbrainz-direct-proper-genre-custody/sha256", stream
    )
    direct_draft = DirectProperGenreCustodyReceipt(
        source_seed_target_byte_sha256=_SHA,
        source_seed_target_output_sha256=_SHA,
        reconciliation_byte_sha256=_SHA,
        reconciliation_output_sha256=_SHA,
        claims_object_key=direct_object[0],
        claims_object_sha256=direct_object[1],
        claims_object_byte_size=direct_object[2],
        claims_uncompressed_sha256=hashlib.sha256(stream).hexdigest(),
        claim_count=len(claims),
        seed_count=4,
        artist_mbid_count=4,
        source_record_sha256_count=1,
        output_sha256="0" * 64,
    )
    direct_receipt = direct_draft.model_copy(
        update={"output_sha256": direct_receipt_sha256(direct_draft)}
    )
    direct_path = directory / "direct-receipt.json"
    direct_path.write_text(direct_receipt.model_dump_json(), encoding="utf-8")

    # Artist one intentionally has the same text as artist three, but cannot name
    # artist four because the join key is the UUID MBID, never display text.
    names = (
        CanonicalArtistName(artist_mbid=_ARTISTS[0], canonical_name="Same Name"),
        CanonicalArtistName(artist_mbid=_ARTISTS[2], canonical_name="Same Name"),
    )
    name_stream = _jsonl(name.model_dump(mode="json") for name in names)
    name_store = directory / "name-objects"
    name_object = _write_object(
        name_store, "musicbrainz-direct-canonical-artist-name-custody/sha256", name_stream
    )
    name_draft = DirectCanonicalArtistNameCustodyReceipt(
        direct_custody_receipt_byte_sha256=_sha256(direct_path),
        direct_custody_receipt_output_sha256=direct_receipt.output_sha256,
        direct_claims_object_sha256=direct_receipt.claims_object_sha256,
        direct_artist_mbid_count=4,
        metadata_artifact_byte_sha256=_SHA,
        metadata_artifact_output_sha256=_SHA,
        metadata_database_sha256=_SHA,
        metadata_database_bytes=1,
        metadata_source_archive_sha256=_SHA,
        canonical_name_count=2,
        absent_direct_artist_mbid_count=2,
        names_object_key=name_object[0],
        names_object_sha256=name_object[1],
        names_object_byte_size=name_object[2],
        names_uncompressed_sha256=hashlib.sha256(name_stream).hexdigest(),
        output_sha256="0" * 64,
    )
    name_receipt = name_draft.model_copy(update={"output_sha256": name_receipt_sha256(name_draft)})
    name_path = directory / "name-receipt.json"
    name_path.write_text(name_receipt.model_dump_json(), encoding="utf-8")
    return direct_path, direct_store, name_path, name_store


def _recovery(
    directory: Path,
    direct_path: Path,
    name_path: Path,
    *,
    bound_name_receipt_sha256: str | None = None,
) -> tuple[Path, Path]:
    direct_receipt = DirectProperGenreCustodyReceipt.model_validate_json(direct_path.read_bytes())
    name_receipt = DirectCanonicalArtistNameCustodyReceipt.model_validate_json(
        name_path.read_bytes()
    )
    row = DirectArtistNameRecoveryRow(
        artist_mbid=_ARTISTS[3],
        canonical_name="Recovered Name",
        source_record_sha256=_SHA,
        source_record_ordinal=0,
        source_observation_count=1,
        name_status="unique_canonical_name",
    )
    stream = _jsonl((row.model_dump(mode="json"),))
    store = directory / "recovery-objects"
    recovery_object = _write_object(store, "musicbrainz-direct-artist-name-recovery/sha256", stream)
    draft = DirectArtistNameRecoveryReceipt(
        direct_custody_receipt_byte_sha256=_sha256(direct_path),
        direct_custody_receipt_output_sha256=direct_receipt.output_sha256,
        direct_claims_object_sha256=direct_receipt.claims_object_sha256,
        name_custody_receipt_byte_sha256=(bound_name_receipt_sha256 or _sha256(name_path)),
        name_custody_receipt_output_sha256=name_receipt.output_sha256,
        name_custody_object_sha256=name_receipt.names_object_sha256,
        source_archive_sha256=_SHA,
        source_archive_byte_size=1,
        source_record_count=1,
        direct_artist_mbid_count=4,
        prior_canonical_name_count=2,
        recovery_target_count=2,
        targeted_source_observation_count=1,
        recovered_unique_mbid_count=1,
        conflicting_mbid_count=0,
        conflicting_name_variant_count=0,
        invalid_name_observation_count=0,
        duplicate_same_name_observation_count=0,
        malformed_source_record_count=0,
        oversized_source_record_count=0,
        missing_mbid_count=1,
        invalid_name_only_mbid_count=0,
        recovery_object_row_count=1,
        recovery_object_key=recovery_object[0],
        recovery_object_sha256=recovery_object[1],
        recovery_object_byte_size=recovery_object[2],
        recovery_rows_uncompressed_sha256=hashlib.sha256(stream).hexdigest(),
        output_sha256="0" * 64,
    )
    receipt = draft.model_copy(update={"output_sha256": recovery_receipt_sha256(draft)})
    path = directory / "recovery-receipt.json"
    path.write_text(receipt.model_dump_json(), encoding="utf-8")
    return path, store


def _jsonl(rows: Iterable[dict[str, object]]) -> bytes:
    return b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in rows
    )


def _write_object(store: Path, prefix: str, payload: bytes) -> tuple[str, str, int]:
    compressed = zstandard.ZstdCompressor(level=1).compress(payload)
    object_sha = hashlib.sha256(compressed).hexdigest()
    key = f"{prefix}/{object_sha}.jsonl.zst"
    path = store / key
    path.parent.mkdir(parents=True)
    path.write_bytes(compressed)
    return key, object_sha, len(compressed)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _certified_site(directory: Path) -> tuple[Path, Path, Path]:
    site = directory / "site"
    assets = site / "assets"
    assets.mkdir(parents=True)
    static, atlas = assets / "static.json", assets / "atlas.json"
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
                        "sha256": _sha256(static),
                    },
                    "semantic_atlas": {"path": "assets/atlas.json", "sha256": _sha256(atlas)},
                }
            }
        ),
        encoding="utf-8",
    )
    return static, manifest, atlas
