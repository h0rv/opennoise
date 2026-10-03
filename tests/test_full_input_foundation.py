"""Full-index coverage checks include duplicate names, Unicode and self-rehashed omissions."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import override

from opennoise.pipeline.full_input_foundation import (
    _write,
    create_identity_database,
    export_identity_indexes,
    normalize_name,
    validate_identity_indexes,
)


class FullInputIndexTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.database = self.output / "identities.sqlite"
        self.rows = [
            (f"00000000-0000-0000-0000-{number:012x}", name)
            for number, name in enumerate(
                ["Same", "Same", "Straße", "\uff33\uff21\uff2d\uff25", "東京", "B", "Other"]
            )
        ]
        create_identity_database(self.database, self.rows)
        export_identity_indexes(self.database, self.output)

    def test_all_identities_in_every_view_including_duplicate_names(self) -> None:
        validate_identity_indexes(self.database, self.output)
        browse = json.loads((self.output / "browse/index.json").read_bytes())
        rows = [
            row for path in browse["pages"] for row in json.loads((self.output / path).read_bytes())
        ]
        self.assertEqual(len(rows), len(self.rows))
        self.assertEqual(sum(row[1] == "Same" for row in rows), 2)
        self.assertEqual(normalize_name("\uff33\uff21\uff2d\uff25"), "same")
        self.assertEqual(normalize_name("Straße"), "strasse")

    def test_duplicate_identity_fails_without_name_merging(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            create_identity_database(self.output / "duplicate.sqlite", [self.rows[0], self.rows[0]])

    def test_fresh_output_protects_existing_database(self) -> None:
        original = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, "fresh"):
            create_identity_database(self.database, [])
        self.assertEqual(self.database.read_bytes(), original)

    def test_omitted_entire_search_bucket_is_rejected(self) -> None:
        path = self.output / "search/index.json"
        document = json.loads(path.read_bytes())
        document["buckets"].pop()
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "bucket universe"):
            validate_identity_indexes(self.database, self.output)

    def test_forged_page_bounds_are_rejected(self) -> None:
        path = self.output / "search/index.json"
        document = json.loads(path.read_bytes())
        document["buckets"][0]["pages"][0]["first"] = "forged"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "bounds"):
            validate_identity_indexes(self.database, self.output)

    def test_omitted_browse_row_is_rejected(self) -> None:
        path = self.output / "browse/000000.json"
        document = json.loads(path.read_bytes())
        document.pop()
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "coverage differs"):
            validate_identity_indexes(self.database, self.output)

    def test_paginated_search_retains_every_row(self) -> None:
        database = self.output / "large.sqlite"
        rows = [(f"ff000000-0000-0000-0000-{n:012x}", f"aa artist {n:05d}") for n in range(1001)]
        create_identity_database(database, rows)
        output = self.output / "large"
        export_identity_indexes(database, output)
        validate_identity_indexes(database, output)
        index = json.loads((output / "search/index.json").read_bytes())
        self.assertEqual(index["buckets"][0]["count"], 1001)
        self.assertEqual([p["count"] for p in index["buckets"][0]["pages"]], [500, 500, 1])

    def test_compact_search_reuses_only_browse_payloads(self) -> None:
        output = self.output / "compact"
        counts = export_identity_indexes(self.database, output, compact=True)
        validate_identity_indexes(self.database, output)
        self.assertEqual(counts["search_pages"], 1)
        self.assertEqual([p.name for p in (output / "search").iterdir()], ["index.json"])
        index = json.loads((output / "search/index.json").read_bytes())
        self.assertEqual(index["count"], len(self.rows))
        self.assertEqual(index["pages"][0][2], len(self.rows))

    def test_compact_bound_forgery_is_rejected(self) -> None:
        output = self.output / "compact-forged"
        export_identity_indexes(self.database, output, compact=True)
        path = output / "search/index.json"
        document = json.loads(path.read_bytes())
        document["pages"][0][0] = "forged"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "lexical bounds"):
            validate_identity_indexes(self.database, output)

    def test_compact_multi_page_bounds_account_for_all_names(self) -> None:
        database = self.output / "large-compact.sqlite"
        rows = [(f"ff000000-0000-0000-0000-{n:012x}", f"aa artist {n:05d}") for n in range(1001)]
        create_identity_database(database, rows)
        output = self.output / "large-compact"
        counts = export_identity_indexes(database, output, compact=True)
        validate_identity_indexes(database, output)
        self.assertEqual(counts["search_pages"], 3)
        index = json.loads((output / "search/index.json").read_bytes())
        self.assertEqual([p[2] for p in index["pages"]], [500, 500, 1])

    def test_writing_linked_identical_json_never_changes_source_inode(self) -> None:
        source = self.output / "preserved.json"
        _write(source, {"value": "original"})
        linked = self.output / "linked.json"
        os.link(source, linked)
        original_bytes, original_time = source.read_bytes(), source.stat().st_mtime_ns
        _write(linked, {"value": "original"})
        with self.assertRaisesRegex(ValueError, "overwrite"):
            _write(linked, {"value": "replacement"})
        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertEqual(source.stat().st_mtime_ns, original_time)
        self.assertEqual(source.stat().st_ino, linked.stat().st_ino)
