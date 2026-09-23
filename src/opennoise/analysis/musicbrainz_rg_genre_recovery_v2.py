"""Hash-selected local holdout from the complete pinned MusicBrainz RG archive."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from opennoise.models.pipeline import SourceLimits
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.source_cache import (
    SourceCacheReceipt,
    receipt_sha256,
    verify_source_cache_receipt,
)
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup, _iter_raw_archive
from opennoise.taxonomy.seeds.universe import normalize_label

_SEED_RECONCILIATION_SHA256: Final = (
    "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0"
)
_SEED_COUNT: Final = 6_291
_SOURCE_CACHE_RECEIPT_SHA256: Final = (
    "2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde"
)
_DECLARED_MANIFEST_SHA256: Final = (
    "86c1658c7713ed2629d6f03a364fdfcbaa719cdbea06e79538722217a75f0064"
)
_HASH_DOMAIN: Final = b"opennoise/musicbrainz-rg-genre-sample-v2\0"
_SAMPLE_MODULUS: Final = 450
_HOLDOUT_MODULUS: Final = 5
_MAX_ARCHIVE_BYTES: Final = 2 * 1024**3
_MAX_RECORD_BYTES: Final = 2 * 1024**2
_MAX_SELECTED_RECORDS: Final = 15_000
_MAX_SELECTED_RECORD_BYTES: Final = 128 * 1024**2
_MAX_RETAINED_FACTS: Final = 1_000_000
_MAX_RETAINED_FACTS_PER_GROUP: Final = 2_000


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _SeedDisposition(_FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    source_item_id: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)


class _SeedReconciliation(_FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    dispositions: tuple[_SeedDisposition, ...]


class SampleGenre(_FrozenModel):
    """One native genre claim retained from a selected source record."""

    genre_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    name: str = Field(min_length=1)
    vote_count: int | None


class SampleTag(_FrozenModel):
    """One positive community tag retained separately from target genres."""

    name: str = Field(min_length=1)
    vote_count: int = Field(gt=0)


class SampledReleaseGroup(_FrozenModel):
    """One complete, hash-selected release-group record."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    record_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_byte_length: int = Field(gt=0)
    artist_mbids: tuple[str, ...]
    proper_genres: tuple[SampleGenre, ...]
    positive_tags: tuple[SampleTag, ...]


class RecoveryMetric(_FrozenModel):
    """Top-one result with scoreable and full target denominators."""

    correct: int = Field(ge=0)
    scoreable_denominator: int = Field(ge=0)
    target_group_denominator: int = Field(ge=0)
    abstentions: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    coverage_adjusted_accuracy: float = Field(ge=0.0, le=1.0)


class MusicBrainzRgGenreRecoveryV2Report(_FrozenModel):
    """Local-only scorecard and bounded sample with source receipts."""

    revision: Literal["musicbrainz-rg-genre-recovery-hash-sample-v2"] = (
        "musicbrainz-rg-genre-recovery-hash-sample-v2"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    population_quality_claimed: Literal[False] = False
    target_definition: str = (
        "positive native proper-genre name, exact normalized match to the pinned seed vocabulary"
    )
    facet_used: Literal["musicbrainz_genre"] = "musicbrainz_genre"
    tags_used_as_targets: Literal[False] = False
    source_id: str = Field(min_length=1)
    source_snapshot: str = Field(min_length=1)
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_archive_bytes: int = Field(gt=0)
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_method: str
    sample_modulus: int = Field(gt=0)
    holdout_rule: str
    sample_limit: int = Field(gt=0)
    max_selected_record_bytes: int = Field(gt=0)
    max_retained_facts: int = Field(gt=0)
    raw_records_seen: int = Field(ge=0)
    selected_records: int = Field(ge=0)
    sampled_group_count: int = Field(ge=0)
    sampled_group_count_with_seed_genre: int = Field(ge=0)
    sampled_malformed_records: int = Field(ge=0)
    oversized_records: int = Field(ge=0)
    selected_oversized_records: int = Field(ge=0)
    selected_record_bytes: int = Field(ge=0)
    retained_fact_count: int = Field(ge=0)
    labeled_group_count: int = Field(ge=0)
    heldout_labeled_group_count: int = Field(ge=0)
    heldout_seed_label_pair_count: int = Field(ge=0)
    train_labeled_group_count: int = Field(ge=0)
    train_seed_label_count: int = Field(ge=0)
    heldout_seed_label_count: int = Field(ge=0)
    heldout_seed_labels_without_train_support: int = Field(ge=0)
    artist_transfer_macro_recall_by_seed: float = Field(ge=0.0, le=1.0)
    train_popularity_macro_recall_by_seed: float = Field(ge=0.0, le=1.0)
    warm_artist_group_count: int = Field(ge=0)
    cold_artist_group_count: int = Field(ge=0)
    artist_transfer_top1: RecoveryMetric
    train_popularity_top1: RecoveryMetric
    sample_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampled_groups: tuple[SampledReleaseGroup, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class _HoldoutScore:
    transfer_correct: int
    transfer_abstentions: int
    popularity_correct: int
    warm_groups: int
    label_pairs: int
    label_count: int
    labels_without_train_support: int
    train_label_count: int
    transfer_macro_recall: float
    popularity_macro_recall: float


@dataclass(frozen=True, slots=True)
class _SampledSource:
    source_id: str
    source_snapshot: str
    archive_sha256: str
    source_receipt_sha256: str
    manifest_sha256: str
    reconciliation_sha256: str
    archive_bytes: int
    raw_records_seen: int
    selected_records: int
    oversized_records: int
    selected_oversized_records: int
    malformed_selected_records: int
    selected_record_bytes: int
    retained_fact_count: int
    sampled_groups: tuple[SampledReleaseGroup, ...]
    seed_names: frozenset[str]
    sampled_seed_label_group_count: int


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def report_sha256(report: MusicBrainzRgGenreRecoveryV2Report) -> str:
    """Hash the complete report payload without its self-referential field."""
    return hashlib.sha256(
        _canonical(report.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def verify_report(report: MusicBrainzRgGenreRecoveryV2Report) -> None:
    """Reject a report whose logical output hash does not replay."""
    if report_sha256(report) != report.output_sha256:
        raise ValueError("hash-sample report output hash does not replay")


def _sample_selected(record_sha256: str) -> bool:
    digest = hashlib.sha256(_HASH_DOMAIN + bytes.fromhex(record_sha256)).digest()
    return int.from_bytes(digest[:8], "big") % _SAMPLE_MODULUS == 0


def _check_sample_limits(
    *, selected_records: int, selected_record_bytes: int, retained_facts: int
) -> None:
    """Fail closed before retained records or facts exceed the declared caps."""
    if selected_records > _MAX_SELECTED_RECORDS:
        raise ValueError("hash-selected record cap exceeded")
    if selected_record_bytes > _MAX_SELECTED_RECORD_BYTES:
        raise ValueError("hash-selected record-byte cap exceeded")
    if retained_facts > _MAX_RETAINED_FACTS:
        raise ValueError("sample retained-fact cap exceeded")


def _heldout(group_id: str) -> bool:
    digest = hashlib.sha256(group_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % _HOLDOUT_MODULUS == 0


def _partition_groups[T](
    groups: dict[str, T],
) -> tuple[dict[str, T], dict[str, T]]:
    """Partition exact release-group IDs so each complete group stays on one side."""
    train = {group_id: value for group_id, value in groups.items() if not _heldout(group_id)}
    test = {group_id: value for group_id, value in groups.items() if _heldout(group_id)}
    return train, test


def _seed_labels(
    release_group: MusicBrainzReleaseGroup, seed_names: frozenset[str]
) -> frozenset[str]:
    return frozenset(
        normalized
        for genre in release_group.genres
        if genre.count is not None
        and genre.count > 0
        and (normalized := normalize_label(genre.name)) in seed_names
    )


def _score_holdout(  # noqa: C901
    train: dict[str, tuple[frozenset[str], frozenset[str]]],
    test: dict[str, tuple[frozenset[str], frozenset[str]]],
) -> _HoldoutScore:
    # One pass keeps all top-one and macro denominators on the same holdout.
    if train.keys() & test.keys():
        raise ValueError("a release-group ID occurs in both train and test")
    artist_labels: dict[str, Counter[str]] = defaultdict(Counter)
    popularity: Counter[str] = Counter()
    for labels, artists in train.values():
        popularity.update(labels)
        for artist in artists:
            artist_labels[artist].update(labels)
    popular_label = (
        min(popularity, key=lambda label: (-popularity[label], label)) if popularity else None
    )

    transfer_correct = transfer_abstentions = popularity_correct = label_pairs = 0
    test_label_groups: Counter[str] = Counter()
    transfer_label_hits: Counter[str] = Counter()
    popularity_label_hits: Counter[str] = Counter()
    for labels, artists in test.values():
        label_pairs += len(labels)
        test_label_groups.update(labels)
        votes: Counter[str] = Counter()
        for artist in artists:
            votes.update(artist_labels.get(artist, {}))
        prediction = min(votes, key=lambda label: (-votes[label], label)) if votes else None
        if prediction is None:
            transfer_abstentions += 1
        elif prediction in labels:
            transfer_correct += 1
            transfer_label_hits[prediction] += 1
        if popular_label is not None and popular_label in labels:
            popularity_correct += 1
            popularity_label_hits[popular_label] += 1
    label_count = len(test_label_groups)

    def macro_recall(hits: Counter[str]) -> float:
        if not label_count:
            return 0.0
        return sum(hits[label] / count for label, count in test_label_groups.items()) / label_count

    return _HoldoutScore(
        transfer_correct=transfer_correct,
        transfer_abstentions=transfer_abstentions,
        popularity_correct=popularity_correct,
        warm_groups=len(test) - transfer_abstentions,
        label_pairs=label_pairs,
        label_count=label_count,
        labels_without_train_support=sum(label not in popularity for label in test_label_groups),
        train_label_count=len(popularity),
        transfer_macro_recall=macro_recall(transfer_label_hits),
        popularity_macro_recall=macro_recall(popularity_label_hits),
    )


# The checks and limits stay beside the only loop that retains source facts.
def _source_facts(  # noqa: C901, PLR0912, PLR0915
    archive_path: Path,
    source_cache_receipt: SourceCacheReceipt,
    seed_reconciliation_path: Path,
    *,
    progress: bool = False,
) -> _SampledSource:
    manifest_path = Path("config/data_sources.toml")
    source = load_download_source(manifest_path, "musicbrainz_json_release_group_research_20260905")
    if (
        source.verified_sha256()
        != "6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43"
    ):
        raise ValueError("MusicBrainz release-group source pin changed")
    if source_cache_receipt.declared_manifest_sha256 != _DECLARED_MANIFEST_SHA256:
        raise ValueError("source-cache receipt manifest digest changed")
    if receipt_sha256(source_cache_receipt) != _SOURCE_CACHE_RECEIPT_SHA256:
        raise ValueError("source-cache receipt hash does not match the pinned receipt")
    verify_source_cache_receipt(
        source_cache_receipt, (source,), declared_manifest_sha256=_DECLARED_MANIFEST_SHA256
    )
    archive_sha256, archive_bytes = _file_sha256(archive_path)
    if archive_sha256 != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise ValueError("archive bytes do not match the pinned MusicBrainz source")

    reconciliation_bytes = seed_reconciliation_path.read_bytes()
    reconciliation_sha256 = hashlib.sha256(reconciliation_bytes).hexdigest()
    if reconciliation_sha256 != _SEED_RECONCILIATION_SHA256:
        raise ValueError("seed reconciliation does not match the pinned 6,291-name scope")
    reconciliation = _SeedReconciliation.model_validate_json(reconciliation_bytes)
    if len(reconciliation.dispositions) != _SEED_COUNT:
        raise ValueError("seed reconciliation does not contain the fixed 6,291-name scope")
    seed_names = frozenset(item.normalized_name for item in reconciliation.dispositions)
    if len(seed_names) != _SEED_COUNT:
        raise ValueError("seed reconciliation has duplicate normalized seed names")

    limits = SourceLimits(max_archive_bytes=_MAX_ARCHIVE_BYTES, max_record_bytes=_MAX_RECORD_BYTES)
    sampled: list[SampledReleaseGroup] = []
    seen_ids: set[str] = set()
    raw_records_seen = selected_records = oversized_records = selected_record_bytes = 0
    selected_oversized_records = 0
    malformed_selected_records = retained_fact_count = 0
    sampled_seed_label_group_count = 0
    started = monotonic()
    for raw in _iter_raw_archive(archive_path, limits, member_name="release-group"):
        raw_records_seen += 1
        if raw.payload is None:
            oversized_records += 1
        if not _sample_selected(raw.sha256):
            if progress and raw_records_seen % 500_000 == 0:
                logging.getLogger(__name__).info(
                    "streamed %s records, selected %s, elapsed %.0fs",
                    f"{raw_records_seen:,}",
                    f"{selected_records:,}",
                    monotonic() - started,
                )
            continue
        selected_records += 1
        selected_record_bytes += raw.byte_length
        _check_sample_limits(
            selected_records=selected_records,
            selected_record_bytes=selected_record_bytes,
            retained_facts=retained_fact_count,
        )
        if raw.byte_length > _MAX_RECORD_BYTES:
            selected_oversized_records += 1
            continue
        if raw.payload is None:
            raise ValueError("selected record has no payload under the configured record limit")
        try:
            release_group = MusicBrainzReleaseGroup.model_validate_json(raw.payload)
        except ValueError:
            # Retain source-wide selection counts, but never put a malformed record in the sample.
            malformed_selected_records += 1
            continue
        group_id = str(release_group.id)
        if group_id in seen_ids:
            raise ValueError("the source repeats a hash-selected release-group ID")
        seen_ids.add(group_id)
        sampled_seed_label_group_count += bool(_seed_labels(release_group, seed_names))
        artists = tuple(sorted({str(item.artist.id) for item in release_group.artist_credit}))
        proper_genres = tuple(
            SampleGenre(genre_mbid=str(item.id), name=item.name, vote_count=item.count)
            for item in release_group.genres
        )
        positive_tags = tuple(
            SampleTag(name=item.name, vote_count=item.count)
            for item in release_group.tags
            if item.count is not None and item.count > 0
        )
        fact_count = len(artists) + len(proper_genres) + len(positive_tags)
        if fact_count > _MAX_RETAINED_FACTS_PER_GROUP:
            raise ValueError("selected release-group fact cap exceeded")
        retained_fact_count += fact_count
        _check_sample_limits(
            selected_records=selected_records,
            selected_record_bytes=selected_record_bytes,
            retained_facts=retained_fact_count,
        )
        sampled.append(
            SampledReleaseGroup(
                release_group_mbid=group_id,
                record_content_sha256=raw.sha256,
                record_byte_length=raw.byte_length,
                artist_mbids=artists,
                proper_genres=proper_genres,
                positive_tags=positive_tags,
            )
        )
        if progress and raw_records_seen % 500_000 == 0:
            logging.getLogger(__name__).info(
                "streamed %s records, selected %s, elapsed %.0fs",
                f"{raw_records_seen:,}",
                f"{selected_records:,}",
                monotonic() - started,
            )
    if raw_records_seen == 0:
        raise ValueError("release-group archive contained no records")
    return _SampledSource(
        source_id=source.id,
        source_snapshot=source.snapshot,
        archive_sha256=archive_sha256,
        source_receipt_sha256=receipt_sha256(source_cache_receipt),
        manifest_sha256=source_cache_receipt.declared_manifest_sha256,
        reconciliation_sha256=reconciliation_sha256,
        archive_bytes=archive_bytes,
        raw_records_seen=raw_records_seen,
        selected_records=selected_records,
        oversized_records=oversized_records,
        selected_oversized_records=selected_oversized_records,
        malformed_selected_records=malformed_selected_records,
        selected_record_bytes=selected_record_bytes,
        retained_fact_count=retained_fact_count,
        sampled_groups=tuple(sampled),
        seed_names=seed_names,
        sampled_seed_label_group_count=sampled_seed_label_group_count,
    )


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def evaluate_musicbrainz_rg_genre_recovery_v2(
    *,
    archive_path: Path,
    source_cache_receipt: SourceCacheReceipt,
    seed_reconciliation_path: Path,
    progress: bool = False,
) -> MusicBrainzRgGenreRecoveryV2Report:
    """Hash-sample the full pinned archive, then evaluate a whole-group holdout."""
    sampled_source = _source_facts(
        archive_path,
        source_cache_receipt,
        seed_reconciliation_path,
        progress=progress,
    )
    reconciliation_sha256 = sampled_source.reconciliation_sha256
    seed_names = sampled_source.seed_names
    sampled_groups = sampled_source.sampled_groups
    groups: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    retained_fact_count = sampled_source.retained_fact_count
    for item in sampled_groups:
        labels = frozenset(
            normalized
            for genre in item.proper_genres
            if genre.vote_count is not None
            and genre.vote_count > 0
            and (normalized := normalize_label(genre.name)) in seed_names
        )
        if labels:
            groups[item.release_group_mbid] = (labels, frozenset(item.artist_mbids))
    train, test = _partition_groups(groups)
    score = _score_holdout(train, test)
    denominator = len(test)

    def metric(correct: int, scoreable: int, abstentions: int) -> RecoveryMetric:
        return RecoveryMetric(
            correct=correct,
            scoreable_denominator=scoreable,
            target_group_denominator=denominator,
            abstentions=abstentions,
            accuracy=correct / scoreable if scoreable else 0.0,
            coverage_adjusted_accuracy=correct / denominator if denominator else 0.0,
        )

    payload = {
        "revision": "musicbrainz-rg-genre-recovery-hash-sample-v2",
        "local_only": True,
        "export_allowed": False,
        "serving_allowed": False,
        "model_input_allowed": False,
        "population_quality_claimed": False,
        "target_definition": (
            "positive native proper-genre name, exact normalized match to the pinned "
            "seed vocabulary"
        ),
        "facet_used": "musicbrainz_genre",
        "tags_used_as_targets": False,
        "source_id": sampled_source.source_id,
        "source_snapshot": sampled_source.source_snapshot,
        "source_archive_sha256": sampled_source.archive_sha256,
        "source_archive_bytes": sampled_source.archive_bytes,
        "source_manifest_sha256": sampled_source.manifest_sha256,
        "source_cache_receipt_sha256": sampled_source.source_receipt_sha256,
        "reconciliation_sha256": reconciliation_sha256,
        "sample_method": (
            "sha256(domain || sha256(raw JSON record bytes)); first_u64 modulo 450 equals 0; "
            "selection is independent of archive position and is applied before JSON model parsing"
        ),
        "sample_modulus": _SAMPLE_MODULUS,
        "holdout_rule": (
            "sha256(exact release-group MBID) first_u64 modulo 5 equals 0; whole groups held out; "
            "credited artists can overlap by design for transfer"
        ),
        "sample_limit": _MAX_SELECTED_RECORDS,
        "max_selected_record_bytes": _MAX_SELECTED_RECORD_BYTES,
        "max_retained_facts": _MAX_RETAINED_FACTS,
        "raw_records_seen": sampled_source.raw_records_seen,
        "selected_records": sampled_source.selected_records,
        "selected_oversized_records": sampled_source.selected_oversized_records,
        "sampled_group_count": len(sampled_groups),
        "sampled_group_count_with_seed_genre": sampled_source.sampled_seed_label_group_count,
        "sampled_malformed_records": sampled_source.malformed_selected_records,
        "oversized_records": sampled_source.oversized_records,
        "selected_record_bytes": sampled_source.selected_record_bytes,
        "retained_fact_count": retained_fact_count,
        "labeled_group_count": len(groups),
        "heldout_labeled_group_count": denominator,
        "heldout_seed_label_pair_count": score.label_pairs,
        "train_labeled_group_count": len(train),
        "train_seed_label_count": score.train_label_count,
        "heldout_seed_label_count": score.label_count,
        "heldout_seed_labels_without_train_support": score.labels_without_train_support,
        "artist_transfer_macro_recall_by_seed": score.transfer_macro_recall,
        "train_popularity_macro_recall_by_seed": score.popularity_macro_recall,
        "warm_artist_group_count": score.warm_groups,
        "cold_artist_group_count": score.transfer_abstentions,
        "artist_transfer_top1": metric(
            score.transfer_correct, score.warm_groups, score.transfer_abstentions
        ),
        "train_popularity_top1": metric(score.popularity_correct, denominator, 0),
        "sample_content_sha256": hashlib.sha256(
            _canonical(
                tuple(
                    (item.record_content_sha256, item.record_byte_length) for item in sampled_groups
                )
            )
        ).hexdigest(),
        "sampled_groups": sampled_groups,
        "output_sha256": "0" * 64,
    }
    placeholder = MusicBrainzRgGenreRecoveryV2Report.model_validate(payload)
    report = placeholder.model_copy(update={"output_sha256": report_sha256(placeholder)})
    verify_report(report)
    return report
