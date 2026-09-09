from __future__ import annotations

import io
import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from musix.taxonomy.genre_seed_universe import SeedInput, SeedName
from musix.musicbrainz_seed_targets import (
    MusicBrainzSeedTargetExtractorError,
    ReviewedSeedAlias,
    SeedTargetExtractorSettings,
    artifact_sha256,
    extract_musicbrainz_seed_targets,
    load_seed_target_artifact,
    settings_sha256,
    verify_seed_target_artifact,
    write_seed_target_artifact,
)


def _seed() -> SeedInput:
    names = (
        SeedName(source_item_id="item1", source_external_id="eno:1", name="Rock"),
        SeedName(source_item_id="item2", source_external_id="eno:2", name="Lo-Fi"),
    )
    return SeedInput(
        source_id="test-seed",
        source_content_sha256="a" * 64,
        artifact_sha256="b" * 64,
        names=names,
    )


def _idm_seed() -> SeedInput:
    return SeedInput(
        source_id="test-seed",
        source_content_sha256="a" * 64,
        artifact_sha256="b" * 64,
        names=(
            SeedName(
                source_item_id="item887",
                source_external_id="eno:887",
                name="intelligent dance music",
            ),
        ),
    )


def _archive(path: Path, records: list[bytes]) -> None:
    payload = b"\n".join(records) + b"\n"
    with tarfile.open(path, "w:xz") as archive:
        schema = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema_data = b"1\n"
        schema.size = len(schema_data)
        archive.addfile(schema, io.BytesIO(schema_data))
        artists = tarfile.TarInfo("mbdump/artist")
        artists.size = len(payload)
        archive.addfile(artists, io.BytesIO(payload))


def _artist(
    artist_id: str, genres: list[dict[str, object]], tags: list[dict[str, object]]
) -> bytes:
    return json.dumps({"id": artist_id, "genres": genres, "tags": tags}).encode()


class MusicBrainzSeedTargetExtractorTests(unittest.TestCase):
    def test_reviewed_idm_alias_preserves_source_and_stable_seed_identity(self) -> None:
        """A reviewed tag-only alias is explicit, provenance-bound, and opt-in."""
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "artist.tar.xz"
            _archive(
                archive,
                [
                    _artist(
                        str(uuid4()),
                        [{"id": str(uuid4()), "name": "IDM"}],
                        [
                            {"name": "IDM", "count": 4},
                            {"name": "intelligent dance music", "count": 2},
                        ],
                    )
                ],
            )
            default = extract_musicbrainz_seed_targets(archive, _idm_seed())
            legacy_path = Path(directory) / "legacy-v1-no-alias.json"
            write_seed_target_artifact(legacy_path, default)
            legacy_roundtrip = load_seed_target_artifact(legacy_path)
            explicit_empty = extract_musicbrainz_seed_targets(
                archive, _idm_seed(), reviewed_aliases=()
            )
            approved = extract_musicbrainz_seed_targets(
                archive,
                _idm_seed(),
                reviewed_aliases=(
                    ReviewedSeedAlias(
                        source_item_id="item887",
                        alias="IDM",
                        approval_ref="reviewed:idm-intelligent-dance-music-v1",
                        facets=("tag",),
                    ),
                ),
            )

        self.assertEqual(default.output_sha256, explicit_empty.output_sha256)
        self.assertEqual(legacy_roundtrip.output_sha256, default.output_sha256)
        self.assertEqual(
            [(row.target_identity, row.match_kind) for row in default.evidence],
            [("tag:intelligent-dance-music", "exact")],
        )
        self.assertEqual(len(approved.evidence), 2)
        exact = next(
            row for row in approved.evidence if row.target_identity == "tag:intelligent-dance-music"
        )
        alias = next(row for row in approved.evidence if row.target_identity == "tag:idm")
        self.assertEqual(exact.target_identity, "tag:intelligent-dance-music")
        self.assertEqual(exact.match_kind, "exact")
        self.assertEqual(alias.seed_source_item_id, "item887")
        self.assertEqual(alias.seed_name, "intelligent dance music")
        self.assertEqual(alias.target_identity, "tag:idm")
        self.assertEqual(alias.target_name, "IDM")
        self.assertEqual(alias.match_kind, "reviewed_alias")
        self.assertIn("reviewed:idm-intelligent-dance-music-v1", alias.evidence_ref)
        self.assertIn("reviewed-alias:", alias.evidence_ref)

    def test_reviewed_aliases_reject_canonical_and_duplicate_spelling_collisions(self) -> None:
        """Alias validation fails before opening an archive or broadening a seed."""
        canonical = ReviewedSeedAlias(
            source_item_id="item887",
            alias="intelligent dance music",
            approval_ref="reviewed:canonical-collision-v1",
        )
        duplicate = ReviewedSeedAlias(
            source_item_id="item887",
            alias="IDM!",
            approval_ref="reviewed:duplicate-alias-v1",
        )
        approved = ReviewedSeedAlias(
            source_item_id="item887",
            alias="IDM",
            approval_ref="reviewed:idm-intelligent-dance-music-v1",
        )

        with self.assertRaisesRegex(MusicBrainzSeedTargetExtractorError, "canonical seed"):
            extract_musicbrainz_seed_targets(
                Path("missing.tar.xz"), _idm_seed(), reviewed_aliases=(canonical,)
            )
        with self.assertRaisesRegex(MusicBrainzSeedTargetExtractorError, "unique normalized"):
            extract_musicbrainz_seed_targets(
                Path("missing.tar.xz"), _idm_seed(), reviewed_aliases=(approved, duplicate)
            )

    def test_signed_tag_counts_never_become_positive_evidence(self) -> None:
        """Keep only positive tag votes while accepting an unweighted genre fact."""
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "artist.tar.xz"
            _archive(
                archive,
                [
                    _artist(
                        str(uuid4()),
                        [
                            {"id": str(uuid4()), "name": "Rock"},
                            {"id": str(uuid4()), "name": "Rock", "count": -1},
                        ],
                        [
                            {"name": "Rock", "count": -2},
                            {"name": "Rock", "count": 0},
                            {"name": "Rock"},
                            {"name": "Rock", "count": True},
                            {"name": "Rock", "count": 2},
                        ],
                    )
                ],
            )
            artifact = extract_musicbrainz_seed_targets(archive, _seed())

        self.assertEqual(
            [(row.facet, row.positive_weight) for row in artifact.evidence],
            [("genre", 1.0), ("tag", 2.0)],
        )
        self.assertEqual(artifact.counters.malformed_claim_count, 3)
        self.assertEqual(artifact.counters.positive_evidence_count, 2)
        self.assertEqual(artifact.coverage[0].genre_evidence_count, 1)
        self.assertEqual(artifact.coverage[0].tag_evidence_count, 1)

    def test_extracts_facets_context_and_replays_deterministically(self) -> None:
        """Extract both facets, context, malformed counts, and stable hashes."""
        with self.subTest("temporary archive"):
            self._test_extracts_facets_context_and_replays_deterministically()

    def _test_extracts_facets_context_and_replays_deterministically(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            self._assert_extraction(tmp_path)

    def _assert_extraction(self, tmp_path: Path) -> None:
        genre_id = str(uuid4())
        archive = tmp_path / "artist.tar.xz"
        _archive(
            archive,
            [
                _artist(
                    str(uuid4()),
                    [{"id": genre_id, "name": "Rock", "count": 3}],
                    [{"name": "Lo-Fi", "count": 5}, {"name": "Detroit", "count": 2}],
                ),
                _artist(
                    str(uuid4()),
                    [{"id": str(uuid4()), "name": "rōck"}],
                    [],
                ),
                b"{not-json",
            ],
        )
        settings = SeedTargetExtractorSettings(max_record_bytes=4096)
        first = extract_musicbrainz_seed_targets(archive, _seed(), settings)
        second = extract_musicbrainz_seed_targets(archive, _seed(), settings)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(first.archive_sha256, second.archive_sha256)
        self.assertEqual({row.facet for row in first.evidence}, {"genre", "tag"})
        self.assertEqual(first.counters.malformed_json_count, 1)
        self.assertEqual(first.counters.contextual_tag_count, 1)
        self.assertEqual(first.contextual_tags[0].tag_name, "Detroit")
        self.assertEqual(first.coverage[0].distinct_artist_count, 2)
        self.assertEqual(first.coverage[1].distinct_artist_count, 1)
        self.assertEqual(first.coverage[1].tag_evidence_count, 1)

    def test_over_limit_and_tamper_checks(self) -> None:
        """Account for oversized records and reject a changed archive hash."""
        with TemporaryDirectory() as directory:
            self._assert_over_limit_and_tamper(Path(directory))

    def test_loader_keeps_large_arrays_streaming_and_replays_tamper_hash(self) -> None:
        """Load rows lazily, replay them, and reject changed row bytes."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            archive = tmp_path / "artist.tar.xz"
            artist_id = str(uuid4())
            _archive(
                archive,
                [
                    _artist(
                        str(uuid4()),
                        [{"id": artist_id, "name": "Rock", "count": 1}],
                        [{"name": "Lo-Fi", "count": 1}, {"name": "Detroit", "count": 1}],
                    )
                ],
            )
            artifact = extract_musicbrainz_seed_targets(archive, _seed())
            output = tmp_path / "artifact.json"
            write_seed_target_artifact(output, artifact)

            loaded = load_seed_target_artifact(output)
            self.assertNotIsInstance(loaded.evidence, tuple)
            self.assertNotIsInstance(loaded.contextual_tags, tuple)
            self.assertEqual(tuple(loaded.evidence), tuple(loaded.evidence))
            self.assertEqual(tuple(loaded.contextual_tags), tuple(loaded.contextual_tags))

            payload = json.loads(output.read_text())
            payload["evidence"][0]["target_name"] = "tampered"
            output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            with self.assertRaisesRegex(ValueError, "output hash"):
                load_seed_target_artifact(output)

    def _assert_over_limit_and_tamper(self, tmp_path: Path) -> None:
        archive = tmp_path / "artist.tar.xz"
        _archive(archive, [_artist(str(uuid4()), [], []), b"{" + b"x" * 500])
        artifact = extract_musicbrainz_seed_targets(
            archive, _seed(), SeedTargetExtractorSettings(max_record_bytes=100)
        )
        self.assertEqual(artifact.counters.record_over_limit_count, 1)
        self.assertEqual(artifact.counters.records_parsed, 1)
        output = tmp_path / "artifact.json"
        write_seed_target_artifact(output, artifact)
        self.assertEqual(load_seed_target_artifact(output).output_sha256, artifact.output_sha256)
        tampered = artifact.model_copy(update={"archive_sha256": "c" * 64})
        with self.assertRaisesRegex(ValueError, "output hash"):
            verify_seed_target_artifact(tampered)
        self.assertEqual(settings_sha256(artifact.settings), artifact.settings_sha256)
        self.assertEqual(artifact_sha256(artifact), artifact.output_sha256)
