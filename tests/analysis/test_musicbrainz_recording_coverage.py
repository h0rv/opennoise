import hashlib
import tempfile
from pathlib import Path
from uuid import UUID

import httpx

from opennoise.analysis.listenbrainz_recording_co_listen import (
    RecordingCoListenExperimentSettings,
    RecordingIdCohortArtifact,
    RecordingMbidCoverage,
)
from opennoise.analysis.musicbrainz_recording_coverage import (
    MusicBrainzRecordingCoverageError,
    RecordingLookupSettings,
    _write_response_object,
    measure_exact_recording_coverage,
    measure_exact_recording_release_coverage,
    replay_exact_recording_coverage,
    replay_exact_recording_release_coverage,
)
from tests._test_client import PollingIsolatedAsyncioTestCase

RECORDING_A = UUID("413c57fc-a41d-4bbe-bc3d-4f86e9e97598")
RECORDING_B = UUID("6e2c5a33-39ca-4df6-8200-311a6a17a9a0")
ARTIST_A = "8d6b734e-0e5d-4f49-8972-6d33c82f0a3b"
ARTIST_B = "f6dcfd47-fd03-4cf1-b5d0-2d6da5914b7c"
COHORT_FILE_SHA256 = "b" * 64


def _cohort() -> RecordingIdCohortArtifact:
    ordered = tuple(sorted((RECORDING_A, RECORDING_B), key=str))
    return RecordingIdCohortArtifact(
        source_artifact_sha256="a" * 64,
        source_artifact_byte_size=1,
        settings=RecordingCoListenExperimentSettings(),
        coverage=RecordingMbidCoverage(
            raw_records_seen=2,
            valid_listen_records=2,
            malformed_listen_records=0,
            mapping_recording_mbid_present=0,
            mapping_recording_mbid_valid_uuid=0,
            additional_recording_mbid_present=2,
            additional_recording_mbid_valid_uuid=2,
            selected_resolved_mapping_recording_count=0,
            selected_submitted_additional_recording_count=2,
        ),
        recording_ids=ordered,
        recording_id_set_sha256=hashlib.sha256("\n".join(map(str, ordered)).encode()).hexdigest(),
    )


class MusicBrainzRecordingCoverageTests(PollingIsolatedAsyncioTestCase):
    async def test_measures_exact_lookup_and_multi_artist_credit_without_names(self) -> None:
        requests: list[httpx.Request] = []

        async def no_sleep(_: float) -> None:
            return None

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            recording_id = request.url.path.rsplit("/", 1)[-1]
            artists = [ARTIST_A] if recording_id == str(RECORDING_A) else [ARTIST_A, ARTIST_B]
            return httpx.Response(
                200,
                json={
                    "id": recording_id,
                    "title": "must not be retained",
                    "artist-credit": [
                        {"name": "must not be retained", "artist": {"id": artist}}
                        for artist in artists
                    ],
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            cache_directory = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_exact_recording_coverage(
                    _cohort(),
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    cohort_artifact_file_sha256=COHORT_FILE_SHA256,
                    settings=RecordingLookupSettings(maximum_recordings=2),
                    response_cache_directory=cache_directory,
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )
            replay = replay_exact_recording_coverage(artifact, cache_directory)

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].url.params["inc"], "artist-credits")
        self.assertEqual(artifact.coverage.successful_exact_lookup_count, 2)
        self.assertEqual(artifact.coverage.artist_credit_present_count, 2)
        self.assertEqual(artifact.coverage.multiple_artist_credit_count, 1)
        self.assertEqual(artifact.coverage.unique_artist_id_count, 2)
        self.assertNotIn("must not be retained", artifact.model_dump_json())
        self.assertEqual(replay, artifact)

    async def test_records_a_nonexact_response_as_an_abstention(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": str(RECORDING_B), "artist-credit": []})

        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_exact_recording_coverage(
                    _cohort(),
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    cohort_artifact_file_sha256=COHORT_FILE_SHA256,
                    settings=RecordingLookupSettings(maximum_recordings=1),
                    response_cache_directory=Path(directory),
                )

        self.assertEqual(artifact.coverage.successful_exact_lookup_count, 0)
        self.assertEqual(artifact.lookups[0].outcome, "nonexact_response")

    async def test_records_not_found_without_erasing_another_exact_lookup(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = request.url.path.rsplit("/", 1)[-1]
            if recording_id == str(RECORDING_A):
                return httpx.Response(404, content=b"not found")
            return httpx.Response(200, json={"id": recording_id, "artist-credit": []})

        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_exact_recording_coverage(
                    _cohort(),
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    cohort_artifact_file_sha256=COHORT_FILE_SHA256,
                    settings=RecordingLookupSettings(maximum_recordings=2),
                    response_cache_directory=Path(directory),
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )

        self.assertEqual(artifact.coverage.successful_exact_lookup_count, 1)
        self.assertEqual(artifact.lookups[0].outcome, "http_not_found")
        self.assertEqual(artifact.lookups[0].http_status_code, 404)

    def test_rejects_an_oversized_response_before_writing_a_custody_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_directory = Path(directory)
            with self.assertRaises(MusicBrainzRecordingCoverageError):
                _write_response_object(cache_directory, b"x" * (512 * 1024 + 1))

            self.assertEqual(tuple(cache_directory.iterdir()), ())

    async def test_rejects_a_tampered_custody_object_during_offline_replay(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"id": recording_id, "artist-credit": []})

        with tempfile.TemporaryDirectory() as directory:
            cache_directory = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_exact_recording_coverage(
                    _cohort(),
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    cohort_artifact_file_sha256=COHORT_FILE_SHA256,
                    settings=RecordingLookupSettings(maximum_recordings=1),
                    response_cache_directory=cache_directory,
                )
            object_path = (
                cache_directory / "sha256" / f"{artifact.lookups[0].response_object.sha256}.json"
            )
            object_path.write_bytes(b"tampered")
            with self.assertRaises(MusicBrainzRecordingCoverageError):
                replay_exact_recording_coverage(artifact, cache_directory)

    async def test_rejects_an_oversized_custody_object_during_offline_replay(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"id": recording_id, "artist-credit": []})

        with tempfile.TemporaryDirectory() as directory:
            cache_directory = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_exact_recording_coverage(
                    _cohort(),
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    cohort_artifact_file_sha256=COHORT_FILE_SHA256,
                    settings=RecordingLookupSettings(maximum_recordings=1),
                    response_cache_directory=cache_directory,
                )
            object_path = (
                cache_directory / "sha256" / f"{artifact.lookups[0].response_object.sha256}.json"
            )
            object_path.write_bytes(b"x" * (512 * 1024 + 1))
            with self.assertRaises(MusicBrainzRecordingCoverageError):
                replay_exact_recording_coverage(artifact, cache_directory)

    async def test_release_receipt_replays_links_types_and_credit_ambiguity(self) -> None:
        async def no_sleep(_: float) -> None:
            return None

        async def handler(request: httpx.Request) -> httpx.Response:
            recording_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "id": recording_id,
                    "artist-credit": [{"artist": {"id": ARTIST_A}}],
                    "releases": [
                        {
                            "id": "10000000-0000-4000-8000-000000000001",
                            "artist-credit": [{"artist": {"id": ARTIST_B}}],
                            "release-group": {
                                "id": "20000000-0000-4000-8000-000000000001",
                                "primary-type": "Album",
                                "secondary-types": ["Compilation"],
                            },
                        },
                        {
                            "id": "10000000-0000-4000-8000-000000000002",
                            "artist-credit": [{"artist": {"id": ARTIST_A}}],
                            "release-group": {
                                "id": "20000000-0000-4000-8000-000000000002",
                                "primary-type": "EP",
                            },
                        },
                    ],
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            cache_directory = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                artifact = await measure_exact_recording_release_coverage(
                    _cohort(),
                    client,
                    user_agent="opennoise/0.1 (maintainer@example.org)",
                    cohort_artifact_file_sha256=COHORT_FILE_SHA256,
                    response_cache_directory=cache_directory,
                    settings=RecordingLookupSettings(maximum_recordings=1),
                    clock=lambda: 1.0,
                    sleep=no_sleep,
                )
            self.assertEqual(artifact.coverage.release_link_count, 2)
            self.assertEqual(artifact.coverage.primary_type_counts, {"Album": 1, "EP": 1})
            self.assertEqual(artifact.coverage.compilation_release_group_count, 1)
            self.assertEqual(artifact.coverage.release_artist_credit_mismatch_count, 1)
            self.assertEqual(
                replay_exact_recording_release_coverage(artifact, cache_directory), artifact
            )
            corrupted = artifact.model_copy(
                update={"coverage": artifact.coverage.model_copy(update={"release_link_count": 0})}
            )
            with self.assertRaises(MusicBrainzRecordingCoverageError):
                replay_exact_recording_release_coverage(corrupted, cache_directory)
