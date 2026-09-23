import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from opennoise.ingest.musicbrainz.entity_genre_observation import (
    EntityGenreObservationError,
    EntityGenreSourceReceipt,
    EntityKind,
    RetainedEntityGenreResponse,
    build_entity_genre_observation_report,
    verify_entity_genre_observation_report,
    write_local_report_once,
)

RECORDING = "00526a18-e31d-4b1f-bc6a-c6c7e318694d"
RELEASE = "018a6ac2-e74f-4874-9b42-7add11ba6ddf"
RELEASE_GROUP = "005909de-978b-3450-a820-c89b7dae787a"
GENRE = "20000000-0000-4000-8000-000000000001"


def _retained(
    kind: EntityKind, entity_id: str, payload: dict[str, object]
) -> RetainedEntityGenreResponse:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return RetainedEntityGenreResponse(
        receipt=EntityGenreSourceReceipt(
            source_partition="musicbrainz_ws2_entity_genre_research_fixture",
            source_snapshot="fixture-20260923",
            entity_kind=kind,
            entity_mbid=UUID(entity_id),
            request_url=(
                f"https://musicbrainz.org/ws/2/{kind.replace('_', '-')}"
                f"/{entity_id}?fmt=json&inc=genres%2Btags"
            ),
            response_sha256=hashlib.sha256(body).hexdigest(),
        ),
        payload=body,
    )


class EntityGenreObservationTests(unittest.TestCase):
    def test_preserves_three_native_entities_and_separate_facets(self) -> None:
        report = build_entity_genre_observation_report(
            (
                _retained(
                    "recording",
                    RECORDING,
                    {
                        "id": RECORDING,
                        "genres": [{"id": GENRE, "name": "Electronic", "count": 8}],
                        "tags": [{"name": "Synthpop", "count": 4}, {"name": "ignored", "count": 0}],
                    },
                ),
                _retained(
                    "release",
                    RELEASE,
                    {
                        "id": RELEASE,
                        "release-group": {"id": RELEASE_GROUP},
                        "genres": [{"id": GENRE, "name": "Electronic", "count": 3}],
                        "tags": [{"name": "Deluxe", "count": 2}],
                    },
                ),
                _retained(
                    "release_group",
                    RELEASE_GROUP,
                    {
                        "id": RELEASE_GROUP,
                        "genres": [{"id": GENRE, "name": "Electronic", "count": 11}],
                        "tags": [{"name": "Album context", "count": 5}],
                    },
                ),
            )
        )

        self.assertEqual(report.genre_observation_count, 3)
        self.assertEqual(report.tag_observation_count, 3)
        self.assertEqual(
            tuple(item.entity_kind for item in report.observations),
            ("recording", "recording", "release", "release", "release_group", "release_group"),
        )
        release_observations = tuple(
            item for item in report.observations if item.entity_kind == "release"
        )
        self.assertEqual(
            {item.release_group_mbid for item in release_observations}, {UUID(RELEASE_GROUP)}
        )
        self.assertTrue(
            all(item.artist_membership_propagated is False for item in report.observations)
        )
        self.assertTrue(all(not hasattr(item, "artist_mbid") for item in report.observations))
        verify_entity_genre_observation_report(report)

    def test_rejects_mismatched_receipt_and_tampered_report(self) -> None:
        body = json.dumps({"id": RECORDING, "genres": [], "tags": []}).encode()
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            RetainedEntityGenreResponse(
                receipt=EntityGenreSourceReceipt(
                    source_partition="fixture",
                    source_snapshot="fixture",
                    entity_kind="recording",
                    entity_mbid=UUID(RECORDING),
                    request_url="local",
                    response_sha256="0" * 64,
                ),
                payload=body,
            )
        report = build_entity_genre_observation_report(
            (_retained("recording", RECORDING, {"id": RECORDING, "genres": [], "tags": []}),)
        )
        with self.assertRaises(EntityGenreObservationError):
            verify_entity_genre_observation_report(
                report.model_copy(update={"tag_observation_count": 1})
            )

    def test_rejects_release_that_does_not_identify_its_parent_group(self) -> None:
        with self.assertRaisesRegex(EntityGenreObservationError, "valid MusicBrainz payload"):
            build_entity_genre_observation_report(
                (_retained("release", RELEASE, {"id": RELEASE, "genres": [], "tags": []}),)
            )

    def test_local_report_writer_refuses_existing_symlink_and_static_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".cache"
            output = root / "report.json"
            write_local_report_once(cache_root=root, output=output, payload=b"report")
            self.assertEqual(output.read_bytes(), b"report")
            with self.assertRaisesRegex(EntityGenreObservationError, "already exists"):
                write_local_report_once(cache_root=root, output=output, payload=b"replacement")
            link = root / "link.json"
            link.symlink_to(output)
            with self.assertRaisesRegex(EntityGenreObservationError, "already exists"):
                write_local_report_once(cache_root=root, output=link, payload=b"report")
            with self.assertRaisesRegex(EntityGenreObservationError, "under .cache"):
                write_local_report_once(
                    cache_root=root,
                    output=Path(directory) / "dist" / "report.json",
                    payload=b"report",
                )
