"""Count-only exact-MBID coverage between sealed Last.fm and direct custody.

This local audit is deliberately not a retrieval result, evaluation, or model
input.  It reads neither Last.fm user identifiers (none exist in the sealed
database) nor direct genre identifiers into its output.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.analysis.lastfm_360k import load_lastfm_360k_sealed_v1_envelope
from opennoise.common.hashing import sha256_file
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path


class LastFmDirectCustodyCoverageError(ValueError):
    """The local-only count audit cannot safely continue."""


@dataclass(frozen=True, slots=True)
class LastFmDirectCustodyCoverageInputs:
    """One fully pinned local input set for a count-only audit."""

    lastfm_artifact_path: Path
    lastfm_companion_receipt_path: Path
    lastfm_database_path: Path
    direct_custody_receipt_path: Path
    expected_direct_custody_receipt_sha256: Sha256
    direct_custody_object_store: Path


class LastFmDirectCustodyCoverageReport(FrozenModel):
    """Pinned aggregate counts, with every downstream-use gate closed."""

    revision: Literal["lastfm-360k-direct-custody-exact-coverage-v1"] = (
        "lastfm-360k-direct-custody-exact-coverage-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    ranking_or_training_allowed: Literal[False] = False
    independent_genre_gold: Literal[False] = False
    genre_quality_claim: Literal[False] = False
    exact_mbid_matching_only: Literal[True] = True
    lastfm_user_identifiers_read: Literal[False] = False
    lastfm_artist_names_read: Literal[False] = False
    direct_genre_identifiers_emitted: Literal[False] = False
    lastfm_original_artifact_sha256: Sha256
    lastfm_companion_receipt_sha256: Sha256
    lastfm_working_database_sha256: Sha256
    lastfm_working_database_byte_size: int = Field(ge=1)
    lastfm_privacy_pair_floor: int = Field(ge=5)
    lastfm_observed_artist_endpoint_count: int = Field(ge=0)
    lastfm_privacy_pair_count: int = Field(ge=0)
    lastfm_privacy_pair_endpoint_count: int = Field(ge=0)
    direct_custody_receipt_sha256: Sha256
    direct_custody_receipt_output_sha256: Sha256
    direct_custody_claims_object_sha256: Sha256
    direct_custody_claim_count: int = Field(ge=0)
    direct_custody_artist_endpoint_count: int = Field(ge=0)
    direct_custody_seed_artist_pair_count: int = Field(ge=0)
    direct_custody_seed_count: int = Field(ge=0)
    direct_artists_in_lastfm_observed_endpoints: int = Field(ge=0)
    direct_seed_artist_pairs_in_lastfm_observed_endpoints: int = Field(ge=0)
    direct_seeds_in_lastfm_observed_endpoints: int = Field(ge=0)
    direct_artists_in_lastfm_privacy_pair_endpoints: int = Field(ge=0)
    direct_seed_artist_pairs_in_lastfm_privacy_pair_endpoints: int = Field(ge=0)
    direct_seeds_in_lastfm_privacy_pair_endpoints: int = Field(ge=0)

    @model_validator(mode="after")
    def _coverage_is_nested(self) -> LastFmDirectCustodyCoverageReport:
        if not (
            self.direct_artists_in_lastfm_privacy_pair_endpoints
            <= self.direct_artists_in_lastfm_observed_endpoints
            <= self.direct_custody_artist_endpoint_count
        ):
            raise ValueError("direct artist endpoint coverage is not nested")
        if not (
            self.direct_seed_artist_pairs_in_lastfm_privacy_pair_endpoints
            <= self.direct_seed_artist_pairs_in_lastfm_observed_endpoints
            <= self.direct_custody_seed_artist_pair_count
        ):
            raise ValueError("direct seed/artist pair coverage is not nested")
        if not (
            self.direct_seeds_in_lastfm_privacy_pair_endpoints
            <= self.direct_seeds_in_lastfm_observed_endpoints
            <= self.direct_custody_seed_count
        ):
            raise ValueError("direct seed coverage is not nested")
        return self


def audit_lastfm_direct_custody_exact_coverage(
    inputs: LastFmDirectCustodyCoverageInputs,
) -> LastFmDirectCustodyCoverageReport:
    """Measure exact-ID membership of direct custody endpoints in sealed aggregates."""
    envelope = load_lastfm_360k_sealed_v1_envelope(
        artifact_path=inputs.lastfm_artifact_path,
        companion_receipt_path=inputs.lastfm_companion_receipt_path,
        database_path=inputs.lastfm_database_path,
    )
    direct_receipt_sha256, _ = sha256_file(inputs.direct_custody_receipt_path)
    if direct_receipt_sha256 != inputs.expected_direct_custody_receipt_sha256:
        raise LastFmDirectCustodyCoverageError(
            "direct custody receipt bytes do not match the predeclared hash"
        )
    direct_receipt = DirectProperGenreCustodyReceipt.model_validate_json(
        inputs.direct_custody_receipt_path.read_bytes()
    )
    direct_artists, direct_pairs = _direct_endpoint_sets(
        receipt=direct_receipt, object_store=inputs.direct_custody_object_store
    )
    observed_endpoints, privacy_pair_endpoints = _lastfm_endpoint_sets(inputs.lastfm_database_path)
    observed_direct_pairs = {pair for pair in direct_pairs if pair[1] in observed_endpoints}
    privacy_direct_pairs = {pair for pair in direct_pairs if pair[1] in privacy_pair_endpoints}
    return LastFmDirectCustodyCoverageReport(
        lastfm_original_artifact_sha256=envelope.original_artifact_sha256,
        lastfm_companion_receipt_sha256=sha256_file(inputs.lastfm_companion_receipt_path)[0],
        lastfm_working_database_sha256=envelope.companion_receipt.working_database_sha256,
        lastfm_working_database_byte_size=envelope.companion_receipt.working_database_byte_size,
        lastfm_privacy_pair_floor=envelope.companion_receipt.working_database_pair_floor,
        lastfm_observed_artist_endpoint_count=len(observed_endpoints),
        lastfm_privacy_pair_count=envelope.companion_receipt.privacy_filtered_pair_count,
        lastfm_privacy_pair_endpoint_count=len(privacy_pair_endpoints),
        direct_custody_receipt_sha256=direct_receipt_sha256,
        direct_custody_receipt_output_sha256=direct_receipt.output_sha256,
        direct_custody_claims_object_sha256=direct_receipt.claims_object_sha256,
        direct_custody_claim_count=direct_receipt.claim_count,
        direct_custody_artist_endpoint_count=len(direct_artists),
        direct_custody_seed_artist_pair_count=len(direct_pairs),
        direct_custody_seed_count=len({seed_id for seed_id, _ in direct_pairs}),
        direct_artists_in_lastfm_observed_endpoints=len(direct_artists & observed_endpoints),
        direct_seed_artist_pairs_in_lastfm_observed_endpoints=len(observed_direct_pairs),
        direct_seeds_in_lastfm_observed_endpoints=len(
            {seed_id for seed_id, _ in observed_direct_pairs}
        ),
        direct_artists_in_lastfm_privacy_pair_endpoints=len(
            direct_artists & privacy_pair_endpoints
        ),
        direct_seed_artist_pairs_in_lastfm_privacy_pair_endpoints=len(privacy_direct_pairs),
        direct_seeds_in_lastfm_privacy_pair_endpoints=len(
            {seed_id for seed_id, _ in privacy_direct_pairs}
        ),
    )


def _direct_endpoint_sets(
    *, receipt: DirectProperGenreCustodyReceipt, object_store: Path
) -> tuple[set[str], set[tuple[str, str]]]:
    """Extract only source seed and exact artist identifiers from verified claims."""
    pairs = {
        (claim.seed_id, claim.artist_mbid)
        for claim in iter_verified_portable_direct_proper_genre_claims(
            receipt, object_store=object_store
        )
    }
    artists = {artist_mbid for _, artist_mbid in pairs}
    seeds = {seed_id for seed_id, _ in pairs}
    if (len(pairs), len(artists), len(seeds)) != (
        receipt.claim_count,
        receipt.artist_mbid_count,
        receipt.seed_count,
    ):
        raise LastFmDirectCustodyCoverageError(
            "direct custody receipt counts do not match its exact seed/artist cohort"
        )
    return artists, pairs


def _lastfm_endpoint_sets(database_path: Path) -> tuple[set[str], set[str]]:
    """Read exact aggregate MBID endpoints only, after sealed DB verification."""
    try:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as db:
            observed = _read_text_column(db, "SELECT artist_id FROM observed_artists")
            privacy_pair = _read_text_column(
                db,
                "SELECT left_artist FROM pair_support UNION SELECT right_artist FROM pair_support",
            )
    except sqlite3.Error as error:
        raise LastFmDirectCustodyCoverageError("cannot read verified Last.fm aggregate") from error
    if not privacy_pair <= observed:
        raise LastFmDirectCustodyCoverageError(
            "Last.fm privacy-pair endpoint is absent from observed artist endpoints"
        )
    return observed, privacy_pair


def _read_text_column(database: sqlite3.Connection, query: str) -> set[str]:
    """Read a one-column exact-ID query without propagating SQLite's Any rows."""
    values: set[str] = set()
    for row in database.execute(query):
        if len(row) != 1 or not isinstance(value := row[0], str):
            raise LastFmDirectCustodyCoverageError("Last.fm endpoint query returned a non-text row")
        values.add(value)
    return values
