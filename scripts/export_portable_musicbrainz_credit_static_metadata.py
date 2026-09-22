"""Locally build one approval-bound artist-detail asset from portable credit custody."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.deployment.musicbrainz_credit_portable_release import (
    PortableMusicBrainzCreditReleaseReceipt,
)
from opennoise.deployment.musicbrainz_credit_portable_static_export import (
    export_portable_musicbrainz_credit_static_metadata,
)
from opennoise.deployment.musicbrainz_credit_static_export import (
    CreditMetadataPublicationApproval,
)
from opennoise.storage import LocalObjectStore


def main() -> int:
    """Restore only tracked credit custody; public gate inputs are always explicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credit-receipt", required=True, type=Path)
    parser.add_argument("--credit-object-store", required=True, type=Path)
    parser.add_argument("--public-database", required=True, type=Path)
    parser.add_argument("--static-discovery", required=True, type=Path)
    parser.add_argument("--approval", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = PortableMusicBrainzCreditReleaseReceipt.model_validate_json(
        arguments.credit_receipt.read_bytes()
    )
    approval = CreditMetadataPublicationApproval.model_validate_json(
        arguments.approval.read_bytes()
    )
    _, digest = export_portable_musicbrainz_credit_static_metadata(
        receipt,
        store=LocalObjectStore(arguments.credit_object_store),
        public_database=arguments.public_database,
        static_discovery=arguments.static_discovery,
        approval=approval,
        output=arguments.output,
    )
    print(digest)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
