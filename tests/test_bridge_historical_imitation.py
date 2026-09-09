import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from musix.history.historical_imitation import (
    H3CustodyInput,
    HistoricalImitationSettings,
    _split_historical,
    build_historical_imitation,
    verify_historical_imitation,
)
from musix.musicbrainz_seed_targets import (
    ContextualArtistTag,
    MusicBrainzSeedTargetArtifact,
    SeedTargetCoverage,
    SeedTargetEvidence,
    SeedTargetExtractorCounters,
    SeedTargetExtractorSettings,
    artifact_sha256,
    settings_sha256,
)
from musix.musicbrainz_spotify_bridge import (
    bridge_artifact_sha256,
    build_musicbrainz_spotify_bridge,
    write_musicbrainz_spotify_bridge,
)
from musix.open_tag_feature_matrix import (
    build_open_tag_feature_matrix,
    load_open_tag_feature_matrix,
    load_receipted_open_tag_feature_matrix,
    publish_open_tag_feature_matrix,
    write_open_tag_feature_matrix_artifact,
)
from musix.spotify_bridge_artifact import (
    SpotifyBridgeArtifactError,
    load_musicbrainz_spotify_bridge,
)
from musix.storage import LocalObjectStore

MBIDS = tuple(f"00000000-0000-0000-0000-00000000000{index}" for index in range(1, 5))
SPOTIFY = tuple(chr(64 + index) * 22 for index in range(1, 5))
SPOTIFY_ALIAS = "E" * 22
SPOTIFY_UNBRIDGED = "F" * 22
_FIRST_GROUP_SIZE = 2


def _source() -> MusicBrainzSeedTargetArtifact:
    settings = SeedTargetExtractorSettings()
    seeds = (("seed-a", "electronic"), ("seed-b", "house"))
    evidence = tuple(
        SeedTargetEvidence(
            seed_source_item_id=seed_id,
            seed_source_external_id=f"legacy:{seed_id}",
            seed_name=seed_name,
            seed_normalized_name=seed_name,
            facet="tag",
            target_namespace="musicbrainz_tag_name",
            target_identity=f"tag:{seed_name}",
            target_name=seed_name,
            artist_id=MBIDS[index],
            source_record_id=f"musicbrainz:artist:{MBIDS[index]}",
            source_record_ordinal=index + 1,
            source_record_sha256="a" * 64,
            source_record_byte_length=1,
            evidence_ref=f"source:{seed_id}:{MBIDS[index]}",
            positive_weight=1.0,
            match_kind="exact",
        )
        for seed_id, seed_name, index in (
            (seeds[0][0], seeds[0][1], 0),
            (seeds[0][0], seeds[0][1], 1),
            (seeds[1][0], seeds[1][1], 2),
            (seeds[1][0], seeds[1][1], 3),
        )
    )
    context = tuple(
        ContextualArtistTag(
            artist_id=MBIDS[index],
            source_record_id=f"musicbrainz:artist:{MBIDS[index]}",
            source_record_ordinal=index + 1,
            source_record_sha256="b" * 64,
            source_record_byte_length=1,
            tag_name=tag,
            tag_identity=f"tag:{tag}",
            tag_count=1,
            matched_seed_source_item_ids=("seed-a" if index < _FIRST_GROUP_SIZE else "seed-b",),
            evidence_ref=f"context:{MBIDS[index]}:{tag}",
        )
        for index, tag in enumerate(("electronic", "dance", "house", "dance"))
    )
    provisional = MusicBrainzSeedTargetArtifact(
        seed_input_sha256="c" * 64,
        seed_source_id="fixture",
        seed_source_content_sha256="d" * 64,
        seed_count=2,
        archive_sha256="e" * 64,
        settings=settings,
        settings_sha256=settings_sha256(settings),
        counters=SeedTargetExtractorCounters(
            **dict.fromkeys(SeedTargetExtractorCounters.model_fields, 0)
        ),
        coverage=tuple(
            SeedTargetCoverage(
                seed_source_item_id=seed_id,
                seed_source_external_id=f"legacy:{seed_id}",
                seed_name=seed_name,
                normalized_name=seed_name,
                evidence_count=2,
                distinct_artist_count=2,
                distinct_target_identity_count=1,
                genre_evidence_count=0,
                tag_evidence_count=2,
            )
            for seed_id, seed_name in seeds
        ),
        evidence=evidence,
        contextual_tags=context,
        output_sha256="0" * 64,
    )
    return provisional.model_copy(update={"output_sha256": artifact_sha256(provisional)})


def _archive(root: Path) -> Path:
    archive = root / "musicbrainz.tar.xz"
    records = b"".join(
        (
            json.dumps(
                {
                    "id": mbid,
                    "relations": [
                        {
                            "target-type": "url",
                            "url": {"resource": f"https://open.spotify.com/artist/{spotify}"},
                        }
                    ]
                    + (
                        [
                            {
                                "target-type": "url",
                                "url": {
                                    "resource": (f"https://open.spotify.com/artist/{SPOTIFY_ALIAS}")
                                },
                            }
                        ]
                        if mbid == MBIDS[0]
                        else []
                    ),
                }
            ).encode()
            + b"\n"
        )
        for mbid, spotify in zip(MBIDS, SPOTIFY, strict=True)
    )
    with tarfile.open(archive, "w:xz") as output:
        schema = b"1\n"
        info = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        info.size = len(schema)
        output.addfile(info, io.BytesIO(schema))
        info = tarfile.TarInfo("mbdump/artist")
        info.size = len(records)
        output.addfile(info, io.BytesIO(records))
    return archive


def _historical_database(root: Path) -> Path:
    database = root / "historical.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            """
            CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE historical_genre_artist_observations (
                genre_id INTEGER NOT NULL,
                source_artist_id TEXT,
                observation_role TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO genres VALUES (?, ?)", ((1, "electronic"), (2, "house"))
        )
        connection.executemany(
            "INSERT INTO historical_genre_artist_observations VALUES (?, ?, 'genre_page_member')",
            (
                (1, SPOTIFY[0]),
                (1, SPOTIFY[1]),
                (1, SPOTIFY_ALIAS),
                (2, SPOTIFY[2]),
                (2, SPOTIFY[3]),
                (2, SPOTIFY_UNBRIDGED),
            ),
        )
        connection.commit()
    return database


class BridgeHistoricalImitationTests(unittest.TestCase):
    def test_whole_label_cold_split_and_edge_holdout_are_disjoint_and_replay(self) -> None:
        positives = {
            f"genre-{index}": {f"artist-{artist}" for artist in range(4)} for index in range(20)
        }
        settings = HistoricalImitationSettings(cold_label_fraction=0.4, edge_holdout_fraction=0.5)
        first = _split_historical(positives, settings)
        second = _split_historical(positives, settings)
        self.assertEqual(first, second)
        training, holdout, cold, cold_count = first
        self.assertEqual(cold_count, len(cold))
        self.assertTrue(set(cold).isdisjoint(training))
        self.assertTrue(set(cold).isdisjoint(holdout))
        for genre, artists in positives.items():
            if genre in cold:
                self.assertEqual(cold[genre], artists)
            else:
                self.assertTrue(training[genre].isdisjoint(holdout.get(genre, set())))
                self.assertEqual(training[genre] | holdout.get(genre, set()), artists)

    def test_heavily_cold_split_does_not_require_non_cold_training(self) -> None:
        positives = {"seed-a": {"artist-a"}, "seed-b": {"artist-b"}}
        training, holdout, cold, _cold_count = _split_historical(
            positives,
            HistoricalImitationSettings(split_seed=0, cold_label_fraction=0.9),
        )
        self.assertTrue(set(cold).isdisjoint(training))
        self.assertTrue(set(cold).isdisjoint(holdout))

    def test_open_direct_evidence_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _source()
            historical = _historical_database(root)
            bridge = build_musicbrainz_spotify_bridge(_archive(root), historical)
            bridge_path = root / "bridge.json"
            write_musicbrainz_spotify_bridge(bridge, bridge_path)
            matrix_path = root / "features.sqlite"
            matrix = build_open_tag_feature_matrix(source, matrix_path)
            manifest_path = root / "features.json"
            write_open_tag_feature_matrix_artifact(matrix, manifest_path)
            with self.assertRaisesRegex(ValueError, "open direct evidence exceeds"):
                build_historical_imitation(
                    source,
                    load_musicbrainz_spotify_bridge(bridge_path),
                    load_open_tag_feature_matrix(manifest_path, matrix_path),
                    H3CustodyInput(database_path=historical),
                    HistoricalImitationSettings(max_open_evidence_rows=1),
                )

    def test_streamed_bridge_matrix_and_positive_only_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _source()
            historical = _historical_database(root)
            bridge = build_musicbrainz_spotify_bridge(_archive(root), historical)
            bridge_path = root / "bridge.json"
            write_musicbrainz_spotify_bridge(bridge, bridge_path)
            loaded_bridge = load_musicbrainz_spotify_bridge(bridge_path)
            self.assertEqual(len(loaded_bridge.rows), 5)
            self.assertEqual(next(iter(loaded_bridge.rows)).spotify_artist_id, SPOTIFY[0])

            matrix_path = root / "features.sqlite"
            matrix = build_open_tag_feature_matrix(source, matrix_path)
            manifest_path = root / "features.json"
            write_open_tag_feature_matrix_artifact(matrix, manifest_path)
            reader = load_open_tag_feature_matrix(manifest_path, matrix_path)
            self.assertEqual(len(tuple(reader.iter_features_for_artists(MBIDS))), 4)

            result = build_historical_imitation(
                source,
                loaded_bridge,
                reader,
                H3CustodyInput(database_path=historical),
                HistoricalImitationSettings(cold_label_fraction=0.5, edge_holdout_fraction=0.5),
            )
            verify_historical_imitation(result)
            self.assertEqual(result.coverage.historical_observation_count, 6)
            self.assertEqual(result.coverage.historical_mapped_observation_count, 5)
            self.assertEqual(result.coverage.historical_duplicate_mbid_observation_count, 1)
            self.assertEqual(result.coverage.historical_unbridged_artist_observation_count, 1)
            self.assertFalse(result.h3_absence_treated_as_negative)
            self.assertFalse(result.h3_membership_rank_used)
            self.assertTrue(result.open_only_baseline_historical_evaluation_labels_read)
            self.assertFalse(result.open_only_baseline_historical_training_used)
            self.assertFalse(result.open_only_baseline_historical_features_used)
            self.assertFalse(result.open_only_baseline_historical_candidate_eligibility_used)
            self.assertEqual(
                result.open_only_feature_index_sha256,
                result.historical_feature_index_sha256,
            )

    def test_bridge_tampering_fails_streaming_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = _historical_database(root)
            bridge = build_musicbrainz_spotify_bridge(_archive(root), historical)
            bridge_path = root / "bridge.json"
            write_musicbrainz_spotify_bridge(bridge, bridge_path)
            bridge_path.write_text(
                bridge_path.read_text(encoding="utf-8").replace(SPOTIFY[0], "Z" * 22, 1),
                encoding="utf-8",
            )
            with self.assertRaises(SpotifyBridgeArtifactError):
                load_musicbrainz_spotify_bridge(bridge_path)

    def test_resealed_duplicate_accepted_spotify_identity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = _historical_database(root)
            bridge = build_musicbrainz_spotify_bridge(_archive(root), historical)
            duplicate = bridge.rows[0].model_copy(
                update={
                    "musicbrainz_artist_id": "00000000-0000-0000-0000-000000000099",
                    "evidence_ref": "tampered:duplicate-accepted-spotify",
                }
            )
            rows = tuple(
                sorted(
                    (*bridge.rows, duplicate),
                    key=lambda row: (row.musicbrainz_artist_id, row.spotify_artist_id),
                )
            )
            counters = bridge.counters.model_copy(
                update={
                    "distinct_claim_count": bridge.counters.distinct_claim_count + 1,
                    "accepted_bridge_count": bridge.counters.accepted_bridge_count + 1,
                }
            )
            resealed = bridge.model_copy(
                update={"rows": rows, "counters": counters, "output_sha256": "0" * 64}
            )
            resealed = resealed.model_copy(
                update={"output_sha256": bridge_artifact_sha256(resealed)}
            )
            path = root / "resealed.json"
            path.write_text(
                json.dumps(resealed.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SpotifyBridgeArtifactError, "ambiguous bridge identity"):
                load_musicbrainz_spotify_bridge(path)

    def test_matrix_manifest_binds_sqlite_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix_path = root / "features.sqlite"
            matrix = build_open_tag_feature_matrix(_source(), matrix_path)
            manifest_path = root / "features.json"
            write_open_tag_feature_matrix_artifact(matrix, manifest_path)
            with matrix_path.open("ab") as stream:
                stream.write(hashlib.sha256(b"tamper").digest())
            with self.assertRaisesRegex(ValueError, "bytes"):
                load_open_tag_feature_matrix(manifest_path, matrix_path)

    def test_receipted_matrix_rejects_substitution_and_uses_private_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix_path = root / "features.sqlite"
            matrix = build_open_tag_feature_matrix(_source(), matrix_path)
            manifest_path = root / "features.json"
            receipt = publish_open_tag_feature_matrix(
                matrix,
                artifact_path=manifest_path,
                matrix_path=matrix_path,
                store=LocalObjectStore(root / "objects"),
            )
            receipt_path = root / "receipt.json"
            receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")
            receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            reader = load_receipted_open_tag_feature_matrix(
                manifest_path,
                matrix_path,
                receipt_path,
                receipt_sha,
            )
            try:
                matrix_path.write_bytes(b"substituted")
                self.assertEqual(len(tuple(reader.iter_all_features())), 4)
            finally:
                reader.close()
            with self.assertRaisesRegex(ValueError, "files do not match"):
                load_receipted_open_tag_feature_matrix(
                    manifest_path,
                    matrix_path,
                    receipt_path,
                    receipt_sha,
                )

    def test_no_open_features_becomes_explicit_abstention_not_a_negative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = _source()
            altered = original.model_copy(update={"contextual_tags": (), "output_sha256": "0" * 64})
            source = altered.model_copy(update={"output_sha256": artifact_sha256(altered)})
            historical = _historical_database(root)
            bridge = build_musicbrainz_spotify_bridge(_archive(root), historical)
            bridge_path = root / "bridge.json"
            write_musicbrainz_spotify_bridge(bridge, bridge_path)
            matrix_path = root / "features.sqlite"
            matrix = build_open_tag_feature_matrix(source, matrix_path)
            manifest_path = root / "features.json"
            write_open_tag_feature_matrix_artifact(matrix, manifest_path)
            result = build_historical_imitation(
                source,
                load_musicbrainz_spotify_bridge(bridge_path),
                load_open_tag_feature_matrix(manifest_path, matrix_path),
                H3CustodyInput(database_path=historical),
            )
            self.assertEqual(result.open_only_baseline.predicted_genre_count, 0)
            self.assertEqual(
                result.open_only_baseline.abstained_genre_count,
                result.open_only_baseline.genre_count,
            )
            self.assertEqual(result.open_only_baseline.micro_recall_at_k, 0.0)


if __name__ == "__main__":
    unittest.main()
