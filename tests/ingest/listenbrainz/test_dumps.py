import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import zstandard

from opennoise.ingest.listenbrainz.dumps import (
    AdapterLimits,
    CooccurrenceConfig,
    ListenBrainzAdapterError,
    SourceProvenance,
    aggregate_artist_cooccurrence,
    iter_listen_archive,
    iter_listens_jsonl,
    write_cooccurrence_evidence,
)

ARTIST_A = "30238ead-59fa-41e2-a7ab-b7f6e6363c4b"
ARTIST_B = "f59c5520-5f46-4d2c-b2c4-822eabf53419"
ARTIST_C = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
SHA256 = "a" * 64


def _listen(
    user: str,
    listened_at: int,
    artist_ids: list[str],
    *,
    fallback_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "listened_at": listened_at,
        "user_name": user,
        "track_metadata": {
            "artist_name": "not persisted",
            "track_name": "not persisted",
            "mbid_mapping": {"artist_mbids": artist_ids},
            "additional_info": {"artist_mbids": fallback_ids or []},
        },
    }


def _jsonl(*records: dict[str, object]) -> bytes:
    return b"".join(json.dumps(record).encode() + b"\n" for record in records)


def _write_tar_zst(path: Path, payload: bytes, *, member_name: str = "2026/8.listens") -> None:
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    path.write_bytes(zstandard.ZstdCompressor().compress(tar_stream.getvalue()))


class ListenBrainzParsingTests(unittest.TestCase):
    def test_prefers_server_mapping_and_uses_valid_fallback(self) -> None:
        payload = _jsonl(
            _listen("listener-1", 100, [ARTIST_A, "invalid"], fallback_ids=[ARTIST_B]),
            _listen("listener-2", 101, [], fallback_ids=[ARTIST_B]),
        )
        records = list(iter_listens_jsonl(io.BytesIO(payload), AdapterLimits()))

        self.assertEqual(records[0].artist_ids, (f"musicbrainz:artist:{ARTIST_A}",))
        self.assertEqual(records[1].artist_ids, (f"musicbrainz:artist:{ARTIST_B}",))

    def test_streams_official_tar_zst_shape_and_rejects_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "sample.tar.zst"
            _write_tar_zst(archive_path, _jsonl(_listen("listener", 100, [ARTIST_A])))
            records = list(
                iter_listen_archive(archive_path, AdapterLimits(), compression="tar.zst")
            )
            self.assertEqual(len(records), 1)

            unsafe_path = root / "unsafe.tar.zst"
            _write_tar_zst(
                unsafe_path,
                _jsonl(_listen("listener", 100, [ARTIST_A])),
                member_name="../listen.jsonl",
            )
            with self.assertRaises(ListenBrainzAdapterError):
                list(iter_listen_archive(unsafe_path, AdapterLimits(), compression="tar.zst"))


class ListenBrainzAggregationTests(unittest.TestCase):
    def test_emits_distinct_user_window_evidence_without_user_or_score(self) -> None:
        payload = _jsonl(
            _listen("listener-1", 100, [ARTIST_A]),
            _listen("listener-1", 101, [ARTIST_B]),
            _listen("listener-1", 102, [ARTIST_B]),
            _listen("listener-2", 103, [ARTIST_A]),
            _listen("listener-2", 104, [ARTIST_B]),
            _listen("listener-3", 105, [ARTIST_A]),
            _listen("listener-3", 106, [ARTIST_C]),
        )
        limits = AdapterLimits()
        evidence = list(
            aggregate_artist_cooccurrence(
                iter_listens_jsonl(io.BytesIO(payload), limits),
                CooccurrenceConfig(window_seconds=60, minimum_distinct_users=2),
                SourceProvenance(snapshot_ref="sample-2026", artifact_sha256=SHA256),
                limits,
            )
        )

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].distinct_user_count, 2)
        self.assertEqual(evidence[0].window_start, 60)
        serialized = evidence[0].model_dump_json()
        self.assertNotIn("listener", serialized)
        self.assertNotIn("score", serialized)
        self.assertNotIn("coordinate", serialized)

    def test_rejects_unordered_windows_and_bounded_user_state(self) -> None:
        limits = AdapterLimits(max_users_per_window=1)
        provenance = SourceProvenance(snapshot_ref="sample-2026", artifact_sha256=SHA256)
        unordered = iter_listens_jsonl(
            io.BytesIO(
                _jsonl(
                    _listen("listener", 120, [ARTIST_A]),
                    _listen("listener", 1, [ARTIST_B]),
                )
            ),
            limits,
        )
        with self.assertRaises(ListenBrainzAdapterError):
            list(
                aggregate_artist_cooccurrence(
                    unordered,
                    CooccurrenceConfig(window_seconds=60),
                    provenance,
                    limits,
                )
            )

        too_many_users = iter_listens_jsonl(
            io.BytesIO(
                _jsonl(
                    _listen("listener-1", 1, [ARTIST_A]),
                    _listen("listener-2", 2, [ARTIST_B]),
                )
            ),
            limits,
        )
        with self.assertRaises(ListenBrainzAdapterError):
            list(
                aggregate_artist_cooccurrence(
                    too_many_users,
                    CooccurrenceConfig(window_seconds=60),
                    provenance,
                    limits,
                )
            )

    def test_writer_persists_only_aggregate_evidence(self) -> None:
        limits = AdapterLimits()
        listens = iter_listens_jsonl(
            io.BytesIO(
                _jsonl(
                    _listen("private-user", 1, [ARTIST_A]),
                    _listen("private-user", 2, [ARTIST_B]),
                )
            ),
            limits,
        )
        evidence = aggregate_artist_cooccurrence(
            listens,
            CooccurrenceConfig(window_seconds=60, minimum_distinct_users=1),
            SourceProvenance(snapshot_ref="sample-2026", artifact_sha256=SHA256),
            limits,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "evidence.jsonl"
            count = write_cooccurrence_evidence(evidence, destination)
            content = destination.read_text(encoding="utf-8")

        self.assertEqual(count, 1)
        self.assertNotIn("private-user", content)


if __name__ == "__main__":
    unittest.main()
