"""Build a local, pending policy-review input for direct MusicBrainz genres.

This module only reads the existing local candidate and custody receipt.  Its
result is review material, not a publication approval, export input, or static
discovery contract.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.musicbrainz_direct_local_static_candidate import (
    LocalMusicBrainzStaticCandidateManifest,
    local_candidate_manifest_sha256,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    receipt_sha256,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves this at definition.

if TYPE_CHECKING:
    from pathlib import Path

_PINNED_DIRECT_CUSTODY_RECEIPT_OUTPUT_SHA256: Final = (
    "a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9"
)
_PINNED_LOCAL_CANDIDATE_MANIFEST_OUTPUT_SHA256: Final = (
    "a8f0059e7c53c802af88f27d473f6fec35b8e2f137218470e9fc3bee1b71ee70"
)
_PINNED_DIRECT_CUSTODY_RECEIPT_BYTE_SHA256: Final = (
    "41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615"
)
_PINNED_LOCAL_CANDIDATE_MANIFEST_BYTE_SHA256: Final = (
    "d4c52a47a1137ea93104b1fd56e6068c524622bb2b1df8f46dc5ef630f3a8b89"
)
_EXPECTED_PLACED_SEED_COUNT: Final = 412
_PROPOSED_PUBLIC_SOURCE_WORDING: Final = (
    "MusicBrainz proper-genre observation on this artist record."
)
_QUALITY_REPORT_FIELDS: Final = (
    "source_coverage",
    "duplicate_count",
    "exclusion_count",
    "ambiguous_name_rejection_count",
    "per_genre_row_counts",
    "manually_sampled_public_source_links",
)

type QualityReportField = Literal[
    "source_coverage",
    "duplicate_count",
    "exclusion_count",
    "ambiguous_name_rejection_count",
    "per_genre_row_counts",
    "manually_sampled_public_source_links",
]


class MusicBrainzDirectStaticPolicyReviewError(ValueError):
    """The local review input cannot be tied to the pinned candidate."""


class MusicBrainzDirectStaticPolicyReviewInput(FrozenModel):
    """One pending decision over the exact local-only MusicBrainz candidate."""

    revision: Literal["musicbrainz-direct-static-policy-review-input-v1"] = (
        "musicbrainz-direct-static-policy-review-input-v1"
    )
    review_decision: Literal["pending"] = "pending"
    source_role: Literal["musicbrainz_artist_proper_genre_observation"] = (
        "musicbrainz_artist_proper_genre_observation"
    )
    proposed_public_source_wording: Literal[
        "MusicBrainz proper-genre observation on this artist record."
    ] = _PROPOSED_PUBLIC_SOURCE_WORDING
    direct_custody_receipt_output_sha256: Sha256
    direct_custody_receipt_byte_sha256: Sha256
    direct_claims_object_sha256: Sha256
    local_candidate_manifest_output_sha256: Sha256
    local_candidate_manifest_byte_sha256: Sha256
    placed_candidate_seed_ids: tuple[str, ...] = Field(min_length=_EXPECTED_PLACED_SEED_COUNT)
    required_quality_report_fields: tuple[QualityReportField, ...] = _QUALITY_REPORT_FIELDS
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_claims_authorized: Literal[False] = False
    release_gate: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_pinned_pending_review(self) -> MusicBrainzDirectStaticPolicyReviewInput:
        """Keep the review input limited to the sealed source and exact scope."""
        if (
            self.direct_custody_receipt_output_sha256
            != _PINNED_DIRECT_CUSTODY_RECEIPT_OUTPUT_SHA256
        ):
            raise ValueError("policy review input uses an unpinned direct custody receipt")
        if (
            self.local_candidate_manifest_output_sha256
            != _PINNED_LOCAL_CANDIDATE_MANIFEST_OUTPUT_SHA256
        ):
            raise ValueError("policy review input uses an unpinned local candidate manifest")
        if self.direct_custody_receipt_byte_sha256 != _PINNED_DIRECT_CUSTODY_RECEIPT_BYTE_SHA256:
            raise ValueError("policy review input uses unpinned direct custody receipt bytes")
        if (
            self.local_candidate_manifest_byte_sha256
            != _PINNED_LOCAL_CANDIDATE_MANIFEST_BYTE_SHA256
        ):
            raise ValueError("policy review input uses unpinned local candidate manifest bytes")
        if len(self.placed_candidate_seed_ids) != _EXPECTED_PLACED_SEED_COUNT:
            raise ValueError(
                "policy review input must contain exactly 412 placed candidate seed IDs"
            )
        if self.placed_candidate_seed_ids != tuple(sorted(self.placed_candidate_seed_ids)):
            raise ValueError("policy review input seed IDs must be sorted")
        if len(self.placed_candidate_seed_ids) != len(set(self.placed_candidate_seed_ids)):
            raise ValueError("policy review input seed IDs repeat")
        if self.required_quality_report_fields != _QUALITY_REPORT_FIELDS:
            raise ValueError(
                "policy review input quality report fields differ from the required set"
            )
        if policy_review_input_sha256(self) != self.output_sha256:
            raise ValueError("policy review input self-hash does not match")
        return self


def build_musicbrainz_direct_static_policy_review_input(  # noqa: C901 - explicit review gates.
    *,
    direct_custody_receipt_path: Path,
    direct_custody_object_store: Path,
    local_candidate_manifest_path: Path,
) -> MusicBrainzDirectStaticPolicyReviewInput:
    """Read pinned local artifacts and return a pending review input.

    The caller must supply both artifact paths.  The function performs no
    writes and does not change the custody or publication policy.
    """
    direct_bytes, direct = _load_direct_custody_receipt(direct_custody_receipt_path)
    candidate_bytes, candidate = _load_local_candidate_manifest(local_candidate_manifest_path)
    if direct.public_export_authorized:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct custody receipt authorizes public export"
        )
    if direct.output_sha256 != _PINNED_DIRECT_CUSTODY_RECEIPT_OUTPUT_SHA256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct custody receipt does not match the pin"
        )
    if receipt_sha256(direct) != direct.output_sha256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct custody receipt self-hash does not match"
        )
    if _sha256_bytes(direct_bytes) != _PINNED_DIRECT_CUSTODY_RECEIPT_BYTE_SHA256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct custody receipt bytes do not match the pin"
        )
    _require_direct_claim_object(direct, object_store=direct_custody_object_store)
    if candidate.public_export_authorized or candidate.serving_authorized:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate manifest authorizes public use"
        )
    if candidate.membership_claims_authorized or candidate.release_gate:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate manifest authorizes membership"
        )
    if candidate.direct_custody_output_sha256 != direct.output_sha256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate binds a different direct custody receipt"
        )
    if local_candidate_manifest_sha256(candidate) != candidate.output_sha256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate manifest self-hash does not match"
        )
    if candidate.output_sha256 != _PINNED_LOCAL_CANDIDATE_MANIFEST_OUTPUT_SHA256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate manifest does not match the pin"
        )
    if _sha256_bytes(candidate_bytes) != _PINNED_LOCAL_CANDIDATE_MANIFEST_BYTE_SHA256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate manifest bytes do not match the pin"
        )
    provisional = MusicBrainzDirectStaticPolicyReviewInput.model_construct(
        direct_custody_receipt_output_sha256=direct.output_sha256,
        direct_custody_receipt_byte_sha256=_sha256_bytes(direct_bytes),
        direct_claims_object_sha256=direct.claims_object_sha256,
        local_candidate_manifest_output_sha256=candidate.output_sha256,
        local_candidate_manifest_byte_sha256=_sha256_bytes(candidate_bytes),
        placed_candidate_seed_ids=candidate.placed_candidate_seed_ids,
        output_sha256="0" * 64,
    )
    return MusicBrainzDirectStaticPolicyReviewInput(
        direct_custody_receipt_output_sha256=direct.output_sha256,
        direct_custody_receipt_byte_sha256=_sha256_bytes(direct_bytes),
        direct_claims_object_sha256=direct.claims_object_sha256,
        local_candidate_manifest_output_sha256=candidate.output_sha256,
        local_candidate_manifest_byte_sha256=_sha256_bytes(candidate_bytes),
        placed_candidate_seed_ids=candidate.placed_candidate_seed_ids,
        output_sha256=policy_review_input_sha256(provisional),
    )


def policy_review_input_sha256(review: MusicBrainzDirectStaticPolicyReviewInput) -> str:
    """Hash the review input without trusting its embedded self-hash."""
    return _sha256_bytes(_canonical_json(review.model_dump(mode="json", exclude={"output_sha256"})))


def write_musicbrainz_direct_static_policy_review_input(
    path: Path, review: MusicBrainzDirectStaticPolicyReviewInput
) -> str:
    """Write one canonical local review file without replacing an existing file."""
    if path.exists() or path.is_symlink():
        raise MusicBrainzDirectStaticPolicyReviewError("policy review output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = _canonical_json(review.model_dump(mode="json")) + b"\n"
    try:
        with path.open("xb") as stream:
            stream.write(contents)
    except OSError as error:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "policy review output cannot be written"
        ) from error
    return _sha256_bytes(contents)


def _load_direct_custody_receipt(path: Path) -> tuple[bytes, DirectProperGenreCustodyReceipt]:
    try:
        contents = path.read_bytes()
        return contents, DirectProperGenreCustodyReceipt.model_validate_json(contents)
    except (OSError, ValueError) as error:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct custody receipt is invalid"
        ) from error


def _load_local_candidate_manifest(
    path: Path,
) -> tuple[bytes, LocalMusicBrainzStaticCandidateManifest]:
    try:
        contents = path.read_bytes()
        return contents, LocalMusicBrainzStaticCandidateManifest.model_validate_json(contents)
    except (OSError, ValueError) as error:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "local candidate manifest is invalid"
        ) from error


def _require_direct_claim_object(
    receipt: DirectProperGenreCustodyReceipt, *, object_store: Path
) -> None:
    try:
        actual_sha256 = _sha256_bytes((object_store / receipt.claims_object_key).read_bytes())
    except OSError as error:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct claims object cannot be read"
        ) from error
    if actual_sha256 != receipt.claims_object_sha256:
        raise MusicBrainzDirectStaticPolicyReviewError(
            "direct claims object bytes do not match receipt"
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()
