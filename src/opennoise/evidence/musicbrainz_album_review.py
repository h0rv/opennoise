"""Build a small source-bound local review packet for MusicBrainz Album contexts."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common.hashing import sha256_json
from opennoise.ingest.musicbrainz.release_group_album_examples import (
    ReleaseGroupAlbumExamplesReport,
    verify_release_group_album_examples,
)
from opennoise.models import FrozenModel

_SELECTION: Final = (
    ("rock", "broad"),
    ("jazz", "broad"),
    ("folk", "broad"),
    ("metal", "broad"),
    ("hyperpop", "micro"),
    ("ambient", "micro"),
    ("drone", "micro"),
    ("shoegaze", "micro"),
    ("grindcore", "micro"),
    ("afrobeat", "geographic_cultural"),
    ("bossa nova", "geographic_cultural"),
    ("cumbia", "geographic_cultural"),
    ("k pop", "geographic_cultural"),
    ("reggaeton", "geographic_cultural"),
    ("salsa", "geographic_cultural"),
    ("pop", "ambiguous"),
    ("rap", "ambiguous"),
    ("hip hop", "ambiguous"),
    ("soundtrack", "ambiguous"),
    ("chanson", "ambiguous"),
)
_SOURCE_SEED_COUNT: Final = 6_291
_SOURCE_POPULATED_SEED_COUNT: Final = 893


class AlbumReviewCandidate(FrozenModel):
    """One candidate album with its unaltered native MusicBrainz source context."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    title: str = Field(min_length=1)
    first_release_date: str | None
    credited_artist_mbids: tuple[str, ...]
    source_record_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    genre_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    genre_name: str = Field(min_length=1)
    positive_native_vote_count: int = Field(gt=0)
    source_role: Literal["native_proper_genre_observation"] = "native_proper_genre_observation"
    credit_role: Literal["release_group_credit_context"] = "release_group_credit_context"
    reviewer_fit_judgment: Literal["fits", "does_not_fit", "uncertain"] | None = None
    reviewer_notes: str | None = None


class AlbumSeedReview(FrozenModel):
    """A seed question, including abstention when the candidate report has no row."""

    seed_source_item_id: str = Field(min_length=1)
    normalized_seed_name: str = Field(min_length=1)
    reconciliation_disposition: str = Field(min_length=1)
    sampling_stratum: Literal["broad", "micro", "geographic_cultural", "ambiguous"]
    candidates: tuple[AlbumReviewCandidate, ...]
    reviewer_seed_judgment: Literal["supported", "unsupported", "uncertain"] | None = None
    reviewer_notes: str | None = None

    @model_validator(mode="after")
    def judgment_state_matches_candidates(self) -> AlbumSeedReview:
        """Keep a no-candidate seed as an abstention."""
        if not self.candidates and self.reviewer_seed_judgment is not None:
            raise ValueError("a seed with no candidates must remain an abstention")
        return self


class MusicBrainzAlbumReviewPacket(FrozenModel):
    """Small immutable local review packet; source votes are evidence, not labels."""

    revision: Literal["musicbrainz-album-context-review-v2"] = "musicbrainz-album-context-review-v2"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    representative_album_claimed: Literal[False] = False
    quintessential_album_claimed: Literal[False] = False
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_seed_count: int = Field(ge=1)
    source_seed_rows_with_examples: int = Field(ge=0)
    source_seed_example_limit: int = Field(ge=1, le=20)
    seed_reviews: tuple[AlbumSeedReview, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def output_hash_replays(self) -> MusicBrainzAlbumReviewPacket:
        """Require unique seed questions and a replayable source evidence digest."""
        if len({row.normalized_seed_name for row in self.seed_reviews}) != len(self.seed_reviews):
            raise ValueError("review packet repeats a seed")
        if self.output_sha256 != review_source_sha256(self):
            raise ValueError("review packet output hash does not replay")
        return self


def review_source_sha256(packet: MusicBrainzAlbumReviewPacket) -> str:
    """Hash immutable source evidence while allowing a reviewer overlay in the packet."""
    payload = packet.model_dump(mode="json", exclude={"output_sha256"})
    reviews = payload["seed_reviews"]
    for review in reviews:
        review.pop("reviewer_seed_judgment", None)
        review.pop("reviewer_notes", None)
        for candidate in review["candidates"]:
            candidate.pop("reviewer_fit_judgment", None)
            candidate.pop("reviewer_notes", None)
    return sha256_json(payload)


def build_musicbrainz_album_review_packet(
    report: ReleaseGroupAlbumExamplesReport,
    *,
    source_report_sha256: str,
    reconciliation: dict[str, tuple[str, str]],
) -> MusicBrainzAlbumReviewPacket:
    """Assemble fixed broad, micro, and ambiguous seed strata from verified local evidence."""
    verify_release_group_album_examples(report)
    if (
        len(report.seed_rows) != _SOURCE_POPULATED_SEED_COUNT
        or report.seed_count != _SOURCE_SEED_COUNT
    ):
        raise ValueError("source report no longer matches the recorded seed coverage")
    report_by_name = {row.normalized_seed_name: row for row in report.seed_rows}
    reviews: list[AlbumSeedReview] = []
    for name, stratum in _SELECTION:
        identity = reconciliation.get(name)
        if identity is None:
            raise ValueError(f"seed identity is missing from reconciliation: {name}")
        seed_id, disposition = identity
        if stratum == "ambiguous" and disposition != "ambiguous":
            raise ValueError(f"selected ambiguous seed is no longer ambiguous: {name}")
        source_seed = report_by_name.get(name)
        if source_seed is None and name not in {"rap", "soundtrack", "chanson"}:
            raise ValueError(f"selected seed has no retained examples: {name}")
        if source_seed is not None and not source_seed.examples:
            raise ValueError(f"selected report row has no examples: {name}")
        if source_seed is not None and len(source_seed.examples) > report.examples_per_seed_limit:
            raise ValueError(f"selected examples exceed source cap: {name}")
        candidates = tuple(
            AlbumReviewCandidate(
                release_group_mbid=item.release_group_mbid,
                title=item.title,
                first_release_date=item.first_release_date,
                credited_artist_mbids=tuple(
                    artist.artist_mbid for artist in item.credited_artist_mbids
                ),
                source_record_content_sha256=item.record_content_sha256,
                genre_mbid=item.genre_mbid,
                genre_name=item.genre_name,
                positive_native_vote_count=item.genre_vote_count,
            )
            for item in (() if source_seed is None else source_seed.examples[:2])
        )
        reviews.append(
            AlbumSeedReview(
                seed_source_item_id=seed_id,
                normalized_seed_name=name,
                reconciliation_disposition=disposition,
                sampling_stratum=stratum,
                candidates=candidates,
            )
        )
    fields = {
        "revision": "musicbrainz-album-context-review-v2",
        "local_only": True,
        "export_allowed": False,
        "serving_allowed": False,
        "model_input_allowed": False,
        "artist_membership_asserted": False,
        "representative_album_claimed": False,
        "quintessential_album_claimed": False,
        "source_report_sha256": source_report_sha256,
        "source_archive_sha256": report.source_archive_sha256,
        "source_cache_receipt_sha256": report.source_cache_receipt_sha256,
        "seed_reconciliation_sha256": report.seed_reconciliation_sha256,
        "source_seed_count": report.seed_count,
        "source_seed_rows_with_examples": len(report.seed_rows),
        "source_seed_example_limit": report.examples_per_seed_limit,
        "seed_reviews": tuple(
            row.model_dump(
                exclude={
                    "reviewer_seed_judgment": True,
                    "reviewer_notes": True,
                    "candidates": {"__all__": {"reviewer_fit_judgment", "reviewer_notes"}},
                }
            )
            for row in reviews
        ),
    }
    return MusicBrainzAlbumReviewPacket.model_validate(
        {**fields, "output_sha256": sha256_json(fields)}
    )
