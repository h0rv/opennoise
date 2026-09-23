"""Measure the pinned local MusicBrainz direct static candidate for review.

This module reads only local custody, the local candidate, and the pending
policy-review input.  It cannot create a public payload or approve a release.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.musicbrainz_direct_local_static_candidate import (
    LocalCandidateMembership,
    LocalMusicBrainzStaticCandidateManifest,
    local_candidate_manifest_sha256,
    verify_local_musicbrainz_direct_static_candidate,
)
from opennoise.checkpoints.musicbrainz_direct_static_policy_review import (
    MusicBrainzDirectStaticPolicyReviewInput,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
    receipt_sha256,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves this at definition.

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_REVISION: Final = "musicbrainz-direct-static-quality-report-v1"
_EXPECTED_SEED_COUNT: Final = 412
_SAMPLE_COUNT: Final = 12


class MusicBrainzDirectStaticQualityReportError(ValueError):
    """The local candidate cannot be measured against its pinned inputs."""


class MusicBrainzDirectStaticQualityGenreRow(FrozenModel):
    """One placed candidate genre and its exact source row count."""

    seed_id: str = Field(min_length=1)
    row_count: int = Field(gt=0)
    distinct_artist_mbid_count: int = Field(gt=0)
    distinct_source_record_sha256_count: int = Field(gt=0)


class MusicBrainzDirectStaticQualitySample(FrozenModel):
    """A stable generated link for one exact local candidate row."""

    seed_id: str = Field(min_length=1)
    artist_mbid: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    canonical_name: str = Field(min_length=1)
    musicbrainz_genre_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    review_reason: Literal["hash_sample", "high_row_count", "low_row_count"]
    public_source_link: str = Field(pattern=r"^https://musicbrainz\.org/artist/[0-9a-f-]{36}$")


class MusicBrainzDirectStaticQualityReport(FrozenModel):
    """A self-hashed, review-only account of one exact local candidate."""

    revision: Literal["musicbrainz-direct-static-quality-report-v1"] = _REVISION
    review_decision: Literal["pending"] = "pending"
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_claims_authorized: Literal[False] = False
    release_gate: Literal[False] = False
    direct_custody_receipt_output_sha256: Sha256
    direct_claims_object_sha256: Sha256
    local_candidate_manifest_output_sha256: Sha256
    policy_review_input_output_sha256: Sha256
    placed_seed_count: Literal[412] = _EXPECTED_SEED_COUNT
    source_claim_count: int = Field(gt=0)
    candidate_row_count: int = Field(gt=0)
    source_coverage: float = Field(ge=0, le=1)
    name_coverage: float = Field(ge=0, le=1)
    duplicate_count: int = Field(ge=0)
    exclusion_count: int = Field(ge=0)
    ambiguous_name_rejection_count: None = None
    ambiguous_name_exclusions_measured: Literal[False] = False
    missing_source_row_count: int = Field(ge=0)
    unexpected_candidate_row_count: int = Field(ge=0)
    exact_id_integrity_failure_count: int = Field(ge=0)
    per_genre_row_counts: tuple[MusicBrainzDirectStaticQualityGenreRow, ...] = Field(
        min_length=_EXPECTED_SEED_COUNT
    )
    largest_genres: tuple[MusicBrainzDirectStaticQualityGenreRow, ...] = Field(min_length=1)
    smallest_genres: tuple[MusicBrainzDirectStaticQualityGenreRow, ...] = Field(min_length=1)
    review_sample_public_source_links: tuple[MusicBrainzDirectStaticQualitySample, ...] = Field(
        min_length=1, max_length=_SAMPLE_COUNT
    )
    suspicious_review_samples: tuple[MusicBrainzDirectStaticQualitySample, ...] = Field(
        min_length=1, max_length=4
    )
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_pending_review_scope(self) -> MusicBrainzDirectStaticQualityReport:
        """Keep the report local, complete, and suitable only for review."""
        if tuple(row.seed_id for row in self.per_genre_row_counts) != tuple(
            sorted(row.seed_id for row in self.per_genre_row_counts)
        ):
            raise ValueError("quality report per-genre rows must be sorted")
        if len({row.seed_id for row in self.per_genre_row_counts}) != _EXPECTED_SEED_COUNT:
            raise ValueError("quality report does not cover exactly 412 placed seeds")
        if quality_report_sha256(self) != self.output_sha256:
            raise ValueError("quality report self-hash does not match")
        return self


def quality_report_sha256(report: MusicBrainzDirectStaticQualityReport) -> str:
    """Return the logical report hash without its embedded self-hash."""
    return _sha256_bytes(_canonical_json(report.model_dump(mode="json", exclude={"output_sha256"})))


def build_musicbrainz_direct_static_quality_report(
    *,
    direct_custody_receipt_path: Path,
    direct_custody_object_store: Path,
    local_candidate_directory: Path,
    policy_review_input_path: Path,
) -> MusicBrainzDirectStaticQualityReport:
    """Measure the exact pending candidate without writing or authorizing anything."""
    receipt_bytes = direct_custody_receipt_path.read_bytes()
    review_bytes = policy_review_input_path.read_bytes()
    try:
        receipt = DirectProperGenreCustodyReceipt.model_validate_json(receipt_bytes)
        review = MusicBrainzDirectStaticPolicyReviewInput.model_validate_json(review_bytes)
    except ValueError as error:
        raise MusicBrainzDirectStaticQualityReportError("pinned local input is invalid") from error
    manifest = verify_local_musicbrainz_direct_static_candidate(local_candidate_directory)
    _require_pinned_inputs(
        receipt,
        receipt_bytes,
        manifest,
        (local_candidate_directory / "manifest.json").read_bytes(),
        review,
        review_bytes,
    )
    candidate_rows = tuple(_iter_candidate_rows(local_candidate_directory, manifest))
    claims = iter_verified_portable_direct_proper_genre_claims(
        receipt, object_store=direct_custody_object_store
    )
    return _measure(receipt, manifest, review, claims, candidate_rows)


def write_musicbrainz_direct_static_quality_report(
    output_path: Path, report: MusicBrainzDirectStaticQualityReport
) -> str:
    """Write a canonical report once and return its byte SHA-256."""
    if output_path.exists() or output_path.is_symlink():
        raise MusicBrainzDirectStaticQualityReportError("quality report output already exists")
    payload = _canonical_json(report.model_dump(mode="json")) + b"\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return _sha256_bytes(payload)


def _require_pinned_inputs(  # noqa: PLR0913, PLR0917 - one explicit local input boundary.
    receipt: DirectProperGenreCustodyReceipt,
    receipt_bytes: bytes,
    manifest: LocalMusicBrainzStaticCandidateManifest,
    manifest_bytes: bytes,
    review: MusicBrainzDirectStaticPolicyReviewInput,
    review_bytes: bytes,
) -> None:
    if receipt_sha256(receipt) != receipt.output_sha256:
        raise MusicBrainzDirectStaticQualityReportError(
            "direct custody receipt self-hash does not match"
        )
    if review.direct_custody_receipt_output_sha256 != receipt.output_sha256:
        raise MusicBrainzDirectStaticQualityReportError(
            "policy review input names a different custody receipt"
        )
    if review.direct_custody_receipt_byte_sha256 != _sha256_bytes(receipt_bytes):
        raise MusicBrainzDirectStaticQualityReportError(
            "policy review input names different custody bytes"
        )
    if review.direct_claims_object_sha256 != receipt.claims_object_sha256:
        raise MusicBrainzDirectStaticQualityReportError(
            "policy review input names a different custody object"
        )
    if review.local_candidate_manifest_output_sha256 != manifest.output_sha256:
        raise MusicBrainzDirectStaticQualityReportError(
            "policy review input names a different candidate"
        )
    if local_candidate_manifest_sha256(manifest) != manifest.output_sha256:
        raise MusicBrainzDirectStaticQualityReportError(
            "candidate manifest self-hash does not match"
        )
    if review.local_candidate_manifest_byte_sha256 != _sha256_bytes(manifest_bytes):
        raise MusicBrainzDirectStaticQualityReportError(
            "policy review input names different candidate bytes"
        )
    if _sha256_bytes(review_bytes) != _sha256_bytes(
        _canonical_json(review.model_dump(mode="json")) + b"\n"
    ):
        raise MusicBrainzDirectStaticQualityReportError("policy review input is not canonical JSON")
    if review.review_decision != "pending" or any(
        (
            review.public_export_authorized,
            review.serving_authorized,
            review.membership_claims_authorized,
            review.release_gate,
        )
    ):
        raise MusicBrainzDirectStaticQualityReportError("policy review input authorizes public use")


def _iter_candidate_rows(
    directory: Path, manifest: LocalMusicBrainzStaticCandidateManifest
) -> Iterable[LocalCandidateMembership]:
    for shard in manifest.shards:
        with (directory / shard.path).open("rb") as stream:
            for line in stream:
                try:
                    yield LocalCandidateMembership.model_validate_json(line)
                except ValueError as error:
                    raise MusicBrainzDirectStaticQualityReportError(
                        "candidate membership row is invalid"
                    ) from error


def _measure(
    receipt: DirectProperGenreCustodyReceipt,
    manifest: LocalMusicBrainzStaticCandidateManifest,
    review: MusicBrainzDirectStaticPolicyReviewInput,
    claims: Iterable[DirectProperGenreClaim],
    rows: tuple[LocalCandidateMembership, ...],
) -> MusicBrainzDirectStaticQualityReport:
    seed_ids = frozenset(review.placed_candidate_seed_ids)
    source = tuple(claim for claim in claims if claim.seed_id in seed_ids)
    source_signatures = {_claim_signature(claim) for claim in source}
    row_signatures = {_row_signature(row) for row in rows}
    duplicate_count = len(rows) - len(row_signatures)
    missing_source_rows = len(source_signatures - row_signatures)
    unexpected_candidate_rows = len(row_signatures - source_signatures)
    exclusion_count = missing_source_rows + unexpected_candidate_rows
    id_failures = sum(not _has_exact_ids(row) for row in rows)
    named_rows = sum(bool(row.canonical_name.strip()) for row in rows)
    per_genre = _per_genre_rows(rows, seed_ids)
    provisional = MusicBrainzDirectStaticQualityReport.model_construct(
        direct_custody_receipt_output_sha256=receipt.output_sha256,
        direct_claims_object_sha256=receipt.claims_object_sha256,
        local_candidate_manifest_output_sha256=manifest.output_sha256,
        policy_review_input_output_sha256=review.output_sha256,
        source_claim_count=len(source),
        candidate_row_count=len(rows),
        source_coverage=_ratio(len(source_signatures & row_signatures), len(source_signatures)),
        name_coverage=_ratio(named_rows, len(rows)),
        duplicate_count=duplicate_count,
        exclusion_count=exclusion_count,
        missing_source_row_count=missing_source_rows,
        unexpected_candidate_row_count=unexpected_candidate_rows,
        exact_id_integrity_failure_count=id_failures,
        per_genre_row_counts=per_genre,
        largest_genres=_largest_genres(per_genre),
        smallest_genres=_smallest_genres(per_genre),
        review_sample_public_source_links=_review_samples(rows),
        suspicious_review_samples=_distribution_extreme_samples(rows, per_genre),
        output_sha256="0" * 64,
    )
    return MusicBrainzDirectStaticQualityReport(
        direct_custody_receipt_output_sha256=receipt.output_sha256,
        direct_claims_object_sha256=receipt.claims_object_sha256,
        local_candidate_manifest_output_sha256=manifest.output_sha256,
        policy_review_input_output_sha256=review.output_sha256,
        source_claim_count=len(source),
        candidate_row_count=len(rows),
        source_coverage=_ratio(len(source_signatures & row_signatures), len(source_signatures)),
        name_coverage=_ratio(named_rows, len(rows)),
        duplicate_count=duplicate_count,
        exclusion_count=exclusion_count,
        missing_source_row_count=missing_source_rows,
        unexpected_candidate_row_count=unexpected_candidate_rows,
        exact_id_integrity_failure_count=id_failures,
        per_genre_row_counts=per_genre,
        largest_genres=_largest_genres(per_genre),
        smallest_genres=_smallest_genres(per_genre),
        review_sample_public_source_links=_review_samples(rows),
        suspicious_review_samples=_distribution_extreme_samples(rows, per_genre),
        output_sha256=quality_report_sha256(provisional),
    )


def _per_genre_rows(
    rows: tuple[LocalCandidateMembership, ...], seed_ids: frozenset[str]
) -> tuple[MusicBrainzDirectStaticQualityGenreRow, ...]:
    counts = Counter(row.seed_id for row in rows)
    artists: dict[str, set[str]] = {seed_id: set() for seed_id in seed_ids}
    records: dict[str, set[str]] = {seed_id: set() for seed_id in seed_ids}
    for row in rows:
        artists[row.seed_id].add(row.artist_mbid)
        records[row.seed_id].add(row.source_record_sha256)
    return tuple(
        MusicBrainzDirectStaticQualityGenreRow(
            seed_id=seed_id,
            row_count=counts[seed_id],
            distinct_artist_mbid_count=len(artists[seed_id]),
            distinct_source_record_sha256_count=len(records[seed_id]),
        )
        for seed_id in sorted(seed_ids)
    )


def _largest_genres(
    rows: tuple[MusicBrainzDirectStaticQualityGenreRow, ...],
) -> tuple[MusicBrainzDirectStaticQualityGenreRow, ...]:
    return tuple(sorted(rows, key=lambda row: (-row.row_count, row.seed_id))[:5])


def _smallest_genres(
    rows: tuple[MusicBrainzDirectStaticQualityGenreRow, ...],
) -> tuple[MusicBrainzDirectStaticQualityGenreRow, ...]:
    return tuple(sorted(rows, key=lambda row: (row.row_count, row.seed_id))[:5])


def _review_samples(
    rows: tuple[LocalCandidateMembership, ...],
) -> tuple[MusicBrainzDirectStaticQualitySample, ...]:
    selected = sorted(rows, key=lambda row: (_sample_key(row), _row_signature(row)))[:_SAMPLE_COUNT]
    return tuple(
        MusicBrainzDirectStaticQualitySample(
            seed_id=row.seed_id,
            artist_mbid=row.artist_mbid,
            canonical_name=row.canonical_name,
            musicbrainz_genre_id=row.musicbrainz_genre_id,
            review_reason="hash_sample",
            public_source_link=f"https://musicbrainz.org/artist/{row.artist_mbid}",
        )
        for row in selected
    )


def _distribution_extreme_samples(
    rows: tuple[LocalCandidateMembership, ...],
    per_genre: tuple[MusicBrainzDirectStaticQualityGenreRow, ...],
) -> tuple[MusicBrainzDirectStaticQualitySample, ...]:
    by_seed: dict[str, list[LocalCandidateMembership]] = {}
    for row in rows:
        by_seed.setdefault(row.seed_id, []).append(row)
    selections = (
        *((row, "high_row_count") for row in _largest_genres(per_genre)[:2]),
        *((row, "low_row_count") for row in _smallest_genres(per_genre)[:2]),
    )
    return tuple(
        _sample_from_row(
            min(by_seed[genre.seed_id], key=lambda row: (_sample_key(row), _row_signature(row))),
            reason=reason,
        )
        for genre, reason in selections
    )


def _sample_from_row(
    row: LocalCandidateMembership,
    *,
    reason: Literal["hash_sample", "high_row_count", "low_row_count"],
) -> MusicBrainzDirectStaticQualitySample:
    return MusicBrainzDirectStaticQualitySample(
        seed_id=row.seed_id,
        artist_mbid=row.artist_mbid,
        canonical_name=row.canonical_name,
        musicbrainz_genre_id=row.musicbrainz_genre_id,
        review_reason=reason,
        public_source_link=f"https://musicbrainz.org/artist/{row.artist_mbid}",
    )


def _sample_key(row: LocalCandidateMembership) -> str:
    return _sha256_bytes("\0".join(_row_signature(row)).encode())


def _claim_signature(claim: DirectProperGenreClaim) -> tuple[str, str, str, str, str, str]:
    return (
        claim.seed_id,
        claim.artist_mbid,
        claim.musicbrainz_genre_id,
        claim.source_record_id,
        claim.source_record_sha256,
        claim.source_evidence_ref,
    )


def _row_signature(row: LocalCandidateMembership) -> tuple[str, str, str, str, str, str]:
    return (
        row.seed_id,
        row.artist_mbid,
        row.musicbrainz_genre_id,
        row.source_record_id,
        row.source_record_sha256,
        row.source_evidence_ref,
    )


def _has_exact_ids(row: LocalCandidateMembership) -> bool:
    return row.source_record_id == f"musicbrainz:artist:{row.artist_mbid}"


def _ratio(numerator: int, denominator: int) -> float:
    return 0 if denominator == 0 else numerator / denominator


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
