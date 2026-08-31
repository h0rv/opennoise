"""Prepare deterministic Wikidata query shards from the public co-listen graph."""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from musix.models import FrozenModel

MBID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
MAX_SHARD_SIZE = 500
MAX_MEDIA_SHARD_SIZE = 200
MEDIA_KINDS: tuple[Literal["release_group", "recording"], ...] = (
    "release_group",
    "recording",
)


class RankedArtist(FrozenModel):
    """One exact artist identity selected from aggregate graph support."""

    musicbrainz_id: str = Field(pattern=MBID_PATTERN)
    weighted_degree: int = Field(gt=0)
    neighbor_count: int = Field(gt=0)
    active_windows: int = Field(gt=0)


class Phase3Selection(FrozenModel):
    """Record the exact deterministic selection and its aggregate input."""

    schema_version: Literal[1] = 1
    strategy: Literal["weighted_degree_desc_neighbors_desc_windows_desc_mbid"]
    aggregate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_ref: str = Field(min_length=1)
    requested_limit: int = Field(gt=0, le=2_000)
    shard_size: int = Field(gt=0, le=500)
    media_shard_size: int = Field(gt=0, le=200)
    artists: tuple[RankedArtist, ...]


def select_artists(database: Path, limit: int) -> Phase3Selection:
    """Select graph artists by deterministic aggregate centrality."""
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        output = connection.execute(
            """SELECT content_sha256 FROM derived_outputs
               WHERE output_kind = 'multi_source_aggregate'
                 AND output_ref = 'listenbrainz_joint_20260824_20260830'"""
        ).fetchone()
        if output is None or output[0] is None:
            raise RuntimeError("joint ListenBrainz aggregate identity is missing")
        runs = connection.execute(
            """SELECT run.run_ref, run.ingest_attempt_id
               FROM artist_co_listen_runs AS run
               JOIN source_artifacts AS artifact ON artifact.id = run.artifact_id
               JOIN source_snapshots AS snapshot ON snapshot.id = artifact.snapshot_id
               JOIN data_sources AS source ON source.id = snapshot.source_id
               WHERE source.source_key = 'listenbrainz_joint_20260824_20260830'
                 AND artifact.sha256 = ?""",
            (str(output[0]),),
        ).fetchall()
        if len(runs) != 1:
            raise RuntimeError("expected exactly one joint ListenBrainz run")
        run_ref, attempt_id = str(runs[0][0]), int(runs[0][1])
        rows = connection.execute(
            """WITH endpoints AS (
                 SELECT left_artist_source_id AS artist_ref,
                        right_artist_source_id AS neighbor_ref,
                        window_start,
                        distinct_user_count AS support
                 FROM artist_co_listen_evidence
                 WHERE ingest_attempt_id = ?
                 UNION ALL
                 SELECT right_artist_source_id, left_artist_source_id,
                        window_start, distinct_user_count
                 FROM artist_co_listen_evidence
                 WHERE ingest_attempt_id = ?
               )
               SELECT substr(artist_ref, length('musicbrainz:artist:') + 1),
                      sum(support), count(DISTINCT neighbor_ref),
                      count(DISTINCT window_start)
               FROM endpoints
               GROUP BY artist_ref
               ORDER BY sum(support) DESC, count(DISTINCT neighbor_ref) DESC,
                        count(DISTINCT window_start) DESC, artist_ref
               LIMIT ?""",
            (attempt_id, attempt_id, limit + 1),
        ).fetchall()
    if len(rows) > limit:
        rows = rows[:limit]
    artists = tuple(
        RankedArtist(
            musicbrainz_id=str(row[0]),
            weighted_degree=int(row[1]),
            neighbor_count=int(row[2]),
            active_windows=int(row[3]),
        )
        for row in rows
    )
    if not artists:
        raise RuntimeError("joint ListenBrainz graph contains no artist identities")
    return Phase3Selection(
        strategy="weighted_degree_desc_neighbors_desc_windows_desc_mbid",
        aggregate_sha256=str(output[0]),
        run_ref=run_ref,
        requested_limit=limit,
        shard_size=200,
        media_shard_size=200,
        artists=artists,
    )


def render_artist_query(artists: Sequence[RankedArtist]) -> str:
    """Render one bounded exact-MBID artist evidence query."""
    values = "\n".join(f'    "{artist.musicbrainz_id}"' for artist in artists)
    return f"""PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>

SELECT ?entity ?entityKind ?label ?alias ?musicbrainzId ?genre ?statement
       ?rank ?reference ?referenceUrl ?inception
WHERE {{
  VALUES ?musicbrainzId {{
{values}
  }}
  ?entity wdt:P434 ?musicbrainzId.
  FILTER NOT EXISTS {{
    ?otherEntity wdt:P434 ?musicbrainzId.
    FILTER(?otherEntity != ?entity)
  }}
  FILTER NOT EXISTS {{
    ?entity wdt:P434 ?otherMusicbrainzId.
    FILTER(?otherMusicbrainzId != ?musicbrainzId)
  }}
  BIND("artist" AS ?entityKind)
  OPTIONAL {{
    {{ ?entity rdfs:label ?label.
       FILTER(LANG(?label) IN ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar", "hi")) }}
    UNION
    {{ ?entity skos:altLabel ?alias.
       FILTER(LANG(?alias) IN ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar", "hi")) }}
    UNION
    {{ ?entity wdt:P571 ?inception. }}
    UNION
    {{ ?entity p:P136 ?statement.
       ?statement ps:P136 ?genre;
                  wikibase:rank ?rank.
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


def render_media_discovery_query(
    artists: Sequence[RankedArtist], entity_kind: Literal["release_group", "recording"]
) -> str:
    """Select a bounded exact-ID media cohort before fetching claim details."""
    values = "\n".join(f'    "{artist.musicbrainz_id}"' for artist in artists)
    identifier_property = "P436" if entity_kind == "release_group" else "P4404"
    return f"""PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>

SELECT DISTINCT ?entity ?entityKind ?musicbrainzId
WHERE {{
  VALUES ?selectedMusicbrainzId {{
{values}
  }}
  ?selectedArtist wdt:P434 ?selectedMusicbrainzId.
  FILTER NOT EXISTS {{
    ?otherArtist wdt:P434 ?selectedMusicbrainzId.
    FILTER(?otherArtist != ?selectedArtist)
  }}
  FILTER NOT EXISTS {{
    ?selectedArtist wdt:P434 ?otherSelectedMusicbrainzId.
    FILTER(?otherSelectedMusicbrainzId != ?selectedMusicbrainzId)
  }}
  ?entity wdt:P175 ?selectedArtist;
          wdt:{identifier_property} ?musicbrainzId;
          p:P136 ?statement.
  FILTER(REGEX(STR(?musicbrainzId),
    "^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$"))
  ?statement ps:P136 ?genre;
             wikibase:rank ?rank.
  FILTER(?rank != wikibase:DeprecatedRank)
  FILTER NOT EXISTS {{
    ?otherEntity wdt:{identifier_property} ?musicbrainzId.
    FILTER(?otherEntity != ?entity)
  }}
  FILTER NOT EXISTS {{
    ?entity wdt:{identifier_property} ?otherMusicbrainzId.
    FILTER(?otherMusicbrainzId != ?musicbrainzId)
  }}
  BIND("{entity_kind}" AS ?entityKind)
}}
ORDER BY ?entity
LIMIT 100
"""


def _write_exact(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def prepare(
    database: Path,
    output: Path,
    limit: int,
    shard_size: int,
    media_shard_size: int,
) -> dict[str, object]:
    """Write one selection manifest and its deterministic query shards."""
    selection = select_artists(database, limit).model_copy(
        update={"shard_size": shard_size, "media_shard_size": media_shard_size}
    )
    manifest = selection.model_dump_json(indent=2).encode()
    manifest_sha256 = _write_exact(output / "selection.json", manifest)
    query_hashes: dict[str, str] = {}
    for offset in range(0, len(selection.artists), shard_size):
        ordinal = offset // shard_size
        shard = selection.artists[offset : offset + shard_size]
        path = output / f"artists-{ordinal:02d}.rq"
        query_hashes[path.name] = _write_exact(path, render_artist_query(shard).encode())
    for offset in range(0, len(selection.artists), media_shard_size):
        ordinal = offset // media_shard_size
        shard = selection.artists[offset : offset + media_shard_size]
        for entity_kind in MEDIA_KINDS:
            label = "release-groups" if entity_kind == "release_group" else "recordings"
            path = output / f"{label}-discovery-{ordinal:02d}.rq"
            query = render_media_discovery_query(shard, entity_kind)
            query_hashes[path.name] = _write_exact(path, query.encode())
    return {
        "aggregate_sha256": selection.aggregate_sha256,
        "artists": len(selection.artists),
        "manifest_sha256": manifest_sha256,
        "query_sha256": query_hashes,
        "artist_shards": len(selection.artists[::shard_size]),
        "media_shards": len(selection.artists[::media_shard_size]),
        "query_files": len(query_hashes),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--shard-size", type=int, default=200)
    parser.add_argument("--media-shard-size", type=int, default=200)
    return parser


def main() -> int:
    """Prepare shards and print their exact identities."""
    args = _parser().parse_args()
    if not 0 < args.shard_size <= MAX_SHARD_SIZE:
        raise ValueError("shard size must be between 1 and 500")
    if not 0 < args.media_shard_size <= MAX_MEDIA_SHARD_SIZE:
        raise ValueError("media shard size must be between 1 and 200")
    result = prepare(
        args.database,
        args.output,
        args.limit,
        args.shard_size,
        args.media_shard_size,
    )
    sys.stdout.write(f"{json.dumps(result, indent=2, sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
