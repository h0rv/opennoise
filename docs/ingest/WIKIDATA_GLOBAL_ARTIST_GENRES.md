# Bounded Wikidata global artist genre sample

`scripts/acquire_wikidata_global_artist_genres.py` captures an open source cohort
that is independent of the curated Every Noise seed and commercial streaming
labels. Its pinned query selects direct Wikidata P136 claims whose value is an
instance of musical genre (Q188451), joined to MusicBrainz artist UUIDs through
P434. It requests at most 20,001 rows so the 20,000-row usable cap is detectable.

The script verifies the complete 2,999,670-row CC0 core artist identity
projection by streaming its 95,458,405 compressed bytes and matching the
identity receipt's SHA-256 and row count. UUIDs found by the source query are
ranked by a fixed SHA-256 function before Wikidata labels are fetched. At most
3,000 IDs are selected. UUIDs absent from the core, duplicate core UUIDs,
duplicate P434 QIDs, reused QIDs, and labels that do not match the native core
name after NFKC case folding are excluded from resolved claims. Name comparison
only checks candidate coherence; it does not join records.

Artist English labels and P31 types and genre English labels are hydrated in no
more than 20 follow-up requests. Each response is capped at 2 MB, the initial
scan at 10 MB, and total captured response bytes at 20 MB. Genre labels beyond
the request cap remain explicitly unhydrated. Request failures and capped
responses remain in the evidence pack. The complete pack, including query
responses, selection, projection, manifest, and hash receipt, is kept in
`.cache/wikidata-global-musical-artists-20261002-v1`; it is local research data
and is not part of a release.

Replay and verify an existing pack offline with:

```sh
.venv/bin/python scripts/acquire_wikidata_global_artist_genres.py --verify
```

The scan is capped and selected by UUID hash. It makes no full coverage claim.
Every P136 value remains a direct Wikidata source assertion, not a human
reviewed genre judgment. Wikidata structured data is CC0; the separate
MusicBrainz input contributes only CC0 artist UUID and native-name identities.

The first detail batches used 500 pairs and received HTTP 503 reset responses.
Those response bodies remain in the pack. Retrying the same frozen roster in
smaller batches yielded valid SPARQL JSON bodies for 650 artist pairs. The
capture process ended before committing HTTP status metadata for those retry
bodies, so the manifest records their HTTP status as unknown while offline
replay validates each body against its requested exact QID/UUID pairs. The
remaining roster stays unresolved; no claim is inferred from missing details.
