# Browse retained recordings by exact credited artist

An ordinary caller can now start from a canonical MusicBrainz artist ID and
retrieve paged recording contexts, optionally filtered by the same literal title
matching as the [title query](../recording-title-search-20261021/README.md).
Previously artist navigation exposed genres and related artists, while recording
queries required a recording ID or title. `artist_works` ranks a supplied pool;
it does not discover the retained native credit pool.

`PublicRecordingNavigationStore.recordings_for_artist(artist_mbid,
title_filter=None, offset=0, limit=10, genre_limit=10, related_limit=5)` returns
`ArtistRecordingsResponse.results`, a tuple of the existing full recording
contexts. This is a browse of **retained primary-credit recordings**, not a
complete discography, popularity ranking or musical recommendation. Artist genre
context remains each credited artist's own direct source context; it does not
assert recording genre membership.

## Query contract

The exact seed artist identity and a source name each require local_search and
display permission on the same observation. The recording identity and emitted
title also require both uses on their own observations. A matching primary-credit
link and its credit definition require both uses, and the credit must survive
intact display authorization of every member. At least one independently eligible
intact matching observation establishes the association. A withheld duplicate
does not veto another allowed observation; conflicting eligible whole credits
omit the recording. There is no name, album, release or component identity fallback.
Unknown and unavailable seed artists return the same empty shape, with only the
caller-supplied MBID echoed.

Eligibility, association and context reads share one read transaction. Recording
IDs are deduplicated before pagination, sorted by normalized authorized title then
native recording MBID. The optional filter uses Unicode NFKC, casefold and
whitespace normalization followed by literal substring matching, without wildcard
syntax, fuzzy joins or diacritic guessing. Equal titles retain separate MBIDs.
Limits are 1–10 results, offset 0–10,000, meaningful alphanumeric filters of at most
200 characters, 10,000 raw matching credit observations, and 100,000 seed/name
observations or candidate recording-title observations. Bounds fail explicitly;
no hidden total or silently truncated candidate pool is returned. Structurally
malformed, gapped or oversized credit definitions, PR99's 64-observation bound,
identity ambiguity and raw scan overflow abort the whole request; no partial page
is returned. Rights-withheld credits and eligible conflicting whole-credit status
omit the association instead. Existing credit/member/context bounds remain in force.

## Reproduce

The paths below are current-executor examples, not tracked inputs or a promise of
future custody. The retained CC0 catalog must first be rebuilt using the
[registered core-custody recipe](../recording-source-context-20261020/README.md),
or supplied as an independently pinned standalone SQLite file. Missing approved
inputs are a blocked build, not permission to invent source custody. Old sealed
catalogs without that inventory remain unavailable under the existing gates.

```sh
PYTHONPATH=src .venv/bin/poe sync
PYTHONPATH=src .venv/bin/python scripts/query_recording_context.py \
  --database /workspace/recording-title-search-20261021/catalog/musicbrainz-first.sqlite \
  --database-sha256 c748a6efcf11a91ac241fd8783b62f1de682db813b0e753254f26e9d2c00640e \
  --artist-mbid e20747e7-55a4-452e-8766-7b985585082d --limit 10
PYTHONPATH=src .venv/bin/python scripts/query_recording_context.py \
  --database /workspace/recording-title-search-20261021/catalog/musicbrainz-first.sqlite \
  --database-sha256 c748a6efcf11a91ac241fd8783b62f1de682db813b0e753254f26e9d2c00640e \
  --artist-mbid e20747e7-55a4-452e-8766-7b985585082d --title-filter 'Be-Bop Tango'
PYTHONPATH=src .venv/bin/python -m unittest tests.serving.public.test_artist_recording_browse
PYTHONPATH=src .venv/bin/poe check
```

`--artist-mbid`, `--query` and `--recording-mbid` are exclusive entry modes;
`--title-filter` is valid only with the artist mode. Prior modes remain available.
The CLI retains externally pinned immutable SQLite reads, sidecar rejection,
before/after hash checks, 100 MB database, 2 MB output and 120-second/1 GB limits.

## Retained evidence and limits

The fixed source pool has 351 credited artists, 1,242 distinct artist–recording
edges and 1,031 recordings. Ninety-six artists have multiple retained recordings;
the largest pool has 68. Frank Zappa's exact artist ID exposes that 68-recording
pool without requiring callers to know its titles. Five duplicate-title groups
share a credited artist, so even the combined artist/title filter preserves
ambiguity. There are 1,237 distinct full-title filters within the artist pools.

The native edge oracle was sealed before implementation. Independent ordinary
consumer comparisons use retained core credits and separately pinned hydration
titles, not new upstream requests or invented recording-title facts. Safe cached
credit projections do not retain title fields; the track-derived display-title
custody and prior assessment header correction are documented in the title recipe.
Source packs are MusicBrainz/Wikidata CC0; no NC research data or model is used.
The independent final ordinary-consumer proof checked both ingestion orders:
761 artist pages, 1,237 title-filter queries, five shared-artist duplicate-title
checks and 2,515 full contexts per order exactly matched the independently frozen
native credit oracle and prior verified recording contexts. All 47 actual-catalog
controls passed, including 45 exact suppression releases, intact co-artist
withholding, independent duplicate support, eligible conflicts, pre-page gates,
hidden duplicate owners and hard malformed-credit errors. Network, process and
SQLite-write denial probes were active; actual forbidden attempts were zero and
the externally pinned input databases remained unchanged. The native edge-order
hash was identical in both orders. This verifies source traversal, not relevance
or completeness beyond this retained pool. See `results.json` for exact source,
runtime, corpus-proof and check pins.

No source acquisition, supervised fitting, new judgment or quality measurement was
performed. The stopped Jamendo study and reserved style fold remain unchanged.

The final full `poe check` passed formatting, linting and type checks, 2,445 Python
tests (36 skips, 278.559 seconds), and 122 Node tests (44 skips). The eight focused
browse tests passed in 22.846 seconds. Local logs are recorded in `results.json`;
publication and CI are tracked by the source pull request.
