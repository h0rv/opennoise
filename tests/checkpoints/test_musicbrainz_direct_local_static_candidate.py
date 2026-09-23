"""Small synthetic contracts for the local sharded direct MusicBrainz candidate."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from opennoise.checkpoints.musicbrainz_direct_local_static_candidate import (
    LocalMusicBrainzStaticCandidateError,
    LocalMusicBrainzStaticCandidateManifest,
    _placed_candidate_seed_ids,
    _write_candidate,
    verify_local_musicbrainz_direct_static_candidate,
)
from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    DirectArtistNameRecoveryReceipt,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyReceipt,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_DIRECT_RECEIPT_SHA = "a" * 64
_NAME_RECEIPT_SHA = "b" * 64
_RECOVERY_RECEIPT_SHA = "c" * 64
_DIRECT_OUTPUT_SHA = "d" * 64
_DIRECT_OBJECT_SHA = "e" * 64
_NAME_OUTPUT_SHA = "f" * 64
_NAME_OBJECT_SHA = "1" * 64
_RECOVERY_OBJECT_SHA = "2" * 64
_SEED = "item2"
_GENRE = "00000000-0000-4000-8000-000000000001"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(index: int) -> DirectProperGenreClaim:
    artist = f"{index:08x}-0000-4000-8000-{index:012x}"
    return DirectProperGenreClaim(
        seed_id=_SEED,
        artist_mbid=artist,
        musicbrainz_genre_id=_GENRE,
        source_record_id=f"musicbrainz:artist:{artist}",
        source_record_sha256=f"{index % 16:x}" * 64,
        source_evidence_ref=f"source:{index}",
    )


@dataclass(frozen=True)
class _NameRow:
    artist_mbid: str
    canonical_name: str


def _direct_receipt(*, seed_count: int = 1) -> DirectProperGenreCustodyReceipt:
    return DirectProperGenreCustodyReceipt.model_construct(
        public_export_authorized=False,
        output_sha256=_DIRECT_OUTPUT_SHA,
        claims_object_sha256=_DIRECT_OBJECT_SHA,
        seed_count=seed_count,
    )


def _name_receipt() -> DirectCanonicalArtistNameCustodyReceipt:
    return DirectCanonicalArtistNameCustodyReceipt.model_construct(
        public_export_authorized=False,
        output_sha256=_NAME_OUTPUT_SHA,
        names_object_sha256=_NAME_OBJECT_SHA,
    )


def _recovery_receipt() -> DirectArtistNameRecoveryReceipt:
    return DirectArtistNameRecoveryReceipt.model_construct(
        public_export_authorized=False,
        recovery_object_sha256=_RECOVERY_OBJECT_SHA,
    )


class LocalMusicBrainzStaticCandidateTests(unittest.TestCase):
    """Protect local-only source shape, deterministic shards, and certified scope derivation."""

    def test_writes_hashed_genre_shards_at_the_1000_row_boundary(self) -> None:
        claims = tuple(_claim(index) for index in range(1, 1_002))

        def canonical_names(*_args: object, **_kwargs: object) -> Iterator[_NameRow]:
            for claim in claims:
                yield _NameRow(artist_mbid=claim.artist_mbid, canonical_name="Name")

        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            with (
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_direct_canonical_artist_names",
                    canonical_names,
                ),
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_unique_recovered_names",
                    lambda *_args, **_kwargs: iter(()),
                ),
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_portable_direct_proper_genre_claims",
                    lambda *_args, **_kwargs: iter(claims),
                ),
            ):
                manifest = _write_candidate(
                    staging,
                    direct=_direct_receipt(),
                    direct_object_store=staging,
                    names=_name_receipt(),
                    canonical_name_object_store=staging,
                    recovered=_recovery_receipt(),
                    recovered_name_object_store=staging,
                    candidate_ids=(_SEED,),
                    direct_receipt_sha256=_DIRECT_RECEIPT_SHA,
                    canonical_name_receipt_sha256=_NAME_RECEIPT_SHA,
                    recovered_name_receipt_sha256=_RECOVERY_RECEIPT_SHA,
                    static_sha="3" * 64,
                    atlas_sha="4" * 64,
                )
            shard_rows = tuple(shard.row_count for shard in manifest.shards)
            shard_paths = tuple(staging / shard.path for shard in manifest.shards)
            shard_hashes = tuple(_sha256(path) for path in shard_paths)
            replayed = verify_local_musicbrainz_direct_static_candidate(staging)

        self.assertEqual(shard_rows, (1_000, 1))
        self.assertEqual(shard_hashes, tuple(shard.sha256 for shard in manifest.shards))
        self.assertEqual(replayed, manifest)
        self.assertEqual(manifest.membership_count, 1_001)
        self.assertFalse(manifest.public_export_authorized)
        self.assertFalse(manifest.serving_authorized)

    def test_rejects_a_direct_pair_without_an_exact_name(self) -> None:
        claim = _claim(1)
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            with (
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_direct_canonical_artist_names",
                    lambda *_args, **_kwargs: iter(()),
                ),
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_unique_recovered_names",
                    lambda *_args, **_kwargs: iter(()),
                ),
                patch(
                    "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_portable_direct_proper_genre_claims",
                    lambda *_args, **_kwargs: iter((claim,)),
                ),
                self.assertRaisesRegex(LocalMusicBrainzStaticCandidateError, "canonical name"),
            ):
                _write_candidate(
                    staging,
                    direct=_direct_receipt(),
                    direct_object_store=staging,
                    names=_name_receipt(),
                    canonical_name_object_store=staging,
                    recovered=_recovery_receipt(),
                    recovered_name_object_store=staging,
                    candidate_ids=(_SEED,),
                    direct_receipt_sha256=_DIRECT_RECEIPT_SHA,
                    canonical_name_receipt_sha256=_NAME_RECEIPT_SHA,
                    recovered_name_receipt_sha256=_RECOVERY_RECEIPT_SHA,
                    static_sha="3" * 64,
                    atlas_sha="4" * 64,
                )

    def test_derives_only_placed_ids_absent_from_the_certified_static_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            static = directory / "static.json"
            atlas = directory / "atlas.json"
            static.write_text(json.dumps({"genres": [{"node_id": "item1"}]}))
            atlas.write_text(json.dumps({"nodes": [{"id": "item1"}, {"id": _SEED}]}))
            manifest = directory / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "assets": {
                            "static_discovery": {"path": "static.json", "sha256": _sha256(static)},
                            "semantic_atlas": {"path": "atlas.json", "sha256": _sha256(atlas)},
                        }
                    }
                )
            )
            direct_claims = (
                _claim(1).model_copy(update={"seed_id": "item1"}),
                _claim(2),
                _claim(3).model_copy(update={"seed_id": "unplaced"}),
            )
            with patch(
                "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_portable_direct_proper_genre_claims",
                lambda *_args, **_kwargs: iter(direct_claims),
            ):
                candidate_ids, static_sha, atlas_sha = _placed_candidate_seed_ids(
                    static_discovery_path=static,
                    certified_manifest_path=manifest,
                    certified_layout_path=atlas,
                    direct=_direct_receipt(seed_count=3),
                    direct_object_store=directory,
                )

        self.assertEqual(candidate_ids, (_SEED,))
        self.assertEqual(len(static_sha), 64)
        self.assertEqual(len(atlas_sha), 64)

    def test_rejects_tampered_manifest_self_hash(self) -> None:
        claim = _claim(1)
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            manifest = self._write_small_candidate(staging, (claim,))
            manifest_path = staging / "manifest.json"
            payload = json.loads(manifest_path.read_text())
            payload["direct_custody_output_sha256"] = "9" * 64
            manifest_path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            )

            with self.assertRaisesRegex(LocalMusicBrainzStaticCandidateError, "self-hash"):
                verify_local_musicbrainz_direct_static_candidate(staging)

        self.assertEqual(manifest.membership_count, 1)

    def test_rejects_tampered_shard_bytes(self) -> None:
        claim = _claim(1)
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            manifest = self._write_small_candidate(staging, (claim,))
            shard_path = staging / manifest.shards[0].path
            with shard_path.open("ab") as shard:
                shard.write(b"x")

            with self.assertRaisesRegex(LocalMusicBrainzStaticCandidateError, "byte count"):
                verify_local_musicbrainz_direct_static_candidate(staging)

    def _write_small_candidate(
        self, staging: Path, claims: tuple[DirectProperGenreClaim, ...]
    ) -> LocalMusicBrainzStaticCandidateManifest:
        def canonical_names(*_args: object, **_kwargs: object) -> Iterator[_NameRow]:
            for claim in claims:
                yield _NameRow(artist_mbid=claim.artist_mbid, canonical_name="Name")

        with (
            patch(
                "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_direct_canonical_artist_names",
                canonical_names,
            ),
            patch(
                "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_unique_recovered_names",
                lambda *_args, **_kwargs: iter(()),
            ),
            patch(
                "opennoise.checkpoints.musicbrainz_direct_local_static_candidate.iter_verified_portable_direct_proper_genre_claims",
                lambda *_args, **_kwargs: iter(claims),
            ),
        ):
            return _write_candidate(
                staging,
                direct=_direct_receipt(),
                direct_object_store=staging,
                names=_name_receipt(),
                canonical_name_object_store=staging,
                recovered=_recovery_receipt(),
                recovered_name_object_store=staging,
                candidate_ids=(_SEED,),
                direct_receipt_sha256=_DIRECT_RECEIPT_SHA,
                canonical_name_receipt_sha256=_NAME_RECEIPT_SHA,
                recovered_name_receipt_sha256=_RECOVERY_RECEIPT_SHA,
                static_sha="3" * 64,
                atlas_sha="4" * 64,
            )
