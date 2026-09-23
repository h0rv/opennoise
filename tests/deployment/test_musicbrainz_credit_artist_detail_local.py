"""Exercise the isolated local MusicBrainz credit artist-detail renderer."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from opennoise.deployment.musicbrainz_credit_artist_detail_local import (
    LocalMusicBrainzCreditArtistDetailError,
    export_local_musicbrainz_credit_artist_detail_payload,
)
from opennoise.deployment.musicbrainz_credit_static_export import (
    MusicBrainzCreditMemberPayload,
    MusicBrainzCreditMetadataRow,
    MusicBrainzCreditStaticMetadataPayload,
    export_musicbrainz_credit_static_metadata,
    sha256_file,
)
from opennoise.deployment.public_static_discovery_v2 import (
    PublicStaticDiscoveryV2Artist,
    PublicStaticDiscoveryV2Coverage,
    PublicStaticDiscoveryV2Genre,
    PublicStaticDiscoveryV2InputChain,
    PublicStaticDiscoveryV2Membership,
    PublicStaticDiscoveryV2Payload,
)
from opennoise.deployment.static_discovery import (
    StaticDiscoveryEvidencePayload,
    StaticDiscoverySourceCount,
    StaticDiscoverySourcePayload,
)
from tests.deployment.test_musicbrainz_credit_static_export import _CreditFixture

_ARTIST_MBID = "10000000-0000-4000-8000-000000000001"
_OTHER_MBID = "10000000-0000-4000-8000-000000000002"
_RELEASE_MBID = "20000000-0000-4000-8000-000000000001"


class LocalMusicBrainzCreditArtistDetailTests(unittest.TestCase):
    """The local render is source-bound and remains outside public export paths."""

    def test_renders_only_the_exact_visible_artist_with_source_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            local_root = root / ".cache"
            local_root.mkdir()
            output = local_root / "artist-detail.json"
            discovery.write_bytes(b"source-bound-discovery")
            metadata.write_text(
                self._metadata(discovery.read_bytes()).model_dump_json(), encoding="utf-8"
            )
            with patch(
                "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                return_value=self._discovery(),
            ):
                payload, _ = export_local_musicbrainz_credit_artist_detail_payload(
                    credit_metadata=metadata,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output=output,
                )
            rendered = output.read_text(encoding="utf-8")
            self.assertEqual(payload.credit_row_count, 1)
            self.assertEqual(
                payload.publication_status, "local_candidate_only_not_authorized_for_publication"
            )
            self.assertIn("MusicBrainz credit metadata", rendered)
            self.assertIn("Title & <safe>", rendered)
            self.assertIn("local_candidate_only_not_authorized_for_publication", rendered)
            self.assertNotIn("genre", rendered.casefold())
            self.assertNotIn("rank", rendered.casefold())

    def test_renders_a_fixture_asset_after_the_existing_strict_gate(self) -> None:
        """The renderer consumes a gated artifact; it does not invent approval input."""
        with _CreditFixture(self, "allow") as fixture:
            metadata = fixture.candidate.parent / "credit-metadata.json"
            local_root = fixture.candidate.parent / ".cache"
            local_root.mkdir()
            rendered = local_root / "artist-detail.json"
            gate_discovery = SimpleNamespace(
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
            )
            with patch(
                "opennoise.deployment.musicbrainz_credit_static_export._parse_discovery",
                return_value=gate_discovery,
            ):
                export_musicbrainz_credit_static_metadata(
                    candidate_database=fixture.candidate,
                    candidate_report=fixture.report,
                    public_database=fixture.public,
                    static_discovery=fixture.discovery,
                    approval=fixture.approval,
                    output=metadata,
                )
            with patch(
                "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                return_value=self._discovery(public_database_sha256=sha256_file(fixture.public)),
            ):
                payload, _ = export_local_musicbrainz_credit_artist_detail_payload(
                    credit_metadata=metadata,
                    static_discovery=fixture.discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output=rendered,
                )
            self.assertEqual(payload.credit_row_count, 1)
            self.assertEqual(payload.rows[0].title, "Release")

    def test_rejects_a_row_that_only_matches_the_static_artist_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            local_root = root / ".cache"
            local_root.mkdir()
            discovery.write_bytes(b"source-bound-discovery")
            payload = self._metadata(discovery.read_bytes())
            metadata.write_text(
                payload.model_copy(
                    update={
                        "rows": (
                            payload.rows[0].model_copy(
                                update={"musicbrainz_artist_id": _OTHER_MBID}
                            ),
                        )
                    }
                ).model_dump_json(),
                encoding="utf-8",
            )
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                    return_value=self._discovery(),
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError, "exact static MusicBrainz-ID join"
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_payload(
                    credit_metadata=metadata,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output=local_root / "artist-detail.json",
                )

    def test_rejects_an_output_outside_the_explicit_cache_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            local_root = root / ".cache"
            local_root.mkdir()
            discovery.write_bytes(b"source-bound-discovery")
            metadata.write_text(
                self._metadata(discovery.read_bytes()).model_dump_json(), encoding="utf-8"
            )
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                    return_value=self._discovery(),
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError, "stay below local .cache"
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_payload(
                    credit_metadata=metadata,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output=root / "dist" / "artist-detail.json",
                )

    def test_rejects_metadata_bound_to_different_discovery_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            local_root = root / ".cache"
            local_root.mkdir()
            discovery.write_bytes(b"current-discovery")
            metadata.write_text(
                self._metadata(b"older-discovery").model_dump_json(), encoding="utf-8"
            )
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                    return_value=self._discovery(),
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError, "different static discovery bytes"
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_payload(
                    credit_metadata=metadata,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output=local_root / "artist-detail.json",
                )

    def test_rejects_a_cache_directory_under_repository_dist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            discovery = root / "discovery.json"
            metadata = root / "credit-metadata.json"
            dist_root = root / "dist"
            local_root = dist_root / ".cache"
            local_root.mkdir(parents=True)
            discovery.write_bytes(b"source-bound-discovery")
            metadata.write_text(
                self._metadata(discovery.read_bytes()).model_dump_json(), encoding="utf-8"
            )
            with (
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._parse_discovery",
                    return_value=self._discovery(),
                ),
                patch(
                    "opennoise.deployment.musicbrainz_credit_artist_detail_local._REPOSITORY_DIST",
                    dist_root,
                ),
                self.assertRaisesRegex(
                    LocalMusicBrainzCreditArtistDetailError, "inside this repository's dist"
                ),
            ):
                export_local_musicbrainz_credit_artist_detail_payload(
                    credit_metadata=metadata,
                    static_discovery=discovery,
                    static_artist_id="artist:1",
                    local_root=local_root,
                    output=local_root / "artist-detail.json",
                )

    @staticmethod
    def _metadata(discovery_bytes: bytes) -> MusicBrainzCreditStaticMetadataPayload:
        return MusicBrainzCreditStaticMetadataPayload(
            candidate_database_sha256="b" * 64,
            public_database_sha256="a" * 64,
            static_discovery_sha256=hashlib.sha256(discovery_bytes).hexdigest(),
            visible_artist_count=1,
            artists_with_credit_rows_count=1,
            release_row_count=1,
            recording_row_count=0,
            rows=(
                MusicBrainzCreditMetadataRow(
                    static_artist_id="artist:1",
                    musicbrainz_artist_id=_ARTIST_MBID,
                    entity_kind="release",
                    musicbrainz_entity_id=_RELEASE_MBID,
                    title="Title & <safe>",
                    credit_record_fingerprint="c" * 64,
                    credit_artifact_sha256="d" * 64,
                    credit_members=(
                        MusicBrainzCreditMemberPayload(
                            position=0,
                            musicbrainz_artist_id=_ARTIST_MBID,
                            credited_name="First",
                            join_phrase=" & ",
                        ),
                        MusicBrainzCreditMemberPayload(
                            position=1,
                            musicbrainz_artist_id=_OTHER_MBID,
                            credited_name="Second",
                            join_phrase="",
                        ),
                    ),
                ),
            ),
        )

    @staticmethod
    def _discovery(*, public_database_sha256: str = "a" * 64) -> PublicStaticDiscoveryV2Payload:
        evidence = StaticDiscoveryEvidencePayload(
            evidence_id=1,
            source_key="source",
            source_record_id="record",
            method_key="method",
            method_version="v1",
            provenance_id=1,
        )
        membership = PublicStaticDiscoveryV2Membership(
            node_id="item1",
            catalog_genre_id=1,
            catalog_genre_name="Direct genre",
            binding="exact_casefolded_label",
            evidence=(evidence,),
        )
        return PublicStaticDiscoveryV2Payload(
            input_chain=PublicStaticDiscoveryV2InputChain(
                merged_public_direct_discovery_sha256="e" * 64,
                base_static_discovery_sha256="f" * 64,
                sealed_qid_additive_static_discovery_sha256="0" * 64,
                sealed_qid_direct_bridge_sha256="1" * 64,
                public_database_sha256=public_database_sha256,
                semantic_atlas_sha256="2" * 64,
            ),
            source=StaticDiscoverySourcePayload(
                database_sha256=public_database_sha256,
                database_byte_count=1,
                observation_kind="direct_source_claim",
                sources=(StaticDiscoverySourceCount(source_key="source", observation_count=1),),
            ),
            coverage=PublicStaticDiscoveryV2Coverage(
                placed_map_node_count=1,
                exact_label_bound_catalog_genre_count=1,
                one_to_one_qid_position_bound_catalog_genre_count=0,
                exact_label_genres_with_direct_artists=1,
                one_to_one_qid_position_genres_with_direct_artists=0,
                genres_with_direct_artists=1,
                artists_with_direct_map_genres=1,
                direct_catalog_observation_count=1,
                bound_direct_observation_count=1,
                artist_relation_method="shared_direct_catalog_genre",
                unserved_colisten_reason="active_display_policy_denies_colisten",
            ),
            genres=(
                PublicStaticDiscoveryV2Genre(
                    node_id="item1",
                    catalog_genre_id=1,
                    catalog_genre_name="Direct genre",
                    binding="exact_casefolded_label",
                    artist_ids=("artist:1",),
                ),
            ),
            artists=(
                PublicStaticDiscoveryV2Artist(
                    artist_id="artist:1",
                    name="Exact artist",
                    musicbrainz_url=f"https://musicbrainz.org/artist/{_ARTIST_MBID}",
                    memberships=(membership,),
                    shared_genre_artists=(),
                ),
            ),
            output_sha256="3" * 64,
        )
