"""Build a source-neutral, conservative open-label alignment checkpoint.

The only target-side construction input is the immutable seed name and its
open reconciliation state.  The graph supplies independently identifiable
open labels and their observed support.  Historical outputs are intentionally
absent from this module; they belong in ``diagnostics`` after this artifact has
been sealed.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from opennoise.common import (
    canonical_json,
    connect_readonly,
    sha256_file,
    sha256_hex,
    write_durable_bytes,
)
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.ml.label_alignment.contracts import (
    ColdLabelAlignmentArtifact,
    ColdLabelAlignmentCoverage,
    ColdLabelAlignmentReceipt,
    ColdLabelAlignmentSettings,
    DispositionCoverage,
    InputBinding,
    LabelAlignmentAbstention,
    LabelAlignmentCandidate,
    MaskedEvaluation,
    OpenIdentityNamespace,
    OpenIdentityReference,
    SeedPartitionRow,
)
from opennoise.ml.label_alignment.normalize import (
    character_ngram_cosine,
    head_modifier_score,
    initialism_forms,
    is_generic_root,
    normalized_label,
    semantic_alias_target,
    shares_retrieval_token,
    token_jaccard,
    tokens,
)
from opennoise.ml.label_alignment.release_group_vocabulary import (
    ReleaseGroupVocabularyArtifact,
    ReleaseGroupVocabularyReceipt,
    verify_release_group_vocabulary,
)
from opennoise.taxonomy.seeds.reconciliation import (
    ReconciledIdentity,
    SeedReconciliationArtifact,
    SeedReconciliationDisposition,
    load_seed_reconciliation,
)

if TYPE_CHECKING:
    from pathlib import Path

_OPEN_NAMESPACES: Final = frozenset(
    {"musicbrainz_genre_id", "musicbrainz_tag_name", "wikidata_genre_qid"}
)
_TRUSTED_DISPOSITIONS: Final = frozenset({"reconciled", "public_only", "musicbrainz_only"})
_COMPOSITIONAL_HEAD_MINIMUM: Final = 0.6


class ColdLabelAlignmentError(ValueError):
    """A source cannot support a safe, replayable cold-label alignment."""


@dataclass(frozen=True, slots=True)
class ColdLabelAlignmentInputs:
    """The sealed graph and complete reconciliation required for one run."""

    graph_database: Path
    graph_receipt: Path
    reconciliation: Path
    supplemental_vocabulary: Path | None = None
    supplemental_vocabulary_receipt: Path | None = None


@dataclass(frozen=True, slots=True)
class _Cluster:
    normalized: str
    label: str
    identities: tuple[OpenIdentityReference, ...]
    context_score: float


@dataclass(frozen=True, slots=True)
class _Vocabulary:
    clusters: tuple[_Cluster, ...]
    by_identity: dict[tuple[str, str], _Cluster]
    by_normalized: dict[str, _Cluster]
    by_compact_label: dict[str, tuple[_Cluster, ...]]
    by_head: dict[str, tuple[_Cluster, ...]]
    projected_identity_count: int
    supplemental_identity_count: int


@dataclass(frozen=True, slots=True)
class _MaskedOutcome:
    retrievable: bool
    top_1_hit: bool
    top_k_hit: bool
    accepted_prediction: bool
    accepted_hit: bool
    review_prediction: bool
    review_hit: bool
    acronym_review_prediction: bool
    acronym_review_hit: bool


def cold_label_alignment_settings_sha256(settings: ColdLabelAlignmentSettings) -> str:
    """Hash fixed matcher controls before reading any source rows."""
    return sha256_hex(canonical_json(settings.model_dump(mode="json")))


def cold_label_alignment_artifact_sha256(artifact: ColdLabelAlignmentArtifact) -> str:
    """Return the logical digest of a sealed construction-only artifact."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_cold_label_alignment(artifact: ColdLabelAlignmentArtifact) -> None:
    """Fail closed if artifact data no longer replays its declared digest."""
    try:
        ColdLabelAlignmentArtifact.model_validate_json(artifact.model_dump_json())
    except ValueError as error:
        raise ColdLabelAlignmentError("cold-label alignment invariants do not replay") from error
    if cold_label_alignment_artifact_sha256(artifact) != artifact.output_sha256:
        raise ColdLabelAlignmentError("cold-label alignment output hash does not replay")


def build_cold_label_alignment(  # noqa: PLR0915 - complete partition accounting stays auditable.
    inputs: ColdLabelAlignmentInputs,
    settings: ColdLabelAlignmentSettings | None = None,
) -> ColdLabelAlignmentArtifact:
    """Classify every seed as existing-accepted, inferred-accepted, review, or abstain."""
    resolved_settings = settings or ColdLabelAlignmentSettings()
    receipt, graph_binding = _load_graph_receipt(inputs.graph_receipt, inputs.graph_database)
    reconciliation, reconciliation_binding = _load_reconciliation(inputs.reconciliation)
    supplemental_references, supplemental_bindings = _load_supplemental_vocabulary(inputs)
    vocabulary = _load_graph_vocabulary(inputs.graph_database, supplemental_references)
    if receipt.identity_count != reconciliation.seed_count:
        raise ColdLabelAlignmentError("graph receipt and reconciliation seed counts do not match")

    accepted: list[LabelAlignmentCandidate] = []
    review: list[LabelAlignmentCandidate] = []
    abstentions: list[LabelAlignmentAbstention] = []
    existing_count = 0
    inferred_count = 0
    compositional_review_seed_count = 0
    acronym_review_seed_count = 0
    semantic_alias_review_seed_count = 0
    ambiguous_existing_review_seed_count = 0
    generic_abstention_count = 0

    seed_normalized_counts = Counter(
        normalized_label(seed.seed_name) for seed in reconciliation.dispositions
    )
    seed_initialism_counts = Counter(
        initialism
        for seed in reconciliation.dispositions
        for initialism in initialism_forms(seed.seed_name)
    )
    for seed in reconciliation.dispositions:
        existing_clusters = _existing_clusters(
            seed.musicbrainz_identities + seed.public_identities, vocabulary
        )
        existing = existing_clusters[0] if len(existing_clusters) == 1 else None
        if seed.disposition in _TRUSTED_DISPOSITIONS and existing is not None:
            accepted.append(
                _candidate(
                    seed,
                    existing,
                    decision_kind="existing_open_identity",
                    status="accepted",
                )
            )
            existing_count += 1
            continue
        if seed.disposition == "ambiguous" and existing_clusters:
            review.extend(
                _candidate(
                    seed,
                    cluster,
                    decision_kind="ambiguous_existing_identity",
                    status="review",
                )
                for cluster in existing_clusters
            )
            ambiguous_existing_review_seed_count += 1
            continue
        decision = _cold_decision(
            seed.seed_name,
            vocabulary,
            resolved_settings,
            allow_unique_normalized=seed_normalized_counts[normalized_label(seed.seed_name)] == 1,
            allow_initialism=any(
                seed_initialism_counts[initialism] == 1
                for initialism in initialism_forms(seed.seed_name)
            ),
        )
        if decision[0] == "accepted":
            accepted.append(
                _candidate(
                    seed,
                    decision[2][0],
                    decision_kind=decision[1],
                    status="accepted",
                )
            )
            inferred_count += 1
        elif decision[0] == "review":
            review.extend(
                _candidate(
                    seed,
                    cluster,
                    decision_kind=decision[1],
                    status="review",
                )
                for cluster in decision[2]
            )
            if decision[1] == "compositional":
                compositional_review_seed_count += 1
            elif decision[1] == "acronym_initialism":
                acronym_review_seed_count += 1
            else:
                semantic_alias_review_seed_count += decision[1] == "semantic_alias"
                ambiguous_existing_review_seed_count += decision[1] == "ambiguous_existing_identity"
        else:
            reason = decision[3]
            abstentions.append(
                LabelAlignmentAbstention(
                    source_item_id=seed.source_item_id,
                    seed_name=seed.seed_name,
                    reconciliation_disposition=seed.disposition,
                    reason=reason,
                    best_score=decision[4],
                )
            )
            generic_abstention_count += reason == "generic_root_prohibited"

    coverage = ColdLabelAlignmentCoverage(
        seed_count=reconciliation.seed_count,
        reconciliation=_disposition_coverage(reconciliation),
        open_identity_count=vocabulary.projected_identity_count
        + vocabulary.supplemental_identity_count,
        projected_open_identity_count=vocabulary.projected_identity_count,
        supplemental_open_identity_count=vocabulary.supplemental_identity_count,
        open_label_cluster_count=len(vocabulary.clusters),
        existing_open_identity_accepted_seed_count=existing_count,
        inferred_unique_normalized_accepted_seed_count=inferred_count,
        compositional_review_seed_count=compositional_review_seed_count,
        acronym_initialism_review_seed_count=acronym_review_seed_count,
        semantic_alias_review_seed_count=semantic_alias_review_seed_count,
        ambiguous_existing_identity_review_seed_count=ambiguous_existing_review_seed_count,
        abstained_seed_count=len(abstentions),
        generic_root_abstention_count=generic_abstention_count,
    )
    masked = _masked_evaluation(
        reconciliation,
        vocabulary,
        resolved_settings,
        seed_normalized_counts,
        seed_initialism_counts,
    )
    settings_sha = cold_label_alignment_settings_sha256(resolved_settings)
    vocabulary_sha = _vocabulary_sha(vocabulary)
    base = ColdLabelAlignmentArtifact(
        inputs=(
            graph_binding,
            _receipt_binding(inputs.graph_receipt, receipt.output_sha256),
            reconciliation_binding,
            *supplemental_bindings,
        ),
        seed_identity_sha256=reconciliation.seed_identity_sha256,
        settings=resolved_settings,
        settings_sha256=settings_sha,
        input_sha256=sha256_hex(
            canonical_json(
                {
                    "inputs": [
                        graph_binding.model_dump(mode="json"),
                        _receipt_binding(inputs.graph_receipt, receipt.output_sha256).model_dump(
                            mode="json"
                        ),
                        reconciliation_binding.model_dump(mode="json"),
                        *[binding.model_dump(mode="json") for binding in supplemental_bindings],
                    ],
                    "settings_sha256": settings_sha,
                }
            )
        ),
        vocabulary_sha256=vocabulary_sha,
        seed_partition=tuple(
            SeedPartitionRow(
                source_item_id=seed.source_item_id,
                source_external_id=seed.source_external_id,
                seed_name=seed.seed_name,
                disposition=seed.disposition,
            )
            for seed in sorted(reconciliation.dispositions, key=lambda item: item.source_item_id)
        ),
        accepted=tuple(sorted(accepted, key=lambda candidate: candidate.source_item_id)),
        review=tuple(
            sorted(
                review,
                key=lambda candidate: (
                    candidate.source_item_id,
                    -candidate.score,
                    candidate.candidate_normalized_label,
                ),
            )
        ),
        abstentions=tuple(sorted(abstentions, key=lambda abstention: abstention.source_item_id)),
        masked_evaluation=masked,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    artifact = base.model_copy(update={"output_sha256": cold_label_alignment_artifact_sha256(base)})
    verify_cold_label_alignment(artifact)
    return artifact


def write_cold_label_alignment(
    artifact: ColdLabelAlignmentArtifact, output_root: Path
) -> tuple[ColdLabelAlignmentReceipt, Path, Path]:
    """Publish the artifact and receipt under a durable content-addressed root."""
    verify_cold_label_alignment(artifact)
    object_directory = output_root / "sha256"
    object_directory.mkdir(parents=True, exist_ok=True)
    artifact_path = object_directory / f"{artifact.output_sha256}.json"
    payload = canonical_json(artifact.model_dump(mode="json")) + b"\n"
    write_durable_bytes(artifact_path, payload)
    artifact_sha = sha256_hex(payload)
    receipt = ColdLabelAlignmentReceipt(
        artifact_sha256=artifact_sha,
        artifact_byte_count=len(payload),
        logical_output_sha256=artifact.output_sha256,
        object_key=f"cold-label-alignment/v1/sha256/{artifact.output_sha256}.json",
    )
    receipt_path = object_directory / f"{artifact.output_sha256}.receipt.json"
    write_durable_bytes(receipt_path, canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return receipt, artifact_path, receipt_path


def _load_graph_receipt(
    path: Path, database_path: Path
) -> tuple[EvidenceGraphProjectionArtifact, InputBinding]:
    try:
        receipt = EvidenceGraphProjectionArtifact.model_validate_json(path.read_bytes())
        verify_evidence_graph_projection(receipt)
    except (OSError, ValueError) as error:
        raise ColdLabelAlignmentError("graph receipt is not sealed") from error
    database_sha, database_size = sha256_file(database_path)
    if (database_sha, database_size) != (receipt.database_sha256, receipt.database_bytes):
        raise ColdLabelAlignmentError("graph database does not match its receipt")
    return receipt, InputBinding(
        role="source_neutral_evidence_graph_database",
        byte_sha256=database_sha,
        byte_count=database_size,
        logical_sha256=receipt.output_sha256,
    )


def _load_reconciliation(path: Path) -> tuple[SeedReconciliationArtifact, InputBinding]:
    try:
        reconciliation = load_seed_reconciliation(path)
    except (OSError, ValueError) as error:
        raise ColdLabelAlignmentError("seed reconciliation is not sealed") from error
    byte_sha, byte_size = sha256_file(path)
    return reconciliation, InputBinding(
        role="seed_reconciliation",
        byte_sha256=byte_sha,
        byte_count=byte_size,
        logical_sha256=reconciliation.output_sha256,
    )


def _receipt_binding(path: Path, logical_sha256: str) -> InputBinding:
    byte_sha, byte_size = sha256_file(path)
    return InputBinding(
        role="source_neutral_evidence_graph_receipt",
        byte_sha256=byte_sha,
        byte_count=byte_size,
        logical_sha256=logical_sha256,
    )


def _load_supplemental_vocabulary(
    inputs: ColdLabelAlignmentInputs,
) -> tuple[tuple[OpenIdentityReference, ...], tuple[InputBinding, ...]]:
    vocabulary_path = inputs.supplemental_vocabulary
    receipt_path = inputs.supplemental_vocabulary_receipt
    if vocabulary_path is None and receipt_path is None:
        return (), ()
    if vocabulary_path is None or receipt_path is None:
        raise ColdLabelAlignmentError(
            "supplemental vocabulary and its receipt must be provided together"
        )
    try:
        artifact = ReleaseGroupVocabularyArtifact.model_validate_json(vocabulary_path.read_bytes())
        verify_release_group_vocabulary(artifact)
        receipt = ReleaseGroupVocabularyReceipt.model_validate_json(receipt_path.read_bytes())
    except (OSError, ValueError) as error:
        raise ColdLabelAlignmentError("supplemental vocabulary is not sealed") from error
    vocabulary_sha, vocabulary_size = sha256_file(vocabulary_path)
    if (
        receipt.logical_output_sha256 != artifact.output_sha256
        or receipt.artifact_sha256 != vocabulary_sha
        or receipt.artifact_byte_count != vocabulary_size
    ):
        raise ColdLabelAlignmentError("supplemental vocabulary receipt does not bind its artifact")
    references = tuple(
        OpenIdentityReference(
            namespace=kind,
            identifier=f"release-group-label:{label.normalized}",
            label=label.label,
            open_artist_count=0,
            open_claim_count=(
                label.genre_observation_count
                if kind == "musicbrainz_release_group_genre_name"
                else label.tag_observation_count
            ),
        )
        for label in artifact.labels
        for kind in label.kinds
    )
    receipt_sha, receipt_size = sha256_file(receipt_path)
    return references, (
        InputBinding(
            role="musicbrainz_release_group_vocabulary_artifact",
            byte_sha256=vocabulary_sha,
            byte_count=vocabulary_size,
            logical_sha256=artifact.output_sha256,
        ),
        InputBinding(
            role="musicbrainz_release_group_vocabulary_receipt",
            byte_sha256=receipt_sha,
            byte_count=receipt_size,
            logical_sha256=artifact.output_sha256,
        ),
    )


def _load_graph_vocabulary(
    path: Path, supplemental_references: tuple[OpenIdentityReference, ...]
) -> _Vocabulary:
    try:
        with closing(connect_readonly(path)) as database:
            identities = tuple(
                database.execute(
                    """SELECT namespace, identifier, label
                         FROM identity
                        WHERE namespace IN (
                                  'musicbrainz_genre_id',
                                  'musicbrainz_tag_name',
                                  'wikidata_genre_qid'
                              )
                          AND label IS NOT NULL
                     ORDER BY namespace, identifier"""
                )
            )
            support_rows = tuple(
                database.execute(
                    """SELECT object_namespace, object_identifier,
                              COUNT(DISTINCT subject_identifier), COUNT(*)
                         FROM claim
                        WHERE subject_namespace = 'musicbrainz_artist'
                          AND object_namespace IN (
                                  'musicbrainz_genre_id',
                                  'musicbrainz_tag_name',
                                  'wikidata_genre_qid'
                              )
                     GROUP BY object_namespace, object_identifier"""
                )
            )
    except OSError as error:
        raise ColdLabelAlignmentError("cannot read source-neutral graph database") from error
    support = {
        (str(namespace), str(identifier)): (int(artist_count), int(claim_count))
        for namespace, identifier, artist_count, claim_count in support_rows
    }
    maximum_claim_count = max(
        (
            *(count for _artists, count in support.values()),
            *(reference.open_claim_count for reference in supplemental_references),
        ),
        default=0,
    )
    grouped: dict[str, list[OpenIdentityReference]] = defaultdict(list)
    for namespace, identifier, raw_label in identities:
        normalized = normalized_label(str(raw_label))
        if not normalized:
            continue
        artist_count, claim_count = support.get((str(namespace), str(identifier)), (0, 0))
        grouped[normalized].append(
            OpenIdentityReference(
                namespace=cast("OpenIdentityNamespace", str(namespace)),
                identifier=str(identifier),
                label=str(raw_label),
                open_artist_count=artist_count,
                open_claim_count=claim_count,
            )
        )
    for reference in supplemental_references:
        grouped[reference.identifier.removeprefix("release-group-label:")].append(reference)
    clusters: list[_Cluster] = []
    by_identity: dict[tuple[str, str], _Cluster] = {}
    for normalized, references in sorted(grouped.items()):
        ordered = tuple(
            sorted(references, key=lambda reference: (reference.namespace, reference.identifier))
        )
        representative = min(
            (reference.label for reference in ordered), key=lambda label: (len(label), label)
        )
        context_score = max(
            (
                math.log1p(reference.open_claim_count) / math.log1p(maximum_claim_count)
                if maximum_claim_count
                else 0.0
                for reference in ordered
            ),
            default=0.0,
        )
        cluster = _Cluster(normalized, representative, ordered, context_score)
        clusters.append(cluster)
        by_identity.update(
            {(reference.namespace, reference.identifier): cluster for reference in ordered}
        )
    compact_index: dict[str, list[_Cluster]] = defaultdict(list)
    head_index: dict[str, list[_Cluster]] = defaultdict(list)
    for cluster in clusters:
        if " " not in cluster.normalized:
            compact_index[cluster.normalized].append(cluster)
        cluster_tokens = tokens(cluster.normalized)
        if cluster_tokens:
            head_index[cluster_tokens[-1]].append(cluster)
    return _Vocabulary(
        clusters=tuple(clusters),
        by_identity=by_identity,
        by_normalized={cluster.normalized: cluster for cluster in clusters},
        by_compact_label={key: tuple(value) for key, value in compact_index.items()},
        by_head={key: tuple(value) for key, value in head_index.items()},
        projected_identity_count=len(identities),
        supplemental_identity_count=len(supplemental_references),
    )


def _existing_clusters(
    identities: tuple[ReconciledIdentity, ...], vocabulary: _Vocabulary
) -> tuple[_Cluster, ...]:
    clusters = {
        vocabulary.by_identity[(identity.namespace, identity.identifier)]
        for identity in identities
        if (identity.namespace, identity.identifier) in vocabulary.by_identity
    }
    return tuple(sorted(clusters, key=lambda cluster: cluster.normalized))


def _cold_decision(  # noqa: PLR0911 - each explicit abstention keeps the safety policy auditable.
    seed_name: str,
    vocabulary: _Vocabulary,
    settings: ColdLabelAlignmentSettings,
    *,
    allow_unique_normalized: bool,
    allow_initialism: bool,
) -> tuple[
    Literal["accepted", "review", "abstain"],
    Literal[
        "unique_normalized_label",
        "compositional",
        "acronym_initialism",
        "semantic_alias",
        "ambiguous_existing_identity",
    ],
    tuple[_Cluster, ...],
    Literal["generic_root_prohibited", "no_open_label_candidate", "ambiguous_or_weak_composition"],
    float | None,
]:
    normalized = normalized_label(seed_name)
    alias_target = semantic_alias_target(seed_name)
    if alias_target is not None:
        alias_cluster = vocabulary.by_normalized.get(alias_target)
        if alias_cluster is not None and not is_generic_root(alias_cluster.label):
            return "review", "semantic_alias", (alias_cluster,), "no_open_label_candidate", 0.95
        return "abstain", "semantic_alias", (), "no_open_label_candidate", None
    if is_generic_root(seed_name):
        return "abstain", "compositional", (), "generic_root_prohibited", None
    exact = vocabulary.by_normalized.get(normalized)
    if exact is not None and allow_unique_normalized and not is_generic_root(exact.label):
        return "accepted", "unique_normalized_label", (exact,), "no_open_label_candidate", 1.0
    if exact is not None and not allow_unique_normalized:
        return "abstain", "compositional", (), "ambiguous_or_weak_composition", 1.0
    initialism = _rank_initialism(seed_name, vocabulary) if allow_initialism else ()
    if initialism:
        return "review", "acronym_initialism", initialism, "no_open_label_candidate", 0.9
    candidates = _rank_compositional(seed_name, vocabulary, settings)
    if candidates:
        return (
            "review",
            "compositional",
            tuple(cluster for cluster, _score in candidates),
            "no_open_label_candidate",
            candidates[0][1],
        )
    retrieved = _retrieved_clusters(seed_name, vocabulary, settings.maximum_head_candidates)
    if not retrieved:
        return "abstain", "compositional", (), "no_open_label_candidate", None
    best_score = max(
        (
            _candidate_score(seed_name, cluster)[0]
            for cluster in retrieved
            if not is_generic_root(cluster.label)
        ),
        default=None,
    )
    return "abstain", "compositional", (), "ambiguous_or_weak_composition", best_score


def _rank_initialism(seed_name: str, vocabulary: _Vocabulary) -> tuple[_Cluster, ...]:
    """Retrieve compact source labels only from a unique expanded initialism."""
    forms = initialism_forms(seed_name)
    if not forms:
        return ()
    matches = tuple(
        cluster
        for form in forms
        for cluster in vocabulary.by_compact_label.get(form, ())
        if not is_generic_root(cluster.label)
    )
    return matches if len(matches) == 1 else ()


def _retrieved_clusters(
    seed_name: str, vocabulary: _Vocabulary, maximum_candidates: int
) -> tuple[_Cluster, ...]:
    seed_tokens = tokens(seed_name)
    if not seed_tokens:
        return ()
    return tuple(
        sorted(
            vocabulary.by_head.get(seed_tokens[-1], ()),
            key=lambda cluster: (-cluster.context_score, cluster.normalized),
        )[:maximum_candidates]
    )


def _rank_compositional(
    seed_name: str, vocabulary: _Vocabulary, settings: ColdLabelAlignmentSettings
) -> tuple[tuple[_Cluster, float], ...]:
    ranked: list[tuple[_Cluster, float]] = []
    for cluster in _retrieved_clusters(seed_name, vocabulary, settings.maximum_head_candidates):
        if is_generic_root(cluster.label) or not shares_retrieval_token(seed_name, cluster.label):
            continue
        score, token_score, character_score, head_score = _candidate_score(seed_name, cluster)
        same_head = tokens(seed_name)[-1:] == tokens(cluster.label)[-1:]
        if (
            not same_head
            or token_score < settings.minimum_review_token_jaccard
            or character_score < settings.minimum_review_character_cosine
            or head_score < _COMPOSITIONAL_HEAD_MINIMUM
            or score < settings.minimum_review_score
        ):
            continue
        ranked.append((cluster, score))
    return tuple(
        sorted(ranked, key=lambda row: (-row[1], row[0].normalized))[: settings.candidates_per_seed]
    )


def _candidate_score(seed_name: str, cluster: _Cluster) -> tuple[float, float, float, float]:
    token_score = token_jaccard(seed_name, cluster.label)
    character_score = character_ngram_cosine(seed_name, cluster.label)
    head_score = head_modifier_score(seed_name, cluster.label)
    score = min(
        1.0,
        0.42 * token_score
        + 0.28 * character_score
        + 0.22 * head_score
        + 0.08 * cluster.context_score,
    )
    return score, token_score, character_score, head_score


def _candidate(
    seed: SeedReconciliationDisposition,
    cluster: _Cluster,
    *,
    decision_kind: Literal[
        "existing_open_identity",
        "unique_normalized_label",
        "compositional",
        "acronym_initialism",
        "semantic_alias",
        "ambiguous_existing_identity",
    ],
    status: Literal["accepted", "review"],
) -> LabelAlignmentCandidate:
    if decision_kind == "existing_open_identity":
        score, token_score, character_score, head_score = 1.0, 1.0, 1.0, 1.0
        signals = ("reconciliation_open_identity", "open_graph_identity")
    elif decision_kind == "unique_normalized_label":
        score, token_score, character_score, head_score = 1.0, 1.0, 1.0, 1.0
        signals = ("unicode_token_normalized_exact", "open_graph_identity")
    elif decision_kind == "compositional":
        score, token_score, character_score, head_score = _candidate_score(seed.seed_name, cluster)
        signals = ("shared_head", "token_overlap", "character_rank", "open_graph_context")
    elif decision_kind == "acronym_initialism":
        score, token_score, character_score, head_score = 0.9, 0.0, 0.0, 0.0
        signals = ("unique_seed_initialism", "unique_open_compact_label", "open_graph_identity")
    elif decision_kind == "semantic_alias":
        score, token_score, character_score, head_score = 0.95, 0.0, 0.0, 0.0
        signals = ("declared_popular_music_alias", "open_graph_identity")
    else:
        score, token_score, character_score, head_score = 0.0, 0.0, 0.0, 0.0
        signals = ("reconciliation_ambiguity", "multiple_open_identity_clusters")
    return LabelAlignmentCandidate(
        source_item_id=seed.source_item_id,
        seed_name=seed.seed_name,
        reconciliation_disposition=seed.disposition,
        candidate_normalized_label=cluster.normalized,
        candidate_label=cluster.label,
        identities=cluster.identities,
        decision_kind=decision_kind,
        score=score,
        token_jaccard=token_score,
        character_ngram_cosine=character_score,
        head_modifier_score=head_score,
        open_graph_context_score=cluster.context_score,
        evidence_signals=signals,
        status=status,
    )


def _disposition_coverage(reconciliation: SeedReconciliationArtifact) -> DispositionCoverage:
    counts = Counter(seed.disposition for seed in reconciliation.dispositions)
    return DispositionCoverage(
        reconciled=counts["reconciled"],
        public_only=counts["public_only"],
        musicbrainz_only=counts["musicbrainz_only"],
        review_only=counts["review_only"],
        ambiguous=counts["ambiguous"],
        unresolved=counts["unresolved"],
    )


def _masked_evaluation(
    reconciliation: SeedReconciliationArtifact,
    vocabulary: _Vocabulary,
    settings: ColdLabelAlignmentSettings,
    seed_normalized_counts: Counter[str],
    seed_initialism_counts: Counter[str],
) -> MaskedEvaluation:
    eligible: list[tuple[SeedReconciliationDisposition, frozenset[tuple[str, str]]]] = []
    for seed in reconciliation.dispositions:
        if seed.disposition not in _TRUSTED_DISPOSITIONS:
            continue
        expected = frozenset(
            (identity.namespace, identity.identifier)
            for identity in seed.musicbrainz_identities + seed.public_identities
            if (identity.namespace, identity.identifier) in vocabulary.by_identity
        )
        if expected:
            eligible.append((seed, expected))
    masked = tuple(
        (seed, expected) for seed, expected in eligible if _is_masked(seed.source_item_id, settings)
    )
    outcomes = tuple(
        _masked_outcome(
            seed,
            expected,
            vocabulary,
            settings,
            seed_normalized_counts,
            seed_initialism_counts,
        )
        for seed, expected in masked
    )
    retrievable = sum(outcome.retrievable for outcome in outcomes)
    top_1_hits = sum(outcome.top_1_hit for outcome in outcomes)
    top_k_hits = sum(outcome.top_k_hit for outcome in outcomes)
    accepted_predictions = sum(outcome.accepted_prediction for outcome in outcomes)
    accepted_hits = sum(outcome.accepted_hit for outcome in outcomes)
    review_predictions = sum(outcome.review_prediction for outcome in outcomes)
    review_hits = sum(outcome.review_hit for outcome in outcomes)
    acronym_predictions = sum(outcome.acronym_review_prediction for outcome in outcomes)
    acronym_hits = sum(outcome.acronym_review_hit for outcome in outcomes)
    return MaskedEvaluation(
        eligible_high_confidence_seed_count=len(eligible),
        masked_seed_count=len(masked),
        retrievable_seed_count=retrievable,
        top_1_recall=top_1_hits / len(masked) if masked else None,
        top_k_recall=top_k_hits / len(masked) if masked else None,
        accepted_prediction_count=accepted_predictions,
        accepted_precision=accepted_hits / accepted_predictions if accepted_predictions else None,
        review_prediction_count=review_predictions,
        review_precision=review_hits / review_predictions if review_predictions else None,
        acronym_review_prediction_count=acronym_predictions,
        acronym_review_precision=acronym_hits / acronym_predictions
        if acronym_predictions
        else None,
    )


def _masked_outcome(  # noqa: PLR0913, PLR0917 - all held-out inputs are explicit.
    seed: SeedReconciliationDisposition,
    expected: frozenset[tuple[str, str]],
    vocabulary: _Vocabulary,
    settings: ColdLabelAlignmentSettings,
    seed_normalized_counts: Counter[str],
    seed_initialism_counts: Counter[str],
) -> _MaskedOutcome:
    """Score one hidden trusted mapping without reading its reconciliation edge."""
    decision = _cold_decision(
        seed.seed_name,
        vocabulary,
        settings,
        allow_unique_normalized=seed_normalized_counts[normalized_label(seed.seed_name)] == 1,
        allow_initialism=any(
            seed_initialism_counts[initialism] == 1
            for initialism in initialism_forms(seed.seed_name)
        ),
    )
    hits = tuple(
        bool(
            {(reference.namespace, reference.identifier) for reference in cluster.identities}
            & expected
        )
        for cluster in decision[2]
    )
    first_hit = bool(hits and hits[0])
    review = decision[0] == "review"
    acronym = review and decision[1] == "acronym_initialism"
    return _MaskedOutcome(
        retrievable=bool(decision[2]),
        top_1_hit=first_hit,
        top_k_hit=any(hits[: settings.candidates_per_seed]),
        accepted_prediction=decision[0] == "accepted",
        accepted_hit=decision[0] == "accepted" and first_hit,
        review_prediction=review,
        review_hit=review and first_hit,
        acronym_review_prediction=acronym,
        acronym_review_hit=acronym and first_hit,
    )


def _is_masked(seed_id: str, settings: ColdLabelAlignmentSettings) -> bool:
    value = (
        int.from_bytes(
            hashlib.sha256(f"{settings.split_seed}\0{seed_id}".encode()).digest()[:8], "big"
        )
        / 2**64
    )
    return value < settings.masked_evaluation_fraction


def _vocabulary_sha(vocabulary: _Vocabulary) -> str:
    return sha256_hex(
        canonical_json(
            [
                {
                    "normalized": cluster.normalized,
                    "label": cluster.label,
                    "identities": [
                        identity.model_dump(mode="json") for identity in cluster.identities
                    ],
                }
                for cluster in vocabulary.clusters
            ]
        )
    )
