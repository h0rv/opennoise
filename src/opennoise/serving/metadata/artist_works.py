"""Rank exact credited music metadata with explainable, bounded diversity."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.serving.metadata.links import metadata_url

if TYPE_CHECKING:
    from pathlib import Path

_MAX_SELECTION = 100
_PROJECTION_FIELDS = {
    "revision",
    "publication_status",
    "method",
    "limitations",
    "rights",
    "artists",
}
_ARTIST_FIELDS = {"artist_mbid", "name", "recordings", "release_groups", "sample_recording_count"}
_RANKING_FIELDS = {"rank", "url", "score_components", "score", "classification"}
_SCORE_FIELDS = {
    "exact_artist_credit",
    "original_album_context",
    "nonvariant_recording",
    "dated_metadata",
    "unseen_release_context",
    "distinct_title",
}


class CreditedMusicCandidate(FrozenModel):
    """Source-backed metadata, without popularity or inherited genre assignments."""

    entity_kind: Literal["recording", "release_group"]
    entity_id: str
    title: str = Field(min_length=1)
    credited_artist_mbids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    release_group_ids: tuple[str, ...] = ()
    first_release_date: str = ""
    original_album: bool = False
    variant: bool = False

    @model_validator(mode="after")
    def validate_link(self) -> CreditedMusicCandidate:
        """Require kind-specific catalog identity rather than arbitrary external URLs."""
        if metadata_url(self.entity_kind, self.entity_id) is None:
            raise ValueError("candidate requires a safe exact metadata identifier")
        return self


class RankedArtistWork(FrozenModel):
    """One deterministic selection with all ranking components exposed."""

    candidate: CreditedMusicCandidate
    rank: int = Field(gt=0)
    url: str
    score_components: dict[str, int]
    score: int
    classification: Literal["credited_metadata_example"] = "credited_metadata_example"


def rank_artist_works(
    artist_mbid: str,
    candidates: tuple[CreditedMusicCandidate, ...],
    *,
    limit: int = 6,
) -> tuple[RankedArtistWork, ...]:
    """Select per-artist examples, rewarding album context and unseen releases.

    This ranks the supplied bounded sample, not the artist's complete discography.
    MusicBrainz search relevance and popularity are deliberately absent. A release
    credit must be proven independently; recording credits cannot establish it.
    """
    if not 1 <= limit <= _MAX_SELECTION:
        raise ValueError("selection limit must be between 1 and 100")
    remaining: dict[str, CreditedMusicCandidate] = {}
    for candidate in candidates:
        if artist_mbid not in candidate.credited_artist_mbids:
            continue
        prior = remaining.get(candidate.entity_id)
        if prior is None:
            remaining[candidate.entity_id] = candidate
            continue
        if (
            prior.entity_kind != candidate.entity_kind
            or prior.title != candidate.title
            or set(prior.credited_artist_mbids) != set(candidate.credited_artist_mbids)
            or prior.variant != candidate.variant
        ):
            raise ValueError("conflicting duplicate metadata identity")
        dates = sorted(
            date for date in (prior.first_release_date, candidate.first_release_date) if date
        )
        remaining[candidate.entity_id] = prior.model_copy(
            update={
                "credited_artist_mbids": tuple(sorted(set(prior.credited_artist_mbids))),
                "evidence_refs": tuple(sorted(set(prior.evidence_refs + candidate.evidence_refs))),
                "release_group_ids": tuple(
                    sorted(set(prior.release_group_ids + candidate.release_group_ids))
                ),
                "first_release_date": dates[0] if dates else "",
                "original_album": prior.original_album or candidate.original_album,
            }
        )
    selected: list[RankedArtistWork] = []
    seen_groups: set[str] = set()
    seen_titles: set[str] = set()
    while remaining and len(selected) < limit:
        scored: list[tuple[int, str, CreditedMusicCandidate, dict[str, int]]] = []
        for candidate in remaining.values():
            groups = set(candidate.release_group_ids)
            components = {
                "exact_artist_credit": 100,
                "original_album_context": 30 if candidate.original_album else 0,
                "nonvariant_recording": 15 if not candidate.variant else 0,
                "dated_metadata": 5 if candidate.first_release_date else 0,
                "unseen_release_context": 20 if groups - seen_groups else 0,
                "distinct_title": 10 if candidate.title.casefold() not in seen_titles else -50,
            }
            scored.append((sum(components.values()), candidate.entity_id, candidate, components))
        score, _, candidate, components = min(scored, key=lambda row: (-row[0], row[1]))
        url = metadata_url(candidate.entity_kind, candidate.entity_id)
        if url is None:
            raise ValueError("validated metadata candidate lost its safe URL")
        selected.append(
            RankedArtistWork(
                candidate=candidate,
                rank=len(selected) + 1,
                url=url,
                score_components=components,
                score=score,
            )
        )
        seen_groups.update(candidate.release_group_ids)
        seen_titles.add(candidate.title.casefold())
        del remaining[candidate.entity_id]
    return tuple(selected)


def _require_projected_work_fields(row: dict[str, Any], candidate_fields: set[str]) -> None:
    if set(row) - candidate_fields - _RANKING_FIELDS:
        raise ValueError("unapproved work fields in CC0 music projection")
    if "score_components" in row and (
        not isinstance(row["score_components"], dict)
        or set(row["score_components"]) - _SCORE_FIELDS
    ):
        raise ValueError("unapproved ranking fields in CC0 music projection")


def verify_projected_artist_work_examples(projection: Path, receipt: Path) -> dict[str, Any]:
    """Verify projected bytes, identities and permitted fields, without native source replay."""
    body = projection.read_bytes()
    proof = json.loads(receipt.read_text())
    if (
        proof.get("license") != "MusicBrainz core metadata CC0 1.0"
        or proof.get("license_url") != "https://musicbrainz.org/doc/About/Data_License"
        or hashlib.sha256(body).hexdigest() != proof.get("projection_sha256")
    ):
        raise ValueError("projected MusicBrainz receipt does not verify")
    artifact = json.loads(body)
    if artifact.get("revision") != "credited-music-examples-v1":
        raise ValueError("unknown credited music projection revision")
    if set(artifact) - _PROJECTION_FIELDS:
        raise ValueError("unapproved fields in CC0 music projection")
    fields = set(CreditedMusicCandidate.model_fields)
    seen: set[str] = set()
    for artist in artifact["artists"]:
        if set(artist) - _ARTIST_FIELDS:
            raise ValueError("unapproved artist fields in CC0 music projection")
        artist_id = artist["artist_mbid"]
        if artist_id in seen or metadata_url("artist", f"musicbrainz:artist:{artist_id}") is None:
            raise ValueError("invalid or repeated exact artist identity")
        seen.add(artist_id)
        for kind in ("recordings", "release_groups"):
            for row in artist[kind]:
                _require_projected_work_fields(row, fields)
                candidate = CreditedMusicCandidate.model_validate_json(
                    json.dumps({key: value for key, value in row.items() if key in fields})
                )
                expected_kind = "recording" if kind == "recordings" else "release_group"
                if (
                    candidate.entity_kind != expected_kind
                    or artist_id not in candidate.credited_artist_mbids
                    or row["url"] != metadata_url(candidate.entity_kind, candidate.entity_id)
                ):
                    raise ValueError("projected music row identity or safe URL differs")
    return artifact
