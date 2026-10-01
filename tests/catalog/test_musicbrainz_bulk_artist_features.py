"""Fixed-hash cohort reproducibility, native seed strata and exact UUID exclusions."""

from __future__ import annotations

import unittest
from typing import override

from opennoise.catalog.musicbrainz_bulk_artist_features import (
    _fixed_hash,
    _round_robin,
    select_additional_artist_cohort,
)
from opennoise.catalog.musicbrainz_candidate import (
    CandidateCatalogError,
    build_local_musicbrainz_candidate_catalog,
)
from opennoise.catalog.musicbrainz_open_features import build_open_artist_feature_projection
from tests.catalog import test_musicbrainz_open_features as feature_fixtures
from tests.catalog.test_musicbrainz_candidate import _fixture, _uuid


class BulkArtistFeatureSelectionTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.existing = feature_fixtures.OpenArtistFeaturesTests()
        self.existing.setUp()
        self.addCleanup(self.existing.doCleanups)
        build_open_artist_feature_projection(directory=self.existing.directory)
        self.catalog = self.existing.directory / "catalog"
        inputs = self.existing.directory / "inputs"
        inputs.mkdir()
        build_local_musicbrainz_candidate_catalog(**_fixture(inputs), output_directory=self.catalog)

    def test_selected_ids_are_disjoint_and_singletons_are_reserved(self) -> None:
        report = select_additional_artist_cohort(
            catalog_directory=self.catalog,
            existing_feature_directory=self.existing.directory,
            artist_limit=2,
        )
        self.assertEqual(report["artist_ids"], [_uuid(2), _uuid(3)])
        self.assertEqual(report["singleton_artist_count"], 2)
        self.assertEqual(report["reserved_singletons_selected"], 1)
        self.assertEqual(report["selected_native_seed_count"], 1)
        self.assertEqual(report["selected_direct_pair_count"], 2)
        self.assertEqual(report["excluded_existing_artist_count"], 1)
        repeated = select_additional_artist_cohort(
            catalog_directory=self.catalog,
            existing_feature_directory=self.existing.directory,
            artist_limit=2,
        )
        self.assertEqual(repeated, report)

    def test_hash_sampling_does_not_use_names_or_source_iteration_order(self) -> None:
        one = select_additional_artist_cohort(
            catalog_directory=self.catalog,
            existing_feature_directory=self.existing.directory,
            artist_limit=1,
        )
        expected = min((_uuid(2), _uuid(3)), key=lambda value: (_fixed_hash(value), value))
        self.assertEqual(one["artist_ids"], [expected])
        first: set[str] = set()
        second: set[str] = set()
        _round_robin({"seed:b": ["c", "d"], "seed:a": ["a", "b"]}, first, 3)
        _round_robin({"seed:a": ["a", "b"], "seed:b": ["c", "d"]}, second, 3)
        self.assertEqual(first, second)
        self.assertEqual(first, {"a", "b", "c"})

    def test_unbounded_and_unsatisfiable_cohorts_are_rejected(self) -> None:
        for count in (0, 15_001):
            with self.assertRaisesRegex(CandidateCatalogError, "15,000"):
                select_additional_artist_cohort(
                    catalog_directory=self.catalog,
                    existing_feature_directory=self.existing.directory,
                    artist_limit=count,
                )
        with self.assertRaisesRegex(CandidateCatalogError, "cannot meet"):
            select_additional_artist_cohort(
                catalog_directory=self.catalog,
                existing_feature_directory=self.existing.directory,
                artist_limit=3,
            )

    def test_source_cohort_bytes_are_verified_before_sampling(self) -> None:
        database = self.catalog / "catalog.sqlite"
        database.write_bytes(database.read_bytes() + b" ")
        with self.assertRaisesRegex(CandidateCatalogError, "database bytes"):
            select_additional_artist_cohort(
                catalog_directory=self.catalog,
                existing_feature_directory=self.existing.directory,
                artist_limit=1,
            )
