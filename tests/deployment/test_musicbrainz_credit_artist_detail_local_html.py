"""Exercise the local, no-JavaScript MusicBrainz credit HTML preview."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.deployment.musicbrainz_credit_artist_detail_local import (
    LocalMusicBrainzCreditArtistDetailError,
)
from opennoise.deployment.musicbrainz_credit_artist_detail_local_html import (
    export_local_musicbrainz_credit_artist_detail_html_preview,
)
from opennoise.deployment.musicbrainz_credit_static_export import CreditMetadataPublicationApproval
from tests.deployment.test_musicbrainz_credit_artist_detail_local import (
    LocalMusicBrainzCreditArtistDetailTests,
)


class LocalMusicBrainzCreditArtistDetailHtmlTests(unittest.TestCase):
    """The preview has no public-output path and shows only verified credit rows."""

    def test_renders_escaped_source_bound_release_without_javascript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            approval = root / "approval.json"
            local_root = root / ".cache"
            local_root.mkdir()
            discovery.write_bytes(b"source-bound-discovery")
            metadata.write_text(
                LocalMusicBrainzCreditArtistDetailTests._metadata(  # noqa: SLF001
                    discovery.read_bytes()
                ).model_dump_json(),
                encoding="utf-8",
            )
            approval.write_text(self._approval(discovery.read_bytes()), encoding="utf-8")
            with patch(
                "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                return_value=LocalMusicBrainzCreditArtistDetailTests._discovery(),  # noqa: SLF001
            ):
                preview = export_local_musicbrainz_credit_artist_detail_html_preview(
                    credit_metadata=metadata,
                    approval=approval,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output_directory=local_root / "artist-detail-preview",
                )
            html = preview.html_path.read_text(encoding="utf-8")
            self.assertEqual(preview.payload.credit_row_count, 1)
            self.assertTrue(preview.payload_path.is_file())
            self.assertIn("MusicBrainz credit metadata", html)
            self.assertIn(
                'data-publication-status="local_candidate_only_not_authorized_for_publication"',
                html,
            )
            self.assertIn("Title: Title &amp; &lt;safe&gt;", html)
            self.assertIn("First</span> &amp; <span", html)
            self.assertIn('data-entity-kind="release"', html)
            self.assertNotIn("<script", html.casefold())
            self.assertNotIn("genre", html.casefold())
            self.assertNotIn("rank", html.casefold())

    def test_rejects_identity_mismatch_before_creating_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            approval = root / "approval.json"
            local_root = root / ".cache"
            local_root.mkdir()
            discovery.write_bytes(b"source-bound-discovery")
            payload = LocalMusicBrainzCreditArtistDetailTests._metadata(  # noqa: SLF001
                discovery.read_bytes()
            )
            metadata.write_text(
                payload.model_copy(
                    update={
                        "rows": (
                            payload.rows[0].model_copy(
                                update={
                                    "musicbrainz_artist_id": "10000000-0000-4000-8000-000000000002"
                                }
                            ),
                        )
                    }
                ).model_dump_json(),
                encoding="utf-8",
            )
            approval.write_text(self._approval(discovery.read_bytes()), encoding="utf-8")
            output_directory = local_root / "artist-detail-preview"
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                    return_value=LocalMusicBrainzCreditArtistDetailTests._discovery(),  # noqa: SLF001
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError, "exact static MusicBrainz-ID join"
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_html_preview(
                    credit_metadata=metadata,
                    approval=approval,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output_directory=output_directory,
                )
            self.assertFalse(output_directory.exists())

    def test_rejects_an_approval_not_bound_to_static_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            approval = root / "approval.json"
            local_root = root / ".cache"
            local_root.mkdir()
            discovery.write_bytes(b"source-bound-discovery")
            metadata.write_text(
                LocalMusicBrainzCreditArtistDetailTests._metadata(  # noqa: SLF001
                    discovery.read_bytes()
                ).model_dump_json(),
                encoding="utf-8",
            )
            approval.write_text(
                CreditMetadataPublicationApproval.model_validate_json(
                    self._approval(discovery.read_bytes())
                )
                .model_copy(update={"static_discovery_sha256": "0" * 64})
                .model_dump_json(),
                encoding="utf-8",
            )
            output_directory = local_root / "artist-detail-preview"
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                    return_value=LocalMusicBrainzCreditArtistDetailTests._discovery(),  # noqa: SLF001
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError,
                    "approval does not bind local preview inputs",
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_html_preview(
                    credit_metadata=metadata,
                    approval=approval,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output_directory=output_directory,
                )
            self.assertFalse(output_directory.exists())

    def test_rejects_a_preview_directory_outside_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_root = root / ".cache"
            local_root.mkdir()
            with self.assertRaisesRegex(
                LocalMusicBrainzCreditArtistDetailError, "stay below local .cache"
            ):
                export_local_musicbrainz_credit_artist_detail_html_preview(
                    credit_metadata=root / "unused-metadata.json",
                    approval=root / "unused-approval.json",
                    static_discovery=root / "unused-discovery.json",
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output_directory=root / "dist" / "artist-detail-preview",
                )

    def test_rejects_a_local_cache_root_inside_repository_dist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_root = root / "dist" / ".cache"
            local_root.mkdir(parents=True)
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local_html._REPOSITORY_DIST",
                    root / "dist",
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError,
                    "inside this repository's dist",
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_html_preview(
                    credit_metadata=root / "unused-metadata.json",
                    approval=root / "unused-approval.json",
                    static_discovery=root / "unused-discovery.json",
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output_directory=local_root / "artist-detail-preview",
                )

    @staticmethod
    def _approval(discovery_bytes: bytes) -> str:
        return CreditMetadataPublicationApproval(
            decision="approved",
            candidate_database_sha256="b" * 64,
            candidate_report_sha256="c" * 64,
            public_database_sha256="a" * 64,
            static_discovery_sha256=hashlib.sha256(discovery_bytes).hexdigest(),
            credit_artifact_sha256="d" * 64,
            approved_policy_key="fixture-policy",
        ).model_dump_json()
