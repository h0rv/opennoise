"""Immutable contracts for the source-neutral, review-only transfer channel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "colisten-membership-transfer-v1"
_SHA: Final = r"^[0-9a-f]{64}$"
_SEED_COUNT: Final = 6_291


class CoListenMembershipTransferError(ValueError):
    """Raised when a sealed input or review-only transfer artifact is invalid."""


class CoListenMembershipTransferSettings(FrozenModel):
    """Bounded controls for transfer and its direct-positive evaluation split."""

    revision: Literal["colisten-membership-transfer-settings-v1"] = (
        "colisten-membership-transfer-settings-v1"
    )
    split_seed: int = Field(default=20260920, ge=0)
    heldout_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    maximum_candidates_per_artist: int = Field(default=25, ge=1, le=100)
    maximum_provenance_rows_per_candidate: int = Field(default=20, ge=1, le=100)
    maximum_total_candidates: int = Field(default=50_000, ge=1, le=200_000)


class InputBinding(FrozenModel):
    """One exact byte input and the logical artifact it is admitted under."""

    role: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=_SHA)
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=_SHA)


@dataclass(frozen=True, slots=True)
class CoListenMembershipTransferInputs:
    """The two sealed v2 inputs which actually contribute transfer features."""

    graph_database: Path
    graph_receipt: Path
    colisten_database: Path
    colisten_receipt: Path


class CoListenSupport(FrozenModel):
    """One retained aggregate path from a source artist through one co-listen relation."""

    source_artist_mbid: str = Field(min_length=1)
    co_listen_evidence_fingerprint: str = Field(min_length=1)
    distinct_user_count: int = Field(ge=1)
    contribution: float = Field(gt=0)


class ReviewCandidate(FrozenModel):
    """A never-factual candidate with bounded, immutable aggregate provenance."""

    artist_mbid: str = Field(min_length=1)
    stable_seed_id: str = Field(min_length=1)
    score: float = Field(gt=0)
    supporting_artist_count: int = Field(ge=1)
    supporting_colisten_edge_count: int = Field(ge=1)
    summed_distinct_user_support: int = Field(ge=1)
    retained_supports: tuple[CoListenSupport, ...] = Field(min_length=1, max_length=100)
    omitted_support_row_count: int = Field(ge=0)
    membership_semantics: Literal["review_only_not_factual_membership"] = (
        "review_only_not_factual_membership"
    )

    @model_validator(mode="after")
    def complete_support_accounting(self) -> ReviewCandidate:
        """Require retained and omitted aggregate paths to reconstruct the support ledger."""
        if (
            len(self.retained_supports) + self.omitted_support_row_count
            != self.supporting_colisten_edge_count
        ):
            raise ValueError("candidate support rows do not account for all co-listen edges")
        if self.supporting_artist_count > self.supporting_colisten_edge_count:
            raise ValueError("candidate source artist count exceeds co-listen edge count")
        retained_source_count = len({item.source_artist_mbid for item in self.retained_supports})
        if self.omitted_support_row_count == 0:
            if self.supporting_artist_count != retained_source_count:
                raise ValueError("complete candidate support does not replay source artist count")
        elif self.supporting_artist_count < retained_source_count:
            raise ValueError("candidate source artist count understates retained support diversity")
        return self


class TransferEvaluation(FrozenModel):
    """Positive-only held-out recovery for artists without a train-side direct label."""

    heldout_direct_positive_count: int = Field(ge=0)
    eligible_heldout_artist_count: int = Field(ge=0)
    abstained_no_colisten_or_support_artist_count: int = Field(ge=0)
    scoreable_direct_positive_count: int = Field(ge=0)
    recovered_at_10_count: int = Field(ge=0)
    recovered_at_25_count: int = Field(ge=0)
    recall_at_10: float | None = Field(default=None, ge=0, le=1)
    recall_at_25: float | None = Field(default=None, ge=0, le=1)
    absence_is_negative: Literal[False] = False
    precision_claimed: Literal[False] = False

    @model_validator(mode="after")
    def positive_only_accounting(self) -> TransferEvaluation:
        """Replay every positive-only retrieval fraction from its counts."""
        if self.scoreable_direct_positive_count > self.heldout_direct_positive_count:
            raise ValueError("scoreable positives exceed held-out direct positives")
        if self.recovered_at_10_count > self.recovered_at_25_count:
            raise ValueError("recall at 10 cannot exceed recall at 25")
        if self.recovered_at_25_count > self.heldout_direct_positive_count:
            raise ValueError("recovered positives exceed held-out direct positives")
        if self.heldout_direct_positive_count:
            if self.recall_at_10 != self.recovered_at_10_count / self.heldout_direct_positive_count:
                raise ValueError("recall at 10 does not replay its positive-only numerator")
            if self.recall_at_25 != self.recovered_at_25_count / self.heldout_direct_positive_count:
                raise ValueError("recall at 25 does not replay its positive-only numerator")
        elif self.recall_at_10 is not None or self.recall_at_25 is not None:
            raise ValueError("empty held-out evaluation must abstain from recall")
        return self


class TransferCoverage(FrozenModel):
    """Complete accounting for the 6,291 seed universe and co-listen target scope."""

    stable_seed_count: Literal[6291] = _SEED_COUNT
    colisten_artist_count: int = Field(ge=0)
    direct_labeled_colisten_artist_count: int = Field(ge=0)
    direct_cold_colisten_artist_count: int = Field(ge=0)
    eligible_cold_artist_count: int = Field(ge=0)
    abstained_cold_artist_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)

    @model_validator(mode="after")
    def complete_cold_artist_accounting(self) -> TransferCoverage:
        """Partition every co-listen artist and every direct-cold target exactly once."""
        if (
            self.direct_labeled_colisten_artist_count + self.direct_cold_colisten_artist_count
            != self.colisten_artist_count
        ):
            raise ValueError("co-listen artists are not fully partitioned by direct membership")
        if (
            self.eligible_cold_artist_count + self.abstained_cold_artist_count
            != self.direct_cold_colisten_artist_count
        ):
            raise ValueError("cold co-listen artists are not fully accounted")
        return self


class CoListenMembershipTransferArtifact(FrozenModel):
    """The reusable transfer channel; no candidate can become a graph membership claim."""

    revision: Literal["colisten-membership-transfer-v1"] = _REVISION
    inputs: tuple[InputBinding, ...] = Field(min_length=4, max_length=4)
    graph_receipt_output_sha256: str = Field(pattern=_SHA)
    colisten_receipt_output_sha256: str = Field(pattern=_SHA)
    settings: CoListenMembershipTransferSettings
    settings_sha256: str = Field(pattern=_SHA)
    coverage: TransferCoverage
    candidates: tuple[ReviewCandidate, ...] = Field(max_length=200_000)
    heldout_evaluation: TransferEvaluation
    train_only_global_popularity_baseline: TransferEvaluation
    direct_only_no_colisten_ablation: TransferEvaluation
    historical_inputs_read_for_construction: Literal[False] = False
    audio_read_for_construction: Literal[False] = False
    listener_identifiers_read_for_construction: Literal[False] = False
    factual_memberships_written: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def exact_input_roles_and_candidate_boundaries(self) -> CoListenMembershipTransferArtifact:
        """Keep all input roles and review candidate paths immutable and non-self-referential."""
        if tuple(item.role for item in self.inputs) != (
            "graph_database",
            "graph_receipt",
            "colisten_database",
            "colisten_receipt",
        ):
            raise ValueError("transfer artifact input roles do not replay")
        if len({(row.artist_mbid, row.stable_seed_id) for row in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("transfer candidates must be unique artist-seed pairs")
        if any(
            row.artist_mbid == support.source_artist_mbid
            for row in self.candidates
            for support in row.retained_supports
        ):
            raise ValueError("a target artist cannot support its own transferred candidate")
        if self.coverage.candidate_count != len(self.candidates):
            raise ValueError("coverage candidate count does not replay")
        if (
            len({row.artist_mbid for row in self.candidates})
            != self.coverage.eligible_cold_artist_count
        ):
            raise ValueError("coverage eligible artist count does not replay")
        evaluations = (
            self.heldout_evaluation,
            self.train_only_global_popularity_baseline,
            self.direct_only_no_colisten_ablation,
        )
        heldout_counts = {item.heldout_direct_positive_count for item in evaluations}
        eligible_counts = {item.eligible_heldout_artist_count for item in evaluations}
        if len(heldout_counts) != 1 or len(eligible_counts) != 1:
            raise ValueError("evaluation cohorts do not share held-out positive and artist counts")
        return self


class CoListenMembershipTransferReceipt(FrozenModel):
    """Byte custody for a compact, immutable transfer artifact."""

    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)


def settings_sha256(settings: CoListenMembershipTransferSettings) -> str:
    """Hash every evaluated transfer control."""
    return sha256_hex(canonical_json(settings.model_dump(mode="json")))


def artifact_sha256(artifact: CoListenMembershipTransferArtifact) -> str:
    """Return the logical digest excluding its self-referential hash."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_colisten_membership_transfer(artifact: CoListenMembershipTransferArtifact) -> None:
    """Fail closed unless settings and logical artifact hashes replay exactly."""
    if artifact.settings_sha256 != settings_sha256(artifact.settings):
        raise CoListenMembershipTransferError("transfer settings hash does not replay")
    if artifact.output_sha256 != artifact_sha256(artifact):
        raise CoListenMembershipTransferError("transfer artifact hash does not replay")
