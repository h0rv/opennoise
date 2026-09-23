"""Boundary tests for the local-only Last.fm/direct-custody count audit."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.analysis.lastfm_direct_custody_coverage import (
    LastFmDirectCustodyCoverageError,
    _direct_endpoint_sets,
    _lastfm_endpoint_sets,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
)

_SHA256 = "0" * 64
_ARTIST_MBID = "00000000-0000-0000-0000-000000000001"
_GENRE_MBID = "00000000-0000-0000-0000-000000000002"


class LastFmDirectCustodyCoverageTest(unittest.TestCase):
    """Reject a pair cohort mismatch and an impossible aggregate endpoint set."""

    def test_direct_pairs_must_match_pinned_receipt_counts(self) -> None:
        receipt = _receipt(claim_count=2)
        claim = DirectProperGenreClaim(
            seed_id="seed-1",
            artist_mbid=_ARTIST_MBID,
            musicbrainz_genre_id=_GENRE_MBID,
            source_record_id=f"musicbrainz:artist:{_ARTIST_MBID}",
            source_record_sha256=_SHA256,
            source_evidence_ref="test",
        )
        with (
            patch(
                "opennoise.analysis.lastfm_direct_custody_coverage."
                "iter_verified_portable_direct_proper_genre_claims",
                return_value=iter((claim,)),
            ),
            self.assertRaisesRegex(LastFmDirectCustodyCoverageError, "receipt counts"),
        ):
            _direct_endpoint_sets(receipt=receipt, object_store=Path("/unused"))

    def test_privacy_pair_endpoints_must_be_observed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "aggregate.sqlite"
            with sqlite3.connect(database_path) as database:
                database.execute("CREATE TABLE observed_artists (artist_id TEXT PRIMARY KEY)")
                database.execute("CREATE TABLE pair_support (left_artist TEXT, right_artist TEXT)")
                database.execute("INSERT INTO observed_artists VALUES (?)", (_ARTIST_MBID,))
                database.execute(
                    "INSERT INTO pair_support VALUES (?, ?)",
                    (_ARTIST_MBID, "00000000-0000-0000-0000-000000000003"),
                )
            with self.assertRaisesRegex(LastFmDirectCustodyCoverageError, "absent"):
                _lastfm_endpoint_sets(database_path)


def _receipt(*, claim_count: int) -> DirectProperGenreCustodyReceipt:
    return DirectProperGenreCustodyReceipt(
        source_seed_target_byte_sha256=_SHA256,
        source_seed_target_output_sha256=_SHA256,
        reconciliation_byte_sha256=_SHA256,
        reconciliation_output_sha256=_SHA256,
        claims_object_key=(f"musicbrainz-direct-proper-genre-custody/sha256/{_SHA256}.jsonl.zst"),
        claims_object_sha256=_SHA256,
        claims_object_byte_size=1,
        claims_uncompressed_sha256=_SHA256,
        claim_count=claim_count,
        seed_count=1,
        artist_mbid_count=1,
        source_record_sha256_count=1,
        output_sha256=_SHA256,
    )
