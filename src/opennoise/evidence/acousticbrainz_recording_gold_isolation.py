"""Fail-closed source-isolation gate for AcousticBrainz recording-label evaluation.

The AcousticBrainz Genre Dataset has exact recording identifiers, but its
Discogs, Last.fm, and Tagtraum annotations may have later entered MusicBrainz
tags. This gate has no retained verifier for a prediction artifact and its
construction receipt, so it permanently abstains. It never opens TSV label
columns or converts a recording label into an artist label.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.analysis.acousticbrainz_discogs_overlap import AcousticBrainzDiscogsOverlapReport
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from pathlib import Path


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class AcousticBrainzRecordingGoldIsolationAudit(FrozenModel):
    """A no-label receipt stating whether a source-isolated recording evaluation can begin."""

    revision: Literal["acousticbrainz-recording-gold-isolation-audit-v1"] = (
        "acousticbrainz-recording-gold-isolation-audit-v1"
    )
    overlap_receipt_sha256: Sha256
    acousticbrainz_source_sha256: Sha256
    catalog_sha256: Sha256
    exact_recording_overlap_count: int = Field(ge=0)
    exact_release_group_consistent_one_primary_artist_overlap_count: int = Field(ge=0)
    label_columns_read: Literal[False] = False
    prediction_lineage_verification: Literal["unavailable"] = "unavailable"
    decision: Literal["abstain_missing_verified_prediction_lineage"] = (
        "abstain_missing_verified_prediction_lineage"
    )
    source_isolated_recording_evaluation_ready: Literal[False] = False
    independent_artist_genre_gold_ready: Literal[False] = False
    reasons: tuple[str, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_honest_decision(self) -> AcousticBrainzRecordingGoldIsolationAudit:
        """Keep the recording-only, positive-only boundary explicit."""
        if (
            self.exact_release_group_consistent_one_primary_artist_overlap_count
            > self.exact_recording_overlap_count
        ):
            raise ValueError("one-primary-artist overlap exceeds exact recording overlap")
        if self.output_sha256 != _audit_sha256(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("isolation-audit output hash does not replay")
        return self


def _audit_sha256(value: object) -> Sha256:
    payload = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_acousticbrainz_recording_gold_isolation(
    overlap: AcousticBrainzDiscogsOverlapReport,
    *,
    overlap_receipt_sha256: Sha256,
) -> AcousticBrainzRecordingGoldIsolationAudit:
    """Produce a no-go receipt until a real prediction-lineage verifier is implemented."""
    if overlap.label_columns_read:
        raise ValueError("the overlap receipt must not have read AcousticBrainz label columns")
    reasons = (
        (
            "no verifier is retained to hash a prediction file and inspect its construction "
            "receipt; evaluation abstains before labels"
        ),
        (
            "MusicBrainz artist tags, recording genres, release-group genres, and historical "
            "Every Noise remain forbidden"
        ),
        (
            "a caller declaration is not custody evidence; a future verifier must prove "
            "excluded inputs are absent"
        ),
        "the cohort is recording-level and positive-only, never independent artist--genre gold",
    )
    fields = {
        "revision": "acousticbrainz-recording-gold-isolation-audit-v1",
        "overlap_receipt_sha256": overlap_receipt_sha256,
        "acousticbrainz_source_sha256": overlap.source_file_sha256,
        "catalog_sha256": overlap.catalog_file_sha256,
        "exact_recording_overlap_count": overlap.exact_recording_mbid_overlap_count,
        "exact_release_group_consistent_one_primary_artist_overlap_count": (
            overlap.one_primary_artist_release_group_consistent_overlap_count
        ),
        "label_columns_read": False,
        "prediction_lineage_verification": "unavailable",
        "decision": "abstain_missing_verified_prediction_lineage",
        "source_isolated_recording_evaluation_ready": False,
        "independent_artist_genre_gold_ready": False,
        "reasons": reasons,
    }
    return AcousticBrainzRecordingGoldIsolationAudit.model_validate(
        {**fields, "output_sha256": _audit_sha256(fields)}
    )


def load_overlap_receipt(path: Path) -> tuple[AcousticBrainzDiscogsOverlapReport, Sha256]:
    """Parse the counts-only receipt and bind its exact bytes before evaluating lineage."""
    report = AcousticBrainzDiscogsOverlapReport.model_validate_json(path.read_bytes())
    return report, _sha256_file(path)
