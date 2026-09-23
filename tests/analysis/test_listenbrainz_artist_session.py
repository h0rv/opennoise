import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.analysis.listenbrainz_artist_session import (
    ArtistSessionError,
    ArtistSessionSettings,
    run_artist_session_approximation,
)


def _write_archive(path: Path, rows: list[dict[str, object]]) -> str:
    payload = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as out:
        info = tarfile.TarInfo("x.listens")
        info.size = len(payload)
        out.addfile(info, io.BytesIO(payload))
    path.write_bytes(zstandard.ZstdCompressor().compress(tar.getvalue()))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive(path: Path) -> str:
    return _write_archive(
        path,
        [
            {
                "timestamp": 100,
                "user_id": 1,
                "track_metadata": {
                    "additional_info": {"artist_mbids": ["00000000-0000-4000-8000-000000000001"]}
                },
            },
            {
                "timestamp": 200,
                "user_id": 1,
                "track_metadata": {
                    "additional_info": {"artist_mbids": ["00000000-0000-4000-8000-000000000002"]}
                },
            },
            {
                "timestamp": 700,
                "user_id": 2,
                "track_metadata": {
                    "additional_info": {"artist_mbids": ["00000000-0000-4000-8000-000000000001"]}
                },
            },
            {
                "timestamp": 800,
                "user_id": 2,
                "track_metadata": {
                    "additional_info": {"artist_mbids": ["00000000-0000-4000-8000-000000000002"]}
                },
            },
        ],
    )


class ArtistSessionTests(unittest.TestCase):
    def test_emits_only_aggregate_threshold_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.tar.zst"
            digest = _archive(path)
            artifact = run_artist_session_approximation(
                archive_path=path, source_artifact_sha256=digest
            )
        self.assertEqual(artifact.candidate_pair_count, 1)
        self.assertEqual(artifact.threshold_pair_count, 0)
        self.assertNotIn("00000000-0000-4000-8000-000000000001", artifact.model_dump_json())

    def test_rejects_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.tar.zst"
            digest = _archive(path)
            with self.assertRaisesRegex(ArtistSessionError, "line"):
                run_artist_session_approximation(
                    archive_path=path,
                    source_artifact_sha256=digest,
                    settings=ArtistSessionSettings(maximum_line_bytes=1),
                )

    def test_rejects_decompressed_byte_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.tar.zst"
            digest = _archive(path)
            with self.assertRaisesRegex(ArtistSessionError, "decompressed bytes"):
                run_artist_session_approximation(
                    archive_path=path,
                    source_artifact_sha256=digest,
                    settings=ArtistSessionSettings(maximum_decompressed_bytes=1),
                )

    def test_rejects_non_listen_member_under_decompression_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.tar.zst"
            tar = io.BytesIO()
            with tarfile.open(fileobj=tar, mode="w") as out:
                payload = b"x" * 4096
                info = tarfile.TarInfo("unrelated.bin")
                info.size = len(payload)
                out.addfile(info, io.BytesIO(payload))
            path.write_bytes(zstandard.ZstdCompressor().compress(tar.getvalue()))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ArtistSessionError, "decompressed bytes"):
                run_artist_session_approximation(
                    archive_path=path,
                    source_artifact_sha256=digest,
                    settings=ArtistSessionSettings(maximum_decompressed_bytes=1024),
                )

    def test_rejects_pair_support_event_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.tar.zst"
            digest = _archive(path)
            with self.assertRaisesRegex(ArtistSessionError, "support events"):
                run_artist_session_approximation(
                    archive_path=path,
                    source_artifact_sha256=digest,
                    settings=ArtistSessionSettings(maximum_pair_support_events=1),
                )

    def test_one_user_high_score_cannot_qualify(self) -> None:
        first = "00000000-0000-4000-8000-000000000001"
        second = "00000000-0000-4000-8000-000000000002"
        rows: list[dict[str, object]] = []
        for session in range(11):
            timestamp = session * 481
            rows.extend(
                [
                    {
                        "timestamp": timestamp,
                        "user_id": 1,
                        "track_metadata": {"additional_info": {"artist_mbids": [artist]}},
                    }
                    for artist in (first, second)
                ]
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.tar.zst"
            digest = _write_archive(path, rows)
            artifact = run_artist_session_approximation(
                archive_path=path,
                source_artifact_sha256=digest,
                settings=ArtistSessionSettings(
                    maximum_user_pair_contribution=20,
                    minimum_pair_score_exclusive=10,
                ),
            )
        self.assertEqual(artifact.candidate_pair_count, 1)
        self.assertEqual(artifact.threshold_pair_count, 0)
