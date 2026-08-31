import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import zstandard

from musix.models.catalog import ArtistCoListenProjection, ArtistCoListenRunProjection
from musix.models.listenbrainz import ListenBrainzAggregationConfig
from musix.models.pipeline import (
    ParsedSourceRecord,
    RejectedSourceRecord,
    SourceLimits,
    SourceRecord,
)
from musix.sources.listenbrainz import ListenBrainzIncrementalAdapter, ListenBrainzSourceError

ARTIST_A = "30238ead-59fa-41e2-a7ab-b7f6e6363c4b"
ARTIST_B = "f59c5520-5f46-4d2c-b2c4-822eabf53419"
ARTIST_C = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"


def _listen(user_id: int, timestamp: int, artist_ids: list[str]) -> bytes:
    return json.dumps(
        {
            "user_id": user_id,
            "user_name": "must-not-survive",
            "timestamp": timestamp,
            "track_metadata": {
                "track_name": "discarded",
                "artist_name": "discarded",
                "additional_info": {"artist_mbids": artist_ids},
            },
        },
        separators=(",", ":"),
    ).encode()


def _archive(
    path: Path, lines: tuple[bytes, ...], *, member_name: str = "dump/listens/8.listens"
) -> None:
    payload = b"\n".join(lines) + b"\n"
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    path.write_bytes(zstandard.ZstdCompressor().compress(tar_bytes.getvalue()))


def _records(
    path: Path,
    *,
    config: ListenBrainzAggregationConfig | None = None,
    limits: SourceLimits | None = None,
) -> list[SourceRecord]:
    adapter = ListenBrainzIncrementalAdapter(config)
    effective_limits = limits or SourceLimits(max_decompression_ratio=1024.0)
    return list(adapter.iter_records(path, effective_limits, start_after=-1))


class ListenBrainzIncrementalAdapterTests(unittest.TestCase):
    def test_counts_each_pair_once_per_user_window_and_emits_no_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listens.tar.zst"
            _archive(
                path,
                (
                    _listen(1, 119, [ARTIST_A]),
                    _listen(1, 118, [ARTIST_B]),
                    _listen(1, 117, [ARTIST_B]),
                    _listen(2, 116, [ARTIST_A]),
                    _listen(2, 115, [ARTIST_B]),
                    _listen(3, 114, [ARTIST_A]),
                    _listen(3, 113, [ARTIST_C]),
                ),
            )
            records = _records(
                path,
                config=ListenBrainzAggregationConfig(
                    window_seconds=60,
                    minimum_distinct_users=2,
                ),
            )

        pairs = [
            record.projection
            for record in records
            if hasattr(record, "projection")
            and isinstance(record.projection, ArtistCoListenProjection)
        ]
        runs = [
            record.projection
            for record in records
            if hasattr(record, "projection")
            and isinstance(record.projection, ArtistCoListenRunProjection)
        ]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].distinct_user_count, 2)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].listens_seen, 7)
        self.assertEqual(runs[0].distinct_artists, 3)
        self.assertEqual(runs[0].user_windows, 3)
        serialized = b"\n".join(record.model_dump_json().encode() for record in records)
        self.assertNotIn(b"must-not-survive", serialized)
        self.assertNotIn(b"user_id", serialized)
        self.assertNotIn(b"similarity", serialized)
        self.assertNotIn(b"weight", serialized)

    def test_quarantines_malformed_record_without_retaining_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listens.tar.zst"
            _archive(path, (b'{"user_name":"private"}',))
            records = _records(path)

        rejected = [record for record in records if isinstance(record, RejectedSourceRecord)]
        self.assertEqual(len(rejected), 1)
        self.assertNotIn("private", rejected[0].model_dump_json())
        final_record = records[-1]
        assert isinstance(final_record, ParsedSourceRecord)
        run = final_record.projection
        assert isinstance(run, ArtistCoListenRunProjection)
        self.assertEqual(run.quarantined_records, 1)

    def test_rejects_order_and_all_adapter_state_limits(self) -> None:
        scenarios = (
            (
                "ordering",
                (_listen(1, 1, [ARTIST_A]), _listen(1, 2, [ARTIST_B])),
                ListenBrainzAggregationConfig(window_seconds=1),
                SourceLimits(),
            ),
            (
                "records",
                (_listen(1, 2, [ARTIST_A]), _listen(1, 1, [ARTIST_B])),
                ListenBrainzAggregationConfig(),
                SourceLimits(max_records=1),
            ),
            (
                "users",
                (_listen(1, 2, [ARTIST_A]), _listen(2, 1, [ARTIST_B])),
                ListenBrainzAggregationConfig(max_users_per_window=1),
                SourceLimits(),
            ),
            (
                "artists",
                (_listen(1, 1, [ARTIST_A, ARTIST_B, ARTIST_C]),),
                ListenBrainzAggregationConfig(max_artists_per_user_window=2),
                SourceLimits(),
            ),
            (
                "pairs",
                (_listen(1, 1, [ARTIST_A, ARTIST_B, ARTIST_C]),),
                ListenBrainzAggregationConfig(max_pairs_per_window=2),
                SourceLimits(),
            ),
        )
        for label, lines, config, limits in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "listens.tar.zst"
                _archive(path, lines)
                with self.assertRaises(ListenBrainzSourceError):
                    _records(path, config=config, limits=limits)

    def test_rejects_line_member_decompression_and_path_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            line_path = root / "line.tar.zst"
            _archive(line_path, (_listen(1, 1, [ARTIST_A]),))
            with self.assertRaises(ListenBrainzSourceError):
                _records(line_path, limits=SourceLimits(max_record_bytes=20))
            with self.assertRaises(ListenBrainzSourceError):
                _records(line_path, limits=SourceLimits(max_member_bytes=20))
            with self.assertRaises(ListenBrainzSourceError):
                _records(line_path, limits=SourceLimits(max_decompression_ratio=0.1))

            unsafe_path = root / "unsafe.tar.zst"
            _archive(unsafe_path, (_listen(1, 1, [ARTIST_A]),), member_name="../8.listens")
            with self.assertRaises(ListenBrainzSourceError):
                _records(unsafe_path)

    def test_checkpoint_replays_source_but_skips_committed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listens.tar.zst"
            _archive(path, (_listen(1, 2, [ARTIST_A]), _listen(1, 1, [ARTIST_B])))
            adapter = ListenBrainzIncrementalAdapter(
                ListenBrainzAggregationConfig(minimum_distinct_users=1)
            )
            limits = SourceLimits(max_decompression_ratio=1024.0)
            first = list(adapter.iter_records(path, limits, start_after=-1))
            resumed = list(adapter.iter_records(path, limits, start_after=0))

        self.assertEqual(len(first), 2)
        self.assertEqual(len(resumed), 1)
        resumed_record = resumed[0]
        assert isinstance(resumed_record, ParsedSourceRecord)
        self.assertIsInstance(resumed_record.projection, ArtistCoListenRunProjection)


if __name__ == "__main__":
    unittest.main()
