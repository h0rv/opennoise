import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Literal

from musix.ingest.wikidata.wikidata_seed_resolver import (
    SparqlBinding,
    SparqlHead,
    SparqlResponse,
    SparqlResults,
    WikidataResolverConfig,
    _RequestResult,
    merge_wikidata_public_anchors,
    resolve_wikidata_seed_batch,
    select_wikidata_seed_targets,
    write_wikidata_seed_resolution,
)


def _binding(kind: Literal["uri", "literal", "typed-literal"], value: str) -> SparqlBinding:
    return SparqlBinding(type=kind, value=value)


class _Fetcher:
    def __init__(self, response: SparqlResponse) -> None:
        self.response = response

    async def fetch(self, query: str, *, offline: bool) -> _RequestResult:
        return _RequestResult(
            response=self.response,
            request_sha256=hashlib.sha256(query.encode()).hexdigest(),
            response_sha256="a" * 64,
            cache_hit=offline,
        )


class WikidataSeedResolverTests(unittest.TestCase):
    def _source(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "seed_input": {
                        "source_id": "legacy",
                        "source_content_sha256": "b" * 64,
                        "artifact_sha256": "c" * 64,
                        "names": [
                            {
                                "source_item_id": "1",
                                "source_external_id": "legacy:1",
                                "name": "A genre",
                            },
                            {
                                "source_item_id": "2",
                                "source_external_id": "legacy:2",
                                "name": "B genre",
                            },
                            {
                                "source_item_id": "3",
                                "source_external_id": "legacy:3",
                                "name": "C genre",
                            },
                            {
                                "source_item_id": "4",
                                "source_external_id": "legacy:4",
                                "name": "Already canonical",
                            },
                        ],
                    },
                    "nodes": [
                        {"source_item_id": "1", "taxonomy_status": "abstained"},
                        {"source_item_id": "2", "taxonomy_status": "ambiguous_exact"},
                        {"source_item_id": "3", "taxonomy_status": "abstained"},
                        {"source_item_id": "4", "taxonomy_status": "canonical_exact"},
                    ],
                    "historical_coordinates": [[999, -999]],
                    "artists": ["must never be read"],
                }
            ),
            encoding="utf-8",
        )

    def _config(self) -> WikidataResolverConfig:
        return WikidataResolverConfig(
            expected_seed_count=4,
            batch_limit=3,
            sparql_terms_per_request=3,
            user_agent="musix-test/1.0 (test@example.invalid)",
        )

    def test_exact_unique_music_genre_only_is_accepted_and_merge_has_no_memberships(self) -> None:
        response = SparqlResponse(
            head=SparqlHead(vars=()),
            results=SparqlResults(
                bindings=(
                    {
                        "term": _binding("literal", "a genre"),
                        "item": _binding("uri", "http://www.wikidata.org/entity/Q1"),
                        "label": _binding("literal", "A genre"),
                        "matchedName": _binding("literal", "A Genre"),
                        "matchKind": _binding("literal", "label"),
                        "classes": _binding("literal", "http://www.wikidata.org/entity/Q188451"),
                        "parents": _binding("literal", ""),
                    },
                    {
                        "term": _binding("literal", "b genre"),
                        "item": _binding("uri", "http://www.wikidata.org/entity/Q2"),
                        "label": _binding("literal", "B genre"),
                        "matchedName": _binding("literal", "b genre"),
                        "matchKind": _binding("literal", "alias"),
                        "classes": _binding("literal", "http://www.wikidata.org/entity/Q483394"),
                        "parents": _binding("literal", ""),
                    },
                    {
                        "term": _binding("literal", "c genre"),
                        "item": _binding("uri", "http://www.wikidata.org/entity/Q3"),
                        "label": _binding("literal", "C genre"),
                        "matchedName": _binding("literal", "C genre"),
                        "matchKind": _binding("literal", "label"),
                        "classes": _binding("literal", "http://www.wikidata.org/entity/Q188451"),
                        "parents": _binding("literal", ""),
                    },
                    {
                        "term": _binding("literal", "c genre"),
                        "item": _binding("uri", "http://www.wikidata.org/entity/Q4"),
                        "label": _binding("literal", "Other C genre"),
                        "matchedName": _binding("literal", "C genre"),
                        "matchKind": _binding("literal", "alias"),
                        "classes": _binding("literal", "http://www.wikidata.org/entity/Q188451"),
                        "parents": _binding("literal", ""),
                    },
                )
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source.json", root / "batch.json"
            self._source(source)
            artifact = asyncio.run(
                resolve_wikidata_seed_batch(
                    source,
                    config=self._config(),
                    cache_directory=root / "cache",
                    fetcher=_Fetcher(response),
                )
            )
            self.assertEqual([item.wikidata_qid for item in artifact.accepted_exact_unique], ["Q1"])
            self.assertEqual(artifact.counts.artist_membership_count, 0)
            self.assertEqual(
                {item.reason for item in artifact.abstentions},
                {
                    "unique_exact_match_lacks_music_genre_evidence",
                    "ambiguous_exact_wikidata_candidates",
                },
            )
            write_wikidata_seed_resolution(artifact, output)
            merge = merge_wikidata_public_anchors(output)
            self.assertEqual(merge.anchor_count, 1)
            self.assertEqual(merge.artist_membership_count, 0)
            self.assertFalse(merge.canonical_membership_created)

    def test_offline_cache_miss_abstains_without_a_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.json"
            self._source(source)
            artifact = asyncio.run(
                resolve_wikidata_seed_batch(
                    source,
                    config=self._config(),
                    cache_directory=Path(temporary) / "empty-cache",
                    offline=True,
                )
            )
            self.assertEqual(artifact.counts.offline_cache_miss_count, 3)
            self.assertEqual(artifact.counts.accepted_exact_unique_count, 0)

    def test_committed_projection_selects_a_bounded_ambiguous_or_unresolved_batch(self) -> None:
        source = Path(__file__).parents[3] / "data/model/open-construction-graph-v1.json"
        selected = select_wikidata_seed_targets(
            source,
            WikidataResolverConfig(
                batch_limit=250, user_agent="musix-test/1.0 (test@example.invalid)"
            ),
        )
        self.assertEqual(selected.seed_count, 6291)
        self.assertEqual(len(selected.selected_targets), 250)
        self.assertTrue(
            all(
                target.prior_status in {"abstained", "ambiguous_exact", "ambiguous_compositional"}
                for target in selected.selected_targets
            )
        )


if __name__ == "__main__":
    unittest.main()
