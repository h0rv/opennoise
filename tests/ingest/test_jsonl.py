import json
import tempfile
import unittest
from pathlib import Path

from musix.db import Database
from musix.ingest.jsonl import ImportOptions, RecordParseError, import_jsonl, parse_catalog_record
from tests._test_client import run_async


class IngestTests(unittest.TestCase):
    def test_parser_accepts_bootstrap_shape_and_rejects_bad_boundaries(self) -> None:
        record = parse_catalog_record(
            {
                "type": "genre",
                "external_id": "enao-legacy:item1",
                "name": "pop",
                "slug": "pop",
                "aliases": [],
                "identifiers": [
                    {"type": "source_id", "namespace": "enao-legacy", "value": "item1"}
                ],
            }
        )
        self.assertEqual(record.kind, "genre")
        with self.assertRaises(RecordParseError):
            parse_catalog_record({"type": "genre", "name": "missing identity", "slug": "bad"})

    def test_import_is_local_idempotent_and_quarantines_bad_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "genres.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "type": "genre",
                        "external_id": "enao-legacy:item1",
                        "name": "pop",
                        "slug": "pop",
                        "aliases": ["popular"],
                    }
                )
                + "\n{broken\n",
                encoding="utf-8",
            )
            options = ImportOptions(
                input_path=input_path,
                database_path=root / "catalog.sqlite",
                vault_path=root / "vault",
                source_key="enao-legacy",
                source_name="Every Noise legacy snapshot",
            )
            first = run_async(import_jsonl(options))
            second = run_async(import_jsonl(options))
            self.assertEqual(first.accepted, 1)
            self.assertEqual(first.quarantined, 1)
            self.assertFalse(first.reused_attempt)
            self.assertTrue(second.reused_attempt)
            self.assertEqual(second.catalog_entities, 1)
            self.assertTrue((root / "vault" / first.artifact_sha256).is_file())
            database = Database(root / "catalog.sqlite")
            self.assertEqual([hit.name for hit in database.search("pop")], ["pop"])
            with database.connect() as connection:
                policy = connection.execute(
                    "SELECT classification, local_only FROM rights_policies"
                ).fetchone()
                parsed = connection.execute(
                    "SELECT parsed_json FROM staged_records WHERE parse_status = 'accepted'"
                ).fetchone()
            self.assertEqual(tuple(policy), ("user_authorized_local", 1))
            self.assertNotIn(str(input_path), str(parsed[0]))


if __name__ == "__main__":
    unittest.main()
