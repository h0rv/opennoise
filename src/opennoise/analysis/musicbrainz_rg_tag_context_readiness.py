"""Bounded, local-only readiness audit for MusicBrainz RG positive tags.

Positive tags are retained as weak context only.  In particular, this module
never compares them with ``proper_genres`` from the same MusicBrainz sample:
that would turn source-native genres into leaked targets.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
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

_REVISION: Final = "musicbrainz-rg-positive-tag-context-readiness-v1"
_MAX_SAMPLE_REPORT_BYTES: Final = 64 * 1024 * 1024
_MAX_GOLD_FILES: Final = 8
_MAX_GOLD_BYTES: Final = 32 * 1024 * 1024
_MAX_PUBLIC_DATABASE_BYTES: Final = 512 * 1024 * 1024
_MAX_RECONCILIATION_BYTES: Final = 16 * 1024 * 1024

if TYPE_CHECKING:
    from pathlib import Path


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


class MusicBrainzRgTagContextReadinessReport(FrozenModel):
    """A no-score checkpoint that prevents same-source target leakage."""

    revision: Literal["musicbrainz-rg-positive-tag-context-readiness-v1"] = _REVISION
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
        group_tags = {normalize_label(tag.name) for tag in group.positive_tags}
        for artist_mbid in group.artist_mbids:
            tags_by_artist.setdefault(artist_mbid, set()).update(group_tags)
    overlap = {(artist, seed) for artist, seed in p136_pairs if artist in tags_by_artist}
    hits = {
        (artist, seed) for artist, seed in overlap if seed_names.get(seed) in tags_by_artist[artist]
    }

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
