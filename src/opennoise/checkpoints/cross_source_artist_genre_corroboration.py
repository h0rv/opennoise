"""Local-only exact-ID overlap accounting for retained MusicBrainz and Last.fm inputs.

This is deliberately an audit of two separately retained observations.  A
Last.fm literal tag candidate is neither a factual membership nor independent
gold, and matching it to a MusicBrainz custody observation does not change
that status.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_file, sha256_json
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.evidence.lastfm_artisttags2007_seed_candidates import (
    LastFmArtistTags2007SeedCandidateArtifact,
    LastFmArtistTags2007SeedParseCoverage,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves aliases at runtime.

if TYPE_CHECKING:
    from pathlib import Path


_REVISION: Final = "cross-source-artist-genre-corroboration-audit-v1"
_MAX_LASTFM_CANDIDATES: Final = 250_000
_MAX_CORROBORATED_PAIRS: Final = 250_000
_MAX_CANDIDATE_ARTIFACT_BYTES: Final = 128 * 1024 * 1024


class CrossSourceArtistGenreCorroborationError(ValueError):
    """Report an invalid source boundary or a prohibited join interpretation."""


class MusicBrainzDirectProperGenreAuditSource(FrozenModel):
    """Receipt-bound MusicBrainz custody counts retained separately from Last.fm."""

    receipt_byte_sha256: Sha256
    receipt_output_sha256: Sha256
    claims_object_sha256: Sha256
    canonical_seed_vocabulary_byte_sha256: Sha256
    direct_proper_genre_observation_count: int = Field(ge=0)
    exact_artist_mbid_count: int = Field(ge=0)
    canonical_seed_id_count: int = Field(ge=0)
    custody_only: Literal[True] = True
    factual_direct_membership: Literal[False] = False
    public_export_authorized: Literal[False] = False


class LastFmLiteralCandidateAuditSource(FrozenModel):
    """Candidate and abstention accounting without treating tags as facts."""

    artifact_byte_sha256: Sha256
    artifact_output_sha256: Sha256
    archive_sha256: Sha256
    canonical_seed_vocabulary_byte_sha256: Sha256
    literal_candidate_row_count: int = Field(ge=0, le=_MAX_LASTFM_CANDIDATES)
    exact_artist_mbid_count: int = Field(ge=0)
    canonical_seed_id_count: int = Field(ge=0)
    parse_coverage: LastFmArtistTags2007SeedParseCoverage
    local_only: Literal[True] = True
    factual_direct_membership: Literal[False] = False
    independent_gold_input: Literal[False] = False
    construction_allowed: Literal[False] = False


class ExactArtistSeedOverlap(FrozenModel):
    """Counts for the sole permitted exact `(artist MBID, canonical seed ID)` join."""

    join_key: Literal["exact_musicbrainz_artist_mbid_and_canonical_seed_id"] = (
        "exact_musicbrainz_artist_mbid_and_canonical_seed_id"
    )
    shared_seed_vocabulary_byte_sha256: Sha256
    musicbrainz_observations_with_lastfm_candidate_count: int = Field(ge=0)
    lastfm_candidate_rows_with_musicbrainz_observation_count: int = Field(ge=0)
    exact_artist_seed_pair_count: int = Field(ge=0, le=_MAX_CORROBORATED_PAIRS)
    exact_artist_seed_pair_stream_sha256: Sha256
    factual_membership_inferred: Literal[False] = False
    independent_gold_inferred: Literal[False] = False
    precision_or_recall_estimated: Literal[False] = False

    @model_validator(mode="after")
    def counts_are_bounded_by_matching_pairs(self) -> ExactArtistSeedOverlap:
        """Ensure pair and per-source overlap accounting stays internally consistent."""
        if self.lastfm_candidate_rows_with_musicbrainz_observation_count != (
            self.exact_artist_seed_pair_count
        ):
            raise ValueError("each retained Last.fm candidate must contribute one exact pair")
        if self.musicbrainz_observations_with_lastfm_candidate_count < (
            self.exact_artist_seed_pair_count
        ):
            raise ValueError("MusicBrainz observation overlap cannot be smaller than pair overlap")
        return self


class CrossSourceArtistGenreCorroborationAudit(FrozenModel):
    """Hash-replayable, local-only candidate-overlap report with no promotion semantics."""

    revision: Literal["cross-source-artist-genre-corroboration-audit-v1"] = _REVISION
    audit_scope: Literal["local_only_candidate_overlap_and_coverage"] = (
        "local_only_candidate_overlap_and_coverage"
    )
    musicbrainz_direct_proper_genre: MusicBrainzDirectProperGenreAuditSource
    lastfm_artisttags2007_literal_candidate: LastFmLiteralCandidateAuditSource
    exact_artist_seed_overlap: ExactArtistSeedOverlap
    public_or_static_artifact_read: Literal[False] = False
    public_or_static_artifact_mutated: Literal[False] = False
    factual_membership_claimed: Literal[False] = False
    independent_gold_claimed: Literal[False] = False
    model_or_release_input: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def sources_share_the_same_canonical_seed_boundary(
        self,
    ) -> CrossSourceArtistGenreCorroborationAudit:
        """Require the report's three retained source-boundary hashes to agree."""
        if {
            self.musicbrainz_direct_proper_genre.canonical_seed_vocabulary_byte_sha256,
            self.lastfm_artisttags2007_literal_candidate.canonical_seed_vocabulary_byte_sha256,
            self.exact_artist_seed_overlap.shared_seed_vocabulary_byte_sha256,
        } != {self.exact_artist_seed_overlap.shared_seed_vocabulary_byte_sha256}:
            raise ValueError("audit sources do not share one canonical seed vocabulary")
        if self.output_sha256 != sha256_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("cross-source audit output hash does not replay")
        return self


def build_cross_source_artist_genre_corroboration_audit(
    *,
    musicbrainz_receipt: Path,
    musicbrainz_object_store: Path,
    lastfm_candidate_artifact: Path,
) -> CrossSourceArtistGenreCorroborationAudit:
    """Measure exact source-separated overlap without interpreting it as membership."""
    receipt_sha256, _receipt_bytes = sha256_file(musicbrainz_receipt)
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(musicbrainz_receipt.read_bytes())
    if receipt.output_sha256 != _receipt_output_sha256(receipt):
        raise CrossSourceArtistGenreCorroborationError(
            "MusicBrainz receipt output hash does not replay"
        )
    candidate_sha256, candidate_bytes = sha256_file(lastfm_candidate_artifact)
    if candidate_bytes > _MAX_CANDIDATE_ARTIFACT_BYTES:
        raise CrossSourceArtistGenreCorroborationError(
            "Last.fm candidate artifact exceeds byte bound"
        )
    candidate = LastFmArtistTags2007SeedCandidateArtifact.model_validate_json(
        lastfm_candidate_artifact.read_bytes()
    )
    if candidate.seed_vocabulary_sha256 != receipt.reconciliation_byte_sha256:
        raise CrossSourceArtistGenreCorroborationError(
            "sources do not share the same byte-pinned canonical seed vocabulary"
        )
    if len(candidate.candidates) > _MAX_LASTFM_CANDIDATES:
        raise CrossSourceArtistGenreCorroborationError("Last.fm candidate count exceeds bound")

    lastfm_pairs = {
        _exact_pair(row.musicbrainz_artist_id, row.seed_source_item_id)
        for row in candidate.candidates
    }
    if len(lastfm_pairs) != len(candidate.candidates):
        raise CrossSourceArtistGenreCorroborationError(
            "Last.fm candidate artifact repeats an exact pair"
        )
    matched_pairs: set[tuple[str, str]] = set()
    matched_musicbrainz_observations = 0
    musicbrainz_artists: set[str] = set()
    musicbrainz_seeds: set[str] = set()
    for claim in iter_verified_portable_direct_proper_genre_claims(
        receipt, object_store=musicbrainz_object_store
    ):
        pair = _exact_pair(claim.artist_mbid, claim.seed_id)
        musicbrainz_artists.add(pair[0])
        musicbrainz_seeds.add(pair[1])
        if pair in lastfm_pairs:
            matched_musicbrainz_observations += 1
            matched_pairs.add(pair)
            if len(matched_pairs) > _MAX_CORROBORATED_PAIRS:
                raise CrossSourceArtistGenreCorroborationError("exact pair overlap exceeds bound")

    overlap = ExactArtistSeedOverlap(
        shared_seed_vocabulary_byte_sha256=receipt.reconciliation_byte_sha256,
        musicbrainz_observations_with_lastfm_candidate_count=matched_musicbrainz_observations,
        lastfm_candidate_rows_with_musicbrainz_observation_count=len(matched_pairs),
        exact_artist_seed_pair_count=len(matched_pairs),
        exact_artist_seed_pair_stream_sha256=_pair_stream_sha256(matched_pairs),
    )
    base = CrossSourceArtistGenreCorroborationAudit.model_construct(
        musicbrainz_direct_proper_genre=MusicBrainzDirectProperGenreAuditSource(
            receipt_byte_sha256=receipt_sha256,
            receipt_output_sha256=receipt.output_sha256,
            claims_object_sha256=receipt.claims_object_sha256,
            canonical_seed_vocabulary_byte_sha256=receipt.reconciliation_byte_sha256,
            direct_proper_genre_observation_count=receipt.claim_count,
            exact_artist_mbid_count=len(musicbrainz_artists),
            canonical_seed_id_count=len(musicbrainz_seeds),
        ),
        lastfm_artisttags2007_literal_candidate=LastFmLiteralCandidateAuditSource(
            artifact_byte_sha256=candidate_sha256,
            artifact_output_sha256=candidate.output_sha256,
            archive_sha256=candidate.archive_sha256,
            canonical_seed_vocabulary_byte_sha256=candidate.seed_vocabulary_sha256,
            literal_candidate_row_count=len(candidate.candidates),
            exact_artist_mbid_count=len({pair[0] for pair in lastfm_pairs}),
            canonical_seed_id_count=len({pair[1] for pair in lastfm_pairs}),
            parse_coverage=candidate.parse_coverage,
        ),
        exact_artist_seed_overlap=overlap,
        output_sha256="0" * 64,
    )
    payload = base.model_dump(exclude={"output_sha256"})
    payload["output_sha256"] = sha256_json(payload)
    return CrossSourceArtistGenreCorroborationAudit.model_validate(payload)


def _exact_pair(artist_mbid: str, canonical_seed_id: str) -> tuple[str, str]:
    if not canonical_seed_id:
        raise CrossSourceArtistGenreCorroborationError("canonical seed ID must not be empty")
    try:
        parsed = uuid.UUID(artist_mbid)
    except ValueError as error:
        raise CrossSourceArtistGenreCorroborationError(
            "artist ID is not a canonical UUID"
        ) from error
    if str(parsed) != artist_mbid:
        raise CrossSourceArtistGenreCorroborationError(
            "artist ID is not a canonical lowercase UUID"
        )
    return artist_mbid, canonical_seed_id


def _pair_stream_sha256(pairs: set[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for artist_mbid, canonical_seed_id in sorted(pairs):
        digest.update(
            json.dumps(
                {"artist_mbid": artist_mbid, "canonical_seed_id": canonical_seed_id},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            + b"\n"
        )
    return digest.hexdigest()


def _receipt_output_sha256(receipt: DirectProperGenreCustodyReceipt) -> str:
    return sha256_json(receipt.model_dump(mode="json", exclude={"output_sha256"}))
