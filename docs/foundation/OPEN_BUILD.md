# Independent portable open build

The unavailable historical canonical release cannot be reconstructed exactly from
this checkout. `data/public.sqlite` must hash to
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`;
`.cache/semantic-map-layout-v3/artifact.json` must hash to
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.
Neither is present. The retained historical vault is approximately 3.7 MB, rather
than the 62-object 1.54 GB Phase 3 open metadata vault. Layout construction also
needs the original peer, hierarchy and co-listen adapter artifacts. Matching
catalog names cannot recover the sealed database's provenance, timestamps,
schema or bytes, and cannot establish layout equivalence. The legacy promotion
and sealed deployment checks retain their original pins and fail closed.

A separate CC0 path builds real source projections from retained open responses:

```sh
.venv/bin/python scripts/build_open_foundation.py legacy-inputs
.venv/bin/python scripts/build_open_foundation.py build \
  --output .cache/open-foundation-portable-v1
.venv/bin/python scripts/build_open_foundation.py validate \
  --output .cache/open-foundation-portable-v1
.venv/bin/python scripts/run_dev.py \
  --directory .cache/open-foundation-portable-v1
```

Use `--root /path/to/checkout` to select a checkout. Each build requires a new
output directory and makes no network requests. These scripts are library/CLI
entry points, not new Poe tasks. `poe dev` continues serving `dist` unless the
integration workflow selects this new export. `poe deploy` remains the sealed
release path; the portable build grants no deployment authorization.

The default source roster unions the earlier 110 identity-only requested artists
and 42 independently curated exact MusicBrainz identities. Aphex Twin and Four
Tet overlap, giving 150 unique artists. The earlier cohort's selection involved
optional MusicBrainz supplementary genres; those selection values were removed
from the portable pack, and none enter this builder. Cohort selection bias
remains a limit. Unmatched requested identities stay searchable with explicit
missingness. The independent pack adds native Wikidata direct claims, not
historical labels or coordinates. Several artists still have no observed genre.

Each output contains:

- `catalog.sqlite`: a new schema-v1 normalized artist, genre, direct-claim and
  exact recording-credit projection, independently named and deterministic.
- `data.json`: the complete selected artist roster, native direct claims,
  provenance, missingness, bounded credited recordings and source-declared
  listening destinations. Artist destinations do not resolve recording playback.
- `layout.json`: an alphabetical presentation grid. Every genre abstains from
  semantic coordinates; the grid has no musical axes.
- A small static explorer with search, exact IDs, full artist and genre cohorts,
  URL fragment history and reload, keyboard controls, mobile layout, metadata
  links and the browser-local listening list.
- `receipt.json`: byte hashes for every source member, adapter implementation,
  static asset and output, plus the SQLite logical hash and explicit partial
  scope. `legacy-inputs.json` reports the separate unavailable release boundary.

Validation replays native Wikidata responses through exact P434 identities,
MusicBrainz recording responses through literal artist credits, and MusicBrainz
URL relationships. It verifies every output member, checks SQLite integrity and
foreign keys, and compares every SQL row to source replay. Rewriting a generated
membership table and its receipt hashes cannot pass the source comparison.
Acoustic summaries have checked projection custody and finite numeric values;
the portable example does not contain their native raw captures, so the receipt
explicitly calls them **projection-only**, never native raw replay. No model
suggestions, semantic coordinates, audio, historical memberships, Spotify API
resources, or noncommercial research artifacts enter construction. Source
MusicBrainz provider URL relationships can include Spotify destinations.

This is a runnable **partial selected-cohort foundation**, not a 150-artist
substitution for full Every Noise coverage. Independent recommendation quality,
large-scale overlapping communities, semantic map quality, complete discography,
full-source coverage and calibrated musical fit remain missing. The separate
[acceptance dossier](ACCEPTANCE.md) continues reporting those gaps. The optional
[core identity projection](../checkpoints/CORE_ARTIST_IDENTITIES_20261002.md)
contains approximately three million CC0 artist identities; names alone add no
genres, memberships or recommendations and are not silently merged into this
portable profile. Local custody-only/noncommercial catalogs with
`serving_authorized=false` are never served by this path.

For browser verification, serve the export on loopback and run the retained
Chromium harness into a fresh evidence directory:

```sh
node scripts/capture_open_foundation.mjs http://127.0.0.1:3000/ \
  .cache/open-foundation-browser-v1
```

The harness exercises exact-ID keyboard search, selection, history, reload,
every complete genre cohort, all ten native recording-credit benchmark routes,
missing genre evidence, the listening list, mobile overflow and static-only
network requests. `report.json` binds the checked export file hashes; screenshots
are review evidence rather than assertions of musical quality.

An optional `--profile portable-taxonomy` adds the independently captured 1,000
Wikidata genre entities, P279-only source neighborhoods, component-local graph
positions and explicit unpositioned genres. It links the unchanged portable
artist explorer under `artists/` and retains exact direct claims without taxonomy
inheritance. See the [source graph checkpoint](../checkpoints/OPEN_TAXONOMY_NEIGHBORHOODS_20261003.md)
for commands, frozen holdouts, poor recovery versus the degree baseline, browser
checks and larger-vocabulary acquisition options. The default profile is unchanged.
