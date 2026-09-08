# Offline MSD Last.fm evidence

`build-msd-lastfm-evidence` reads exactly three local SQLite databases:
`track_metadata.db`, `lastfm_tags.db`, and `lastfm_similars.db`. It never
accepts an MSD directory, HDF5 data, music files, audio features, Spotify, or
H3/historical construction inputs.

The official Million Song Dataset describes Last.fm as **song-level tags and
similarity**, not artist genre ground truth, on its [home page](https://millionsongdataset.com/)
and [tasks page](https://millionsongdataset.com/pages/tasks-demos). Its
[FAQ](https://millionsongdataset.com/faq) identifies `track_metadata.db` as the
SQLite database used to locate a track's artist information. The official
metadata-only endpoints are:

| Role | URL |
| --- | --- |
| MSD artist metadata | `https://millionsongdataset.com/sites/default/files/AdditionalFiles/track_metadata.db` |
| Last.fm track tags | `https://millionsongdataset.com/sites/default/files/lastfm/lastfm_tags.db` |
| Last.fm directed track similarity | `https://millionsongdataset.com/sites/default/files/lastfm/lastfm_similars.db` |

No current checksum or byte-size declaration was found in official MSD
documentation. On 2026-09-06 the official host was unreachable from the build
environment, so this repository intentionally does not invent those values or
start a large download. Therefore every manually supplied SQLite file is
labelled `unverified_local_input`: its SHA-256 records local custody only, and
the URL and timestamp are informational, not an official-acquisition
attestation. The source cache is local custody: the raw multi-GB SQLite files
are not published to the object store.

The adapter reads SQLite in read-only/query-only mode and uses `fetchmany()`.
Similarity has explicit row and edge bounds (200,000 and 1,000,000 by default);
tag input, support output, and name-only-review output each have a 2,000,000
row cap. Exceeding any cap or encountering a duplicate exact source row fails
the build rather than silently producing a partial artifact.
It maps exact normalized Last.fm labels to the complete 6,291 target labels
from the sealed seed reconciliation artifact. An exact tag only becomes
`exact_track_tag_support` when `track_metadata.db` supplies a valid MusicBrainz
artist ID. A source artist name without a valid MBID is a name-only review row.
An MBID linked to two exact target labels remains an explicit conflict. Each
unmapped target gets an abstention.

Similarity remains directed track-similarity support. Both source and target
tracks need valid metadata MBIDs; the adapter does not join artist names or
construct Spotify/H3-derived edges.

The artifact reports deterministic cumulative artist/target coverage at 25%,
50%, 75%, and 100% of a stable support ordering. Its held-out metric removes a
deterministic fifth of `(artist MBID, target, track)` anchors and measures only
whether another track from that same artist retains the same exact target tag.
It is source redundancy recovery, not an independent genre-quality score.

```sh
uv run poe build-msd-lastfm-evidence
```

For an already verified cache receipt, run the script directly with
`--reuse-source-cache-receipt`; this validates every cache file before SQLite
is opened and does not make network requests.

The focused SQLite fixture has two target labels and four tracks. It produces
three MBID-linked exact tag-support rows, one name-only review, one directed
similarity support, one multi-target artist conflict, and zero abstentions.
This is a schema/provenance test, not a claim about live MSD coverage.
