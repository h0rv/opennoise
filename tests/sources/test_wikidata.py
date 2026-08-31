import tempfile
import unittest
from collections import Counter
from pathlib import Path

from musix.models.catalog import EntityProjection
from musix.models.pipeline import ParsedSourceRecord, SourceLimits
from musix.sources.wikidata import WikidataSliceError, WikidataSourceAdapter

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "wikidata_music_slice.json"


class WikidataSourceAdapterTests(unittest.TestCase):
    def test_projects_every_supported_music_entity_kind(self) -> None:
        records = list(
            WikidataSourceAdapter().iter_records(FIXTURE, SourceLimits(), start_after=-1)
        )
        accepted = [record for record in records if isinstance(record, ParsedSourceRecord)]
        projections = [
            record.projection
            for record in accepted
            if isinstance(record.projection, EntityProjection)
        ]

        self.assertEqual(len(accepted), 5)
        self.assertEqual(len(projections), len(accepted))
        self.assertEqual(
            Counter(projection.entity_kind for projection in projections),
            Counter(dict.fromkeys(("artist", "genre", "recording", "release_group", "work"), 1)),
        )

    def test_preserves_rank_reference_language_script_and_source_identity(self) -> None:
        record = next(
            record
            for record in WikidataSourceAdapter().iter_records(
                FIXTURE, SourceLimits(), start_after=-1
            )
            if isinstance(record, ParsedSourceRecord)
        )
        projection = record.projection
        self.assertIsInstance(projection, EntityProjection)
        if not isinstance(projection, EntityProjection):
            self.fail("expected the Wikidata entity projection")

        self.assertEqual(projection.source_identity.value, "Q100")
        self.assertIn("ja", {name.language_tag for name in projection.names})
        self.assertIn("Jpan", {name.script_code for name in projection.names})
        genre_claim = next(claim for claim in projection.claims if claim.claim_kind == "relation")
        self.assertEqual(genre_claim.rank, "preferred")
        self.assertEqual(genre_claim.target.value, "Q500")
        self.assertEqual(genre_claim.references[0].identity.value, "ref-1")

    def test_resumes_by_stable_group_ordinal(self) -> None:
        records = list(WikidataSourceAdapter().iter_records(FIXTURE, SourceLimits(), start_after=2))

        self.assertEqual([record.ordinal for record in records], [3, 4])

    def test_rejects_an_artifact_over_its_bound(self) -> None:
        limits = SourceLimits(max_archive_bytes=1)
        with self.assertRaises(WikidataSliceError):
            list(WikidataSourceAdapter().iter_records(FIXTURE, limits, start_after=-1))

    def test_parser_property_is_deterministic_for_repeated_runs(self) -> None:
        adapter = WikidataSourceAdapter()
        first = list(adapter.iter_records(FIXTURE, SourceLimits(), start_after=-1))
        second = list(adapter.iter_records(FIXTURE, SourceLimits(), start_after=-1))

        self.assertEqual(first, second)
        self.assertEqual(
            [record.exact_sha256 for record in first],
            [record.exact_sha256 for record in second],
        )

    def test_invalid_binding_shape_fails_at_the_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                '{"results":{"bindings":[{"entity":{"type":"literal","value":"Q1"}}]}}',
                encoding="utf-8",
            )
            with self.assertRaises(WikidataSliceError):
                list(WikidataSourceAdapter().iter_records(path, SourceLimits(), start_after=-1))


if __name__ == "__main__":
    unittest.main()
