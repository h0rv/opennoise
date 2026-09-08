"""Build a small reviewed-alias enrichment from retained contextual MusicBrainz tags."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, TypeAdapter, model_validator

from musix.models import FrozenModel
from musix.models.modeling import DirectMembershipEvidence, PublicArtifact, PublicModelInput
from musix.musicbrainz_model_adapter import (
    AdapterAggregate,
    AdapterFacet,
    MusicBrainzModelAdapterPolicy,
    MusicBrainzModelAdapterReport,
    MusicBrainzModelAdapterResult,
    adapt_musicbrainz_seed_targets,
    verify_musicbrainz_model_adapter_report,
)
from musix.musicbrainz_seed_targets import (
    ReviewedSeedAlias,
    load_seed_target_artifact,
    normalize_label,
    verify_seed_target_artifact,
)
from musix.types import Sha256  # noqa: TC001

_MAX_ROWS: Final = 10_000
_REVISION: Final = "musicbrainz-reviewed-alias-context-v1"

if TYPE_CHECKING:
    from pathlib import Path

    from musix.musicbrainz_seed_targets import MusicBrainzSeedTargetArtifact
    from musix.seed_reconciliation import SeedReconciliationArtifact


class ReviewedAliasContextError(ValueError):
    """Report an invalid reviewed alias overlay or retained-context source."""


class ReviewedAliasContextMembership(FrozenModel):
    """One exact tag claim retained for an approved stable-seed alias."""

    evidence_kind: Literal["reviewed_alias_context"] = "reviewed_alias_context"
    seed_source_item_id: str = Field(min_length=1)
    artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    facet: Literal["tag"] = "tag"
    tag_identity: str = Field(min_length=1)
    tag_name: str = Field(min_length=1)
    tag_count: int = Field(ge=1)
    positive_weight: float = Field(gt=0.0)
    source_record_id: str = Field(min_length=1)
    source_record_ordinal: int = Field(gt=0)
    source_record_sha256: Sha256
    source_record_byte_length: int = Field(gt=0)
    contextual_evidence_ref: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    alias_config_sha256: Sha256


class ReviewedAliasContextArtifact(FrozenModel):
    """Hash-bound additive membership enrichment, never a baseline replacement."""

    revision: Literal["musicbrainz-reviewed-alias-context-v1"] = _REVISION
    scope: Literal["retained_contextual_tags_only"] = "retained_contextual_tags_only"
    baseline_output_sha256: Sha256
    baseline_file_sha256: Sha256
    baseline_file_bytes: int = Field(gt=0)
    alias_config_sha256: Sha256
    alias_mapping_sha256: Sha256
    memberships: tuple[ReviewedAliasContextMembership, ...] = Field(max_length=_MAX_ROWS)
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_unique_memberships(self) -> ReviewedAliasContextArtifact:
        """Reject repeated stable seed and artist memberships."""
        keys = {(row.seed_source_item_id, row.artist_id) for row in self.memberships}
        if len(keys) != len(self.memberships):
            raise ValueError("reviewed alias context memberships must be unique by seed and artist")
        return self


class ReviewedAliasCombinedAdapterResult(FrozenModel):
    """Separate local adapter result that preserves reviewed-context lineage."""

    revision: Literal["musicbrainz-reviewed-alias-combined-adapter-v1"] = (
        "musicbrainz-reviewed-alias-combined-adapter-v1"
    )
    baseline_adapter_output_sha256: Sha256
    baseline_seed_target_output_sha256: Sha256
    reviewed_alias_context_output_sha256: Sha256
    baseline_unique_seed_artist_count: int = Field(ge=0)
    reviewed_alias_unique_seed_artist_count: int = Field(ge=0)
    combined_unique_seed_artist_count: int = Field(ge=0)
    reviewed_alias_context_aggregates: tuple[AdapterAggregate, ...]
    combined_aggregates: tuple[AdapterAggregate, ...]
    model_input: PublicModelInput
    output_sha256: Sha256


class ReviewedAliasCombinedModelReceipt(FrozenModel):
    """Bind a separately written combined input to its immutable source artifacts."""

    revision: Literal["musicbrainz-reviewed-alias-combined-model-v1"] = (
        "musicbrainz-reviewed-alias-combined-model-v1"
    )
    baseline_model_input_sha256: Sha256
    baseline_adapter_output_sha256: Sha256
    baseline_seed_target_output_sha256: Sha256
    reviewed_alias_context_output_sha256: Sha256
    combined_model_input_sha256: Sha256
    baseline_unique_seed_artist_count: int = Field(ge=0)
    reviewed_alias_unique_seed_artist_count: int = Field(ge=0)
    combined_unique_seed_artist_count: int = Field(ge=0)
    output_sha256: Sha256


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha(value: object) -> Sha256:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> tuple[Sha256, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def artifact_sha256(artifact: ReviewedAliasContextArtifact) -> Sha256:
    """Return the logical hash of one reviewed-alias context artifact."""
    return _sha(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def verify_reviewed_alias_context_artifact(artifact: ReviewedAliasContextArtifact) -> None:
    """Fail closed when a reviewed-alias context artifact was changed."""
    if artifact_sha256(artifact) != artifact.output_sha256:
        raise ReviewedAliasContextError("reviewed alias context artifact hash does not replay")


def load_reviewed_aliases(path: Path) -> tuple[ReviewedSeedAlias, ...]:
    """Load and reject ambiguous or malformed reviewed alias configuration."""
    try:
        aliases = TypeAdapter(tuple[ReviewedSeedAlias, ...]).validate_json(path.read_bytes())
    except (OSError, TypeError, ValueError) as error:
        raise ReviewedAliasContextError("reviewed alias configuration is invalid") from error
    normalized = [normalize_label(row.alias) for row in aliases]
    if (
        not aliases
        or any(not value for value in normalized)
        or len(set(normalized)) != len(normalized)
    ):
        raise ReviewedAliasContextError("reviewed aliases must be nonempty and unique")
    return aliases


def build_reviewed_alias_context(
    *, baseline_path: Path, alias_config_path: Path
) -> ReviewedAliasContextArtifact:
    """Replay approved tag aliases against already-retained contextual tag rows."""
    baseline = load_seed_target_artifact(baseline_path)
    verify_seed_target_artifact(baseline)
    aliases = load_reviewed_aliases(alias_config_path)
    baseline_ids = {row.seed_source_item_id for row in baseline.coverage}
    canonical = {normalize_label(row.seed_name) for row in baseline.coverage}
    alias_sha, _ = _file_sha(alias_config_path)
    alias_rows = tuple(
        sorted(
            aliases,
            key=lambda row: (row.source_item_id, normalize_label(row.alias), row.approval_ref),
        )
    )
    approvals = _sha([row.model_dump(mode="json") for row in alias_rows])
    allowed = {
        normalize_label(row.alias): row
        for row in aliases
        if row.facets == ("tag",) and row.source_item_id in baseline_ids
    }
    if len(allowed) != len(aliases) or set(allowed) & canonical:
        raise ReviewedAliasContextError("reviewed aliases must target known noncanonical tag seeds")
    memberships: dict[tuple[str, str], ReviewedAliasContextMembership] = {}
    for row in baseline.contextual_tags:
        alias = allowed.get(normalize_label(row.tag_name))
        if (
            alias is None
            or row.tag_count is None
            or row.tag_count <= 0
            or row.tag_identity != f"tag:{normalize_label(alias.alias)}"
        ):
            continue
        key = (alias.source_item_id, row.artist_id)
        memberships.setdefault(
            key,
            ReviewedAliasContextMembership(
                seed_source_item_id=alias.source_item_id,
                artist_id=row.artist_id,
                tag_identity=row.tag_identity,
                tag_name=row.tag_name,
                tag_count=row.tag_count,
                positive_weight=float(row.tag_count),
                source_record_id=row.source_record_id,
                source_record_ordinal=row.source_record_ordinal,
                source_record_sha256=row.source_record_sha256,
                source_record_byte_length=row.source_record_byte_length,
                contextual_evidence_ref=row.evidence_ref,
                approval_ref=alias.approval_ref,
                alias_config_sha256=alias_sha,
            ),
        )
        if len(memberships) > _MAX_ROWS:
            raise ReviewedAliasContextError("reviewed alias context exceeds membership bound")
    baseline_sha, baseline_bytes = _file_sha(baseline_path)
    preliminary = ReviewedAliasContextArtifact(
        baseline_output_sha256=baseline.output_sha256,
        baseline_file_sha256=baseline_sha,
        baseline_file_bytes=baseline_bytes,
        alias_config_sha256=alias_sha,
        alias_mapping_sha256=approvals,
        memberships=tuple(
            sorted(memberships.values(), key=lambda row: (row.seed_source_item_id, row.artist_id))
        ),
        output_sha256="0" * 64,
    )
    artifact = preliminary.model_copy(update={"output_sha256": artifact_sha256(preliminary)})
    verify_reviewed_alias_context_artifact(artifact)
    return artifact


def write_reviewed_alias_context(path: Path, artifact: ReviewedAliasContextArtifact) -> None:
    """Write a verified reviewed-alias context artifact canonically."""
    verify_reviewed_alias_context_artifact(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(artifact.model_dump(mode="json")) + b"\n")


def combined_adapter_sha256(result: ReviewedAliasCombinedAdapterResult) -> Sha256:
    """Return the logical hash for one separate additive adapter result."""
    return _sha(result.model_dump(mode="json", exclude={"output_sha256"}))


def public_model_input_sha256(model_input: PublicModelInput) -> Sha256:
    """Hash one public model input without assigning it a mutable wrapper."""
    return _sha(model_input.model_dump(mode="json"))


def combined_model_receipt_sha256(receipt: ReviewedAliasCombinedModelReceipt) -> Sha256:
    """Return the logical hash of one combined-model receipt."""
    return _sha(receipt.model_dump(mode="json", exclude={"output_sha256"}))


def verify_reviewed_alias_combined_model_receipt(
    receipt: ReviewedAliasCombinedModelReceipt,
) -> None:
    """Fail closed when a combined-model receipt does not replay."""
    if combined_model_receipt_sha256(receipt) != receipt.output_sha256:
        raise ReviewedAliasContextError(
            "reviewed alias combined model receipt hash does not replay"
        )


def combine_reviewed_alias_context_model_input(
    baseline_model_input: PublicModelInput,
    baseline_adapter_report: MusicBrainzModelAdapterReport,
    context: ReviewedAliasContextArtifact,
) -> tuple[PublicModelInput, ReviewedAliasCombinedModelReceipt]:
    """Add reviewed context to an already materialized baseline input exactly once.

    This does not re-read the large seed-target extractor artifact.  The adapter
    report supplies the sealed target identity that both inputs must bind.
    """
    verify_musicbrainz_model_adapter_report(baseline_adapter_report)
    verify_reviewed_alias_context_artifact(context)
    if context.baseline_output_sha256 != baseline_adapter_report.seed_target_output_sha256:
        raise ReviewedAliasContextError("reviewed alias context does not bind the adapter target")
    baseline_target_artifacts = {
        row.content_sha256
        for row in baseline_model_input.artifacts
        if row.source == "musicbrainz" and row.artifact_key == "musicbrainz-seed-target-artifact"
    }
    if baseline_target_artifacts != {baseline_adapter_report.seed_target_output_sha256}:
        raise ReviewedAliasContextError("baseline model input does not bind the adapter target")
    baseline_pairs = {
        (row.genre_id, row.artist_id.removeprefix("musicbrainz:artist:"))
        for row in baseline_model_input.direct_memberships
    }
    context_pairs = {(row.seed_source_item_id, row.artist_id) for row in context.memberships}
    memberships = {
        (row.genre_id, row.artist_id, row.facet): row
        for row in baseline_model_input.direct_memberships
    }
    for row in context.memberships:
        key = (row.seed_source_item_id, f"musicbrainz:artist:{row.artist_id}", "musicbrainz_tag")
        context_ref = (
            f"reviewed-alias-context:{context.output_sha256}:{row.contextual_evidence_ref}:"
            f"target:musicbrainz_tag_name:{row.tag_identity}:{row.approval_ref}:"
            f"{context.alias_mapping_sha256}"
        )
        baseline = memberships.get(key)
        if baseline is None:
            memberships[key] = DirectMembershipEvidence(
                artist_id=key[1],
                genre_id=key[0],
                facet="musicbrainz_tag",
                value=row.positive_weight,
                evidence_ref=context_ref,
            )
            continue
        memberships[key] = DirectMembershipEvidence(
            artist_id=baseline.artist_id,
            genre_id=baseline.genre_id,
            facet=baseline.facet,
            value=baseline.value + row.positive_weight,
            evidence_ref=(
                f"reviewed-alias-context-union:{context.output_sha256}:{baseline.evidence_ref}:"
                f"{_sha((context_ref,))[:24]}"
            ),
        )
    if context.memberships:
        combined = PublicModelInput(
            artifacts=(
                *baseline_model_input.artifacts,
                PublicArtifact(
                    source="musicbrainz",
                    snapshot=context.revision,
                    artifact_key="musicbrainz-reviewed-alias-context",
                    content_sha256=context.output_sha256,
                    export_allowed=False,
                ),
            ),
            genres=baseline_model_input.genres,
            direct_memberships=tuple(memberships[key] for key in sorted(memberships)),
            artist_pairs=baseline_model_input.artist_pairs,
            metadata_candidates=baseline_model_input.metadata_candidates,
            hierarchy=baseline_model_input.hierarchy,
        )
    else:
        combined = baseline_model_input
    preliminary = ReviewedAliasCombinedModelReceipt(
        baseline_model_input_sha256=public_model_input_sha256(baseline_model_input),
        baseline_adapter_output_sha256=baseline_adapter_report.output_sha256,
        baseline_seed_target_output_sha256=baseline_adapter_report.seed_target_output_sha256,
        reviewed_alias_context_output_sha256=context.output_sha256,
        combined_model_input_sha256=public_model_input_sha256(combined),
        baseline_unique_seed_artist_count=len(baseline_pairs),
        reviewed_alias_unique_seed_artist_count=len(context_pairs),
        combined_unique_seed_artist_count=len(baseline_pairs | context_pairs),
        output_sha256="0" * 64,
    )
    receipt = preliminary.model_copy(
        update={"output_sha256": combined_model_receipt_sha256(preliminary)}
    )
    verify_reviewed_alias_combined_model_receipt(receipt)
    return combined, receipt


def adapt_reviewed_alias_context(
    baseline: MusicBrainzSeedTargetArtifact,
    reconciliation: SeedReconciliationArtifact,
    context: ReviewedAliasContextArtifact,
    policy: MusicBrainzModelAdapterPolicy | None = None,
) -> ReviewedAliasCombinedAdapterResult:
    """Bind a reviewed-context union to an unchanged baseline adapter result."""
    verify_reviewed_alias_context_artifact(context)
    if context.baseline_output_sha256 != baseline.output_sha256:
        raise ReviewedAliasContextError("reviewed alias context does not bind the baseline target")
    baseline_result: MusicBrainzModelAdapterResult = adapt_musicbrainz_seed_targets(
        baseline, reconciliation, policy
    )
    baseline_pairs = {
        (row.seed_source_item_id, row.artist_id.removeprefix("musicbrainz:artist:"))
        for row in baseline_result.aggregates
    }
    context_aggregates = tuple(
        AdapterAggregate(
            seed_source_item_id=row.seed_source_item_id,
            artist_id=f"musicbrainz:artist:{row.artist_id}",
            facet="musicbrainz_tag",
            positive_weight=row.positive_weight,
            source_evidence_refs=(
                (
                    f"reviewed-alias-context:{context.output_sha256}:{row.contextual_evidence_ref}:"
                    f"target:musicbrainz_tag_name:{row.tag_identity}:{row.approval_ref}:"
                    f"{context.alias_mapping_sha256}"
                ),
            ),
        )
        for row in context.memberships
    )
    aggregate_states: dict[tuple[str, str, AdapterFacet], tuple[float, set[str]]] = {
        (row.seed_source_item_id, row.artist_id, row.facet): (
            row.positive_weight,
            set(row.source_evidence_refs),
        )
        for row in baseline_result.aggregates
    }
    for row in context_aggregates:
        key = (row.seed_source_item_id, row.artist_id, row.facet)
        weight, refs = aggregate_states.get(key, (0.0, set()))
        refs.update(row.source_evidence_refs)
        aggregate_states[key] = (weight + row.positive_weight, refs)
    combined_aggregates = tuple(
        AdapterAggregate(
            seed_source_item_id=seed_id,
            artist_id=artist_id,
            facet=facet,
            positive_weight=weight,
            source_evidence_refs=tuple(sorted(refs)),
        )
        for (seed_id, artist_id, facet), (weight, refs) in sorted(aggregate_states.items())
    )
    if context_aggregates:
        baseline_memberships = {
            (row.genre_id, row.artist_id, row.facet): row
            for row in baseline_result.model_input.direct_memberships
        }
        combined_memberships: list[DirectMembershipEvidence] = []
        for row in combined_aggregates:
            key = (row.seed_source_item_id, row.artist_id, row.facet)
            baseline_membership = baseline_memberships.get(key)
            if baseline_membership is not None and len(row.source_evidence_refs) == 1:
                combined_memberships.append(baseline_membership)
                continue
            lineage = _sha(row.source_evidence_refs)[:24]
            combined_memberships.append(
                DirectMembershipEvidence(
                    artist_id=row.artist_id,
                    genre_id=row.seed_source_item_id,
                    facet=row.facet,
                    value=row.positive_weight,
                    evidence_ref=(
                        f"reviewed-alias-context-union:{context.output_sha256}:"
                        f"{row.seed_source_item_id}:{row.artist_id}:{row.facet}:{lineage}"
                    ),
                )
            )
        model_input = PublicModelInput(
            artifacts=(
                *baseline_result.model_input.artifacts,
                PublicArtifact(
                    source="musicbrainz",
                    snapshot=context.revision,
                    artifact_key="musicbrainz-reviewed-alias-context",
                    content_sha256=context.output_sha256,
                    export_allowed=False,
                ),
            ),
            genres=baseline_result.model_input.genres,
            direct_memberships=tuple(combined_memberships),
            artist_pairs=baseline_result.model_input.artist_pairs,
            metadata_candidates=baseline_result.model_input.metadata_candidates,
            hierarchy=baseline_result.model_input.hierarchy,
        )
    else:
        model_input = baseline_result.model_input
    context_pairs = {(row.seed_source_item_id, row.artist_id) for row in context.memberships}
    preliminary = ReviewedAliasCombinedAdapterResult(
        baseline_adapter_output_sha256=baseline_result.report.output_sha256,
        baseline_seed_target_output_sha256=baseline.output_sha256,
        reviewed_alias_context_output_sha256=context.output_sha256,
        baseline_unique_seed_artist_count=len(baseline_pairs),
        reviewed_alias_unique_seed_artist_count=len(context_pairs),
        combined_unique_seed_artist_count=len(baseline_pairs | context_pairs),
        reviewed_alias_context_aggregates=context_aggregates,
        combined_aggregates=combined_aggregates,
        model_input=model_input,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": combined_adapter_sha256(preliminary)})
