# Wikidata music slice

The Wikidata source uses the bounded query in
[`config/wikidata_music_slice.rq`](../config/wikidata_music_slice.rq). It selects up to 50
source objects for each of five independently identified kinds: genre, artist, MusicBrainz
release group, MusicBrainz recording, and MusicBrainz work. The entity kind is established by
the dedicated MusicBrainz identifier property. It is never guessed from a label.

The query preserves QIDs, MusicBrainz IDs, ten label and alias languages, P136 genre statements,
P279 parent genres, P571 inception, P577 publication date, statement rank, reference nodes, and
reference URLs. An item that legitimately carries identifiers for more than one catalog kind is
projected into a separate catalog entity for each kind, and each entity retains the same Wikidata
QID. No name match or
automatic canonical redirect is created.

Run the current bounded export and ingest it with:

```sh
uv run poe ingest-wikidata
```

The task performs an async POST and retries only temporary errors. It applies byte and row limits,
hashes the query and response, and publishes the response to the content addressed vault. The
shared pipeline then records the snapshot, checkpoints, quarantine, policy, transaction, and
projection. A repeated exact artifact reuses its complete attempt.

## Measured run

The live export acquired on 2026-08-31 was 6,745,314 bytes with SHA256
`8b59cc299a1d4671ac7129ff978f9d241e42924e932e4a80f7f61be29c89fb66`. It contained 6,651 SPARQL
rows and 230 source entities: 48 artists, 36 genres, 50 recordings, 50 release groups, and 46
works. The first request returned a transient 502 and the retry succeeded.

The complete local ingest took 2.74 seconds and produced:

| Measure | Count |
| --- | ---: |
| Accepted source entities | 230 |
| Quarantined source entities | 0 |
| Catalog entities, including explicit QID genre targets | 362 |
| Names | 1,326 |
| Identifiers | 808 |
| Preserved claims | 346 |
| Direct artist genre observations | 39 |
| Direct album genre observations | 98 |
| Genre hierarchy relations | 42 |

The SQLite database was 2,572,288 bytes. An exact replay completed in 0.018 seconds and reused the
same attempt without adding records.

## Full dump decision

The dated full JSON dump is about 102.8 GB compressed and the truthy RDF dump is about 43.3 GB
compressed. Although the machine had 244 GB free, neither is safe for a first laptop ingest once
expansion, vault retention, checkpoints, and a second working copy are included. Full dump parsing
remains available as an offline adapter direction. The bounded export is the reproducible starting
slice.
