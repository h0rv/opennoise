"""Calibrate held-source detection, never semantic membership or musical relevance.

A non-detection is an absent held-source observation, not a negative musical
label. Rates depend on the source capture and declared withholding mechanism.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# Fixed before evaluation; score and rank retain separate meaning.
SCORE_EDGES = (0.0, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
MIN_CALIBRATION_SUPPORT = 32
PRIOR_SUPPORT = 32
MAX_CALIBRATION_ROWS = 250_000
MAX_PROPOSALS = 10
CONTRACT = {
    "revision": "held-source-reobservation-calibration-v1",
    "event": "nominated_value_detected_in_held_source_component",
    "score_edges": SCORE_EDGES,
    "minimum_support": MIN_CALIBRATION_SUPPORT,
    "prior_support": PRIOR_SUPPORT,
    "semantic_membership_probability": None,
    "absence_is_semantic_negative": False,
    "public_export_authorized": False,
}


def score_bin(score: float) -> int:
    """Assign finite positive association scores to prespecified log-scale cells."""
    if not np.isfinite(score) or score <= 0:
        raise ValueError("source calibration requires finite positive scores")
    return int(np.searchsorted(SCORE_EDGES, score, side="right") - 1)


@dataclass(frozen=True)
class SourceReobservationCalibration:
    """Bin frequencies bound to one scorer, source, and withholding mechanism."""

    source_sha256: str
    scorer_sha256: str
    split_salt: str
    nominated: tuple[int, ...]
    detected: tuple[int, ...]

    def __post_init__(self) -> None:
        """Reject malformed frequency artifacts instead of guessing missing rates."""
        if (
            not self.source_sha256
            or not self.scorer_sha256
            or not self.split_salt
            or len(self.nominated) != len(SCORE_EDGES)
            or len(self.detected) != len(SCORE_EDGES)
            or any(type(n) is not int for n in (*self.nominated, *self.detected))
            or sum(self.nominated) > MAX_CALIBRATION_ROWS
            or any(
                n < 0 or d < 0 or d > n for n, d in zip(self.nominated, self.detected, strict=True)
            )
        ):
            raise ValueError("source calibration identity or count contract differs")

    @property
    def global_rate(self) -> float:
        """Return the calibration capture rate; absence is still not a genre negative."""
        return sum(self.detected) / max(1, sum(self.nominated))

    def estimate(self, score: float) -> tuple[float | None, int]:
        """Abstain in thin bins; otherwise shrink the source event rate to its prior."""
        cell = score_bin(score)
        support = self.nominated[cell]
        if support < MIN_CALIBRATION_SUPPORT:
            return None, support
        rate = (self.detected[cell] + PRIOR_SUPPORT * self.global_rate) / (support + PRIOR_SUPPORT)
        return rate, support

    def proposals(
        self,
        scored: Sequence[tuple[str, float]],
        *,
        minimum_detection_rate: float = 0.1,
    ) -> tuple[dict[str, object], ...]:
        """Gate suggestions on held-source detection, without inventing artist facts."""
        if not 0 <= minimum_detection_rate <= 1:
            raise ValueError("source detection threshold must be between zero and one")
        if len(scored) > MAX_PROPOSALS or len({value for value, _score in scored}) != len(scored):
            raise ValueError("calibrated source proposals require unique top-ten candidates")
        result: list[dict[str, object]] = []
        for value, score in scored:
            rate, support = self.estimate(score)
            if rate is None or rate < minimum_detection_rate:
                continue
            result.append(
                {
                    "value": value,
                    "raw_association_score": score,
                    "held_source_detection_rate": rate,
                    "calibration_nominations": support,
                    "role": "inferred_source_value_proposal",
                    "native_fact": False,
                    "semantic_membership_probability": None,
                    "genre_identity_validated": False,
                    "calibration_scope": "declared_source_capture_and_withholding_only",
                    "source_sha256": self.source_sha256,
                    "scorer_sha256": self.scorer_sha256,
                }
            )
        return tuple(result)


def fit_source_reobservation(
    observations: Iterable[tuple[float, bool]],
    *,
    source_sha256: str,
    scorer_sha256: str,
    split_salt: str,
) -> SourceReobservationCalibration:
    """Fit bounded source event counts after the base scorer has been frozen."""
    nominated = [0] * len(SCORE_EDGES)
    detected = [0] * len(SCORE_EDGES)
    for count, (score, event) in enumerate(observations, start=1):
        if count > MAX_CALIBRATION_ROWS:
            raise ValueError("source calibration exceeds the nomination bound")
        if not isinstance(event, bool):
            raise TypeError("source detection events must be boolean")
        cell = score_bin(score)
        nominated[cell] += 1
        detected[cell] += event
    return SourceReobservationCalibration(
        source_sha256, scorer_sha256, split_salt, tuple(nominated), tuple(detected)
    )


def calibration_to_dict(model: SourceReobservationCalibration) -> dict[str, object]:
    """Serialize counts together with the evidence-role and event contract."""
    return {**CONTRACT, **asdict(model)}


def calibration_from_dict(raw: Mapping[str, object]) -> SourceReobservationCalibration:
    """Load exact declared fields; caller verifies the enclosing file receipt."""
    from pydantic import TypeAdapter  # noqa: PLC0415 - runtime input boundary.

    if any(raw.get(key) != value for key, value in CONTRACT.items() if key != "score_edges"):
        raise ValueError("source calibration event or role contract differs")
    if tuple(TypeAdapter(list[float]).validate_python(raw.get("score_edges"))) != SCORE_EDGES:
        raise ValueError("source calibration score bin contract differs")
    counts = TypeAdapter(tuple[int, ...])
    return SourceReobservationCalibration(
        str(raw["source_sha256"]),
        str(raw["scorer_sha256"]),
        str(raw["split_salt"]),
        counts.validate_python(raw["nominated"]),
        counts.validate_python(raw["detected"]),
    )


def load_source_reobservation(
    path: str,
    *,
    expected_sha256: str,
    source_sha256: str,
    scorer_sha256: str,
) -> SourceReobservationCalibration:
    """Verify exact calibration bytes and identities before applying source rates.

    A full-source refit has a different scorer identity and cannot inherit a
    held-out fit's calibration without a separate transport evaluation.
    """
    import json  # noqa: PLC0415 - artifact input boundary.
    from pathlib import Path  # noqa: PLC0415 - artifact input boundary.

    from opennoise.common import sha256_file  # noqa: PLC0415 - artifact input boundary.

    source = Path(path)
    if sha256_file(source)[0] != expected_sha256:
        raise ValueError("source calibration file identity mismatch")
    model = calibration_from_dict(json.loads(source.read_bytes()))
    if model.source_sha256 != source_sha256 or model.scorer_sha256 != scorer_sha256:
        raise ValueError("source calibration scorer or source identity mismatch")
    return model
