"""Evaluation-only comparison for a sealed direct MusicBrainz seed candidate.

The direct custody object is fully verified before the historical artifact is
opened. Historical Every Noise/H3 data is an observed-positive reference only:
a zero membership count and a missing node are abstentions, never negatives or
precision evidence. Since nearly every retained seed has an H3 membership,
this is an identity/coverage smoke test, not a quality measurement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)

_REVISION: Final = "musicbrainz-direct-seed-h3-positive-only-holdout-v1"
_HISTORICAL_PREFIX: Final = "enao-legacy:"

if TYPE_CHECKING:
    from pathlib import Path


class DirectGenreSeedHoldoutError(ValueError):
    """An input would make the evaluation identity-unsafe or non-positive-only."""


@dataclass(frozen=True, slots=True)
class _HistoricalCoverage:
    observed_positive: frozenset[str]
    zero_membership: frozenset[str]
    known_seed_ids: frozenset[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(path: Path, *, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise DirectGenreSeedHoldoutError(f"{label} must be a JSON object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise DirectGenreSeedHoldoutError(f"{label} keys must be strings")
        result[key] = item
    return result


def _public_seed_ids(path: Path) -> frozenset[str]:
    payload = _object(path, label="public static discovery")
    rows = payload.get("genres")
    if not isinstance(rows, list):
        raise DirectGenreSeedHoldoutError("public static discovery requires genres")
    result: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(seed_id := row.get("node_id"), str):
            raise DirectGenreSeedHoldoutError("every public genre requires string node_id")
        if not seed_id or seed_id in result:
            raise DirectGenreSeedHoldoutError("public genre node_ids must be nonempty and unique")
        result.add(seed_id)
    return frozenset(result)


def _historical_coverage(path: Path) -> _HistoricalCoverage:
    payload = _object(path, label="historical semantic artifact")
    rows = payload.get("nodes")
    if not isinstance(rows, list):
        raise DirectGenreSeedHoldoutError("historical semantic artifact requires nodes")
    observed_positive: set[str] = set()
    zero_membership: set[str] = set()
    known: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise DirectGenreSeedHoldoutError("every historical node must be an object")
        genre_id, membership_count = row.get("genre_id"), row.get("membership_count")
        if not isinstance(genre_id, str) or not genre_id.startswith(_HISTORICAL_PREFIX):
            raise DirectGenreSeedHoldoutError(
                "historical genre_id must use the retained seed prefix"
            )
        if (
            not isinstance(membership_count, int)
            or isinstance(membership_count, bool)
            or membership_count < 0
        ):
            raise DirectGenreSeedHoldoutError(
                "historical membership_count must be a nonnegative integer"
            )
        seed_id = genre_id.removeprefix(_HISTORICAL_PREFIX)
        if not seed_id or seed_id in known:
            raise DirectGenreSeedHoldoutError("historical seed IDs must be nonempty and unique")
        known.add(seed_id)
        if membership_count > 0:
            observed_positive.add(seed_id)
        else:
            zero_membership.add(seed_id)
    return _HistoricalCoverage(
        frozenset(observed_positive), frozenset(zero_membership), frozenset(known)
    )


def _custodied_seed_ids(receipt_path: Path, object_store: Path) -> tuple[frozenset[str], str]:
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(receipt_path.read_bytes())
    seeds = {
        claim.seed_id
        for claim in iter_verified_portable_direct_proper_genre_claims(
            receipt, object_store=object_store
        )
    }
    if len(seeds) != receipt.seed_count:
        raise DirectGenreSeedHoldoutError("custodied direct seed count does not replay")
    return frozenset(seeds), receipt.output_sha256


def build_direct_genre_seed_holdout(
    *,
    custody_receipt_path: Path,
    custody_object_store: Path,
    public_static_discovery_path: Path,
    historical_semantic_path: Path,
) -> dict[str, object]:
    """Run an identity smoke test after the direct custody object is verified."""
    # The construction-derived custody object is verified before historical data is opened.
    direct_seed_ids, receipt_output_sha256 = _custodied_seed_ids(
        custody_receipt_path, custody_object_store
    )
    public_seed_ids = _public_seed_ids(public_static_discovery_path)
    historical = _historical_coverage(historical_semantic_path)

    shared = direct_seed_ids & public_seed_ids
    novel = direct_seed_ids - public_seed_ids
    public_only = public_seed_ids - direct_seed_ids
    observed_positive = novel & historical.observed_positive
    zero_membership = novel & historical.zero_membership
    unknown = novel - historical.known_seed_ids
    if observed_positive | zero_membership | unknown != novel:
        raise DirectGenreSeedHoldoutError("historical status must partition novel direct seeds")
    report: dict[str, object] = {
        "revision": _REVISION,
        "evaluation_scope": "verified_direct_custody_vs_retained_h3_identity_smoke",
        "historical_used_for_construction_or_tuning": False,
        "historical_absence_is_negative": False,
        "precision_or_negative_metrics_computed": False,
        "release_claims_computed": False,
        "identity_join": "exact retained seed_id; historical enao-legacy:<seed_id> only",
        "inputs": {
            "custody_receipt_byte_sha256": _sha256(custody_receipt_path),
            "custody_receipt_output_sha256": receipt_output_sha256,
            "public_static_discovery_byte_sha256": _sha256(public_static_discovery_path),
            "historical_semantic_byte_sha256": _sha256(historical_semantic_path),
        },
        "seed_sets": {
            "direct_reconciliation_safe_seed_count": len(direct_seed_ids),
            "current_public_seed_count": len(public_seed_ids),
            "shared_direct_and_public_seed_count": len(shared),
            "direct_outside_current_public_seed_count": len(novel),
            "current_public_only_seed_count": len(public_only),
        },
        "novel_direct_historical_identity_smoke": {
            "observed_positive_seed_count": len(observed_positive),
            "zero_membership_abstention_count": len(zero_membership),
            "unknown_historical_identity_abstention_count": len(unknown),
            "quality_inference_supported": False,
            "interpretation_note": (
                "This only checks exact retained seed identity and H3 positive presence. H3 has "
                "observed memberships for nearly the complete retained seed universe, so this "
                "result cannot establish usefulness or correctness of direct artist-genre claims."
            ),
        },
    }
    report["output_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return report
