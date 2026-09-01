"""Write a deterministic, cache-first hierarchy coverage report from a public SQLite build."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from musix.hierarchy import coverage_report


def load_qualified_hierarchy(database: Path) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Load only exact qualified Wikidata QIDs and their direct retained P279 edges."""
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """WITH qualified AS (
                     SELECT DISTINCT genre_id FROM modelable_music_genres
                   ), qids AS (
                     SELECT identifier.entity_id, min(identifier.normalized_value) AS qid
                     FROM entity_identifiers AS identifier
                     JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                     WHERE identifier.namespace = 'wikidata'
                       AND type.type_key IN ('wikidata_qid', 'wikidata_genre_qid')
                     GROUP BY identifier.entity_id
                   )
                   SELECT qids.qid
                   FROM qualified JOIN qids ON qids.entity_id = qualified.genre_id
                   ORDER BY qids.qid"""
        ).fetchall()
        edges = connection.execute(
            """WITH qualified AS (
                     SELECT DISTINCT genre_id FROM modelable_music_genres
                   ), qids AS (
                     SELECT identifier.entity_id, min(identifier.normalized_value) AS qid
                     FROM entity_identifiers AS identifier
                     JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                     WHERE identifier.namespace = 'wikidata'
                       AND type.type_key IN ('wikidata_qid', 'wikidata_genre_qid')
                     GROUP BY identifier.entity_id
                   )
                   SELECT child_qid.qid, parent_qid.qid
                   FROM genre_hierarchy AS hierarchy
                   JOIN qualified AS child ON child.genre_id = hierarchy.child_genre_id
                   JOIN qualified AS parent ON parent.genre_id = hierarchy.parent_genre_id
                   JOIN qids AS child_qid ON child_qid.entity_id = hierarchy.child_genre_id
                   JOIN qids AS parent_qid ON parent_qid.entity_id = hierarchy.parent_genre_id
                   ORDER BY child_qid.qid, parent_qid.qid"""
        ).fetchall()
    return tuple(str(row[0]) for row in rows), tuple((str(row[0]), str(row[1])) for row in edges)


def main() -> int:
    """Emit JSON suitable for a tracked coverage review or CI evidence artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--focus-qid", default="Q9778")
    arguments = parser.parse_args()
    qids, edges = load_qualified_hierarchy(arguments.database)
    result = coverage_report(qids, edges, focus_qid=arguments.focus_qid)
    sys.stdout.write(f"{json.dumps(result, indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
