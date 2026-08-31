import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import ValidationError

from musix.ingest import parse_catalog_record
from musix.sources.musicbrainz import (
    AdapterLimits,
    MusicBrainzAdapterError,
    MusicBrainzArtist,
    MusicBrainzClient,
    iter_artist_archive,
    iter_release_group_jsonl,
    iter_release_jsonl,
    write_artist_outputs,
)

ARTIST_ID = UUID("30238ead-59fa-41e2-a7ab-b7f6e6363c4b")
GENRE_ID = "2f8f4ab6-5f11-4c1c-b3a9-17f0ef4d9cb9"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _artist_payload() -> dict[str, object]:
    return {
        "id": str(ARTIST_ID),
        "name": "Blue Guy",
        "sort-name": "Guy, Blue",
        "aliases": [
            {"name": "The Blue Guy", "locale": "en"},
            {"name": "Blue Guy", "locale": "en"},
        ],
        "genres": [{"id": GENRE_ID, "name": "Electric blues", "count": 4}],
        "isnis": ["0000000121032683"],
        "ipis": ["00123456789"],
    }


def _add_tar_bytes(archive: tarfile.TarFile, name: str, value: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(value)
    archive.addfile(info, io.BytesIO(value))


def _write_archive(path: Path, *, schema: str = "1", artist_name: str = "mbdump/artist") -> None:
    payload = json.dumps(_artist_payload()).encode() + b"\n"
    with tarfile.open(path, "w:xz") as archive:
        _add_tar_bytes(archive, artist_name, payload)
        _add_tar_bytes(archive, "JSON_DUMPS_SCHEMA_NUMBER", f"{schema}\n".encode())


class MusicBrainzArchiveTests(unittest.TestCase):
    def test_artist_genre_claims_are_strictly_bounded_and_unique(self) -> None:
        payload = _artist_payload()
        payload["genres"] = [
            {"id": str(UUID(int=index + 1)), "name": f"Genre {index}", "count": 1}
            for index in range(129)
        ]
        with self.assertRaises(ValidationError):
            MusicBrainzArtist.model_validate(payload)

        duplicate = _artist_payload()
        repeated_genre = {"id": GENRE_ID, "name": "Electric blues", "count": 4}
        duplicate["genres"] = [repeated_genre, repeated_genre]
        with self.assertRaises(ValidationError):
            MusicBrainzArtist.model_validate(duplicate)

    def test_streams_release_groups_and_editions_with_direct_genres(self) -> None:
        with (
            (FIXTURES / "musicbrainz_release_groups.jsonl").open("rb") as groups_stream,
            (FIXTURES / "musicbrainz_releases.jsonl").open("rb") as releases_stream,
        ):
            groups = list(iter_release_group_jsonl(groups_stream, AdapterLimits()))
            releases = list(iter_release_jsonl(releases_stream, AdapterLimits()))

        self.assertEqual(
            [group.release_group.title for group in groups],
            [
                "Synthetic Electronic Album",
                "Synthetic Jazz Album",
                "Synthetic Hip Hop Album",
            ],
        )
        self.assertEqual(groups[1].evidence[0].source_genre_name, "Jazz")
        self.assertEqual(groups[1].evidence[0].evidence_level, "release_group")
        self.assertEqual(releases[0].evidence[0].evidence_level, "release")
        self.assertEqual(
            releases[0].release.release_group_source_id,
            groups[0].release_group.source_id,
        )

    def test_streams_official_archive_shape_into_stable_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "artist.tar.xz"
            _write_archive(archive_path)
            records = list(iter_artist_archive(archive_path, AdapterLimits()))

        self.assertEqual(len(records), 1)
        adapted = records[0]
        self.assertEqual(adapted.artist.external_id, f"musicbrainz:artist:{ARTIST_ID}")
        self.assertEqual(adapted.artist.aliases, ("The Blue Guy",))
        self.assertEqual(adapted.genres[0].external_id, f"musicbrainz:genre:{GENRE_ID}")
        self.assertEqual(adapted.relationships[0].weight, 4)

    def test_rejects_wrong_schema_and_unsafe_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_schema = root / "wrong.tar.xz"
            _write_archive(wrong_schema, schema="2")
            with self.assertRaises(MusicBrainzAdapterError):
                list(iter_artist_archive(wrong_schema, AdapterLimits()))

            unsafe = root / "unsafe.tar.xz"
            _write_archive(unsafe, artist_name="../artist")
            with self.assertRaises(MusicBrainzAdapterError):
                list(iter_artist_archive(unsafe, AdapterLimits()))

    def test_writer_splits_importer_entities_from_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "artist.tar.xz"
            entities_path = root / "entities.jsonl"
            relationships_path = root / "relationships.jsonl"
            _write_archive(archive_path)

            counts = write_artist_outputs(
                archive_path,
                entities_path,
                relationships_path,
                AdapterLimits(),
            )
            entities = [
                parse_catalog_record(json.loads(line))
                for line in entities_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(counts, (2, 1))
        self.assertEqual([entity.kind for entity in entities], ["artist", "genre"])


class MusicBrainzClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_uses_identified_rate_limited_api_request(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=_artist_payload())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = MusicBrainzClient(
                http_client,
                user_agent="musix/0.1 (maintainer@example.test)",
            )
            artist = await client.fetch_artist(ARTIST_ID)

        self.assertEqual(artist.id, ARTIST_ID)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers["user-agent"], "musix/0.1 (maintainer@example.test)")
        self.assertIn("inc=aliases%2Bgenres", str(requests[0].url))


if __name__ == "__main__":
    unittest.main()
