"""Build a local artist-detail credit asset from the portable catalog custody receipt."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.deployment.musicbrainz_credit_portable_release import (
    PortableMusicBrainzCreditReleaseReceipt,
    restore_portable_musicbrainz_credit_catalog,
)
from opennoise.deployment.musicbrainz_credit_static_export import (
    CreditMetadataPublicationApproval,
    MusicBrainzCreditStaticMetadataPayload,
    export_musicbrainz_credit_static_metadata,
)

if TYPE_CHECKING:
    from opennoise.storage import ObjectStore


def export_portable_musicbrainz_credit_static_metadata(  # noqa: PLR0913 - explicit gate boundary.
    receipt: PortableMusicBrainzCreditReleaseReceipt,
    *,
    store: ObjectStore,
    public_database: Path,
    static_discovery: Path,
    approval: CreditMetadataPublicationApproval,
    output: Path,
) -> tuple[MusicBrainzCreditStaticMetadataPayload, str]:
    """Restore the custodied catalog into temporary storage, then replay the strict gate.

    The public database, discovery asset, and approval remain explicit caller
    inputs. This function neither substitutes local cache state nor permits
    custody-only scope to stand in for release approval.
    """
    with tempfile.TemporaryDirectory(prefix="musicbrainz-credit-static-") as directory:
        temporary = Path(directory)
        candidate_database = temporary / "catalog.sqlite"
        candidate_report = temporary / "catalog-report.json"
        restore_portable_musicbrainz_credit_catalog(
            receipt,
            store=store,
            candidate_database=candidate_database,
            candidate_report=candidate_report,
        )
        return export_musicbrainz_credit_static_metadata(
            candidate_database=candidate_database,
            candidate_report=candidate_report,
            public_database=public_database,
            static_discovery=static_discovery,
            approval=approval,
            output=output,
        )
