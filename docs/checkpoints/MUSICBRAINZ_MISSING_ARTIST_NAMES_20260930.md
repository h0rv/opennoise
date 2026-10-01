# Official exact-ID artist name enrichment

The retained portable catalog has 198,409 artist UUIDs, 387,435 distinct direct
artist–seed pairs, and 697 genre seeds. Its initial canonical-name custody resolves
164,404 artists (82.8612%) and 338,327 direct pairs. The official native genre
dictionary already resolves all 697 observed seed labels; missing artist names
are the largest immediately usable display-metadata gap in these inputs.

The new local overlay queries every one of the 34,005 unresolved artist UUIDs in
341 bounded official MusicBrainz artist-search batches. It resolves 33,986 names,
bringing combined name coverage to **198,390 / 198,409 artists (99.9904%)** and
**387,414 / 387,435 direct pairs (99.9946%)**. Nineteen artist identities and 21
direct pairs still lack exact-ID current names. All newly resolved labels have
usable display forms. The combined labels contain 6,334 homonym groups; artist
UUIDs remain distinct and no memberships transfer between matching names.

These are metadata coverage results for the retained MusicBrainz source cohort.
They do not establish Every Noise artist, genre, ranking, map, or audio parity.
The base catalog and its historical name strings remain byte-identical. New names
are observed current metadata rather than corrections of the original source.

## Source and replay contract

The acquisition uses `https://musicbrainz.org/ws/2/artist` with a Lucene query
`arid:(UUID OR UUID ...)`, JSON responses, and `limit=100`. Each batch has at most
100 canonical UUIDs selected from unresolved base artists in descending direct
seed support, then UUID order. Selection is capped at 40,000 artists: at most
400 batches, with three attempts per batch. Requests run sequentially at least
1.1 seconds apart. Every response is capped at 2 MiB, and receipt metadata and
the final projection have separate byte bounds. Existing complete cache pages
are verified and reused without HTTP requests.

The 341 retained source responses total 23,416,908 bytes and were observed from
2026-09-30 17:59:49 UTC through 18:09:07 UTC. Only `id` and `name` enter the
enrichment. Responses can contain tags and other source fields; their retention
does not project them, license them as CC0, or authorize their use as memberships.
The CC0 scope declaration applies only to projected artist identity and name
core metadata. The overlay adds zero membership claims and authorizes no public
export. Historical memberships, labels, positions, and artist assignments were
not consulted.

The verifier first rechecks the base catalog, then recomputes its exact unresolved
cohort. For each source response it checks byte length, SHA-256, official request
URL, requested UUIDs, offset, declared result count, uniqueness, and returned-ID
containment. Search scores do not resolve identities. Returned identities outside
the exact requested set fail replay; omitted identities remain explicit
`missing_official_identity` abstentions. Display normalization preserves source
strings and never changes artist IDs. Final row provenance records a response
hash and batch index, with the exact URL retained once in the page binding.

Three diagnostic lookup requests sampled from the nineteen current-search
absences returned HTTP 301 to different canonical UUIDs. This limited diagnostic
does not establish the causes for the other sixteen absences, and redirects are
not used to substitute names or propagate memberships in this exact-ID overlay.

## Artifacts and reproduction

The overlay is `.cache/musicbrainz-missing-artist-names/name-enrichment.json`,
11,343,392 bytes. It is tied to the base catalog receipt hash
`43593ab9702da7cc3b2c6837e96cd337cfa924556d1f931a7a383a3a00eed0b0`
and direct observation object hash
`b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e`.

- Overlay logical hash:
  `77cd5f7ac77e2cbd37bd7c3fb53c0f360f2e0f24b497c3ff285366dd4be04816`
- Overlay byte hash:
  `5236e0ffc44572bd024d9f67ba7bf1bd43ebe5442d0f0ddd547470a71455ff47`
- Base database byte hash:
  `a0cada0ad8a1207a02ffbebdb50b0aab47672466757c927d9cbbd1460bdf21c5`

From a synchronized checkout, use an existing verified catalog and a new local
destination for acquisition:

```sh
.venv/bin/python scripts/enrich_local_musicbrainz_artist_names.py \
  --catalog-directory .cache/musicbrainz-candidate-catalog-final \
  --output-directory .cache/musicbrainz-missing-artist-names
```

Offline replay creates no HTTP client and must return the same logical hash:

```sh
.venv/bin/python scripts/enrich_local_musicbrainz_artist_names.py \
  --catalog-directory .cache/musicbrainz-candidate-catalog-final \
  --output-directory .cache/musicbrainz-missing-artist-names --verify-only
```

Both final acquisition replay and a separate offline verification passed with
the identical logical hash. Ruff formatting and lint, type checks, and fifteen
catalog/enrichment tests passed. Nine new tests cover exact UUID joins, immutable
base bytes, source-field exclusion, duplicate or foreign IDs, absent identities,
unusable display names, rehashed projection/policy mutation, raw byte/URL
mutation, bounded destinations, and resumable acquisition with zero HTTP calls.

Consumers may call `verify_artist_name_enrichment(catalog_directory=..., directory=...)`
and join only verified rows to the same base UUIDs after source model/layout
construction. Names improve search and readable display; they contribute no
observations or geometric evidence. The overlay remains a local research
artifact rather than a public release or a promotion decision.
