"""Deterministic whole-component splits with an independent identity overlap audit.

Isolation covers supplied identities only. Missing album or duplicate metadata cannot
establish absence of leakage, and a clean split is not evidence of musical quality.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, field_validator

from opennoise.common import canonical_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

Partition = Literal["train", "validation", "test"]
SourceFormat = Literal["identities", "numeric"]
IDENTITY_FIELDS = ("artist_ids", "album_ids", "recording_ids", "duplicate_ids")
PARTITIONS: tuple[Partition, ...] = ("train", "validation", "test")


class TrackIdentity(BaseModel):
    """Source identities; empty groups are unknown, never shared sentinel nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    track_id: str
    artist_ids: tuple[str, ...] = ()
    album_ids: tuple[str, ...] = ()
    recording_ids: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()

    @field_validator("track_id")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        """Prevent collisions between unrelated source identity universes."""
        namespace, separator, identifier = value.partition(":")
        if not separator or not namespace or not identifier or value.strip() != value:
            raise ValueError("identities must use a nonempty provider:value namespace")
        return value

    @field_validator(*IDENTITY_FIELDS)
    @classmethod
    def canonical_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Validate and canonicalize all credited identities, not only one artist."""
        return tuple(sorted({cls.require_namespace(value) for value in values}))


def _index(records: Sequence[TrackIdentity]) -> dict[str, TrackIdentity]:
    indexed: dict[str, TrackIdentity] = {}
    for record in records:
        if record.track_id in indexed:
            raise ValueError("duplicate track rows must be reconciled before splitting")
        indexed[record.track_id] = record
    if not indexed:
        raise ValueError("a split requires at least one track")
    return indexed


def connected_components(records: Sequence[TrackIdentity]) -> tuple[tuple[str, ...], ...]:
    """Connect tracks transitively through any artist, album, recording or duplicate."""
    indexed = _index(records)
    parents = dict(zip(indexed, indexed, strict=True))

    def root(track: str) -> str:
        while parents[track] != track:
            parents[track] = parents[parents[track]]
            track = parents[track]
        return track

    owners: dict[tuple[str, str], str] = {}
    for track, record in sorted(indexed.items()):
        for field in IDENTITY_FIELDS:
            for identity in getattr(record, field):
                other = owners.setdefault((field, identity), track)
                left, right = root(track), root(other)
                parents[max(left, right)] = min(left, right)
    groups: dict[str, list[str]] = defaultdict(list)
    for track in sorted(indexed):
        groups[root(track)].append(track)
    return tuple(sorted(tuple(group) for group in groups.values()))


def audit_split(
    records: Sequence[TrackIdentity], assignments: Mapping[str, str]
) -> dict[str, object]:
    """Audit raw identity intersections without trusting component IDs or union-find."""
    indexed = _index(records)
    if set(indexed) != set(assignments):
        raise ValueError("assignments must cover every track exactly, without extra tracks")
    if any(partition not in PARTITIONS for partition in assignments.values()):
        raise ValueError("unknown split partition")
    overlaps: dict[str, list[str]] = {}
    missing: dict[str, int] = {}
    for field in IDENTITY_FIELDS:
        observed: dict[str, set[str]] = defaultdict(set)
        missing[field] = 0
        for track, record in indexed.items():
            identities = getattr(record, field)
            missing[field] += not bool(identities)
            for identity in identities:
                observed[identity].add(assignments[track])
        overlaps[field] = sorted(key for key, partitions in observed.items() if len(partitions) > 1)
    counts = {partition: list(assignments.values()).count(partition) for partition in PARTITIONS}
    return {
        "known_identity_isolation_passed": not any(overlaps.values()),
        "cross_partition_identities": overlaps,
        "tracks_missing_identity_kind": missing,
        "partition_track_counts": counts,
        "all_partitions_nonempty": all(counts.values()),
        "unknown_identity_leakage_excluded": False,
        "musical_quality_evaluated": False,
    }


def build_split(
    records: Sequence[TrackIdentity],
    *,
    seed: str,
    buckets: tuple[int, int, int] = (8, 1, 1),
) -> dict[str, object]:
    """Hash sealed connected components into partitions without breaking large groups."""
    if (
        not isinstance(seed, str)
        or not seed.strip()
        or len(buckets) != len(PARTITIONS)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in buckets
        )
    ):
        raise ValueError("a nonempty seed and three positive integer bucket counts are required")
    components = connected_components(records)
    assignments: dict[str, Partition] = {}
    manifest = []
    for members in components:
        component_id = hashlib.sha256(json.dumps(members).encode()).hexdigest()
        bucket = int(hashlib.sha256(f"{seed}:{component_id}".encode()).hexdigest(), 16) % sum(
            buckets
        )
        partition: Partition = (
            "train"
            if bucket < buckets[0]
            else "validation"
            if bucket < buckets[0] + buckets[1]
            else "test"
        )
        assignments.update(dict.fromkeys(members, partition))
        manifest.append(
            {"component_id": component_id, "tracks": list(members), "partition": partition}
        )
    audit = audit_split(records, assignments)
    if not audit["known_identity_isolation_passed"]:
        raise ValueError("connected split failed independent identity isolation audit")
    normalized = [
        record.model_dump(mode="json") for record in sorted(records, key=lambda r: r.track_id)
    ]
    return {
        "revision": "connected-track-split-v1",
        "normalized_records_sha256": hashlib.sha256(canonical_json(normalized)).hexdigest(),
        "seed": seed,
        "bucket_counts": dict(zip(PARTITIONS, buckets, strict=True)),
        "component_count": len(components),
        "largest_component_tracks": max(map(len, components)),
        "components": manifest,
        "assignments": dict(sorted(assignments.items())),
        "audit": audit,
        "limitations": [
            "Grouping covers supplied identities; source truth needs source-specific verification.",
            "Missing identities remain unknown; empty groups do not connect unrelated tracks.",
            "Component hashing does not guarantee balanced or nonempty partitions.",
            "Fit preprocessing on training only and select parameters on validation only.",
            "No labels, audio, musical-quality metrics or release eligibility are inferred.",
        ],
    }


def seal_source_split(
    source: bytes,
    *,
    seed: str,
    source_format: SourceFormat,
    buckets: tuple[int, int, int] = (8, 1, 1),
) -> dict[str, object]:
    """Bind raw numeric/identity bytes and canonical identities to a prescribed split.

    Numeric features and labels are sealed as bytes but never inspected for grouping.
    Custody establishes this input's identity, not its truth, license or completeness.
    """
    if source_format == "identities":
        records = TypeAdapter(list[TrackIdentity]).validate_json(source)
    elif source_format == "numeric":
        payload = json.loads(source)
        records = [
            TrackIdentity(
                track_id=row["id"],
                artist_ids=row["artist_ids"],
                album_ids=row["album_ids"],
                recording_ids=row.get("recording_ids", []),
                duplicate_ids=row.get("duplicate_ids", []),
            )
            for row in payload["rows"]
        ]
    else:
        raise ValueError("unknown split source format")
    report = build_split(records, seed=seed, buckets=buckets)
    report.update(
        {
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "source_bytes": len(source),
            "source_format": source_format,
        }
    )
    return report


def verify_source_split(
    source: bytes,
    manifest: Mapping[str, object],
    *,
    seed: str,
    source_format: SourceFormat,
    buckets: tuple[int, int, int] = (8, 1, 1),
) -> dict[str, object]:
    """Reconstruct every manifest field using independently supplied seed and source.

    A rewritten receipt hash, clean overlap audit or unchanged identity digest cannot
    authorize changed assignments or modified numeric observations. The caller must
    retain its prescribed seed/buckets independently rather than reading them here.
    """
    expected = seal_source_split(source, seed=seed, source_format=source_format, buckets=buckets)
    if dict(manifest) != expected:
        raise ValueError(
            "sealed split differs from prescribed source bytes, identities or assignment"
        )
    return expected
