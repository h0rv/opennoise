"""Bounded, local-only readiness audit for MusicBrainz RG positive tags.

Positive tags are retained as weak context only.  In particular, this module
never compares them with ``proper_genres`` from the same MusicBrainz sample:
that would turn source-native genres into leaked targets.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import ConfigDict, Field

from opennoise.analysis.musicbrainz_rg_genre_recovery_v2 import (
    MusicBrainzRgGenreRecoveryV2Report,
    verify_report,
)
from opennoise.evidence.independent_artist_genre_gold import load_gold_set
from opennoise.models import FrozenModel
from opennoise.taxonomy.seeds.universe import normalize_label
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this field at runtime.

_REVISION: Final = "musicbrainz-rg-positive-tag-context-readiness-v2"
_FIXED_TOP_K: Final = 5
_MAX_SAMPLE_REPORT_BYTES: Final = 64 * 1024 * 1024
_MAX_GOLD_FILES: Final = 8
_MAX_GOLD_BYTES: Final = 32 * 1024 * 1024
_MAX_PUBLIC_DATABASE_BYTES: Final = 512 * 1024 * 1024
_MAX_RECONCILIATION_BYTES: Final = 16 * 1024 * 1024

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.analysis.musicbrainz_rg_genre_recovery_v2 import SampledReleaseGroup


class _SeedPublicIdentity(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    namespace: str
    identifier: str


class _SeedDisposition(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    source_item_id: str
    normalized_name: str
    disposition: str
    public_identities: tuple[_SeedPublicIdentity, ...]


class _SeedReconciliation(FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    dispositions: tuple[_SeedDisposition, ...]


class MusicBrainzRgTagContextReadinessError(ValueError):
    """The bounded tag-context audit cannot safely replay its local inputs."""


class GoldReadiness(FrozenModel):
    """One independently governed gold candidate, without inspecting its labels."""

    path: str = Field(min_length=1)
    file_sha256: Sha256
    file_bytes: int = Field(gt=0, le=_MAX_GOLD_BYTES)
    source_kind: str = Field(min_length=1)
    independently_sourced: bool
    judgment_count: int = Field(ge=0)
    threshold_policy_accepted: bool
    usable_for_this_evaluation: Literal[False] = False
    blocker: str = Field(min_length=1)


class PositiveOnlyTopKRecovery(FrozenModel):
    """Fixed-cutoff recovery over external positives, without negative labels."""

    top_k: Literal[5] = _FIXED_TOP_K
    candidate_universe_frozen_before_p136_targets: Literal[True] = True
    ranking_order_frozen_before_p136_targets: Literal[True] = True
    positive_pair_denominator: int = Field(ge=0)
    positive_artist_denominator: int = Field(ge=0)
    frozen_seed_candidate_count: int = Field(ge=0)
    recovered_positive_pair_count: int = Field(ge=0)
    recovered_positive_seed_count: int = Field(ge=0)
    positive_recovery_at_top_k: float = Field(ge=0.0, le=1.0)


class TrainBlindGlobalTagPopularityBaseline(PositiveOnlyTopKRecovery):
    """P136-label-blind global popularity from the same local tag sample."""

    p136_label_blind: Literal[True] = True
    artist_disjoint_from_local_arm: Literal[False] = False
    independently_held_out_baseline: Literal[False] = False
    training_group_rule: Literal["all_sample_groups_before_p136_target_read"] = (
        "all_sample_groups_before_p136_target_read"
    )
    popularity_score: Literal["sum_positive_tag_vote_count_per_release_group"] = (
        "sum_positive_tag_vote_count_per_release_group"
    )
    tie_breaker: Literal["normalized_seed_id_ascending"] = "normalized_seed_id_ascending"
    training_group_count: int = Field(ge=0)


class MusicBrainzRgTagContextReadinessReport(FrozenModel):
    """A no-score checkpoint that prevents same-source target leakage."""

    revision: Literal["musicbrainz-rg-positive-tag-context-readiness-v2"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    performance_evaluation_performed: Literal[False] = False
    positive_only_recovery_evaluation_performed: Literal[True] = True
    negative_labels_used: Literal[False] = False
    precision_computed: Literal[False] = False
    native_proper_genres_used_as_targets: Literal[False] = False
    positive_tags_role: Literal["weak_artist_context_only"] = "weak_artist_context_only"
    proper_genres_role: Literal["source_native_metadata_not_an_evaluation_target"] = (
        "source_native_metadata_not_an_evaluation_target"
    )
    sample_report_path: str = Field(min_length=1)
    sample_report_file_sha256: Sha256
    sample_report_file_bytes: int = Field(gt=0, le=_MAX_SAMPLE_REPORT_BYTES)
    sample_report_output_sha256: Sha256
    sample_content_sha256: Sha256
    sampled_group_count: int = Field(ge=0)
    groups_with_positive_tags: int = Field(ge=0)
    positive_tag_observation_count: int = Field(ge=0)
    positive_tag_artist_attachment_count: int = Field(ge=0)
    distinct_normalized_positive_tag_count: int = Field(ge=0)
    groups_with_native_proper_genres: int = Field(ge=0)
    native_proper_genre_observation_count: int = Field(ge=0)
    wikidata_p136_database_path: str = Field(min_length=1)
    wikidata_p136_database_sha256: Sha256
    wikidata_p136_database_bytes: int = Field(gt=0, le=_MAX_PUBLIC_DATABASE_BYTES)
    seed_reconciliation_path: str = Field(min_length=1)
    seed_reconciliation_sha256: Sha256
    wikidata_p136_raw_exact_pair_count: int = Field(ge=0)
    wikidata_p136_one_to_one_seed_pair_count: int = Field(ge=0)
    wikidata_p136_overlapping_sample_positive_pair_count: int = Field(ge=0)
    wikidata_p136_overlapping_sample_artist_count: int = Field(ge=0)
    wikidata_p136_overlapping_sample_seed_count: int = Field(ge=0)
    positive_tag_exact_seed_hit_count: int = Field(ge=0)
    positive_tag_exact_seed_hit_seed_count: int = Field(ge=0)
    positive_tag_recovery: float = Field(ge=0.0, le=1.0)
    artist_local_positive_tag_top_k: PositiveOnlyTopKRecovery
    train_blind_global_tag_popularity_top_k: TrainBlindGlobalTagPopularityBaseline
    gold_candidates: tuple[GoldReadiness, ...] = Field(max_length=_MAX_GOLD_FILES)
    readiness: Literal["positive_only_recovery_not_full_quality_evaluation"] = (
        "positive_only_recovery_not_full_quality_evaluation"
    )
    blockers: tuple[str, ...] = Field(min_length=1)
    next_required_input: str = Field(min_length=1)
    output_sha256: Sha256


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def report_sha256(report: MusicBrainzRgTagContextReadinessReport) -> Sha256:
    """Return the self-hash of the report excluding its recursive field."""
    return hashlib.sha256(_canonical(report.model_dump(exclude={"output_sha256"}))).hexdigest()


def verify_readiness_report(report: MusicBrainzRgTagContextReadinessReport) -> None:
    """Reject a readiness result whose self-hash cannot replay."""
    if report.output_sha256 != report_sha256(report):
        raise MusicBrainzRgTagContextReadinessError("tag-context readiness hash does not replay")


def _file_sha256(path: Path, *, maximum_bytes: int) -> tuple[Sha256, int]:
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise MusicBrainzRgTagContextReadinessError("local input is outside its byte bound")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), size


def _gold_readiness(path: Path) -> GoldReadiness:
    digest, size = _file_sha256(path, maximum_bytes=_MAX_GOLD_BYTES)
    gold, parsed_digest = load_gold_set(path)
    if digest != parsed_digest:
        raise MusicBrainzRgTagContextReadinessError("gold file digest changed while being read")
    custody = gold.source_custody
    if not gold.independent_public_gold_labels:
        blocker = "gold is fixture-only, not independently sourced"
    elif not gold.threshold_policy_accepted:
        blocker = "gold has no accepted negative-label threshold policy"
    else:
        # The current schema has no approved MBID/seed-ID prediction bridge for RG tags.
        blocker = "gold has no approved exact bridge to MusicBrainz artist and seed identities"
    return GoldReadiness(
        path=str(path),
        file_sha256=digest,
        file_bytes=size,
        source_kind=custody.source_kind,
        independently_sourced=gold.independent_public_gold_labels,
        judgment_count=len(gold.judgments),
        threshold_policy_accepted=gold.threshold_policy_accepted,
        blocker=blocker,
    )


def _wikidata_p136_pairs(
    database: Path, qid_to_seed: dict[str, str]
) -> tuple[int, set[tuple[str, str]]]:
    query = """
        SELECT DISTINCT artist_identifier.normalized_value, genre_identifier.normalized_value
          FROM normalizable_artist_genre_evidence AS evidence
          JOIN entity_identifiers AS artist_identifier
            ON artist_identifier.entity_id = evidence.artist_id
          JOIN identifier_types AS artist_type
            ON artist_type.id = artist_identifier.identifier_type_id
          JOIN entity_identifiers AS genre_identifier
            ON genre_identifier.entity_id = evidence.genre_id
          JOIN identifier_types AS genre_type
            ON genre_type.id = genre_identifier.identifier_type_id
         WHERE evidence.method_key = 'wikidata_p136'
           AND artist_type.type_key = 'musicbrainz_artist_id'
           AND artist_identifier.namespace = 'musicbrainz'
           AND genre_type.type_key = 'wikidata_genre_qid'
           AND genre_identifier.namespace = 'wikidata'
    """
    try:
        with closing(sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)) as connection:
            raw_pairs = {
                (str(artist_mbid), str(genre_qid))
                for artist_mbid, genre_qid in connection.execute(query)
            }
            return len(raw_pairs), {
                (str(artist_mbid), qid_to_seed[str(genre_qid)])
                for artist_mbid, genre_qid in raw_pairs
                if str(genre_qid) in qid_to_seed
            }
    except sqlite3.Error as error:
        raise MusicBrainzRgTagContextReadinessError(
            "cannot read sealed Wikidata P136 database"
        ) from error


def _one_to_one_reconciled_qid_seeds(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    _digest, size = _file_sha256(path, maximum_bytes=_MAX_RECONCILIATION_BYTES)
    if size == 0:
        raise MusicBrainzRgTagContextReadinessError("seed reconciliation is empty")
    reconciliation = _SeedReconciliation.model_validate_json(path.read_bytes())
    qid_candidates: dict[str, set[str]] = {}
    seed_names: dict[str, str] = {}
    for disposition in reconciliation.dispositions:
        if disposition.disposition != "reconciled":
            continue
        seed_names[disposition.source_item_id] = disposition.normalized_name
        for identity in disposition.public_identities:
            if identity.namespace == "wikidata_genre_qid" and identity.identifier.startswith(
                "wikidata:genre:Q"
            ):
                qid = identity.identifier.removeprefix("wikidata:genre:")
                qid_candidates.setdefault(qid, set()).add(disposition.source_item_id)
    return (
        {qid: next(iter(seeds)) for qid, seeds in qid_candidates.items() if len(seeds) == 1},
        seed_names,
    )


def _top_k_recovery(
    *,
    positives: set[tuple[str, str]],
    rankings: dict[str, tuple[str, ...]],
    candidate_seeds: frozenset[str],
) -> PositiveOnlyTopKRecovery:
    """Measure only the fraction of external positive pairs found in top five."""
    recovered = {
        (artist, seed)
        for artist, seed in positives
        if seed in rankings.get(artist, ())[:_FIXED_TOP_K]
    }
    return PositiveOnlyTopKRecovery(
        positive_pair_denominator=len(positives),
        positive_artist_denominator=len({artist for artist, _seed in positives}),
        frozen_seed_candidate_count=len(candidate_seeds),
        recovered_positive_pair_count=len(recovered),
        recovered_positive_seed_count=len({seed for _artist, seed in recovered}),
        positive_recovery_at_top_k=len(recovered) / len(positives) if positives else 0.0,
    )


def _fixed_rankings_before_p136_targets(
    *,
    groups: tuple[SampledReleaseGroup, ...],
    seed_names: dict[str, str],
    candidate_seeds: frozenset[str],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """Freeze artist-local and global orders before P136 target pairs are read."""
    seeds_by_name: dict[str, set[str]] = defaultdict(set)
    for seed, name in seed_names.items():
        seeds_by_name[name].add(seed)
    local_scores: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    global_scores: dict[str, int] = defaultdict(int)
    for group in groups:
        tag_scores = _group_tag_seed_scores(group, seeds_by_name, candidate_seeds)
        for artist in group.artist_mbids:
            for seed, vote_count in tag_scores:
                local_scores[artist][seed] += vote_count
        for seed, vote_count in tag_scores:
            global_scores[seed] += vote_count
    return (
        {
            artist: tuple(sorted(scores, key=lambda seed: (-scores[seed], seed)))
            for artist, scores in local_scores.items()
        },
        tuple(sorted(global_scores, key=lambda seed: (-global_scores[seed], seed))),
    )


def _group_tag_seed_scores(
    group: SampledReleaseGroup,
    seeds_by_name: dict[str, set[str]],
    candidate_seeds: frozenset[str],
) -> tuple[tuple[str, int], ...]:
    """Return the predeclared candidate seeds exactly named by one group's tags."""
    scores: list[tuple[str, int]] = []
    for tag in group.positive_tags:
        normalized = normalize_label(tag.name)
        if normalized:
            scores.extend(
                (seed, tag.vote_count)
                for seed in seeds_by_name.get(normalized, set()).intersection(candidate_seeds)
            )
    return tuple(scores)


def _fixed_ranking_comparison(
    *,
    positives: set[tuple[str, str]],
    candidate_seeds: frozenset[str],
    local_rankings: dict[str, tuple[str, ...]],
    global_ranking: tuple[str, ...],
    training_group_count: int,
) -> tuple[PositiveOnlyTopKRecovery, TrainBlindGlobalTagPopularityBaseline]:
    """Evaluate orders that were frozen before P136 target pairs were read."""
    cohort_artists = {artist for artist, _seed in positives}
    local = _top_k_recovery(
        positives=positives, rankings=local_rankings, candidate_seeds=candidate_seeds
    )
    baseline = TrainBlindGlobalTagPopularityBaseline(
        **_top_k_recovery(
            positives=positives,
            rankings=dict.fromkeys(cohort_artists, global_ranking),
            candidate_seeds=candidate_seeds,
        ).model_dump(),
        training_group_count=training_group_count,
    )
    return local, baseline


def _frozen_sample_tag_candidate_seeds(
    groups: tuple[SampledReleaseGroup, ...], seed_names: dict[str, str]
) -> frozenset[str]:
    """Fix exact-name candidate labels from the sample before P136 is opened."""
    observed_names = {
        normalized
        for group in groups
        for tag in group.positive_tags
        if (normalized := normalize_label(tag.name))
    }
    return frozenset(seed for seed, name in seed_names.items() if name in observed_names)


def audit_musicbrainz_rg_positive_tag_context(
    *,
    sample_report_path: Path,
    wikidata_p136_database_path: Path,
    seed_reconciliation_path: Path,
    independent_gold_paths: tuple[Path, ...] = (),
) -> MusicBrainzRgTagContextReadinessReport:
    """Audit tag-context availability without deriving a target or a performance score."""
    if len(independent_gold_paths) > _MAX_GOLD_FILES:
        raise MusicBrainzRgTagContextReadinessError("too many independent gold candidates")
    sample_digest, sample_bytes = _file_sha256(
        sample_report_path, maximum_bytes=_MAX_SAMPLE_REPORT_BYTES
    )
    sample = MusicBrainzRgGenreRecoveryV2Report.model_validate_json(sample_report_path.read_bytes())
    verify_report(sample)
    if sample.tags_used_as_targets:
        raise MusicBrainzRgTagContextReadinessError("sample report permits tags as targets")
    database_digest, database_bytes = _file_sha256(
        wikidata_p136_database_path, maximum_bytes=_MAX_PUBLIC_DATABASE_BYTES
    )
    reconciliation_digest, _reconciliation_bytes = _file_sha256(
        seed_reconciliation_path, maximum_bytes=_MAX_RECONCILIATION_BYTES
    )
    qid_to_seed, seed_names = _one_to_one_reconciled_qid_seeds(seed_reconciliation_path)
    candidate_seeds = _frozen_sample_tag_candidate_seeds(sample.sampled_groups, seed_names)
    local_rankings, global_ranking = _fixed_rankings_before_p136_targets(
        groups=sample.sampled_groups,
        seed_names=seed_names,
        candidate_seeds=candidate_seeds,
    )
    raw_p136_pairs, p136_pairs = _wikidata_p136_pairs(wikidata_p136_database_path, qid_to_seed)

    tagged_groups = 0
    tag_observations = 0
    tag_artist_attachments = 0
    normalized_tags: set[str] = set()
    native_groups = 0
    native_observations = 0
    for group in sample.sampled_groups:
        if group.positive_tags:
            tagged_groups += 1
            tag_observations += len(group.positive_tags)
            tag_artist_attachments += len(group.artist_mbids)
            normalized_tags.update(
                normalized
                for tag in group.positive_tags
                if (normalized := normalize_label(tag.name))
            )
        if group.proper_genres:
            native_groups += 1
            native_observations += len(group.proper_genres)

    tags_by_artist: dict[str, set[str]] = {}
    for group in sample.sampled_groups:
        group_tags = {
            normalized for tag in group.positive_tags if (normalized := normalize_label(tag.name))
        }
        for artist_mbid in group.artist_mbids:
            tags_by_artist.setdefault(artist_mbid, set()).update(group_tags)
    overlap = {(artist, seed) for artist, seed in p136_pairs if artist in tags_by_artist}
    hits = {
        (artist, seed) for artist, seed in overlap if seed_names.get(seed) in tags_by_artist[artist]
    }

    local_top_k, baseline_top_k = _fixed_ranking_comparison(
        positives=overlap,
        candidate_seeds=candidate_seeds,
        local_rankings=local_rankings,
        global_ranking=global_ranking,
        training_group_count=sample.sampled_group_count,
    )

    gold = tuple(_gold_readiness(path) for path in independent_gold_paths)
    blockers = (
        (
            "positive MusicBrainz release-group tags and native proper genres share one source; "
            "the native genres are prohibited evaluation targets"
        ),
        *(candidate.blocker for candidate in gold),
        (
            "Wikidata P136 contributes positives only; absent tags and absent P136 claims "
            "are not negatives"
        ),
        (
            "the fixed top-five comparison is positive recovery only; it does not compute "
            "precision, infer negatives, or authorize a quality claim"
        ),
        (
            "the global popularity comparator is P136-label-blind but shares the MusicBrainz "
            "tag sample with the artist-local arm; it is not independently held out"
        ),
    )
    draft = MusicBrainzRgTagContextReadinessReport.model_construct(
        sample_report_path=str(sample_report_path),
        sample_report_file_sha256=sample_digest,
        sample_report_file_bytes=sample_bytes,
        sample_report_output_sha256=sample.output_sha256,
        sample_content_sha256=sample.sample_content_sha256,
        sampled_group_count=sample.sampled_group_count,
        groups_with_positive_tags=tagged_groups,
        positive_tag_observation_count=tag_observations,
        positive_tag_artist_attachment_count=tag_artist_attachments,
        distinct_normalized_positive_tag_count=len(normalized_tags),
        groups_with_native_proper_genres=native_groups,
        native_proper_genre_observation_count=native_observations,
        wikidata_p136_database_path=str(wikidata_p136_database_path),
        wikidata_p136_database_sha256=database_digest,
        wikidata_p136_database_bytes=database_bytes,
        seed_reconciliation_path=str(seed_reconciliation_path),
        seed_reconciliation_sha256=reconciliation_digest,
        wikidata_p136_raw_exact_pair_count=raw_p136_pairs,
        wikidata_p136_one_to_one_seed_pair_count=len(p136_pairs),
        wikidata_p136_overlapping_sample_positive_pair_count=len(overlap),
        wikidata_p136_overlapping_sample_artist_count=len({artist for artist, _seed in overlap}),
        wikidata_p136_overlapping_sample_seed_count=len({_seed for _artist, _seed in overlap}),
        positive_tag_exact_seed_hit_count=len(hits),
        positive_tag_exact_seed_hit_seed_count=len({_seed for _artist, _seed in hits}),
        positive_tag_recovery=len(hits) / len(overlap) if overlap else 0.0,
        artist_local_positive_tag_top_k=local_top_k,
        train_blind_global_tag_popularity_top_k=baseline_top_k,
        gold_candidates=gold,
        blockers=blockers,
        next_required_input=(
            "a sealed independently governed artist-genre gold set with accepted judgment policy "
            "and a reviewed exact bridge to MusicBrainz artist MBIDs and the pinned seed IDs"
        ),
        output_sha256="0" * 64,
    )
    report = draft.model_copy(update={"output_sha256": report_sha256(draft)})
    verify_readiness_report(report)
    return report
