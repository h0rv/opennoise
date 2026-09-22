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
from typing import TYPE_CHECKING, Final, Literal

import ijson
from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves the alias at runtime.

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MB_ARTIST_RECORD_PREFIX = "musicbrainz:artist:"
_RETAINED_SEED_COUNT: Final = 6_291
_CLAIM_SAMPLE_LIMIT: Final = 64


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
    evidence_ref: str


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


class DirectGenreMembershipCandidateRow(FrozenModel):
    """One exact-MBID, reconciliation-bound local membership observation."""

    seed_id: str = Field(min_length=1)
    artist_mbid: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    musicbrainz_genre_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_record_sha256: Sha256

    @model_validator(mode="after")
    def _exact_artist_provenance(self) -> DirectGenreMembershipCandidateRow:
        if self.source_record_id != f"{_MB_ARTIST_RECORD_PREFIX}{self.artist_mbid}":
            raise ValueError("candidate row source record is not the exact artist record")
        return self


class DirectGenreMembershipCandidate(FrozenModel):
    """A source-bound local candidate that has no public or layout effect."""

    candidate_revision: Literal["musicbrainz-direct-proper-genre-membership-candidate-v1"]
    publication_scope: Literal["local_only_candidate"]
    historical_assignments_read: Literal[False] = False
    alias_or_name_only_bridge_used: Literal[False] = False
    public_export_authorized: Literal[False] = False
    layout_byte_sha256: Sha256
    layout_output_sha256: Sha256
    frontier_byte_sha256: Sha256
    frontier_output_sha256: Sha256
    reconciliation_byte_sha256: Sha256
    reconciliation_output_sha256: Sha256
    seed_target_byte_sha256: Sha256
    seed_target_output_sha256: Sha256
    memberships: tuple[DirectGenreMembershipCandidateRow, ...]
    membership_count: int = Field(ge=0)
    seed_count: int = Field(ge=0)
    artist_mbid_count: int = Field(ge=0)
    source_record_count: int = Field(ge=0)
    output_sha256: Sha256

    @model_validator(mode="after")
    def _counts_match_rows(self) -> DirectGenreMembershipCandidate:
        if self.membership_count != len(self.memberships):
            raise ValueError("membership count does not match candidate rows")
        if self.seed_count != len({row.seed_id for row in self.memberships}):
            raise ValueError("seed count does not match candidate rows")
        if self.artist_mbid_count != len({row.artist_mbid for row in self.memberships}):
            raise ValueError("artist MBID count does not match candidate rows")
        if self.source_record_count != len({row.source_record_sha256 for row in self.memberships}):
            raise ValueError("source record count does not match candidate rows")
        return self


class DirectMusicBrainzPublicationRow(FrozenModel):
    """One source-reconstructable proper-genre observation for policy review.

    This is intentionally not a ``PublicModelInput`` row.  The retained
    extractor is still marked non-exportable by the model adapter, so these
    rows are a review payload rather than a promotion path.
    """

    seed_id: str = Field(min_length=1)
    artist_mbid: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    musicbrainz_genre_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_record_sha256: Sha256
    source_evidence_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _has_exact_artist_record(self) -> DirectMusicBrainzPublicationRow:
        if self.source_record_id != f"{_MB_ARTIST_RECORD_PREFIX}{self.artist_mbid}":
            raise ValueError("publication row source record is not the exact artist record")
        return self


class DirectMusicBrainzPublicationGate(FrozenModel):
    """A portable, local-only gate for a possible direct-claim publication.

    Its rows are deliberately restricted to literal artist-record genre facts.
    Tags and release/context evidence have no representation in this model.
    """

    revision: Literal["musicbrainz-direct-publication-gate-v1"]
    publication_scope: Literal["local_only_policy_gate"]
    public_export_authorized: Literal[False] = False
    source_adapter_export_allowed: Literal[False] = False
    historical_assignments_read: Literal[False] = False
    release_or_peer_rows_used: Literal[0] = 0
    tag_rows_used: Literal[0] = 0
    seed_target_byte_sha256: Sha256
    seed_target_output_sha256: Sha256
    reconciliation_byte_sha256: Sha256
    reconciliation_output_sha256: Sha256
    layout_byte_sha256: Sha256
    layout_output_sha256: Sha256
    retained_seed_count: Literal[6291] = 6291
    source_proper_genre_frontier_seed_count: int = Field(ge=0, le=6291)
    source_proper_genre_membership_count: int = Field(ge=0)
    source_proper_genre_artist_mbid_count: int = Field(ge=0)
    proper_genre_frontier_seed_count: int = Field(ge=0, le=6291)
    proper_genre_membership_count: int = Field(ge=0)
    proper_genre_artist_mbid_count: int = Field(ge=0)
    placed_seed_count: int = Field(ge=0, le=6291)
    unplaced_seed_count: int = Field(ge=0, le=6291)
    placed_frontier_seed_count: int = Field(ge=0, le=6291)
    unplaced_frontier_seed_count: int = Field(ge=0, le=6291)
    claims_sha256: Sha256
    claim_sample: tuple[DirectMusicBrainzPublicationRow, ...] = Field(max_length=64)
    policy_blockers: tuple[str, ...] = Field(min_length=1)
    output_sha256: Sha256

    @model_validator(mode="after")
    def _replays_counts_and_policy(self) -> DirectMusicBrainzPublicationGate:
        if len(self.claim_sample) > self.proper_genre_membership_count:
            raise ValueError("publication sample exceeds the counted claim set")
        if len(set(self.claim_sample)) != len(self.claim_sample):
            raise ValueError("publication sample rows must be unique")
        if self.placed_seed_count + self.unplaced_seed_count != self.retained_seed_count:
            raise ValueError("placed and unplaced seed counts do not cover retained seeds")
        if self.proper_genre_frontier_seed_count > self.source_proper_genre_frontier_seed_count:
            raise ValueError("identity-safe frontier cannot exceed source proper-genre frontier")
        if self.proper_genre_membership_count > self.source_proper_genre_membership_count:
            raise ValueError("identity-safe claims cannot exceed source proper-genre claims")
        if (
            self.placed_frontier_seed_count + self.unplaced_frontier_seed_count
            != self.proper_genre_frontier_seed_count
        ):
            raise ValueError("placed-map overlap does not cover the direct frontier")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


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
    raw_evidence_ref = row.get("evidence_ref")
    evidence_ref = raw_evidence_ref if isinstance(raw_evidence_ref, str) else ""
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
                evidence_ref,
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


def build_direct_genre_membership_candidate(
    *, layout_path: Path, frontier_path: Path, reconciliation_path: Path, seed_target_path: Path
) -> DirectGenreMembershipCandidate:
    """Project only identity-safe proper-genre rows into a local membership candidate.

    The projection requires exact UUID artist IDs and the seed's own reconciled
    MusicBrainz genre ID. It intentionally does not consult aliases, labels,
    releases, peers, layouts beyond the frozen unplaced scope, or history.
    """
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
    scoped = {seed_id for seed_id in unplaced if not _is_currently_served(frontier_by_id[seed_id])}
    rows: dict[tuple[str, str, str, str], DirectGenreMembershipCandidateRow] = {}
    for raw_row in _iter_evidence(seed_target_path):
        evidence = _parse_evidence(raw_row)
        if evidence is None or evidence.seed_id not in scoped:
            continue
        if not (
            _is_strict_direct_row(evidence, facet="genre")
            and evidence.target_namespace == "musicbrainz_genre_id"
            and evidence.target_identity in canonical_genres_by_id[evidence.seed_id]
            and evidence.evidence_ref
        ):
            continue
        row = DirectGenreMembershipCandidateRow(
            seed_id=evidence.seed_id,
            artist_mbid=evidence.artist_mbid,
            musicbrainz_genre_id=evidence.target_identity,
            source_record_id=evidence.source_record_id,
            source_record_sha256=evidence.source_record_sha256,
        )
        key = (row.seed_id, row.artist_mbid, row.musicbrainz_genre_id, row.source_record_sha256)
        existing = rows.setdefault(key, row)
        if existing != row:
            raise ValueError("membership key maps to conflicting immutable provenance")
    memberships = tuple(rows[key] for key in sorted(rows))
    base = DirectGenreMembershipCandidate(
        candidate_revision="musicbrainz-direct-proper-genre-membership-candidate-v1",
        publication_scope="local_only_candidate",
        historical_assignments_read=False,
        alias_or_name_only_bridge_used=False,
        public_export_authorized=False,
        layout_byte_sha256=_sha256(layout_path),
        layout_output_sha256=_required_sha256(layout, label="layout"),
        frontier_byte_sha256=_sha256(frontier_path),
        frontier_output_sha256=_required_sha256(frontier, label="frontier"),
        reconciliation_byte_sha256=_sha256(reconciliation_path),
        reconciliation_output_sha256=_required_sha256(reconciliation, label="reconciliation"),
        seed_target_byte_sha256=_sha256(seed_target_path),
        seed_target_output_sha256=_streamed_output_sha256(seed_target_path, label="seed target"),
        memberships=memberships,
        membership_count=len(memberships),
        seed_count=len({row.seed_id for row in memberships}),
        artist_mbid_count=len({row.artist_mbid for row in memberships}),
        source_record_count=len({row.source_record_sha256 for row in memberships}),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": direct_genre_membership_candidate_sha256(base)})


def direct_genre_membership_candidate_sha256(candidate: DirectGenreMembershipCandidate) -> str:
    """Return a deterministic candidate checksum excluding its self hash."""
    payload = candidate.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_direct_genre_membership_candidate(candidate: DirectGenreMembershipCandidate) -> None:
    """Reject mutated provenance or any attempt to present this candidate as public."""
    # Re-enter the strict serialized boundary so ``model_copy`` cannot bypass
    # frozen Pydantic validation before the replay hash is checked.
    DirectGenreMembershipCandidate.model_validate_json(candidate.model_dump_json())
    if candidate.output_sha256 != direct_genre_membership_candidate_sha256(candidate):
        raise ValueError("direct genre membership candidate output hash does not replay")


def direct_musicbrainz_publication_gate_sha256(candidate: DirectMusicBrainzPublicationGate) -> str:
    """Return the self-hash for a policy gate without trusting its stored value."""
    payload = candidate.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_direct_musicbrainz_publication_gate(
    *, layout_path: Path, reconciliation_path: Path, seed_target_path: Path
) -> DirectMusicBrainzPublicationGate:
    """Build a fail-closed all-seed direct-genre publication review payload.

    Every accepted row is independently reconstructable from the pinned
    seed-target object: an exact UUID artist record, a literal genre facet,
    matching spelling, and a genre identifier already attached to that stable
    seed by reconciliation.  The method neither reads nor represents tags,
    releases, peer evidence, inferred rows, or history.
    """
    layout = _json_object(layout_path, label="layout")
    reconciliation = _json_object(reconciliation_path, label="reconciliation")
    canonical_genres_by_id = _canonical_genre_identities(reconciliation)
    if len(canonical_genres_by_id) != _RETAINED_SEED_COUNT:
        raise ValueError("reconciliation must contain the retained 6,291-seed universe")
    unplaced = _unplaced_ids(layout)
    if not unplaced <= set(canonical_genres_by_id):
        raise ValueError("layout unplaced IDs must be present in reconciliation")
    placed = set(canonical_genres_by_id) - set(unplaced)
    claim_digest = hashlib.sha256()
    source_membership_count = 0
    source_frontier: set[str] = set()
    source_artists: set[str] = set()
    source_claim_keys: set[bytes] = set()
    membership_count = 0
    frontier: set[str] = set()
    artists: set[str] = set()
    sample: list[DirectMusicBrainzPublicationRow] = []
    for raw_row in _iter_evidence(seed_target_path):
        evidence = _parse_evidence(raw_row)
        if evidence is None or evidence.seed_id not in canonical_genres_by_id:
            continue
        if not (
            _is_strict_direct_row(evidence, facet="genre")
            and evidence.target_namespace == "musicbrainz_genre_id"
            and evidence.evidence_ref
        ):
            continue
        row = DirectMusicBrainzPublicationRow(
            seed_id=evidence.seed_id,
            artist_mbid=evidence.artist_mbid,
            musicbrainz_genre_id=evidence.target_identity,
            source_record_id=evidence.source_record_id,
            source_record_sha256=evidence.source_record_sha256,
            source_evidence_ref=evidence.evidence_ref,
        )
        row_bytes = _canonical_json(row.model_dump(mode="json"))
        row_key = hashlib.sha256(row_bytes).digest()
        if row_key in source_claim_keys:
            continue
        source_claim_keys.add(row_key)
        source_membership_count += 1
        source_frontier.add(evidence.seed_id)
        source_artists.add(evidence.artist_mbid)
        if evidence.target_identity not in canonical_genres_by_id[evidence.seed_id]:
            continue
        # The pinned source object's byte hash makes its streaming order part
        # of the receipt.  This avoids retaining hundreds of thousands of rows
        # merely to sort them before hashing.
        claim_digest.update(row_bytes)
        claim_digest.update(b"\n")
        membership_count += 1
        frontier.add(row.seed_id)
        artists.add(row.artist_mbid)
        if len(sample) < _CLAIM_SAMPLE_LIMIT:
            sample.append(row)
    base = DirectMusicBrainzPublicationGate(
        revision="musicbrainz-direct-publication-gate-v1",
        publication_scope="local_only_policy_gate",
        public_export_authorized=False,
        source_adapter_export_allowed=False,
        historical_assignments_read=False,
        release_or_peer_rows_used=0,
        tag_rows_used=0,
        seed_target_byte_sha256=_sha256(seed_target_path),
        seed_target_output_sha256=_streamed_output_sha256(seed_target_path, label="seed target"),
        reconciliation_byte_sha256=_sha256(reconciliation_path),
        reconciliation_output_sha256=_required_sha256(reconciliation, label="reconciliation"),
        layout_byte_sha256=_sha256(layout_path),
        layout_output_sha256=_required_sha256(layout, label="layout"),
        retained_seed_count=_RETAINED_SEED_COUNT,
        source_proper_genre_frontier_seed_count=len(source_frontier),
        source_proper_genre_membership_count=source_membership_count,
        source_proper_genre_artist_mbid_count=len(source_artists),
        proper_genre_frontier_seed_count=len(frontier),
        proper_genre_membership_count=membership_count,
        proper_genre_artist_mbid_count=len(artists),
        placed_seed_count=len(placed),
        unplaced_seed_count=len(unplaced),
        placed_frontier_seed_count=len(frontier & placed),
        unplaced_frontier_seed_count=len(frontier & set(unplaced)),
        claims_sha256=claim_digest.hexdigest(),
        claim_sample=tuple(sample),
        policy_blockers=(
            (
                "The MusicBrainz model adapter declares its retained source artifact "
                "export_allowed=false."
            ),
            "This gate does not itself authorize public export or alter release policy.",
            "Source rows without a reconciled MusicBrainz genre ID remain excluded.",
            "A separate source-license and release-policy decision must approve any promotion.",
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(
        update={"output_sha256": direct_musicbrainz_publication_gate_sha256(base)}
    )


def verify_direct_musicbrainz_publication_gate(candidate: DirectMusicBrainzPublicationGate) -> None:
    """Verify self-consistency and retain the no-public-export policy boundary."""
    DirectMusicBrainzPublicationGate.model_validate_json(candidate.model_dump_json())
    if candidate.output_sha256 != direct_musicbrainz_publication_gate_sha256(candidate):
        raise ValueError("direct MusicBrainz publication gate output hash does not replay")


def verify_direct_musicbrainz_publication_gate_from_inputs(
    candidate: DirectMusicBrainzPublicationGate,
    *,
    layout_path: Path,
    reconciliation_path: Path,
    seed_target_path: Path,
) -> None:
    """Rebuild a detached receipt from its local source objects and compare it exactly.

    The small receipt is portable, but verification is intentionally not: it
    requires the pinned retained source archive and therefore cannot imply
    fresh-checkout custody or publication readiness.
    """
    verify_direct_musicbrainz_publication_gate(candidate)
    rebuilt = build_direct_musicbrainz_publication_gate(
        layout_path=layout_path,
        reconciliation_path=reconciliation_path,
        seed_target_path=seed_target_path,
    )
    if rebuilt != candidate:
        raise ValueError("direct MusicBrainz publication gate does not replay from inputs")


def report_json(report: DirectGenreFrontierReport) -> str:
    """Serialize a canonical, newline-terminated checkpoint payload."""
    return json.dumps(asdict(report), sort_keys=True, separators=(",", ":")) + "\n"
