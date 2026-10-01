# Bulk named style atlas and source artist maps, 2026-09-30

The final local export is `.cache/named-style-atlas-bulk-20260930-final`, receipt
`7f91c5db7198716c9fd4f2ccdfb14d3497becf74c02ffb4b7e1d03f8a94fdb95`.
It contains complete artist navigation and role cohorts, plus bounded artist
profile maps derived from source musical metadata. These remain unreviewed
candidate styles and inferred geometry. No public deployment, audio similarity,
genre identity, listening relevance, or complete Every Noise parity is claimed.

## Frozen construction and final display

The complete primary-v4 construction is retained in
`.cache/named-style-atlas-bulk-20260930-v1`, receipt
`7c107a144235ff7a91efff4ffbc37d3b9159b4a4b99d985d077a0da74cff6663`.
Its successful run took 279.041 seconds and measured 535,334,912 bytes peak RSS.
Source and proposal JSON were compressed in temporary SQLite staging. The
staging directory was removed after completion. Earlier unsuccessful,
unreceipted drafts were removed; previously frozen exports were preserved.

The final export applies `named-style-display-v4` through verified hardlinks and
atomic replacements. It independently verifies all 83,093 declared files and
2,877,447,392 bytes. All original artist profiles, search, complete role cohort
pages, source geometry, and artist maps remain byte-identical. Exactly 31,865
files change: style detail display fields and `data.json`. Another 51,228 files
retain identical bytes, including 51,225 retained hardlinks. HTML, CSS and
JavaScript are replaced atomically even when their bytes are identical.

V4 conservatively screens reviewed pure role plurals, `organist`,
`jazz musicians`, `records`, and labels beginning with `death by`, `death from`,
or `death due to`. Nine formerly visible labels move to the raw tier:
`composers`, `death by cancer`, `death by covid-19`, `death by plane crash`,
`guitarists`, `jazz musicians`, `organist`, `pianists`, and `records`.
Their atoms, profiles, cohorts, proposals and geometry remain retained.
Musical compounds, geographic musical forms, death metal, deathcore, denpa,
comfy synth, soft visual and unknown labels receive no additional rejection.
This display overlay is not a semantic classifier or a taxonomy validation.

## Input custody

| Input | Binding |
| --- | --- |
| Feature payload, `.cache/microgenre-features-primary-v4/artist-features.jsonl` | `2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252` |
| Feature receipt file | `281a0cdcf87498bad50f6e2fe9b145cf0e010c1ed7c3b48a832ae0b8a094f6d7` |
| Source profiles, `.cache/parity-source-explorer-20260930-v3` | `0deaa234b5637ca734b6558022ad3e1fab1573ee45f7547e37b144deff1d84a9` |
| Primary-v4 enrichment prediction export | `70ea84650de3f95054f5fda34c4bcbb286365bfa5fc8d4f69b8b4bb54d3c4d13` |
| Enrichment model | `650cc9dbead293cea81d214e7cdd0ddf6b99639ac9b503ddca4a68727fd45877` |
| Display-only artist name overlay | `1d894aa330d7f6f7206571f05ce459143a94efbacacbc4cde79cfaeaae1fc5c6` |

Exact construction code is retained in
`.cache/named-style-atlas-codefreeze-bulk-20260930-v1`, receipt
`e75ef57c326e85c282e52692d4f74c35c1774c3b04dd4a2be67c2fc7cb64c43d`.
Every frozen module matches the construction receipt's code bindings. The final
receipt preserves those source bindings separately from its display builder.

```sh
.venv/bin/python scripts/build_local_style_atlas.py \
  --source .cache/parity-source-explorer-20260930-v3 \
  --features .cache/microgenre-features-primary-v4/artist-features.jsonl \
  --enrichment .cache/artist-feature-enrichment-primary-v4 \
  --artist-maps --output .cache/named-style-atlas-NEW

.venv/bin/python scripts/build_local_style_atlas.py \
  --refresh-from .cache/named-style-atlas-bulk-20260930-v1 \
  --output .cache/named-style-atlas-NEW-DISPLAY
```

Replay of the original construction uses its frozen source snapshots. Fresh
paths are mandatory; existing exports and symlink escapes are rejected. The
refresh uses hardlinks, copies only across devices, and replaces every modified
file atomically so linked original bytes cannot be overwritten.

## Complete coverage and names

| Measure | Count |
| --- | ---: |
| Exact source artists | 198,409 |
| Named / unresolved artists | 198,391 / 18 |
| Input feature observations | 1,010,929 |
| Observed artist-feature memberships / pages | 548,824 / 36,133 |
| Credited release-context memberships / pages | 777 / 261 |
| Inferred proposals / pages | 594,799 / 7,228 |
| Candidate style atoms | 31,864 |
| Positioned / unpositioned style atoms | 6,472 / 25,392 |
| Style geometry edges | 29,521 |
| Default styles / positioned default styles | 3,920 / 3,610 |
| Dictionary tier / repeated candidates / raw candidates | 1,593 / 2,327 / 27,944 |

Every declared page contains at most 100 exact artist IDs. Pagination preserves
all 43,622 pages, with no cohort truncation. All profiles and role pages were
reconciled using membership counts and UUID-hash multiset checksums; page IDs,
roles, ordering, names and shard routes were checked independently.
Every non-name source profile field remains unchanged, including native facts.

Names attach after geometry. Verified bulk names fill unresolved names only;
the named and explicitly missing overlays form an exact disjoint source-corpus
cover. One source name is recovered: Swizer,
`ea0edab0-5c09-49d3-8823-511b1e2f3226`, with exact bulk artist-row provenance.
All previously resolved names remain unchanged. Aphex Twin retains its preferred
name even though the overlay contains `Aphex`. All ten fixed benchmark names
remain canonical: Aphex Twin, Four Tet, Boards of Canada, Autechre, Burial,
Squarepusher, Floating Points, Caribou, Brian Eno and Jon Hopkins.

## Source artist map contract

Musical values collapse duplicate source namespace facets before geometry.
Each artist contributes one binary occurrence per canonical musical value.
Only values supported by at least two distinct source artists are usable;
the retained usable vocabulary has 7,979 values. For source corpus size `N` and
distinct-artist support `df`, `idf = 1 + ln((N + 1) / (df + 1))`.
The similarity is cosine on square-root-IDF weighted binary profiles:
`sum(shared_idf) / sqrt(sum(left_idf) * sum(right_idf))`.
At least two distinct shared musical values are required.

Selection is capped at 200 artists per source-supported style, ordered by usable
musical degree and exact MBID. Names do not influence selection or coordinates.
Only observed artist-feature and credited release-context memberships enter the
cohort; proposals never enter geometry. Identical usable profiles abstain across
the complete source corpus, including duplicates outside the selected cohort.
Directed neighbors are capped at ten. Their union supplies the spectral graph,
so undirected degree can exceed ten. Neighbor evidence retains the exact shared
value count and up to five canonical shared-value examples.

There are 3,505 retained map files, including 3,496 still eligible in the final
default display. The nine suppressed labels' maps remain retained in raw data.
There are 3,366 maps with positioned nodes and 139 fully abstained maps;
333 maps are bounded samples of larger complete cohorts. Across maps there are
152,741 selected artist occurrences, 114,674 positioned occurrences, 38,067
abstentions and 746,272 graph edges. These are occurrences across cohorts, not
distinct artist counts. Of the abstentions, 35,300 have identical usable profiles
and 2,767 lack enough shared source values; no spectral nonconvergence occurred.

The payload field `source_model_sha256` binds enrichment prediction lineage only.
That model's proposals and scores do not construct the map. Geometry provenance
is the feature digest, explicit formula, and frozen implementation bindings.
Maps mark `native_fact: false`, `quality_evaluated: false`, and explicitly exclude
names, inferred memberships, historical inputs and audio from geometry.

## Evaluation and verification

Only after construction was sealed, exact NFC/casefold/whitespace whole-name
comparison used the 2023-11-19 historical reference with 6,291 names, raw SHA-256
`1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`.
The reference did not enter feature acquisition, fitting, selection or layout.

| Candidate set | Names | Exact reference matches | Reference name coverage |
| --- | ---: | ---: | ---: |
| All style atoms | 31,864 | 2,112 | 33.57% |
| Final default display | 3,920 | 1,223 | 19.44% |
| Dictionary-name tier | 1,593 | 861 | 13.69% |

These are dated spelling diagnostics, not identity bridges, genre precision,
membership recall, sonic fidelity or a parity percentage. Dictionary matching
does not promote artist memberships to native facts. The final display cleanup
does not change reference matches; its nine excluded labels have no exact match.

The complete base verification report is
`.cache/named-style-atlas-bulk-20260930-v1-verification.json`, self-hash
`fa865a479fafffc7258464f7c1d4c862a0650688a3e2207e22f018b29106efe7`.
Final old/new-byte and hardlink preservation verification is
`.cache/named-style-atlas-bulk-20260930-final-verification.json`, self-hash
`7e6e815ca9146026e827d80927ddefc6d21d5e01c985a8da39b028f306af087e`.
Twenty-one focused backend tests pass with scoped Ruff, formatting and type
checks. Chromium tests exercise the actual Python/SQLite producer through the
renderer, including role separation, shared-value evidence, abstention,
pagination, history and mobile layout. Whole-project checks and final product
browser certification are recorded by the parent integration work.

Core metadata remains CC0-1.0. Tag-derived output retains MusicBrainz contributor
attribution and CC-BY-NC-SA-3.0 noncommercial/share-alike obligations. Construction
and final receipts remain local research with public export and serving
unauthorized; the product is not deployed.
