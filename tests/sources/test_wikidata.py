import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from musix.models.catalog import EntityProjection
from musix.models.pipeline import ParsedSourceRecord, SourceLimits
from musix.sources.wikidata import WikidataSliceError, WikidataSourceAdapter

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "wikidata_music_slice.json"
QUERY = Path(__file__).resolve().parents[2] / "config" / "wikidata_public_genres_20260831.rq"


class WikidataSourceAdapterTests(unittest.TestCase):
    def test_public_genre_query_has_one_explicit_bounded_qid_set(self) -> None:
        query = QUERY.read_text(encoding="utf-8")
        qids = re.findall(r"wd:(Q[1-9][0-9]*)", query)

        self.assertEqual(len(qids), 127)
        self.assertEqual(len(set(qids)), 127)
        self.assertIn("LIMIT 50000", query)
        self.assertNotIn("wikibase:mwapi", query)

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

        self.assertEqual(len(accepted), 6)
        self.assertEqual(len(projections), len(accepted))
        self.assertEqual(
            Counter(projection.entity_kind for projection in projections),
            Counter({"artist": 1, "genre": 2, "recording": 1, "release_group": 1, "work": 1}),
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

        genre_record = next(
            item
            for item in WikidataSourceAdapter().iter_records(
                FIXTURE, SourceLimits(), start_after=-1
            )
            if isinstance(item, ParsedSourceRecord)
            and isinstance(item.projection, EntityProjection)
            and item.projection.entity_kind == "genre"
        )
        genre_projection = genre_record.projection
        if not isinstance(genre_projection, EntityProjection):
            self.fail("expected the Wikidata genre projection")
        parent_claim = next(
            claim
            for claim in genre_projection.claims
            if claim.claim_kind == "relation" and claim.property_key == "subclass_of"
        )
        self.assertIsNotNone(parent_claim.statement_id)
        if parent_claim.statement_id is None:
            self.fail("expected a Wikidata P279 statement identity")
        self.assertEqual(parent_claim.statement_id.value, "Q200-parent")
        self.assertEqual(parent_claim.rank, "preferred")
        self.assertEqual(parent_claim.references[0].identity.value, "ref-parent")

    def test_resumes_by_stable_group_ordinal(self) -> None:
        records = list(WikidataSourceAdapter().iter_records(FIXTURE, SourceLimits(), start_after=2))

        self.assertEqual([record.ordinal for record in records], [3, 4, 5])

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
