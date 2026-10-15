# Every Noise parity

The product target is complete Every Noise discovery parity. Current work is a
local implementation and evaluation checkpoint, not a claim that this target has
been reached. Coverage, model recovery, listening, and interaction are separate
acceptance criteria; they cannot be averaged into a meaningful overall percentage.

## Delivered local explorer — 2026-10-15

This checkpoint describes the delivered FMA listening bundle, inspected against
main `57054bdd76d608922b3ccb926c737a4682aa96e9`. It is distinct from the
September MusicBrainz research exports described below. It does not establish
complete Every Noise parity or a measured overall parity percentage.

| Criterion | Delivered FMA state | Remaining limitation |
| --- | --- | --- |
| Catalog navigation | 109,727 track records, 16,916 source artist records and 164 genre definitions; title, artist and native-ID search, genre/artist/track pages and full-catalog handoff | This is the retained FMA corpus, not the historical 198,409-artist MusicBrainz export or complete reference membership coverage |
| Listening coverage | 104 distinct licensed excerpts from 103 artists; 132 of 164 genres have directly tagged excerpts | 32 genres have no excerpt; 74 have exactly one. Multiple genre tags on one recording do not create independent examples |
| Interaction | Root search, source genre families, direct subgenre navigation, deep links, history, keyboard/mobile controls, retry and skip-link recovery | Full-catalog document handoffs stop the root player; catalog metadata is much broader than attached audio |
| Playback | Persistent single player, attribution, bounded suggestions and up to three starting excerpts across the two collections; 58 genres have multiple starters and 35 starter sequences span collections | Each audio manifest retains its 64-clip bound. Listening coverage and musical representativeness remain separate |
| Maps | Source hierarchy browsing is attached | Neither delivered collection has a descriptor-map attachment. Existing map code or historical map results do not establish current delivery; source hierarchy is not sonic geometry |
| Suggestions and quality | Descriptor suggestions use each collection's bounded pool, exclude the query's artist/album/duplicate component and preserve source/model distinctions | Musical relevance and representative quality remain unmeasured. Starter selection uses distinct artists, fewer direct tags and native ID, not listening judgments |
| Delivery | Checksum-bound local ZIP and genuine-browser evidence; no public deployment | Local delivery does not satisfy public-promotion or canonical production build gates |

The source genre supplement in the full catalogs contains 1,000 Wikidata genre
records and 78 directly associated artists. Those identities and relationships
remain separate from FMA; adding the two label counts would not measure genre
coverage or establish an artist identity bridge.

The delivered archive is `OpenNoise-listening-104-complete-ui-20261015.zip`
(131,029,028 bytes), SHA-256
`22f98215b5b2731bff2ac81257ca147ea1026e527eb66ae2f3550b4e15a8eeed`.
Its `current-export-receipt.json`, SHA-256
`d2110f3802628c7bb0756e5f19466f51f03c6ee6bbaddbd73d5952b05e257ce3`,
records source tree `818f07206f57ec6d6d1946c90ccc6b60ac2e76a9`, 14 passing
genuine-browser tests with zero skips, all 64 expanded-collection clips played,
and unchanged prior native data, model and audio bytes. The later main commit
only changes the browser test's cold-launch allowance. The bundle's
`genre-discovery.json`, SHA-256
`b3522641774d99156fc0c176e0102b03ffd274ca63ad80b6efb8850d669d3cec`,
and both `explorer/catalog.json` files provide the counts above. The receipt
states `public_deployment: false` and `musical_representativeness: not_judged`.
These are retained local artifacts, not newly claimed public URLs.

The executable contracts are the [genre discovery tests](../tests/static/fma_genre_discovery_contract.mjs),
[search and catalog handoff tests](../tests/static/fma_discovery_search_contract.mjs),
[starter sequence test](../tests/static/fma_genre_starters_contract.mjs) and
[playback tests](../tests/static/fma_playback_contract.mjs).
Their successes establish the tested interactions, not musical quality.

## Retained MusicBrainz custody versus serving

The September corpus is not lost: the current offline custody assessment streamed
387,435 direct pairs for 198,409 artists from object
`b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e`,
and 164,404 canonical names from object
`48a9854906c5e430acadae70371165e7c21a6d0e365e9a24177e2e5a37fc7291`.
The retained credit SQLite object
`100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`
contains 352 artists, 87 releases and 1,032 tracks. These are separate retained
inputs, not features currently integrated into the FMA listening bundle.

The assessment found no retained enriched-name overlay supporting the historical
198,391-name result in this workspace. Custody receipts mark public export as
unauthorized and name serving as unauthorized; retained bytes do not grant
serving permission. No exact FMA-to-MusicBrainz identity bridge was demonstrated
by this assessment. Its local evidence is
`opennoise-artist-gap-20261015/assessment.json`, SHA-256
`09e37a877c8010899f95b258044e401e55d5f08f35f9d35ab37a8c2cf1361d9a`.

## Historical reference and acceptance — September/October 2026

The following findings and reproduction commands describe their dated research
exports. Preserve them as historical evidence; they are not the delivered FMA
bundle's current inventory or serving authorization.


Live access to `everynoise.net` and `everynoise.com` was blocked in this environment.
`poe bootstrap` restored the existing pinned 6,291-genre reference with zero
quarantine. Its source SHA-256 is
`1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`.
The reference describes Spotify observations through 2023-11-19, not a live
catalog. Historical names and geometry are evaluation inputs only.

| Criterion | Historical research state | Acceptance still needed |
| --- | --- | --- |
| Genre coverage | 697 exact native source labels match 697 of 6,291 reference names: 11.08% | Learn finer overlapping communities from richer open tags, release context, and aggregates; reference names are an evaluation universe, not the construction ceiling |
| Complete artist navigation | All 198,409 source artists and 387,435 direct pairs are reachable through static pages and search | Complete reference memberships and reviewed identity bridges for a reference-recall measurement |
| Names | 198,391 artists named: 99.9909%; 18 exact-ID abstentions | Resolve redirected identities separately; do not silently change artist IDs |
| Genre map and directory | Search, map/list modes, counts, sorting, placement filters, deep links, history, touch and keyboard controls | Reference behavior across the full genre universe and independently assessed semantic neighborhoods |
| Artist maps | Bounded direct-member overlap maps for every source genre; 683 have geometry | Independent artist relevance and geometry assessment; acoustic-axis equivalence is unverified |
| Artist discovery model | Held-out source reconstruction improves while preserving cold-artist denominators and source roles | External relevance evidence, calibrated ranking, and full missing-genre coverage |
| Releases and tracks | Retained credit metadata for 87 releases and 1,032 tracks, linked to exact source artists | Complete reference release/track coverage; representative ranking and playlists |
| Listening | That historical batch was metadata-only | The separately authorized FMA excerpts above supersede a blanket no-playback description, without establishing broad provider integration |
| Release | Static local builds with receipt-bound inputs and browser evidence | Existing sealed catalog/layout and public-promotion gates |

Open-data model enrichment is the central construction goal: discover overlapping
subgenre and microgenre communities, derive descriptor labels from their evidence,
and evaluate granularity and stability independently. Retaining or name-matching
Every Noise labels does not solve this problem. Existing proper genres provide
one feature facet, not a closed genre vocabulary.

The source-only map's axes and colors are browsing geometry and display styling.
They do not recover Every Noise's organic/mechanical or atmospheric/bouncy axes.
Proper-genre observations, release credits, model neighbors, and artist proposals
retain distinct roles. Album credits never create a genre membership.

The [2026-09-30 unified research export](checkpoints/LOCAL_DISCOVERY_PRODUCT_20260930.md)
adds a named-style atlas alongside learned communities and the source explorer.
Its 31,864 retained values include 3,920 default candidate names; exact matches
cover 2,112 reference names overall (33.57%) and 1,223 in the default view
(19.44%). These are string-coverage diagnostics, not validated genre coverage
or an overall parity percentage. The source-only artist maps cover 3,505
style cohorts with bounded samples, while complete paginated cohorts retain
every source artist. All ten benchmark identities and preferred names verify.
[Independent review](checkpoints/INDEPENDENT_BULK_DISCOVERY_REVIEW_20260930.md)
and real-browser certification preserve source/model separation and explicitly
unmeasured musical and listening criteria.

The [2026-10-01 implementation](checkpoints/OPEN_FOUNDATION_IMPLEMENTATION_20261001.md)
adds a simpler interface, exact-credit work links, a reusable acoustic-metadata
representation, portable CC0 examples, and explicit historical benchmark tools.
Its optional rare-style model confirms a source-recovery gain without replacing
default suggestions. Historical display-neighbor recovery remains very low;
music relevance, sonic axes, representative quality, listening, and complete
reference memberships are still separate unresolved criteria.

## Historical model and data results

The September local research added a bulk MusicBrainz tag source and a
[paired evaluation](checkpoints/EMERGENT_COMMUNITY_EVALUATION_CONTRACT_20260930.md).
On identical held targets, enrichment improves overall Recall@10 from 39.86%
to 47.06% and tag-only recovery from 19.92% to 35.03%. The conditioned baseline
still leads overall, and globally novel-value recovery is only 1.50%.
The [bulk community refit](checkpoints/EMERGENT_BULK_SOURCE_REFIT_20260930.md)
contains 128 broad, 157 subgenre, and 1,048 microgenre candidates, including
micro memberships for all ten exact reference artists.

A [fresh nested fine-style test](checkpoints/AUTHORITY_AWARE_FINE_STYLE_NESTED_20260930.md)
is a recorded negative result: rare-tag Recall@10 is 14.19%, below enrichment
at 22.69%. It contributes no suggestions to the product. These experiments
measure reconstruction of open metadata, not Spotify-level genre validity.

The macro-guarded reconstruction selects among 13 declared arms using validation
only. On its newly salted test, micro Recall@10 improves from 42.7415% to
43.3762%, recovering 490 additional positives; macro recall improves from
32.3457% to 36.7873%. Rare-genre hits rise from 63 to 93. Recall@1 and MRR fall
slightly. This is same-corpus source recovery, not independent recommendation
quality. See [the reconstruction checkpoint](checkpoints/DIRECT_CUSTODY_LINEAR_RECONSTRUCTION_20260930.md).

Official exact-MBID search resolves 33,986 formerly missing names in 341 retained
batches. The overlay preserves base catalog bytes and source identities. Both
acquisition and a separate offline replay pass. See [the name checkpoint](checkpoints/MUSICBRAINZ_MISSING_ARTIST_NAMES_20260930.md).

Artist geometry is computed offline from IDF-weighted shared proper genres,
requiring at least two shared genres. Affinity-only sampling can concentrate
on identical two-genre profiles; that source limitation must not be presented
as fine musical distinctions. Each cohort contains at most 200 directly
observed artists, selected by source genre affinity and exact ID, not importance.
The corpus produces 78,755 selected artist occurrences, 69,219 positions, and
9,536 abstentions across 697 maps. Independent review replays all 668,205
neighbor explanations in the retained first sampling run; the affinity update
has separate deterministic selection tests and source-only diagnostics. This leaves omitted artists in the complete source
directory. See [the artist-map checkpoint](checkpoints/DIRECT_CUSTODY_ARTIST_MAPS_20260930.md).

Release metadata is linked through exact release or recording credits. The
bounded retained slice provides context for 280 source artists and 225 genres.
Genre cards say **Releases credited to source artists**. They do not claim the
albums define or belong to the selected genre. Missing context remains explicit.
See [the release-context checkpoint](checkpoints/OFFLINE_RELEASE_CREDIT_CONTEXT_20260930.md)
for source bindings, role separation, and offline replay.

## Historical research reproduction

Use new `.cache` destinations; builders do not replace completed artifacts.
Synchronize dependencies with `poe sync`. Run the catalog and native-label
commands from [the previous source checkpoint](checkpoints/SOURCE_MODEL_UI_BATCH_20260930.md),
then:

```sh
.venv/bin/python scripts/enrich_local_musicbrainz_artist_names.py \
  --catalog-directory .cache/research-catalog \
  --output-directory .cache/research-artist-names
.venv/bin/python scripts/build_direct_custody_reconstruction.py \
  --output .cache/research-reconstruction
.venv/bin/python scripts/build_local_direct_custody_preview.py \
  --model-directory .cache/research-reconstruction \
  --catalog-directory .cache/research-catalog \
  --label-directory .cache/research-labels \
  --artist-name-directory .cache/research-artist-names \
  --output .cache/parity-explorer
.venv/bin/python -m http.server 8881 --bind 127.0.0.1 \
  --directory .cache/parity-explorer
```

The name acquisition is bounded and resumable; `--verify-only` replays its saved
bytes without network access. All artist maps and browser detail geometry are
precomputed. The browser loads overview metadata first, then fixed static genre
details, artist pages, map cohorts, and release context on demand. Global artist
search loads its separate index only when requested.

In another shell, certify the browser and compare the dated reference:

```sh
node scripts/capture_direct_custody_preview.mjs \
  http://127.0.0.1:8881/ .cache/parity-browser-evidence
poe bootstrap
.venv/bin/python scripts/evaluate_everynoise_parity.py \
  --reference data/vault/raw/sha256/1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180 \
  --preview .cache/parity-explorer --output .cache/parity-report.json
poe check
```

The evaluator verifies every static byte and the actual browser routes. It
reconciles source page counts, zero-based pagination, search identities, profile
metadata, lazy genre details, and all direct source pairs before claiming
complete navigation for the declared source. Missing files and mismatched
projections fail. It always retains unmeasured reference criteria as unknown.

The canonical `poe build` still requires the ignored sealed source catalog and
layout. Research previews and the recovered public presentation do not satisfy
that production gate, and this batch has no deployment path.
