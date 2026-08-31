"""Prepare bounded exact-QID genre metadata and direct hierarchy shards."""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field

from musix.models import FrozenModel

QID_PATTERN = r"^Q[1-9][0-9]*$"
GENRE_SHARD_SIZE = 200


class GenreTarget(FrozenModel):
    """One exact Wikidata genre identity observed in public evidence."""

    qid: str = Field(pattern=QID_PATTERN)


class GenreEnrichmentSelection(FrozenModel):
    """Bind generated genre queries to their observed source artifacts."""

    schema_version: Literal[1] = 1
    input_artifacts: tuple[str, ...]
    targets: tuple[GenreTarget, ...]
    query_mode: Literal["discover_direct_parents", "labels_only"]
    shard_size: int = GENRE_SHARD_SIZE


def load_targets(
    database: Path, query_mode: Literal["discover_direct_parents", "labels_only"]
) -> GenreEnrichmentSelection:
    """Load exact QIDs referenced by direct memberships or known hierarchy."""
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """WITH referenced_genres(genre_id) AS (
                 SELECT genre_id FROM normalizable_artist_genre_evidence
                 UNION SELECT genre_id FROM normalizable_album_genre_memberships
                 UNION SELECT genre_id FROM normalizable_recording_genre_memberships
                 UNION SELECT child_genre_id FROM genre_hierarchy
                 UNION SELECT parent_genre_id FROM genre_hierarchy
               )
               SELECT DISTINCT identifier.normalized_value
               FROM referenced_genres AS referenced
               JOIN entity_identifiers AS identifier
                 ON identifier.entity_id = referenced.genre_id
               JOIN identifier_types AS kind ON kind.id = identifier.identifier_type_id
               WHERE identifier.namespace = 'wikidata'
                 AND kind.type_key IN ('wikidata_qid', 'wikidata_genre_qid')
               ORDER BY identifier.normalized_value"""
        ).fetchall()
        artifacts = connection.execute(
            """SELECT DISTINCT artifact.sha256
               FROM source_artifacts AS artifact
               JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
               JOIN data_sources AS source ON source.id = snapshot.source_id
               WHERE source.source_key LIKE 'wikidata_%'
               ORDER BY artifact.sha256"""
        ).fetchall()
    targets = tuple(GenreTarget(qid=str(row[0])) for row in rows)
    if not targets or not artifacts:
        raise RuntimeError("no exact Wikidata genre targets or input artifacts")
    return GenreEnrichmentSelection(
        input_artifacts=tuple(str(row[0]) for row in artifacts),
        targets=targets,
        query_mode=query_mode,
    )


def render_genre_query(targets: tuple[GenreTarget, ...], *, include_hierarchy: bool = True) -> str:
    """Render labels, aliases, and referenced non-deprecated direct P279 facts."""
    qids = " ".join(f"wd:{target.qid}" for target in targets)
    hierarchy = (
        ""
        if not include_hierarchy
        else """
    UNION
    { ?entity p:P279 ?parentStatement.
      ?parentStatement ps:P279 ?parent;
                       wikibase:rank ?parentRank.
      FILTER(STRSTARTS(STR(?parent), STR(wd:Q)))
      FILTER(?parentRank != wikibase:DeprecatedRank)
      OPTIONAL {
        ?parentStatement prov:wasDerivedFrom ?parentReference.
        OPTIONAL { ?parentReference pr:P854 ?parentReferenceUrl. }
      }
    }"""
    )
    return f"""PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>

SELECT ?entity ?entityKind ?label ?alias ?parent ?parentStatement ?parentRank
       ?parentReference ?parentReferenceUrl
WHERE {{
  VALUES ?entity {{ {qids} }}
  BIND("genre" AS ?entityKind)
  OPTIONAL {{
    {{ ?entity rdfs:label ?label.
       FILTER(LANG(?label) IN ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar", "hi")) }}
    UNION
    {{ ?entity skos:altLabel ?alias.
       FILTER(LANG(?alias) IN ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar", "hi")) }}
    {hierarchy}
  }}
}}
ORDER BY ?entity ?label ?alias ?parentStatement ?parent ?parentReference
LIMIT 20000
"""


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def prepare(database: Path, output: Path, *, labels_only: bool = False) -> dict[str, object]:
    """Write a hashed selection manifest and deterministic query shards."""
    query_mode: Literal["discover_direct_parents", "labels_only"] = (
        "labels_only" if labels_only else "discover_direct_parents"
    )
    selection = load_targets(database, query_mode)
    manifest_sha256 = _write(
        output / "genre-selection.json",
        selection.model_dump_json(indent=2).encode(),
    )
    query_hashes: dict[str, str] = {}
    for offset in range(0, len(selection.targets), selection.shard_size):
        ordinal = offset // selection.shard_size
        path = output / f"genres-{ordinal:02d}.rq"
        query = render_genre_query(
            selection.targets[offset : offset + selection.shard_size],
            include_hierarchy=not labels_only,
        )
        query_hashes[path.name] = _write(path, query.encode())
    return {
        "input_artifacts": len(selection.input_artifacts),
        "manifest_sha256": manifest_sha256,
        "query_files": len(query_hashes),
        "query_sha256": query_hashes,
        "targets": len(selection.targets),
    }


def main() -> int:
    """Prepare exact genre enrichment queries and print the bound manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--labels-only", action="store_true")
    args = parser.parse_args()
    result = prepare(args.database, args.output, labels_only=args.labels_only)
    sys.stdout.write(f"{json.dumps(result, indent=2, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
