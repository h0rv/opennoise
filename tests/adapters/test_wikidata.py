import bz2
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from opennoise.adapters.wikidata import (
    AdapterLimits,
    WikidataAdapterError,
    fetch_sparql_snapshot,
    iter_album_genre_evidence_dump,
    iter_entity_dump,
    iter_sparql_response,
    iter_truthy_dump,
    parse_truthy_line,
    write_genre_outputs,
)
from opennoise.ingest.jsonl import parse_catalog_record
from tests._test_client import PollingIsolatedAsyncioTestCase

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _claim(property_id: str, value: object, value_type: str) -> dict[str, object]:
    return {
        "rank": "normal",
        "mainsnak": {
            "property": property_id,
            "snaktype": "value",
            "datavalue": {"value": value, "type": value_type},
        },
    }


def _genre_entity() -> dict[str, object]:
    return {
        "id": "Q123",
        "type": "item",
        "labels": {
            "en": {"language": "en", "value": "Example music"},
            "ja": {"language": "ja", "value": "例音楽"},
        },
        "aliases": {
            "en": [{"language": "en", "value": "Example genre"}],
        },
        "claims": {
            "P31": [
                _claim(
                    "P31",
                    {"entity-type": "item", "numeric-id": 188451, "id": "Q188451"},
                    "wikibase-entityid",
                )
            ],
            "P279": [
                _claim(
                    "P279",
                    {"entity-type": "item", "numeric-id": 456, "id": "Q456"},
                    "wikibase-entityid",
                )
            ],
            "P8052": [_claim("P8052", "genre-mbid", "string")],
            "P9881": [_claim("P9881", "example-music", "string")],
            "P495": [
                _claim(
                    "P495",
                    {"entity-type": "item", "numeric-id": 30, "id": "Q30"},
                    "wikibase-entityid",
                )
            ],
            "P571": [
                _claim(
                    "P571",
                    {"time": "+1980-00-00T00:00:00Z", "precision": 9},
                    "time",
                )
            ],
        },
    }


class WikidataDumpTests(unittest.TestCase):
    def test_streams_album_and_edition_genre_claims_with_typed_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "albums.json.bz2"
            raw_fixture = (FIXTURES / "wikidata_album_genres.json").read_text(encoding="utf-8")
            with bz2.open(path, "wt", encoding="utf-8") as stream:
                stream.write(raw_fixture)
            records = list(iter_album_genre_evidence_dump(path, AdapterLimits()))

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].evidence_level, "release_group")
        self.assertEqual(records[0].genre_qid, "Q116705808")
        self.assertEqual(records[0].reference_count, 1)
        self.assertEqual(records[0].publication_dates, ("+2001-02-03T00:00:00Z",))
        self.assertEqual(records[1].claim_rank, "preferred")
        self.assertEqual(records[2].evidence_level, "release")

    def test_streams_json_array_without_loading_the_dump(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wikidata.json.bz2"
            with bz2.open(path, "wt", encoding="utf-8") as stream:
                json.dump([_genre_entity(), {"id": "Q999", "type": "item"}], stream)
            records = list(iter_entity_dump(path, AdapterLimits()))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].genre.external_id, "wikidata:genre:Q123")
        self.assertEqual(records[0].genre.aliases, ("例音楽", "Example genre"))
        self.assertEqual(records[0].relationships[0].object_external_id, "wikidata:genre:Q456")
        self.assertEqual(records[0].origins, ("Q30",))

    def test_streams_ordered_sparql_groups(self) -> None:
        response = {
            "head": {"vars": ["genre", "genreLabel", "parent"]},
            "results": {
                "bindings": [
                    {
                        "genre": {"type": "uri", "value": "http://www.wikidata.org/entity/Q1"},
                        "genreLabel": {"type": "literal", "value": "First"},
                        "parent": {"type": "uri", "value": "http://www.wikidata.org/entity/Q2"},
                    },
                    {
                        "genre": {"type": "uri", "value": "http://www.wikidata.org/entity/Q3"},
                        "genreLabel": {"type": "literal", "value": "Third"},
                    },
                ]
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query.json"
            path.write_text(json.dumps(response), encoding="utf-8")
            records = list(iter_sparql_response(path, AdapterLimits()))

        self.assertEqual([record.genre.name for record in records], ["First", "Third"])
        self.assertEqual(records[0].relationships[0].object_external_id, "wikidata:genre:Q2")

    def test_parses_relevant_truthy_rdf_claims(self) -> None:
        relation = (
            "<http://www.wikidata.org/entity/Q123> "
            "<http://www.wikidata.org/prop/direct/P279> "
            "<http://www.wikidata.org/entity/Q456> .\n"
        )
        label = (
            "<http://www.wikidata.org/entity/Q123> "
            '<http://www.w3.org/2000/01/rdf-schema#label> "Example music"@en .\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truthy.nt.bz2"
            with bz2.open(path, "wt", encoding="utf-8") as stream:
                stream.write(relation)
                stream.write(label)
            statements = list(iter_truthy_dump(path, AdapterLimits()))

        parsed_relation = parse_truthy_line(relation)
        if parsed_relation is None:
            raise AssertionError("expected a relevant truthy RDF relation")
        self.assertEqual(parsed_relation.predicate, "subgenre_of")
        self.assertEqual(
            [statement.predicate for statement in statements], ["subgenre_of", "label"]
        )
        self.assertEqual(statements[1].language, "en")

    def test_writer_emits_current_importer_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wikidata.json.bz2"
            entities = root / "entities.jsonl"
            relationships = root / "relationships.jsonl"
            with bz2.open(source, "wt", encoding="utf-8") as stream:
                json.dump([_genre_entity()], stream)
            counts = write_genre_outputs(
                iter_entity_dump(source, AdapterLimits()),
                entities,
                relationships,
            )
            parsed = [
                parse_catalog_record(json.loads(line))
                for line in entities.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(counts, (1, 1))
        self.assertEqual(parsed[0].kind, "genre")

    def test_rejects_a_response_over_its_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query.json"
            path.write_text('{"results":{"bindings":[]}}', encoding="utf-8")
            with self.assertRaises(WikidataAdapterError):
                list(iter_sparql_response(path, AdapterLimits(max_response_bytes=1)))


class WikidataNetworkTests(PollingIsolatedAsyncioTestCase):
    async def test_fetches_bounded_identified_sparql_snapshot(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"head": {"vars": []}, "results": {"bindings": []}},
                headers={"content-type": "application/sparql-results+json"},
            )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "query.json"
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                size = await fetch_sparql_snapshot(
                    client,
                    query="SELECT * WHERE {}",
                    destination=destination,
                    user_agent="opennoise/0.1 (maintainer@example.test)",
                    max_response_bytes=1024,
                )
            payload = json.loads(destination.read_text(encoding="utf-8"))

        self.assertGreater(size, 0)
        self.assertEqual(payload["results"]["bindings"], [])
        self.assertEqual(
            requests[0].headers["user-agent"], "opennoise/0.1 (maintainer@example.test)"
        )


if __name__ == "__main__":
    unittest.main()
