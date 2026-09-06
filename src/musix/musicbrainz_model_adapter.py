"""Adapt stable-ID MusicBrainz seed evidence into the public model boundary.

The extractor has already matched source claims to stable seed IDs.  This
adapter performs no lexical identity resolution.  It only verifies the two
sealed artifacts, preserves genre/tag facets, aggregates positive evidence,
and accounts for every retained seed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Final, Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.models.modeling import (
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
)
from musix.musicbrainz_seed_targets import (
    MusicBrainzSeedTargetArtifact,
    SeedTargetEvidence,
    verify_seed_target_artifact,
)
from musix.seed_reconciliation import (
    SeedReconciliationArtifact,
    verify_seed_reconciliation,
)
from musix.types import Sha256  # noqa: TC001

_REVISION: Final = "musicbrainz-model-adapter-v1"
_MAX_EVIDENCE_REFS = 512
_MAX_MEMBERSHIPS = 1_000_000

type AdapterFacet = Literal["musicbrainz_genre", "musicbrainz_tag"]
type RejectionReason = Literal[
    "unknown_seed_id",
    "seed_name_mismatch",
    "non_positive_weight",
    "membership_bound_exceeded",
]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha(value: object) -> Sha256:
    return hashlib.sha256(_canonical(value)).hexdigest()


class MusicBrainzModelAdapterPolicy(FrozenModel):
    """Bounds for deterministic adapter aggregation."""

    revision: Literal["musicbrainz-model-adapter-policy-v1"] = "musicbrainz-model-adapter-policy-v1"
    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    maximum_memberships: int = Field(default=_MAX_MEMBERSHIPS, ge=1, le=5_000_000)
    maximum_evidence_refs_per_membership: int = Field(default=_MAX_EVIDENCE_REFS, ge=1, le=10_000)


class AdapterRejectedEvidence(FrozenModel):
    """One extractor row deliberately excluded from model input."""

    seed_source_item_id: str = Field(min_length=1, max_length=200)
    artist_id: str = Field(min_length=1, max_length=100)
    facet: Literal["genre", "tag"]
    evidence_ref: str = Field(min_length=1, max_length=500)
    reason: RejectionReason


class AdapterAggregate(FrozenModel):
    """One deduplicated artist-seed-facet row and all source evidence refs."""

    seed_source_item_id: str = Field(min_length=1, max_length=200)
    artist_id: str = Field(min_length=1, max_length=100)
    facet: AdapterFacet
    positive_weight: FiniteFloat = Field(gt=0.0)
    source_evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=_MAX_EVIDENCE_REFS)


class AdapterSeedCoverage(FrozenModel):
    """Per-seed accounting for all 6,291 stable IDs."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    accepted_evidence_count: int = Field(ge=0)
    rejected_evidence_count: int = Field(ge=0)
    aggregate_membership_count: int = Field(ge=0)
    genre_membership_count: int = Field(ge=0)
    tag_membership_count: int = Field(ge=0)


class MusicBrainzModelAdapterReport(FrozenModel):
    """Hash-bound adapter report with explicit source and rejection accounting."""

    revision: Literal["musicbrainz-model-adapter-v1"] = _REVISION
    seed_reconciliation_output_sha256: Sha256
    seed_target_output_sha256: Sha256
    seed_target_archive_sha256: Sha256
    target_seed_input_sha256: Sha256
    reconciliation_seed_input_sha256: Sha256
    seed_source_id: str = Field(min_length=1)
    seed_source_content_sha256: Sha256
    seed_identity_fingerprint: Sha256
    policy_sha256: Sha256
    accepted_evidence_count: int = Field(ge=0)
    rejected_evidence_count: int = Field(ge=0)
    unattributed_rejected_evidence_count: int = Field(ge=0)
    aggregate_membership_count: int = Field(ge=0)
    seed_count: int = Field(ge=1)
    coverage: tuple[AdapterSeedCoverage, ...] = Field(min_length=1)
    rejected: tuple[AdapterRejectedEvidence, ...] = ()
    historical_data_used_for_construction: Literal[False] = False
    lexical_identity_resolution_rerun: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_counts_and_coverage(self) -> MusicBrainzModelAdapterReport:
        """Ensure report rows account for every source and stable seed."""
        if len(self.coverage) != self.seed_count:
            raise ValueError("adapter coverage must contain every stable seed")
        if (
            self.accepted_evidence_count + self.rejected_evidence_count
            != sum(
                row.accepted_evidence_count + row.rejected_evidence_count for row in self.coverage
            )
            + self.unattributed_rejected_evidence_count
        ):
            raise ValueError("adapter evidence counts do not match seed coverage")
        if self.rejected_evidence_count != len(self.rejected):
            raise ValueError("adapter rejection count does not match rejection rows")
        if self.aggregate_membership_count != sum(
            row.aggregate_membership_count for row in self.coverage
        ):
            raise ValueError("adapter aggregate count does not match seed coverage")
        return self


class MusicBrainzModelAdapterResult(FrozenModel):
    """Public input plus the report and deduplication rows used to create it."""

    model_input: PublicModelInput
    aggregates: tuple[AdapterAggregate, ...]
    report: MusicBrainzModelAdapterReport


@dataclass
class _AggregateState:
    weight: float = 0.0
    refs: set[str] = field(default_factory=set)


def adapter_report_sha256(report: MusicBrainzModelAdapterReport) -> Sha256:
    """Recompute a report hash without trusting its stored value."""
    return _sha(report.model_dump(mode="json", exclude={"output_sha256"}))


def verify_musicbrainz_model_adapter_report(report: MusicBrainzModelAdapterReport) -> None:
    """Fail closed if an adapter report was changed."""
    if adapter_report_sha256(report) != report.output_sha256:
        raise ValueError("MusicBrainz model adapter report hash does not replay")


def _source_ref(row: SeedTargetEvidence) -> str:
    return f"{row.evidence_ref}|target:{row.target_namespace}:{row.target_identity}"


def _seed_evidence_set_ref(target_output_sha256: Sha256, seed_id: str, refs: set[str]) -> str:
    """Keep seed identity provenance bounded while binding every direct row.

    A popular seed can have tens of thousands of direct claims.  Its concrete
    membership rows already carry a source-derived reference, while this genre
    identity points to the sealed target artifact and a hash of the complete
    per-seed evidence set.  It must not expand an identity's bounded reference
    field into an unparseable copy of the corpus.
    """
    return (
        f"mb-seed-target-evidence-set:{target_output_sha256}:{seed_id}:{_sha(tuple(sorted(refs)))}"
    )


def _facet(row: SeedTargetEvidence) -> AdapterFacet:
    return "musicbrainz_genre" if row.facet == "genre" else "musicbrainz_tag"


def _seed_identity_fingerprint(rows: object) -> Sha256:
    """Fingerprint the immutable seed identity triple, not a producer-specific wrapper.

    The target extractor records ``SeedInput.artifact_sha256`` while seed
    reconciliation records a hash of the complete ``SeedInput`` model.  Those
    are intentionally different hash domains.  The adapter must instead bind
    the exact ``(source item ID, external ID, name)`` universe it actually
    joins, while preserving both original hashes in its report.
    """
    return _sha(rows)


def adapt_musicbrainz_seed_targets(  # noqa: C901, PLR0912, PLR0915
    target: MusicBrainzSeedTargetArtifact,
    reconciliation: SeedReconciliationArtifact,
    policy: MusicBrainzModelAdapterPolicy | None = None,
) -> MusicBrainzModelAdapterResult:
    """Convert verified stable-ID extractor evidence into all-seed public input."""
    resolved = policy or MusicBrainzModelAdapterPolicy()
    verify_seed_target_artifact(target)
    verify_seed_reconciliation(reconciliation)
    if target.seed_count != resolved.expected_seed_count:
        raise ValueError("seed-target artifact does not contain the expected seed universe")
    if reconciliation.seed_count != resolved.expected_seed_count:
        raise ValueError("seed reconciliation does not contain the expected seed universe")
    reconciliation_rows = {row.source_item_id: row for row in reconciliation.dispositions}
    target_rows = {row.seed_source_item_id: row for row in target.coverage}
    if set(reconciliation_rows) != set(target_rows):
        raise ValueError("seed-target coverage and reconciliation do not cover the same IDs")
    if target.seed_source_id != reconciliation.seed_source_id:
        raise ValueError("seed-target and reconciliation source IDs do not match")
    if target.seed_source_content_sha256 != reconciliation.seed_source_content_sha256:
        raise ValueError("seed-target and reconciliation source content hashes do not match")
    target_seed_identity_fingerprint = _seed_identity_fingerprint(
        [
            {
                "source_item_id": row.seed_source_item_id,
                "source_external_id": row.seed_source_external_id,
                "name": row.seed_name,
            }
            for row in sorted(target.coverage, key=lambda item: item.seed_source_item_id)
        ]
    )
    reconciliation_seed_identity_fingerprint = _seed_identity_fingerprint(
        [
            {
                "source_item_id": row.source_item_id,
                "source_external_id": row.source_external_id,
                "name": row.seed_name,
            }
            for row in sorted(reconciliation.dispositions, key=lambda item: item.source_item_id)
        ]
    )
    if target_seed_identity_fingerprint != reconciliation_seed_identity_fingerprint:
        raise ValueError("seed-target and reconciliation seed identities do not match")
    if target_seed_identity_fingerprint != reconciliation.seed_identity_sha256:
        raise ValueError("reconciliation seed identity hash does not match its stable seed set")
    aggregates: dict[tuple[str, str, AdapterFacet], _AggregateState] = defaultdict(_AggregateState)
    rejected: list[AdapterRejectedEvidence] = []
    accepted_by_seed: Counter[str] = Counter()
    rejected_by_seed: Counter[str] = Counter()
    evidence_by_seed: dict[str, set[str]] = defaultdict(set)
    unattributed_rejected_count = 0
    accepted_count = 0
    for row in target.evidence:
        evidence_by_seed[row.seed_source_item_id].add(row.evidence_ref)
        reason: RejectionReason | None = None
        reconciliation_row = reconciliation_rows.get(row.seed_source_item_id)
        if reconciliation_row is None:
            reason = "unknown_seed_id"
        elif reconciliation_row.seed_name != row.seed_name:
            reason = "seed_name_mismatch"
        elif row.positive_weight <= 0.0:
            reason = "non_positive_weight"
        elif (
            len(aggregates) >= resolved.maximum_memberships
            and (
                row.seed_source_item_id,
                row.artist_id,
                _facet(row),
            )
            not in aggregates
        ):
            reason = "membership_bound_exceeded"
        if reason is not None:
            if reconciliation_row is None:
                unattributed_rejected_count += 1
            else:
                rejected_by_seed[row.seed_source_item_id] += 1
            rejected.append(
                AdapterRejectedEvidence(
                    seed_source_item_id=row.seed_source_item_id,
                    artist_id=row.artist_id,
                    facet=row.facet,
                    evidence_ref=row.evidence_ref,
                    reason=reason,
                )
            )
            continue
        key = (row.seed_source_item_id, f"musicbrainz:artist:{row.artist_id}", _facet(row))
        state = aggregates.setdefault(key, _AggregateState())
        state.weight += row.positive_weight
        state.refs.add(_source_ref(row))
        if len(state.refs) > resolved.maximum_evidence_refs_per_membership:
            raise ValueError("adapter evidence references exceed the declared bound")
        accepted_count += 1
        accepted_by_seed[row.seed_source_item_id] += 1
    ordered_aggregates = tuple(
        AdapterAggregate(
            seed_source_item_id=seed_id,
            artist_id=artist_id,
            facet=facet,
            positive_weight=weight.weight,
            source_evidence_refs=tuple(sorted(weight.refs)),
        )
        for (seed_id, artist_id, facet), weight in sorted(aggregates.items())
    )
    aggregate_by_seed: Counter[str] = Counter(row.seed_source_item_id for row in ordered_aggregates)
    genre_aggregate_by_seed: Counter[str] = Counter(
        row.seed_source_item_id for row in ordered_aggregates if row.facet == "musicbrainz_genre"
    )
    tag_aggregate_by_seed: Counter[str] = Counter(
        row.seed_source_item_id for row in ordered_aggregates if row.facet == "musicbrainz_tag"
    )
    coverage = tuple(
        AdapterSeedCoverage(
            source_item_id=seed_id,
            seed_name=reconciliation_rows[seed_id].seed_name,
            accepted_evidence_count=accepted_by_seed[seed_id],
            rejected_evidence_count=rejected_by_seed[seed_id],
            aggregate_membership_count=aggregate_by_seed[seed_id],
            genre_membership_count=genre_aggregate_by_seed[seed_id],
            tag_membership_count=tag_aggregate_by_seed[seed_id],
        )
        for seed_id in sorted(reconciliation_rows)
    )
    genres = tuple(
        GenreIdentity(
            genre_id=seed_id,
            name=row.seed_name,
            evidence_refs=(
                f"seed-reconciliation:{reconciliation.output_sha256}:{seed_id}",
                _seed_evidence_set_ref(
                    target.output_sha256,
                    seed_id,
                    evidence_by_seed[seed_id],
                ),
            ),
        )
        for seed_id, row in sorted(reconciliation_rows.items())
    )
    memberships = tuple(
        DirectMembershipEvidence(
            artist_id=row.artist_id,
            genre_id=row.seed_source_item_id,
            facet=row.facet,
            value=row.positive_weight,
            evidence_ref=(
                f"mb-seed-target:{target.output_sha256}:{row.seed_source_item_id}:"
                f"{row.artist_id}:{row.facet}:{_sha(row.source_evidence_refs)[:24]}"
            ),
        )
        for row in ordered_aggregates
    )
    model_input = PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="musicbrainz",
                snapshot=target.artifact_revision,
                artifact_key="musicbrainz-seed-target-artifact",
                content_sha256=target.output_sha256,
                export_allowed=False,
            ),
        ),
        genres=genres,
        direct_memberships=memberships,
    )
    report_without_hash = MusicBrainzModelAdapterReport(
        seed_reconciliation_output_sha256=reconciliation.output_sha256,
        seed_target_output_sha256=target.output_sha256,
        seed_target_archive_sha256=target.archive_sha256,
        target_seed_input_sha256=target.seed_input_sha256,
        reconciliation_seed_input_sha256=reconciliation.seed_input_sha256,
        seed_source_id=target.seed_source_id,
        seed_source_content_sha256=target.seed_source_content_sha256,
        seed_identity_fingerprint=target_seed_identity_fingerprint,
        policy_sha256=_sha(resolved.model_dump(mode="json")),
        accepted_evidence_count=accepted_count,
        rejected_evidence_count=len(rejected),
        unattributed_rejected_evidence_count=unattributed_rejected_count,
        aggregate_membership_count=len(ordered_aggregates),
        seed_count=resolved.expected_seed_count,
        coverage=coverage,
        rejected=tuple(rejected),
        output_sha256="0" * 64,
    )
    report = report_without_hash.model_copy(
        update={"output_sha256": adapter_report_sha256(report_without_hash)}
    )
    verify_musicbrainz_model_adapter_report(report)
    return MusicBrainzModelAdapterResult(
        model_input=model_input,
        aggregates=ordered_aggregates,
        report=report,
    )
