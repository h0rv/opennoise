"""Exact native credit metadata is independent of direct artist genre observations."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    build_local_musicbrainz_candidate_catalog,
)
from opennoise.catalog.musicbrainz_release_context import (
    _context_payloads,
    verify_artist_release_contexts,
    write_artist_release_contexts,
)
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.musicbrainz_credit_portable_release import (
    MusicBrainzCreditPortableReleaseError,
)
from tests.catalog.test_musicbrainz_candidate import _fixture, _uuid

_ROOT = Path(__file__).resolve().parents[2]
_STORE = _ROOT / "data/release/musicbrainz-credit-catalog-v1/objects"
_VARIOUS = "89ad4ac3-39f7-470e-963a-56509c546377"
_RECORDING_ONLY = "0008442e-fb0c-4e06-88df-40b6339beea4"
_UNRELATED = "ffffffff-ffff-4fff-8fff-ffffffffffff"


class ReleaseContextTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.catalog = self.directory / "catalog"
        self.output = self.directory / "context"
        mapping = {1: _RECORDING_ONLY, 2: _VARIOUS, 3: _UNRELATED}
        with patch(
            "tests.catalog.test_musicbrainz_candidate._uuid",
            side_effect=lambda value: mapping.get(value, _uuid(value)),
        ):
            sources = _fixture(self.directory)
        build_local_musicbrainz_candidate_catalog(**sources, output_directory=self.catalog)

    def _write(self) -> dict[str, object]:
        return write_artist_release_contexts(
            direct_catalog_directory=self.catalog, output_directory=self.output
        )

    def test_real_portable_metadata_and_exact_direct_artist_join_keep_roles_separate(self) -> None:
        before = sha256_file(self.catalog / "catalog.sqlite")
        report = self._write()
        self.assertEqual(report["source_release_count"], 87)
        self.assertEqual(report["source_track_count"], 1032)
        self.assertEqual(report["source_recording_count"], 1031)
        self.assertEqual(report["credited_direct_artist_count"], 2)
        self.assertEqual(report["direct_artists_without_retained_release_context"], 1)
        self.assertEqual(report["seed_count_with_credit_context"], 2)
        self.assertFalse(report["artist_membership_inferred_from_context"])
        self.assertFalse(report["release_genre_membership_inferred_from_artist"])
        self.assertEqual(report["album_supported_seed_evidence"], [])
        self.assertEqual(report["membership_claims_added"], 0)
        artist = json.loads(
            (self.output / "artist-releases" / f"{_RECORDING_ONLY}.json").read_bytes()
        )
        for release in artist["releases"]:
            self.assertEqual(release["queried_artist_credit_roles"], ["recording_artist_credit"])
            self.assertTrue(release["tracks"])
            self.assertTrue(release["core_metadata_artifact_sha256"])
            for track in release["tracks"]:
                self.assertEqual(track["semantics"], "track_metadata_not_playable_media")
                self.assertIsNone(track["recording_title"])
        genre = json.loads((self.output / "genre-release-examples" / "seed:a.json").read_bytes())
        self.assertEqual(genre["heading"], "Releases credited to source artists")
        self.assertFalse(genre["native_release_genres_available"])
        for release in genre["releases"]:
            self.assertEqual(
                release["relation"],
                "release_credit_to_artist_with_separate_direct_seed_observation",
            )
            for artist in release["matched_source_artists"]:
                for observation in artist["direct_artist_seed_observations"]:
                    self.assertEqual(observation["seed_id"], "seed:a")
                    self.assertEqual(observation["facet"], "artist_direct_proper_genre")
        self.assertEqual(before, sha256_file(self.catalog / "catalog.sqlite"))
        self.assertEqual(
            report,
            verify_artist_release_contexts(
                direct_catalog_directory=self.catalog, output_directory=self.output
            ),
        )

    def test_bounded_genre_examples_retain_remaining_count_and_source_order(self) -> None:
        rows: list[dict[str, object]] = [{"release_mbid": _uuid(value)} for value in range(1, 15)]
        result = _context_payloads({}, {"seed:a": rows}, {})["genre-release-examples/seed:a.json"]
        self.assertEqual(result["total_release_count"], 14)
        self.assertEqual(result["remaining_release_count"], 2)
        self.assertEqual(result["releases"], rows[:12])
        self.assertEqual(result["ordering"], "exact_release_uuid_order_not_relevance")

    def test_missing_context_remains_unavailable_without_name_inference(self) -> None:
        report = self._write()
        paths = report["artist_paths"]
        assert isinstance(paths, dict)
        self.assertNotIn(_UNRELATED, paths)
        self.assertEqual(report["missing_context_status"], "unavailable_in_retained_source_slice")
        self.assertFalse((self.output / "artist-releases" / f"{_UNRELATED}.json").exists())

    def test_source_catalog_byte_mutation_fails_before_projection_writes(self) -> None:
        store = self.directory / "objects"
        shutil.copytree(_STORE, store)
        database = next(store.rglob("*.sqlite"))
        database.write_bytes(database.read_bytes() + b" ")
        with self.assertRaisesRegex(MusicBrainzCreditPortableReleaseError, "differs from receipt"):
            write_artist_release_contexts(
                direct_catalog_directory=self.catalog,
                output_directory=self.output,
                credit_object_store=store,
            )
        self.assertFalse(self.output.exists())

    def test_rehashed_projection_and_source_role_mutations_fail_independent_replay(self) -> None:
        self._write()
        genre_path = self.output / "genre-release-examples" / "seed:a.json"
        original = genre_path.read_bytes()
        changed = json.loads(original)
        changed["release_genre_membership_inferred_from_artist"] = True
        genre_path.write_bytes(canonical_json(changed) + b"\n")
        with self.assertRaisesRegex(CandidateCatalogError, "does not replay"):
            verify_artist_release_contexts(
                direct_catalog_directory=self.catalog, output_directory=self.output
            )
        genre_path.write_bytes(original)
        receipt_path = self.output / "release-context-receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["membership_claims_added"] = 1
        receipt["output_sha256"] = sha256_json(
            {k: v for k, v in receipt.items() if k != "output_sha256"}
        )
        receipt_path.write_bytes(canonical_json(receipt) + b"\n")
        with self.assertRaisesRegex(CandidateCatalogError, "source-role declarations"):
            verify_artist_release_contexts(
                direct_catalog_directory=self.catalog, output_directory=self.output
            )

    def test_no_replacement_or_public_destinations_or_unsafe_seed_paths(self) -> None:
        self._write()
        with self.assertRaisesRegex(CandidateCatalogError, "refusing to replace"):
            self._write()
        with self.assertRaisesRegex(CandidateCatalogError, "inside project .cache"):
            write_artist_release_contexts(
                direct_catalog_directory=self.catalog, output_directory=_ROOT / "dist" / "credits"
            )
        with self.assertRaisesRegex(CandidateCatalogError, "unsafe"):
            _context_payloads({}, {"../escape": []}, {})
