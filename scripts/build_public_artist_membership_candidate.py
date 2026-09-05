"""Build and custody a public artist-membership candidate from sealed inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.public_artist_membership import (
    ApprovedPublicMembershipInput,
    IndependentPublicGoldSet,
    PromotionPolicy,
    PublicArtistMembershipSourcePolicy,
    build_public_artist_membership_candidate_from_seed_artifact,
    evaluate_public_artist_membership_promotion,
    write_public_artist_membership_candidate,
)
from musix.public_artist_membership_adapter import (
    CertifiedPublicMembershipAdapterPolicy,
    CertifiedPublicMembershipAdapterReceipt,
    verify_certified_public_membership_receipt,
)
from musix.storage import LocalObjectStore


def _approved_input(path: Path) -> ApprovedPublicMembershipInput:
    """Parse rows whose hash binds the certified database, not this JSON wrapper."""
    return ApprovedPublicMembershipInput.model_validate_json(path.read_bytes())


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-artifact", type=Path, required=True)
    parser.add_argument("--approved-input", type=Path, required=True)
    parser.add_argument("--adapter-receipt", type=Path, required=True)
    parser.add_argument("--certified-database", type=Path, required=True)
    parser.add_argument("--adapter-policy", type=Path, required=True)
    parser.add_argument("--source-policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--promotion-policy", type=Path, required=True)
    parser.add_argument("--promotion-report", type=Path, required=True)
    parser.add_argument("--independent-gold", type=Path)
    parser.add_argument("--require-promotion", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Build the candidate, custody exact bytes, and report promotion eligibility."""
    arguments = _arguments()
    approved_input = _approved_input(arguments.approved_input)
    adapter_policy = CertifiedPublicMembershipAdapterPolicy.model_validate_json(
        arguments.adapter_policy.read_bytes()
    )
    adapter_receipt = CertifiedPublicMembershipAdapterReceipt.model_validate_json(
        arguments.adapter_receipt.read_bytes()
    )
    verify_certified_public_membership_receipt(
        approved_input, adapter_receipt, arguments.certified_database, adapter_policy
    )
    source_policy = PublicArtistMembershipSourcePolicy.model_validate_json(
        arguments.source_policy.read_bytes()
    )
    artifact = build_public_artist_membership_candidate_from_seed_artifact(
        arguments.seed_artifact, approved_input, source_policy
    )
    publication = write_public_artist_membership_candidate(
        artifact,
        output=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(publication.model_dump_json(indent=2) + "\n", encoding="utf-8")
    promotion_policy = PromotionPolicy.model_validate_json(arguments.promotion_policy.read_bytes())
    gold = (
        IndependentPublicGoldSet.model_validate_json(arguments.independent_gold.read_bytes())
        if arguments.independent_gold is not None
        else None
    )
    promotion = evaluate_public_artist_membership_promotion(artifact, promotion_policy, gold)
    arguments.promotion_report.parent.mkdir(parents=True, exist_ok=True)
    arguments.promotion_report.write_text(
        promotion.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        json.dumps(
            {
                "artifact_output_sha256": artifact.output_sha256,
                "artifact_file_sha256": publication.artifact_file_sha256,
                "promotion_eligible": promotion.promotion_eligible,
                "promotion_failures": promotion.failures,
            },
            indent=2,
        )
        + "\n"
    )
    return 1 if arguments.require_promotion and not promotion.promotion_eligible else 0


if __name__ == "__main__":
    raise SystemExit(main())
