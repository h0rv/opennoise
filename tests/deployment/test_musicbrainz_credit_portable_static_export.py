"""Exercise the local portable-catalog handoff into the strict static export gate."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from opennoise.deployment.musicbrainz_credit_portable_release import (
    PortableMusicBrainzCreditReleaseReceipt,
)
from opennoise.deployment.musicbrainz_credit_portable_static_export import (
    export_portable_musicbrainz_credit_static_metadata,
)
from opennoise.deployment.musicbrainz_credit_static_export import sha256_file
from opennoise.storage import LocalObjectStore
from tests.deployment.test_musicbrainz_credit_static_export import (
    _ARTIST_MBID,
    _CreditFixture,
)

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "config/releases/musicbrainz-credit-catalog-v1/portable-release-receipt.json"
STORE = ROOT / "data/release/musicbrainz-credit-catalog-v1/objects"


class PortableMusicBrainzCreditStaticExportTests(unittest.TestCase):
    """Custody restores a candidate, but it cannot bypass the static export approval."""

    def test_restored_catalog_replays_the_existing_strict_gate(self) -> None:
        receipt = PortableMusicBrainzCreditReleaseReceipt.model_validate_json(RECEIPT.read_bytes())
        with _CreditFixture(self, "allow") as fixture:

            def restore(
                unused_receipt: PortableMusicBrainzCreditReleaseReceipt,
                *,
                store: LocalObjectStore,
                candidate_database: Path,
                candidate_report: Path,
            ) -> SimpleNamespace:
                del unused_receipt, store
                shutil.copyfile(fixture.candidate, candidate_database)
                shutil.copyfile(fixture.report, candidate_report)
                return SimpleNamespace()

            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_portable_static_export"
                    ".restore_portable_musicbrainz_credit_catalog",
                    side_effect=restore,
                ),
                patch(
                    "opennoise.deployment.musicbrainz_credit_static_export._parse_discovery",
                    return_value=SimpleNamespace(
                        availability="ready",
                        source=SimpleNamespace(
                            observation_kind="direct_source_claim",
                            database_sha256=sha256_file(fixture.public),
                        ),
                        artists=(
                            SimpleNamespace(
                                artist_id="artist:1",
                                musicbrainz_url=f"https://musicbrainz.org/artist/{_ARTIST_MBID}",
                            ),
                        ),
                    ),
                ),
            ):
                payload, digest = export_portable_musicbrainz_credit_static_metadata(
                    receipt,
                    store=LocalObjectStore(STORE),
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=fixture.approval,
                    output=fixture.output,
                )
            self.assertEqual((len(payload.rows), payload.release_row_count), (1, 1))
            self.assertEqual(digest, sha256_file(fixture.output))
