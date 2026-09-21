"""Bounded local audit of direct MusicBrainz *genre* evidence.

This module deliberately does not construct memberships.  It measures only
literal, source-bound artist-to-genre observations already retained in the
MusicBrainz seed-target artifact.  MusicBrainz tags, release evidence, peer
membership, and any historical signal are outside the input contract.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import ijson

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MB_ARTIST_RECORD_PREFIX = "musicbrainz:artist:"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """The minimal typed boundary for one retained direct source row."""

    seed_id: str
    seed_name: str
    artist_mbid: str
    facet: str
    match_kind: str
    target_identity: str
    target_name: str
    target_namespace: str
    source_record_id: str
    source_record_sha256: str


@dataclass(frozen=True, slots=True)
class DirectGenreFrontierReport:
    """Deterministic counts for the local-only, no-promotion frontier."""

    audit_revision: str
    publication_scope: str
    historical_assignments_read: bool
    membership_construction_performed: bool
    layout_path: str
    layout_byte_sha256: str
    layout_output_sha256: str
    frontier_path: str
    frontier_byte_sha256: str
    frontier_output_sha256: str
    reconciliation_path: str
    reconciliation_byte_sha256: str
    reconciliation_output_sha256: str
    seed_target_path: str
    seed_target_byte_sha256: str
    seed_target_output_sha256: str
    unplaced_seed_count: int
    currently_served_unplaced_seed_count: int
    unplaced_unserved_seed_count: int
    strict_proper_genre_rows: int
    strict_proper_genre_seed_count: int
    strict_proper_genre_artist_mbid_count: int
    strict_proper_genre_source_record_count: int
    identity_eligible_proper_genre_rows: int
    identity_eligible_proper_genre_seed_count: int
    identity_abstained_proper_genre_rows: int
    identity_abstained_proper_genre_seed_count: int
    exact_loose_tag_rows: int
    exact_loose_tag_seed_count: int
    exact_loose_tag_artist_mbid_count: int
    inferred_membership_rows_used: int
    release_or_peer_rows_used: int
    missing_or_invalid_source_rows: int
    reconciliation_abstentions: dict[str, int]
    publishable_membership_count: int
    policy_abstentions: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path, *, label: str) -> dict[str, object]:
    raw: object = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise TypeError(f"{label} must be a JSON object")
    result: dict[str, object] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise TypeError(f"{label} keys must be strings")
        result[key] = value
    return result


def _required_sha256(raw: dict[str, object], *, label: str) -> str:
    value = raw.get("output_sha256")
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must have a lowercase SHA-256 output_sha256")
    return value


def _streamed_output_sha256(path: Path, *, label: str) -> str:
    """Read only an artifact's terminal hash, without materializing its evidence."""
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream):
            if prefix == "output_sha256" and event == "string":
                if isinstance(value, str) and _SHA256.fullmatch(value) is not None:
                    return value
                raise ValueError(f"{label} must have a lowercase SHA-256 output_sha256")
    raise ValueError(f"{label} must have an output_sha256")


def _unplaced_ids(layout: dict[str, object]) -> frozenset[str]:
    rows = layout.get("unplaced")
    if not isinstance(rows, list):
        raise TypeError("layout must contain an unplaced list")
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(seed_id := row.get("seed_id"), str):
            raise TypeError("every unplaced row requires a string seed_id")
        if not seed_id or seed_id in result:
            raise ValueError("unplaced seed IDs must be nonempty and unique")
        result.add(seed_id)
    return frozenset(result)


def _frontier_rows(frontier: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = frontier.get("rows")
    if not isinstance(rows, list):
        raise TypeError("frontier must contain a rows list")
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(seed_id := row.get("source_item_id"), str):
            raise TypeError("every frontier row requires a string source_item_id")
        observed = row.get("observed_artists")
        if not isinstance(observed, dict) or not isinstance(observed.get("wikidata_p136"), int):
            raise TypeError("every frontier row requires integer wikidata_p136 coverage")
        if seed_id in result:
            raise ValueError("frontier source_item_id values must be unique")
        result[seed_id] = row
    return result


def _canonical_genre_identities(reconciliation: dict[str, object]) -> dict[str, frozenset[str]]:
    rows = reconciliation.get("dispositions")
    if not isinstance(rows, list):
        raise TypeError("reconciliation must contain a dispositions list")
    result: dict[str, frozenset[str]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(seed_id := row.get("source_item_id"), str):
            raise TypeError("every reconciliation disposition requires a string source_item_id")
        identities = row.get("musicbrainz_identities")
        if not isinstance(identities, list):
            raise TypeError("every reconciliation disposition requires identities")
        genre_ids = {
            identity["identifier"]
            for identity in identities
            if isinstance(identity, dict)
            and identity.get("namespace") == "musicbrainz_genre_id"
            and isinstance(identity.get("identifier"), str)
        }
        if seed_id in result:
            raise ValueError("reconciliation source_item_id values must be unique")
        result[seed_id] = frozenset(genre_ids)
    return result


def _parse_evidence(row: object) -> SourceEvidence | None:
    if not isinstance(row, dict):
        raise TypeError("seed-target evidence rows must be objects")
    match (
        row.get("seed_source_item_id"),
        row.get("seed_name"),
        row.get("artist_id"),
        row.get("facet"),
        row.get("match_kind"),
        row.get("target_identity"),
        row.get("target_name"),
        row.get("target_namespace"),
        row.get("source_record_id"),
        row.get("source_record_sha256"),
    ):
        case (
            str() as seed_id,
            str() as seed_name,
            str() as artist_mbid,
            str() as facet,
            str() as match_kind,
            str() as target_identity,
            str() as target_name,
            str() as target_namespace,
            str() as source_record_id,
            str() as source_record_sha256,
        ):
            return SourceEvidence(
                seed_id,
                seed_name,
                artist_mbid,
                facet,
                match_kind,
                target_identity,
                target_name,
                target_namespace,
                source_record_id,
                source_record_sha256,
            )
        case _:
            return None


def _is_currently_served(row: dict[str, object]) -> bool:
    observed = row["observed_artists"]
    if not isinstance(observed, dict) or not isinstance(
        count := observed.get("wikidata_p136"), int
    ):
        raise TypeError("every frontier row requires integer wikidata_p136 coverage")
    return count > 0


def _is_exact_artist_mbid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return str(parsed) == value


def _is_strict_direct_row(evidence: SourceEvidence, *, facet: str) -> bool:
    return (
        evidence.facet == facet
        and evidence.match_kind == "exact"
        and evidence.target_name == evidence.seed_name
        and _is_exact_artist_mbid(evidence.artist_mbid)
        and evidence.source_record_id == f"{_MB_ARTIST_RECORD_PREFIX}{evidence.artist_mbid}"
        and _SHA256.fullmatch(evidence.source_record_sha256) is not None
    )


def _iter_evidence(path: Path) -> Iterator[object]:
    with path.open("rb") as stream:
        yield from ijson.items(stream, "evidence.item")


def audit_direct_genre_frontier(  # noqa: C901, PLR0915
    *, layout_path: Path, frontier_path: Path, reconciliation_path: Path, seed_target_path: Path
) -> DirectGenreFrontierReport:
    """Measure direct MusicBrainz proper-genre coverage without producing memberships."""
    layout = _json_object(layout_path, label="layout")
    frontier = _json_object(frontier_path, label="frontier")
    reconciliation = _json_object(reconciliation_path, label="reconciliation")
    unplaced = _unplaced_ids(layout)
    frontier_by_id = _frontier_rows(frontier)
    canonical_genres_by_id = _canonical_genre_identities(reconciliation)
    if set(frontier_by_id) != set(canonical_genres_by_id):
        raise ValueError("frontier and reconciliation must account for the same seed IDs")
    if not unplaced <= set(frontier_by_id):
        raise ValueError("layout unplaced IDs must be present in the frontier")

    served = {seed_id for seed_id in unplaced if _is_currently_served(frontier_by_id[seed_id])}
    scoped = unplaced - served
    strict_rows: set[tuple[str, str, str, str, str, str]] = set()
    strict_seed_ids: set[str] = set()
    strict_artists: set[str] = set()
    strict_records: set[str] = set()
    eligible_rows: set[tuple[str, str, str, str, str, str]] = set()
    eligible_seed_ids: set[str] = set()
    abstained_rows: set[tuple[str, str, str, str, str, str]] = set()
    abstained_seed_ids: set[str] = set()
    tag_rows: set[tuple[str, str, str, str, str, str]] = set()
    tag_seed_ids: set[str] = set()
    tag_artists: set[str] = set()
    invalid_rows = 0
    for raw_row in _iter_evidence(seed_target_path):
        evidence = _parse_evidence(raw_row)
        if evidence is None:
            invalid_rows += 1
            continue
        if evidence.seed_id not in scoped:
            continue
        if (
            _is_strict_direct_row(evidence, facet="genre")
            and evidence.target_namespace == "musicbrainz_genre_id"
        ):
            row_key = (
                evidence.seed_id,
                evidence.artist_mbid,
                evidence.source_record_sha256,
                evidence.target_namespace,
                evidence.target_identity,
                evidence.target_name,
            )
            strict_rows.add(row_key)
            strict_seed_ids.add(evidence.seed_id)
            strict_artists.add(evidence.artist_mbid)
            strict_records.add(evidence.source_record_sha256)
            if evidence.target_identity in canonical_genres_by_id[evidence.seed_id]:
                eligible_rows.add(row_key)
                eligible_seed_ids.add(evidence.seed_id)
            else:
                abstained_rows.add(row_key)
                abstained_seed_ids.add(evidence.seed_id)
        if (
            _is_strict_direct_row(evidence, facet="tag")
            and evidence.target_namespace == "musicbrainz_tag_name"
        ):
            tag_rows.add(
                (
                    evidence.seed_id,
                    evidence.artist_mbid,
                    evidence.source_record_sha256,
                    evidence.target_namespace,
                    evidence.target_identity,
                    evidence.target_name,
                )
            )
            tag_seed_ids.add(evidence.seed_id)
            tag_artists.add(evidence.artist_mbid)
    dispositions: dict[str, int] = {}
    for seed_id in scoped:
        value = frontier_by_id[seed_id].get("reconciliation_disposition")
        if not isinstance(value, str):
            raise TypeError("frontier reconciliation disposition must be a string")
        dispositions[value] = dispositions.get(value, 0) + 1
    return DirectGenreFrontierReport(
        audit_revision="musicbrainz-direct-proper-genre-frontier-v1",
        publication_scope="local_only_research_audit",
        historical_assignments_read=False,
        membership_construction_performed=False,
        layout_path=str(layout_path),
        layout_byte_sha256=_sha256(layout_path),
        layout_output_sha256=_required_sha256(layout, label="layout"),
        frontier_path=str(frontier_path),
        frontier_byte_sha256=_sha256(frontier_path),
        frontier_output_sha256=_required_sha256(frontier, label="frontier"),
        reconciliation_path=str(reconciliation_path),
        reconciliation_byte_sha256=_sha256(reconciliation_path),
        reconciliation_output_sha256=_required_sha256(reconciliation, label="reconciliation"),
        seed_target_path=str(seed_target_path),
        seed_target_byte_sha256=_sha256(seed_target_path),
        seed_target_output_sha256=_streamed_output_sha256(seed_target_path, label="seed target"),
        unplaced_seed_count=len(unplaced),
        currently_served_unplaced_seed_count=len(served),
        unplaced_unserved_seed_count=len(scoped),
        strict_proper_genre_rows=len(strict_rows),
        strict_proper_genre_seed_count=len(strict_seed_ids),
        strict_proper_genre_artist_mbid_count=len(strict_artists),
        strict_proper_genre_source_record_count=len(strict_records),
        identity_eligible_proper_genre_rows=len(eligible_rows),
        identity_eligible_proper_genre_seed_count=len(eligible_seed_ids),
        identity_abstained_proper_genre_rows=len(abstained_rows),
        identity_abstained_proper_genre_seed_count=len(abstained_seed_ids),
        exact_loose_tag_rows=len(tag_rows),
        exact_loose_tag_seed_count=len(tag_seed_ids),
        exact_loose_tag_artist_mbid_count=len(tag_artists),
        inferred_membership_rows_used=0,
        release_or_peer_rows_used=0,
        missing_or_invalid_source_rows=invalid_rows,
        reconciliation_abstentions=dict(sorted(dispositions.items())),
        publishable_membership_count=0,
        policy_abstentions=(
            "MusicBrainz tags are counted separately and never treated as proper genres.",
            "Only artist-record rows with literal exact seed spelling and UUID MBIDs are counted.",
            "Release, peer, one-hop, and inferred membership evidence is not read or used.",
            (
                "A proper-genre row whose target identifier is not a reconciled MusicBrainz "
                "genre identity remains identity-abstained."
            ),
            (
                "All counts are research coverage diagnostics; no membership or serving "
                "promotion is authorized."
            ),
        ),
    )


def report_json(report: DirectGenreFrontierReport) -> str:
    """Serialize a canonical, newline-terminated checkpoint payload."""
    return json.dumps(asdict(report), sort_keys=True, separators=(",", ":")) + "\n"
