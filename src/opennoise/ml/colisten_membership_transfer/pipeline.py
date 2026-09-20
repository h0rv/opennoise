"""Build a bounded review-only transfer artifact from already sealed v2 inputs."""

from __future__ import annotations

import hashlib
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opennoise.common import canonical_json, sha256_file, write_atomic_bytes
from opennoise.evidence.graph_projection import (
    EvidenceGraphProjectionArtifact,
    verify_evidence_graph_projection,
)
from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlaySources,
    certify_colisten_overlay_sources,
    load_colisten_overlay,
)

from .contracts import (
    CoListenMembershipTransferArtifact,
    CoListenMembershipTransferError,
    CoListenMembershipTransferInputs,
    CoListenMembershipTransferReceipt,
    CoListenMembershipTransferSettings,
    CoListenSupport,
    InputBinding,
    ReviewCandidate,
    TransferCoverage,
    TransferEvaluation,
    artifact_sha256,
    settings_sha256,
    verify_colisten_membership_transfer,
)

if TYPE_CHECKING:
    from pathlib import Path

_SEED_COUNT = 6_291


@dataclass(slots=True)
class _CandidateAccumulator:
    score: float = 0.0
    users: int = 0
    sources: set[str] = field(default_factory=set)
    supports: list[CoListenSupport] = field(default_factory=list)


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _binding(role: str, path: Path, logical_sha256: str) -> InputBinding:
    digest, count = sha256_file(path)
    return InputBinding(
        role=role, byte_sha256=digest, byte_count=count, logical_sha256=logical_sha256
    )


def _is_heldout(artist: str, seed: str, settings: CoListenMembershipTransferSettings) -> bool:
    value = (
        int.from_bytes(
            hashlib.sha256(f"{settings.split_seed}\x1f{artist}\x1f{seed}".encode()).digest()[:8],
            "big",
        )
        / 2**64
    )
    return value < settings.heldout_fraction


def _load_inputs(
    inputs: CoListenMembershipTransferInputs,
) -> tuple[
    tuple[InputBinding, ...],
    EvidenceGraphProjectionArtifact,
    set[str],
]:
    """Certify every byte and ensure the aggregate overlay binds this exact graph."""
    try:
        graph = EvidenceGraphProjectionArtifact.model_validate_json(
            inputs.graph_receipt.read_bytes()
        )
        verify_evidence_graph_projection(graph)
        colisten = load_colisten_overlay(inputs.colisten_receipt)
        certify_colisten_overlay_sources(CoListenOverlaySources(inputs.colisten_database, colisten))
    except (OSError, ValueError) as error:
        raise CoListenMembershipTransferError("one or more sealed v2 inputs are invalid") from error
    if sha256_file(inputs.graph_database) != (graph.database_sha256, graph.database_bytes):
        raise CoListenMembershipTransferError("graph database does not bind graph receipt")
    if colisten.graph_receipt_output_sha256 != graph.output_sha256:
        raise CoListenMembershipTransferError("co-listen overlay binds a different graph receipt")
    with closing(_readonly(inputs.graph_database)) as database:
        seeds = {
            str(seed)
            for (seed,) in database.execute(
                "SELECT identifier FROM identity WHERE namespace = 'stable_seed'"
            )
        }
    if len(seeds) != _SEED_COUNT:
        raise CoListenMembershipTransferError("graph does not account for all 6,291 stable seeds")
    bindings = (
        _binding("graph_database", inputs.graph_database, graph.database_sha256),
        _binding("graph_receipt", inputs.graph_receipt, graph.output_sha256),
        _binding("colisten_database", inputs.colisten_database, colisten.database_sha256),
        _binding("colisten_receipt", inputs.colisten_receipt, colisten.output_sha256),
    )
    return bindings, graph, seeds


def _direct_memberships(graph_database: Path, seeds: set[str]) -> dict[str, set[str]]:
    """Load only direct positive artist memberships, deduplicated before splitting."""
    with closing(_readonly(graph_database)) as database:
        rows = database.execute(
            "SELECT subject_identifier, object_identifier FROM claim "
            "WHERE subject_namespace = 'musicbrainz_artist' AND predicate = 'artist_membership' "
            "AND object_namespace = 'stable_seed' AND evidence_kind = 'artist_direct' "
            "GROUP BY subject_identifier, object_identifier"
        )
        result: dict[str, set[str]] = defaultdict(set)
        for artist, seed in rows:
            artist_text, seed_text = str(artist), str(seed)
            if seed_text not in seeds:
                raise CoListenMembershipTransferError(
                    "direct membership references an unknown seed"
                )
            result[artist_text].add(seed_text)
    return dict(result)


def _relations(colisten_database: Path) -> tuple[tuple[str, str, str, int], ...]:
    """Read privacy-thresholded aggregate rows, never raw listens or listener identities."""
    with closing(_readonly(colisten_database)) as database:
        return tuple(
            (str(left), str(right), str(fingerprint), int(users))
            for left, right, fingerprint, users in database.execute(
                "SELECT left_artist_mbid, right_artist_mbid, evidence_fingerprint, "
                "distinct_user_count FROM colisten_relation ORDER BY left_artist_mbid, "
                "right_artist_mbid, window_start, evidence_fingerprint"
            )
        )


def _transfer(
    relations: tuple[tuple[str, str, str, int], ...],
    source_labels: dict[str, set[str]],
    target_artists: set[str],
    settings: CoListenMembershipTransferSettings,
) -> dict[str, tuple[ReviewCandidate, ...]]:
    """Aggregate only peer training labels into cold target candidates and their exact paths."""
    accumulators: dict[tuple[str, str], _CandidateAccumulator] = {}
    for left, right, fingerprint, users in relations:
        for target, source in ((left, right), (right, left)):
            if target not in target_artists:
                continue
            contribution = math.log1p(users)
            for seed in source_labels.get(source, ()):
                accumulator = accumulators.setdefault((target, seed), _CandidateAccumulator())
                accumulator.score += contribution
                accumulator.users += users
                accumulator.sources.add(source)
                accumulator.supports.append(
                    CoListenSupport(
                        source_artist_mbid=source,
                        co_listen_evidence_fingerprint=fingerprint,
                        distinct_user_count=users,
                        contribution=round(contribution, 12),
                    )
                )
    grouped: dict[str, list[ReviewCandidate]] = defaultdict(list)
    for (artist, seed), accumulator in accumulators.items():
        ordered_supports = tuple(
            sorted(
                accumulator.supports,
                key=lambda row: (
                    -row.contribution,
                    row.source_artist_mbid,
                    row.co_listen_evidence_fingerprint,
                ),
            )
        )
        retained = ordered_supports[: settings.maximum_provenance_rows_per_candidate]
        grouped[artist].append(
            ReviewCandidate(
                artist_mbid=artist,
                stable_seed_id=seed,
                score=round(accumulator.score, 12),
                supporting_artist_count=len(accumulator.sources),
                supporting_colisten_edge_count=len(ordered_supports),
                summed_distinct_user_support=accumulator.users,
                retained_supports=retained,
                omitted_support_row_count=len(ordered_supports) - len(retained),
            )
        )
    return {
        artist: tuple(
            sorted(rows, key=lambda row: (-row.score, row.stable_seed_id))[
                : settings.maximum_candidates_per_artist
            ]
        )
        for artist, rows in grouped.items()
    }


def _evaluation(
    all_labels: dict[str, set[str]],
    relations: tuple[tuple[str, str, str, int], ...],
    settings: CoListenMembershipTransferSettings,
) -> TransferEvaluation:
    """Hold out direct artist-seed positives before any peer label feature is formed."""
    train, heldout = _split_direct_labels(all_labels, settings)
    colisten_artists = {artist for row in relations for artist in row[:2]}
    cold = {artist for artist in colisten_artists if not train.get(artist, set())}
    candidates = _transfer(relations, train, cold, settings)
    positives = {artist: seeds for artist, seeds in heldout.items() if artist in cold and seeds}
    eligible = set(positives)
    scored = {artist for artist in eligible if candidates.get(artist)}
    hits10 = hits25 = 0
    for artist, seeds in positives.items():
        ranked = [row.stable_seed_id for row in candidates.get(artist, ())]
        hits10 += sum(seed in ranked[:10] for seed in seeds)
        hits25 += sum(seed in ranked[:25] for seed in seeds)
    count = sum(len(seeds) for seeds in positives.values())
    scoreable = sum(len(positives[artist]) for artist in scored)
    return TransferEvaluation(
        heldout_direct_positive_count=count,
        eligible_heldout_artist_count=len(eligible),
        abstained_no_colisten_or_support_artist_count=len(eligible - scored),
        scoreable_direct_positive_count=scoreable,
        recovered_at_10_count=hits10,
        recovered_at_25_count=hits25,
        recall_at_10=hits10 / count if count else None,
        recall_at_25=hits25 / count if count else None,
    )


def _split_direct_labels(
    all_labels: dict[str, set[str]], settings: CoListenMembershipTransferSettings
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Split complete direct artist-seed pairs before either baseline forms a feature."""
    return (
        {
            artist: {seed for seed in labels if not _is_heldout(artist, seed, settings)}
            for artist, labels in all_labels.items()
        },
        {
            artist: {seed for seed in labels if _is_heldout(artist, seed, settings)}
            for artist, labels in all_labels.items()
        },
    )


def _global_popularity_baseline(
    all_labels: dict[str, set[str]],
    relations: tuple[tuple[str, str, str, int], ...],
    settings: CoListenMembershipTransferSettings,
) -> TransferEvaluation:
    """Retrieve held-out cold positives from global train-side direct-label frequency only."""
    train, heldout = _split_direct_labels(all_labels, settings)
    colisten_artists = {artist for row in relations for artist in row[:2]}
    cold = {artist for artist in colisten_artists if not train.get(artist, set())}
    positives = {artist: seeds for artist, seeds in heldout.items() if artist in cold and seeds}
    frequency: dict[str, int] = defaultdict(int)
    for labels in train.values():
        for seed in labels:
            frequency[seed] += 1
    ranked = [seed for seed, _ in sorted(frequency.items(), key=lambda row: (-row[1], row[0]))]
    count = sum(len(seeds) for seeds in positives.values())
    hits10 = sum(seed in ranked[:10] for seeds in positives.values() for seed in seeds)
    hits25 = sum(seed in ranked[:25] for seeds in positives.values() for seed in seeds)
    return TransferEvaluation(
        heldout_direct_positive_count=count,
        eligible_heldout_artist_count=len(positives),
        abstained_no_colisten_or_support_artist_count=0 if ranked else len(positives),
        scoreable_direct_positive_count=count if ranked else 0,
        recovered_at_10_count=hits10,
        recovered_at_25_count=hits25,
        recall_at_10=hits10 / count if count else None,
        recall_at_25=hits25 / count if count else None,
    )


def _no_colisten_ablation(evaluation: TransferEvaluation) -> TransferEvaluation:
    """Make the direct-only cold baseline explicit: it cannot transfer an absent direct label."""
    count = evaluation.heldout_direct_positive_count
    return TransferEvaluation(
        heldout_direct_positive_count=count,
        eligible_heldout_artist_count=evaluation.eligible_heldout_artist_count,
        abstained_no_colisten_or_support_artist_count=evaluation.eligible_heldout_artist_count,
        scoreable_direct_positive_count=0,
        recovered_at_10_count=0,
        recovered_at_25_count=0,
        recall_at_10=0.0 if count else None,
        recall_at_25=0.0 if count else None,
    )


def build_colisten_membership_transfer(
    inputs: CoListenMembershipTransferInputs,
    settings: CoListenMembershipTransferSettings | None = None,
) -> CoListenMembershipTransferArtifact:
    """Build only review candidates for direct-cold co-listen artists from admitted v2 inputs."""
    resolved = settings or CoListenMembershipTransferSettings()
    bindings, graph, seeds = _load_inputs(inputs)
    labels = _direct_memberships(inputs.graph_database, seeds)
    relations = _relations(inputs.colisten_database)
    colisten_artists = {artist for row in relations for artist in row[:2]}
    cold = colisten_artists - set(labels)
    candidates_by_artist = _transfer(relations, labels, cold, resolved)
    candidates = tuple(
        row for artist in sorted(candidates_by_artist) for row in candidates_by_artist[artist]
    )
    if len(candidates) > resolved.maximum_total_candidates:
        raise CoListenMembershipTransferError("review candidate bound exceeded")
    candidate_artists = {row.artist_mbid for row in candidates}
    coverage = TransferCoverage(
        colisten_artist_count=len(colisten_artists),
        direct_labeled_colisten_artist_count=len(colisten_artists & set(labels)),
        direct_cold_colisten_artist_count=len(cold),
        eligible_cold_artist_count=len(candidate_artists),
        abstained_cold_artist_count=len(cold - candidate_artists),
        candidate_count=len(candidates),
    )
    evaluation = _evaluation(labels, relations, resolved)
    popularity = _global_popularity_baseline(labels, relations, resolved)
    preliminary = CoListenMembershipTransferArtifact(
        inputs=bindings,
        graph_receipt_output_sha256=graph.output_sha256,
        colisten_receipt_output_sha256=bindings[3].logical_sha256,
        settings=resolved,
        settings_sha256=settings_sha256(resolved),
        coverage=coverage,
        candidates=candidates,
        heldout_evaluation=evaluation,
        train_only_global_popularity_baseline=popularity,
        direct_only_no_colisten_ablation=_no_colisten_ablation(evaluation),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": artifact_sha256(preliminary)})


def write_colisten_membership_transfer(
    output: Path, receipt_path: Path, artifact: CoListenMembershipTransferArtifact
) -> CoListenMembershipTransferReceipt:
    """Write a fully replayed review artifact and its exact byte custody receipt."""
    verify_colisten_membership_transfer(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(artifact.model_dump(mode="json")) + b"\n"
    write_atomic_bytes(output, payload)
    digest, count = sha256_file(output)
    receipt = CoListenMembershipTransferReceipt(
        artifact_sha256=digest,
        artifact_byte_count=count,
        logical_output_sha256=artifact.output_sha256,
    )
    write_atomic_bytes(receipt_path, canonical_json(receipt.model_dump(mode="json")) + b"\n")
    return receipt
