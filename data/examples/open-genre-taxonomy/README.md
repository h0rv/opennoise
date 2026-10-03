# Source-selected Wikidata genre taxonomy

This pack contains **1,000 source-selected genre entities** and **3,091 typed
direct-property claims** captured from Wikidata on October 2, 2026. The data is
CC0-1.0; see [Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing).
The capture used no historical Every Noise names, artist IDs, name searches,
MusicBrainz associations or private data.

The frozen selection verifies [Q188451, music genre](https://www.wikidata.org/wiki/Q188451)
and selects direct `P31 Q188451` entities with `LIMIT 1000`, in the endpoint's
returned order. The cap was reached: **this is an incomplete, potentially biased
selection**, not all Wikidata genres or coverage of Every Noise's 6,291 names.
Genre entities typed only through more specific classes can be absent.

Five exact-QID follow-up batches preserve only `P31` (instance of), `P279`
(subclass of), and English labels. Their raw row counts are below their 2,000-row
limits. All selected entities returned taxonomy rows; two lack English labels.
`taxonomy_complete_for_selected_cohort` refers only to those bounded follow-up
queries, not the completeness of Wikidata or musical truth.

The projection preserves 1,549 `P31` and 1,542 `P279` claims. It assigns no broad,
subgenre or microgenre levels. A source subclass assertion is not an accepted
musical community, and a target outside the selected cohort is not independently
established here as a genre entity. `value_in_selected_cohort` makes that boundary
explicit. There are **zero artist memberships**. Place, movement, artist genre,
and MusicBrainz identity properties never enter these queries or this projection.

Replay without network access from the configured checkout:

```sh
.venv/bin/python scripts/capture_open_genre_taxonomy.py \
  --output data/examples/open-genre-taxonomy --verify
```

`query-plan.json` retains the selection and budgets written before capture.
`manifest.json` retains exact query URLs, IDs, HTTP status, capture times, timing,
byte bindings and failure accounting. `raw/` preserves source response bodies.
`projection.json` stores typed claims, missingness and truncation. Shared
`source_captures` records retain query URLs; claims reference those captures by
`source_capture_id`, hash and observation time. `receipt.json` binds the complete
declared machine artifact set. This README is documentation outside that set.

Capture time is when this client observed a response; it is not a Wikidata dump
snapshot or statement modification date. The direct-property query projects
truthy claims and does not preserve statement ranks, qualifiers or references.
Failures or row-cap hits remain explicit and replayable. Byte verification does
not establish semantic correctness.

A new capture must use a fresh output directory. Budgets are ten requests,
2 MB per response, 10 MB total source bytes, and a 30-second configured request
timeout. This capture used seven requests and 2,092,096 source bytes. No audio,
artist membership model, hierarchy promotion, product release or deployment is
included.
