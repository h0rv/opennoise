"""Prepare exact-QID Wikidata detail shards from bounded media discovery results."""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter

from musix.models import FrozenModel

type MediaKind = Literal["release_group", "recording"]
QID_PATTERN = r"^Q[1-9][0-9]*$"
MBID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
DETAIL_SHARD_SIZE = 100
MEDIA_KIND_ADAPTER = TypeAdapter(MediaKind)


class MediaIdentity(FrozenModel):
    """One exact bijective Wikidata and MusicBrainz media identity."""

    entity_kind: MediaKind
    qid: str = Field(pattern=QID_PATTERN)
    musicbrainz_id: str = Field(pattern=MBID_PATTERN)


class MediaDetailSelection(FrozenModel):
    """Bind detail queries to exact discovery artifacts and identities."""

    schema_version: Literal[1] = 1
    discovery_artifacts: tuple[str, ...]
    identities: tuple[MediaIdentity, ...]
    shard_size: int = DETAIL_SHARD_SIZE


def load_discovery(database: Path) -> MediaDetailSelection:
    """Load only identities projected by the bounded Phase 3 discovery sources."""
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """SELECT DISTINCT entity.entity_kind,
                      qid.normalized_value, mbid.normalized_value
               FROM catalog_entities AS entity
               JOIN entity_identifiers AS qid ON qid.entity_id = entity.id
               JOIN identifier_types AS qid_type ON qid_type.id = qid.identifier_type_id
               JOIN entity_identifiers AS mbid ON mbid.entity_id = entity.id
               JOIN identifier_types AS mbid_type ON mbid_type.id = mbid.identifier_type_id
               WHERE qid.namespace = 'wikidata'
                 AND qid_type.type_key IN (
                   'wikidata_release_group_qid', 'wikidata_recording_qid'
                 )
                 AND mbid.namespace = 'musicbrainz'
                 AND mbid_type.type_key IN (
                   'musicbrainz_release_group_id', 'musicbrainz_recording_id'
                 )
                 AND EXISTS (
                   SELECT 1
                   FROM entity_provenance AS link
                   JOIN provenance_records AS provenance ON provenance.id = link.provenance_id
                   JOIN data_sources AS source ON source.id = provenance.source_id
                   WHERE link.entity_id = entity.id
                     AND source.source_key LIKE 'wikidata_phase3_%_discovery_%'
                 )
               ORDER BY entity.entity_kind, qid.normalized_value, mbid.normalized_value"""
        ).fetchall()
        artifacts = connection.execute(
            """SELECT DISTINCT artifact.sha256
               FROM source_artifacts AS artifact
               JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
               JOIN data_sources AS source ON source.id = snapshot.source_id
               WHERE source.source_key LIKE 'wikidata_phase3_%_discovery_%'
               ORDER BY artifact.sha256"""
        ).fetchall()
    identities = tuple(
        MediaIdentity(
            entity_kind=MEDIA_KIND_ADAPTER.validate_python(row[0], strict=True),
            qid=str(row[1]),
            musicbrainz_id=str(row[2]),
        )
        for row in rows
    )
    by_qid: dict[tuple[MediaKind, str], set[str]] = defaultdict(set)
    by_mbid: dict[tuple[MediaKind, str], set[str]] = defaultdict(set)
    for identity in identities:
        by_qid[(identity.entity_kind, identity.qid)].add(identity.musicbrainz_id)
        by_mbid[(identity.entity_kind, identity.musicbrainz_id)].add(identity.qid)
    if any(len(values) != 1 for values in (*by_qid.values(), *by_mbid.values())):
        raise RuntimeError("media discovery contains an ambiguous exact identity")
    if not identities or not artifacts:
        raise RuntimeError("media discovery produced no exact identities or artifacts")
    return MediaDetailSelection(
        discovery_artifacts=tuple(str(row[0]) for row in artifacts),
        identities=identities,
    )


def render_detail_query(identities: tuple[MediaIdentity, ...], kind: MediaKind) -> str:
    """Render full labels, aliases, dates, and referenced P136 for exact QIDs."""
    qids = " ".join(f"wd:{identity.qid}" for identity in identities)
    identifier_property = "P436" if kind == "release_group" else "P4404"
    return f"""PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>

SELECT ?entity ?entityKind ?label ?alias ?musicbrainzId ?genre ?statement
       ?rank ?reference ?referenceUrl ?inception ?publicationDate
WHERE {{
  VALUES ?entity {{ {qids} }}
  ?entity wdt:{identifier_property} ?musicbrainzId.
  FILTER(REGEX(STR(?musicbrainzId),
    "^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$"))
  FILTER NOT EXISTS {{
    ?otherEntity wdt:{identifier_property} ?musicbrainzId.
    FILTER(?otherEntity != ?entity)
  }}
  FILTER NOT EXISTS {{
    ?entity wdt:{identifier_property} ?otherMusicbrainzId.
    FILTER(?otherMusicbrainzId != ?musicbrainzId)
  }}
  BIND("{kind}" AS ?entityKind)
  OPTIONAL {{
    {{ ?entity rdfs:label ?label.
       FILTER(LANG(?label) IN ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar", "hi")) }}
    UNION
    {{ ?entity skos:altLabel ?alias.
       FILTER(LANG(?alias) IN ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar", "hi")) }}
    UNION
    {{ ?entity wdt:P571 ?inception. }}
    UNION
    {{ ?entity wdt:P577 ?publicationDate. }}
    UNION
    {{ ?entity p:P136 ?statement.
       ?statement ps:P136 ?genre;
                  wikibase:rank ?rank.
       FILTER(STRSTARTS(STR(?genre), STR(wd:Q)))
       FILTER(?rank != wikibase:DeprecatedRank)
       OPTIONAL {{
         ?statement prov:wasDerivedFrom ?reference.
         OPTIONAL {{ ?reference pr:P854 ?referenceUrl. }}
       }}
    }}
  }}
}}
ORDER BY ?entity ?label ?alias ?statement ?genre ?reference
LIMIT 20000
"""


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def prepare(database: Path, output: Path) -> dict[str, object]:
    """Write an exact selection manifest and bounded detail query files."""
    selection = load_discovery(database)
    manifest_sha256 = _write(
        output / "media-selection.json",
        selection.model_dump_json(indent=2).encode(),
    )
    query_hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    for kind in ("release_group", "recording"):
        identities = tuple(item for item in selection.identities if item.entity_kind == kind)
        counts[kind] = len(identities)
        for offset in range(0, len(identities), DETAIL_SHARD_SIZE):
            ordinal = offset // DETAIL_SHARD_SIZE
            path = output / f"{kind}-details-{ordinal:02d}.rq"
            query = render_detail_query(identities[offset : offset + DETAIL_SHARD_SIZE], kind)
            query_hashes[path.name] = _write(path, query.encode())
    return {
        "counts": counts,
        "discovery_artifacts": len(selection.discovery_artifacts),
        "manifest_sha256": manifest_sha256,
        "query_files": len(query_hashes),
        "query_sha256": query_hashes,
    }


def main() -> int:
    """Prepare media detail shards and print exact identities."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.stdout.write(
        f"{json.dumps(prepare(args.database, args.output), indent=2, sort_keys=True)}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
