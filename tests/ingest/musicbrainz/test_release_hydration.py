import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

import httpx

from opennoise.db import Database
from opennoise.ingest.musicbrainz.release_hydration import (
    HydrationSettings,
    MusicBrainzHydrationError,
    MusicBrainzReleaseTrackHydrationAdapter,
    materialize_hydration_catalog,
    select_representative_seeds,
    write_hydration_artifact,
)
from opennoise.serving.metadata.representatives import (
    MetadataRepresentativeArtifact,
    MetadataRepresentativeItem,
    RepresentativeRunProvenance,
)
from opennoise.storage import LocalObjectStore
from tests._test_client import PollingIsolatedAsyncioTestCase

RELEASE_GROUP_ID = "10000000-0000-4000-8000-000000000001"
RELEASE_ID = "30000000-0000-4000-8000-000000000001"
TRACK_ID = "40000000-0000-4000-8000-000000000001"
RECORDING_ID = "50000000-0000-4000-8000-000000000001"
SECOND_RELEASE_GROUP_ID = "10000000-0000-4000-8000-000000000002"


def _representatives() -> MetadataRepresentativeArtifact:
    return MetadataRepresentativeArtifact(
        run=RepresentativeRunProvenance(
            model_run_id=1,
            output_sha256="a" * 64,
            input_provenance_ids=(1,),
        ),
        items=(
            MetadataRepresentativeItem(
                genre_id="musicbrainz:genre:20000000-0000-4000-8000-000000000001",
                entity_kind="release_group",
                entity_id=f"musicbrainz:release-group:{RELEASE_GROUP_ID}",
                display_name="Synthetic Album",
                rank=1,
                direct_evidence_value=1.0,
                source_count=1,
                evidence_refs=("musicbrainz:fixture",),
            ),
        ),
    )


def _release_payload() -> dict[str, object]:
    return {
        "id": RELEASE_ID,
        "title": "Synthetic Album",
        "release-group": {"id": RELEASE_GROUP_ID, "title": "Synthetic Album"},
        "status": "Official",
        "packaging": "Jewel Case",
        "country": "US",
        "date": "2001-02-03",
        "cover-art-archive": {"artwork": True},
        "genres": [{"id": "20000000-0000-4000-8000-000000000001", "name": "Synthetic"}],
        "media": [
            {
                "position": 1,
                "format": "CD",
                "track-count": 1,
                "tracks": [
                    {
                        "id": TRACK_ID,
                        "position": 1,
                        "number": "1",
                        "title": "Synthetic Track",
                        "length": 123456,
                        "recording": {
                            "id": RECORDING_ID,
                            "title": "Synthetic Track",
                            "length": 123456,
                        },
                    }
                ],
            }
        ],
    }


class MusicBrainzReleaseHydrationTests(PollingIsolatedAsyncioTestCase):
    def test_default_settings_expand_two_selected_examples_per_genre(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                HydrationSettings(cache_directory=Path(directory) / "cache").max_seeds_per_genre,
                2,
            )

    def test_selects_multiple_existing_examples_per_genre_without_reordering(self) -> None:
        artifact = MetadataRepresentativeArtifact(
            run=RepresentativeRunProvenance(
                model_run_id=1,
                output_sha256="a" * 64,
                input_provenance_ids=(1,),
            ),
            items=(
                MetadataRepresentativeItem(
                    genre_id="musicbrainz:genre:20000000-0000-4000-8000-000000000001",
                    entity_kind="release_group",
                    entity_id=f"musicbrainz:release-group:{SECOND_RELEASE_GROUP_ID}",
                    display_name="Second Example",
                    rank=2,
                    direct_evidence_value=1.0,
                    source_count=1,
                    evidence_refs=("musicbrainz:fixture",),
                ),
                _representatives().items[0],
            ),
        )

        selected = select_representative_seeds(artifact, max_genres=1, max_seeds_per_genre=2)

        self.assertEqual(
            tuple(item.entity_id for item in selected),
            (
                f"musicbrainz:release-group:{RELEASE_GROUP_ID}",
                f"musicbrainz:release-group:{SECOND_RELEASE_GROUP_ID}",
            ),
        )
        self.assertEqual(tuple(item.classification for item in selected), ("metadata_example",) * 2)

    async def test_hydrates_ordered_core_metadata_and_replays_cache_offline(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith(RELEASE_GROUP_ID):
                return httpx.Response(
                    200,
                    json={
                        "id": RELEASE_GROUP_ID,
                        "releases": [
                            {"id": RELEASE_ID, "title": "Synthetic Album", "date": "2001-02-03"}
                        ],
                    },
                )
            if request.url.path.endswith(RELEASE_ID):
                return httpx.Response(200, json=_release_payload())
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = HydrationSettings(cache_directory=root / "cache", max_genres=1)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = MusicBrainzReleaseTrackHydrationAdapter(
                    client,
                    settings,
                    user_agent="opennoise/0.1 (maintainer@example.test)",
                    sleep=lambda _: _no_sleep(),
                )
                artifact = await adapter.hydrate(_representatives(), source_sha256="b" * 64)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0].url.params["inc"], "releases")
            self.assertEqual(requests[1].url.params["inc"], "release-groups+recordings")
            self.assertEqual(artifact.releases[0].release_id, UUID(RELEASE_ID))
            self.assertEqual(artifact.releases[0].media[0].tracks[0].duration_ms, 123456)
            rendered = artifact.model_dump_json()
            self.assertNotIn("cover-art", rendered)
            self.assertNotIn('"genres":', rendered)
            self.assertNotIn('"preview":', rendered)
            self.assertIn("track_metadata_not_playable_media", rendered)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as offline_client:
                offline = MusicBrainzReleaseTrackHydrationAdapter(
                    offline_client,
                    HydrationSettings(cache_directory=root / "cache", max_genres=1, offline=True),
                    user_agent="opennoise/0.1 (maintainer@example.test)",
                )
                replay = await offline.hydrate(_representatives(), source_sha256="b" * 64)
            self.assertEqual(replay, artifact)
            receipt = write_hydration_artifact(
                artifact,
                output=root / "out.json",
                store=LocalObjectStore(root / "objects"),
            )
            self.assertEqual(
                (receipt.release_count, receipt.medium_count, receipt.track_count), (1, 1, 1)
            )
            self.assertTrue((root / "objects" / receipt.artifact.key.value).is_file())
            catalog = materialize_hydration_catalog(
                artifact,
                database_path=root / "catalog.sqlite",
                artifact_sha256=receipt.artifact.sha256,
            )
            replay_catalog = materialize_hydration_catalog(
                artifact,
                database_path=root / "catalog.sqlite",
                artifact_sha256=receipt.artifact.sha256,
            )
            self.assertEqual(
                (catalog.releases, catalog.media, catalog.tracks, catalog.recordings), (1, 1, 1, 1)
            )
            self.assertEqual(
                (
                    replay_catalog.releases,
                    replay_catalog.media,
                    replay_catalog.tracks,
                    replay_catalog.recordings,
                ),
                (0, 0, 0, 0),
            )
            detail = Database(root / "catalog.sqlite").hydrated_release_metadata_by_source(
                "release_group", RELEASE_GROUP_ID
            )
            self.assertIsNotNone(detail)
            if detail is None:
                self.fail("hydrated release lookup unexpectedly returned no data")
            self.assertEqual(detail.title, "Synthetic Album")
            self.assertEqual(detail.media[0].tracks[0].number, "1")
            self.assertEqual(detail.media[0].tracks[0].length_ms, 123456)
            self.assertIsNone(
                Database(root / "catalog.sqlite").hydrated_release_metadata_by_source(
                    "recording", "00000000-0000-4000-8000-000000000000"
                )
            )

    async def test_offline_cache_miss_fails_without_network(self) -> None:
        async def unexpected_request(_: httpx.Request) -> httpx.Response:
            """Make an accidental offline network request fail as a valid HTTP response."""
            return httpx.Response(599)

        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(unexpected_request)
            ) as client:
                adapter = MusicBrainzReleaseTrackHydrationAdapter(
                    client,
                    HydrationSettings(cache_directory=Path(directory) / "cache", offline=True),
                    user_agent="opennoise/0.1 (maintainer@example.test)",
                )
                with self.assertRaisesRegex(MusicBrainzHydrationError, "offline replay cache miss"):
                    await adapter.hydrate(_representatives(), source_sha256="b" * 64)

    async def test_failed_endpoint_is_negative_cached_for_identical_offline_abstention(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        async def failed_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(404)

        async def unexpected_request(_: httpx.Request) -> httpx.Response:
            self.fail("offline replay made an upstream request")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = HydrationSettings(
                cache_directory=root / "cache", max_genres=1, max_attempts=1
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(failed_handler)) as client:
                adapter = MusicBrainzReleaseTrackHydrationAdapter(
                    client,
                    settings,
                    user_agent="opennoise/0.1 (maintainer@example.test)",
                )
                online = await adapter.hydrate_batch(_representatives(), source_sha256="b" * 64)
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(online.failures), 1)
            self.assertIn("invalid MusicBrainz metadata response", online.failures[0].message)
            cache_entry = next((root / "cache").glob("*.json"))
            cached = json.loads(cache_entry.read_bytes())
            self.assertEqual(cached["record_kind"], "failure")
            self.assertEqual(cached["failure_kind"], "invalid_metadata_response")
            self.assertNotIn("payload", cached)

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(unexpected_request)
            ) as client:
                offline_adapter = MusicBrainzReleaseTrackHydrationAdapter(
                    client,
                    settings.model_copy(update={"offline": True}),
                    user_agent="opennoise/0.1 (maintainer@example.test)",
                )
                offline = await offline_adapter.hydrate_batch(
                    _representatives(), source_sha256="b" * 64
                )
            self.assertEqual(offline.artifact, online.artifact)
            self.assertEqual(offline.failures, online.failures)
            self.assertEqual(offline_adapter.upstream_request_count, 0)


async def _no_sleep() -> None:
    return None


if __name__ == "__main__":
    unittest.main()
