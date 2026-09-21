"""Fail-closed receipt contract for a future public discovery v2 promotion.

This module deliberately has no writer, exporter, certifier, or deployment
entry point.  A later reviewed release may track a concrete receipt only after
the public v2 payload bytes and logical digest are available.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.deployment.public_static_discovery_v2 import (
    PublicStaticDiscoveryV2Error,
    PublicStaticDiscoveryV2Payload,
    public_static_discovery_v2_sha256,
    verify_public_static_discovery_v2_payload,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_SHA256_HEX_LENGTH = 64


class PublicDiscoveryPromotionError(ValueError):
    """A proposed public v2 discovery promotion does not replay exactly."""


class _PromotionFrozenModel(FrozenModel):
    """Reject unreviewed fields from this release-authority schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SealedLayoutPin(_PromotionFrozenModel):
    """The exact layout bytes and logical artifact consumed by promotion."""

    file_sha256: Sha256
    logical_sha256: Sha256


class PublicDiscoveryPromotionInputPins(_PromotionFrozenModel):
    """Every sealed input and intermediate identity required by v2."""

    sealed_layout: SealedLayoutPin
    public_database_sha256: Sha256
    base_static_discovery_sha256: Sha256
    public_qid_seed_map_sha256: Sha256
    sealed_qid_direct_bridge_selection_sha256: Sha256
    sealed_qid_direct_bridge_sha256: Sha256
    sealed_qid_additive_static_discovery_sha256: Sha256
    merged_public_direct_discovery_sha256: Sha256
    semantic_atlas_sha256: Sha256


class PublicDiscoveryV2PayloadPin(_PromotionFrozenModel):
    """Both identities of the future immutable browser asset."""

    logical_sha256: Sha256
    file_sha256: Sha256
    byte_count: int = Field(gt=0)


class PublicDiscoveryPromotionCoverage(_PromotionFrozenModel):
    """The reviewed exact-label and QID-position coverage partition."""

    exact_label_genre_count: Literal[260] = 260
    qid_position_genre_count: Literal[84] = 84
    genre_count: Literal[344] = 344
    artist_count: Literal[1126] = 1126
    bound_direct_observation_count: Literal[3859] = 3859


class PublicDiscoveryPromotionReceipt(_PromotionFrozenModel):
    """A self-hashed, typed authority for one future public v2 asset."""

    revision: Literal["public-static-discovery-v2-promotion-v1"] = (
        "public-static-discovery-v2-promotion-v1"
    )
    publication_scope: Literal["public_static_discovery_v2_only"] = (
        "public_static_discovery_v2_only"
    )
    public_discovery_revision: Literal["static-direct-discovery-v2"] = "static-direct-discovery-v2"
    historical_inputs_used: Literal[False] = False
    reconciliation_inputs_used: Literal[False] = False
    audio_inputs_used: Literal[False] = False
    input_pins: PublicDiscoveryPromotionInputPins
    public_payload: PublicDiscoveryV2PayloadPin
    coverage: PublicDiscoveryPromotionCoverage = Field(
        default_factory=PublicDiscoveryPromotionCoverage
    )
    output_sha256: Sha256

    @model_validator(mode="after")
    def _reject_placeholder_hashes(self) -> PublicDiscoveryPromotionReceipt:
        """Reject a tracked receipt that contains an all-zero pin."""
        if "0" * 64 in _sha256_values(self.model_dump(mode="json", exclude={"output_sha256"})):
            raise ValueError("promotion receipt cannot contain a placeholder SHA-256 pin")
        return self


def public_discovery_promotion_sha256(receipt: PublicDiscoveryPromotionReceipt) -> Sha256:
    """Hash a receipt independently of its self-reference."""
    return sha256_hex(canonical_json(receipt.model_dump(mode="json", exclude={"output_sha256"})))


def verify_public_discovery_promotion(
    receipt: PublicDiscoveryPromotionReceipt, payload_bytes: bytes
) -> PublicStaticDiscoveryV2Payload:
    """Parse the public asset once and require every promotion pin to replay."""
    if receipt.output_sha256 != public_discovery_promotion_sha256(receipt):
        raise PublicDiscoveryPromotionError("promotion receipt self-hash does not replay")
    if sha256_hex(payload_bytes) != receipt.public_payload.file_sha256:
        raise PublicDiscoveryPromotionError("public v2 payload file SHA-256 does not match receipt")
    if len(payload_bytes) != receipt.public_payload.byte_count:
        raise PublicDiscoveryPromotionError("public v2 payload byte count does not match receipt")
    try:
        payload = PublicStaticDiscoveryV2Payload.model_validate_json(payload_bytes)
        # The promotion receipt has no atlas bytes; the v2 verifier still
        # replays all payload-internal accounting and node reciprocity here.
        verify_public_static_discovery_v2_payload(
            payload, frozenset(genre.node_id for genre in payload.genres)
        )
    except (PublicStaticDiscoveryV2Error, ValueError) as error:
        raise PublicDiscoveryPromotionError("public v2 payload does not replay") from error
    _require_payload_matches_receipt(receipt, payload)
    return payload


def _require_payload_matches_receipt(
    receipt: PublicDiscoveryPromotionReceipt, payload: PublicStaticDiscoveryV2Payload
) -> None:
    if (
        payload.revision != receipt.public_discovery_revision
        or payload.output_sha256 != public_static_discovery_v2_sha256(payload)
        or payload.output_sha256 != receipt.public_payload.logical_sha256
    ):
        raise PublicDiscoveryPromotionError(
            "public v2 payload logical identity does not match receipt"
        )
    pins = receipt.input_pins
    chain = payload.input_chain
    if (
        chain.public_database_sha256 != pins.public_database_sha256
        or chain.base_static_discovery_sha256 != pins.base_static_discovery_sha256
        or chain.sealed_qid_additive_static_discovery_sha256
        != pins.sealed_qid_additive_static_discovery_sha256
        or chain.sealed_qid_direct_bridge_sha256 != pins.sealed_qid_direct_bridge_sha256
        or chain.merged_public_direct_discovery_sha256 != pins.merged_public_direct_discovery_sha256
        or chain.semantic_atlas_sha256 != pins.semantic_atlas_sha256
        or payload.source.database_sha256 != pins.public_database_sha256
    ):
        raise PublicDiscoveryPromotionError("public v2 payload input chain does not match receipt")
    exact_genres = sum(genre.binding == "exact_casefolded_label" for genre in payload.genres)
    qid_genres = sum(genre.binding == "one_to_one_qid_position_binding" for genre in payload.genres)
    coverage = receipt.coverage
    if (
        exact_genres != coverage.exact_label_genre_count
        or qid_genres != coverage.qid_position_genre_count
        or len(payload.genres) != coverage.genre_count
        or len(payload.artists) != coverage.artist_count
        or payload.coverage.bound_direct_observation_count
        != coverage.bound_direct_observation_count
    ):
        raise PublicDiscoveryPromotionError("public v2 payload coverage does not match receipt")


def _sha256_values(value: object) -> set[str]:
    """Collect digest-shaped JSON strings without treating ordinary text as pins."""
    if isinstance(value, dict):
        digests: set[str] = set()
        for item in value.values():
            digests.update(_sha256_values(item))
        return digests
    if isinstance(value, list):
        digests = set()
        for item in value:
            digests.update(_sha256_values(item))
        return digests
    if (
        isinstance(value, str)
        and len(value) == _SHA256_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    ):
        return {value}
    return set()
