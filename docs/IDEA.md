# OpenNoise

Build OpenNoise, an open music map from public metadata and privacy safe aggregates.

The end goal includes a reusable open modeling foundation, not only a website.
Use the historical Every Noise scrape as a North Star for discovery behavior
and independent evaluation while constructing representations and overlapping
communities from separately licensed open evidence. The
[foundation goal and acceptance gaps](foundation/GOAL.md) define that scope;
[reproducibility inventory](foundation/README.md) distinguishes runnable
checkout examples from full-corpus stages that need additional inputs.

The [2026-10-03 foundation and recovery checkpoint](checkpoints/OPEN_FOUNDATION_RECOVERY_20261003.md)
records the current integrated source, model and product paths: durable recovery,
three million core artist identities, separate CC0 source explorers, native sonic
credit verification, a complete FMA catalog and independently audited acoustic
baseline. It also records negative results and remaining acceptance gaps. Earlier
checkpoints below retain the history of preceding source and model runs.

The design direction is minimal, plain, and “grug brain,” with usability and
UI/UX preserved. Remove generic dashboard styling, repeated explanatory copy,
badge clutter, and competing controls. Keep search, readable names, clear
navigation, accessibility, and evidence distinctions. Follow the
[design direction](serving/DESIGN.md) for the next UI pass.

The product target is complete Every Noise discovery parity through open-data
modeling and enrichment. The initial 697 source genres are evidence, not a
vocabulary ceiling. The current research pipeline adds verified open tags and
learns overlapping broad, subgenre, and microgenre communities; names and
historical maps do not determine their construction. The preceding cleaned
adaptive fit has 106 broad, 182 subgenre, and 954 microgenre candidates, with
594,776 separately typed style suggestions across 198,409 artists. Independent
within-source tests show tag-only enrichment gains, while overall results
remain below a conditioned genre baseline. Source reconstruction does not
establish independent musical validity or complete parity. See [the emergent
community checkpoint](checkpoints/EMERGENT_MUSIC_COMMUNITIES_20260930.md) and
[the artist enrichment checkpoint](checkpoints/ARTIST_FEATURE_ENRICHMENT_20260930.md)
for source coverage, exact reference artists, measured weaknesses, and the
static hierarchy explorer. The measured product acceptance criteria remain in
[Every Noise parity](EVERYNOISE_PARITY.md).

The subsequent [bulk source acquisition](checkpoints/MUSICBRAINZ_BULK_ARTIST_TAG_SOURCE_20260930.md)
adds aggregate MusicBrainz tags through exact artist UUIDs. After the same
quality policy and model filters, it adds 114,889 canonical artist–value
observations. The independently replayed [paired test](checkpoints/EMERGENT_COMMUNITY_EVALUATION_CONTRACT_20260930.md)
holds the targets fixed: enrichment Recall@10 improves from 39.86% to 47.06%,
and tag-only recovery from 19.92% to 35.03%. Overall recovery remains below the
conditioned genre baseline; novel-label recovery is only 1.50%. The new
[named-style atlas](checkpoints/NAMED_STYLE_ATLAS_BUILD_20260930.md) offers
complete paginated artist cohorts and separates artist observations, release
context, and suggestions. Its default view has 2,226 candidate names, while
weaker annotations remain searchable. Neither these candidates nor name
matches establish a validated Spotify-level taxonomy.

The [bulk community refit](checkpoints/EMERGENT_BULK_SOURCE_REFIT_20260930.md)
learns 128 broad, 157 subgenre, and 1,048 microgenre candidates. All ten
reference artists, including Aphex Twin and Four Tet, have micro memberships.
Almost half the artist cores fall under coarse groups stopped by the safety
budget, so their support status remains explicit. A separate
[coarse-budget experiment](checkpoints/EMERGENT_EXPANDED_COARSE_BUDGET_20260930.md)
stops naturally at 237 broad groups and greatly reduces unsupported coverage,
but loses micro-level navigation for three reference artists. It remains a
construction experiment rather than silently replacing the selected model.

The [authority-aware fine-style experiment](checkpoints/AUTHORITY_AWARE_FINE_STYLE_NESTED_20260930.md)
uses fresh nested folds, training-only support gates, and source-authority
weights. Its prespecified rare-tag Recall@10 is 14.19%, below existing
enrichment at 22.69%. Independent replay reproduces every metric and selection.
It remains an unsuccessful research candidate and contributes no product
suggestions. Further granularity work needs stronger musical evidence; these
outer folds must not become another tuning set.

The [unified local discovery product](checkpoints/LOCAL_DISCOVERY_PRODUCT_20260930.md)
connects named styles, learned communities, and source genres through actual
static routes. The [bulk atlas](checkpoints/NAMED_STYLE_ATLAS_BULK_BUILD_20260930.md)
has 3,920 default candidate names and 3,505 source-only artist maps. All 198,409
artists remain reachable through complete cohorts and exact-ID search; map
samples are bounded and distinguish positioned profiles from abstentions.
Aphex Twin and Four Tet retain their preferred names. Model suggestions stay
separate from artist observations and credited-release context. Chromium
certification covers the real export, history, mobile, and all three explorers.

The [exact-credit AcousticBrainz pilot](checkpoints/ACOUSTICBRAINZ_BENCHMARK_METADATA_20260930.md)
adds a separately verified source of sonic metadata. Thirty recordings were
selected before feature requests; eighteen have both feature endpoints,
including at least one recording for every benchmark artist. A corrected
offline projection retains fourteen numeric descriptors without new requests.
Missing recordings and absent fields remain explicit. This small sample adds
no artist genre facts or model/product input; further experiments need broader
coverage and independent musical judgments. The
[independent metadata review](checkpoints/ACOUSTICBRAINZ_BENCHMARK_METADATA_REVIEW_20260930.md)
records source age, recording identities, schema correction, and these limits.

OpenNoise is the product name; the internal Python package and compatibility
identifiers remain `opennoise` during the staged migration.

The immediate product goal is coherent open music discovery: a user should be
able to traverse a catalog genre to artists, an artist to its directly observed
genres, and then to artists sharing those direct genres. These navigation links
are source-claimed membership only; `shared_direct_genre` is an explained
overlap method, not a learned similarity or an inferred membership. The local
public catalog currently has direct artist claims for, for example, post-punk
(23 artists), jazz (55), free jazz (4), electronic music (44), and folk music
(36). The static export provides these links as a bounded discovery surface.
Direct coverage remains sparse and uneven, and unresolved seeds have no
fabricated artist membership.

A separate portable, source-only experiment now reconstructs held-out
MusicBrainz proper-genre observations from 387,435 exact artist–seed pairs.
Validation-selected specificity transfer improves test Recall@10 from 42.2441%
to 42.6586%; this is a small source-reconstruction gain, not independent
recommendation quality. Its local explorer has exact native labels for all 697
observed genres, 683 source-graph positions, and 14 searchable abstentions.
Direct observations and inferred proposals remain separate. Neither the model
nor the explorer changes the public release. See [the model checkpoint](checkpoints/DIRECT_CUSTODY_SPARSE_NEIGHBORHOODS_20260930.md)
and [the local explorer](checkpoints/DIRECT_CUSTODY_LOCAL_EXPLORER_20260930.md).

The historical Every Noise result is a local reference. It preserves 6,291
immutable genre name seeds and dated observed map output. It does not claim to
recreate Spotify's private data or McDonald's private model.

The open result keeps the source records immutable. Each source claim keeps its
source, license, snapshot, method, and observed time. A versioned derived graph
adds public identities, explicit taxonomy, overlapping review communities,
artist membership, genre similarity, and representative album and track
metadata. A derived record never replaces its source claim.

The first model is simple. Explicit parent and subclass statements provide the
hierarchy. Shared artists, public listener aggregates, and approved metadata
provide separate relation signals. Similarity combines those signals only in a
named model run. An artist can belong to several genres. A candidate relation
stays a review candidate until evidence or a human review promotes it.

The map uses stable neighborhoods. The overview shows broad connected groups.
Zooming reveals their child genres and nearby related genres. Further zooming
reveals artists and representative metadata. The map does not treat a denser
flat batch of points as a more detailed neighborhood.

The published v3 atlas is built only from sealed open graph inputs. Its
deterministic placement reduces near-overlapping points at `1e-4` from 262
to zero and labels needing more than `1e6` reveal scale from 117 to zero.
Its remaining problem is semantic: better coordinates do not create missing
genre or artist evidence. See [the layout checkpoint](checkpoints/LAYOUT_NAVIGATION_SEPARATION_SWEEP.md).

The current full-corpus hierarchy checkpoint retains all 6,291 immutable names
and 66,132 directed public-evidence candidates: 160 accepted, 59,911 review,
and 6,061 abstained. The separately sealed all-seed frontier is built from the
restored public catalog snapshot. Neither artifact inherits artist memberships
through the hierarchy or uses historical data during construction.

The sealed v5 frontier receipt-binds and preserves the full Wikidata-fused v4
ledger: 2,377 MusicBrainz release direct-anchor seeds, 292 Wikidata seeds, 291
cross-source corroborations, and 2,378 source-anchor seeds in union. It adds
23,497 ListenBrainz-derived review candidates across 425 seeds, all of which
already have source anchors. The MusicBrainz anchor count is not an
artist-direct membership count. This adds no factual memberships and
no direct-coverage seeds. Its logical hash is
`edf01e96b8ab12d7c90b49cf9119aa5fb0a01ccdea253924b7923ed3e0ecbef8`;
the artifact byte hash is
`4c0dbc32b28d01b95ce79f988750b39db74241368a8b1257d6e2a9345c1c0db2`.

The downstream H3 check is evaluation only. It joins H3 page-member positives
through accepted receipt-bound Spotify-to-MusicBrainz bridges and never feeds
them into v5. Its artifact hash is
`7cbcd8b6859fd8207ac271c9564963f96fea9bfe57d8cc1541c125d4fa2fb6bb`.
It reports 179 top-50 hits among 15,772 positives for the 425 candidate-covered
genres (conditional recall 1.1349%), and 179 among all 120,163 bridge-resolved
unique positives (global positive-only recall 0.14896%). It abstains on 5,644
of 6,069 H3-positive genres. Precision is intentionally unavailable because
an H3 absence is unknown, not a negative.

Historical taxonomy overlay and v6 frontier files are present locally but are
superseded and unverified under the current row-bound provenance schema. The
checked-in Poe workflow writes any replay to separate candidate directories.
Its source is the sealed catalog snapshot, not an undeclared relation-feed
path. The corresponding evaluator replays that same snapshot, so construction
and holdout evaluation share a declared immutable source boundary.
The current verified standalone replay retains all 6,291 seeds and projects
216 accepted factual edges from 853 permitted catalog P279 rows; 346 seeds have
an exact-QID mapping and 6,057 remain factual-isolated. It reports no review or
cycle rows. Its taxonomy input was
`.worktrees/open-construction-graph/data/model/genre-seed-public-taxonomy-v1.json`
(SHA-256 `5c8bac592fdbd982d529a422940b3d601c0c81b83e42d0c7641779821b03f712`)
and its logical artifact hash is
`21126aae5cf8b849edd132e9125ad12f1037474fecc1f89f6b8c1f8254efbd15`.
This is a taxonomy-only candidate, not a hierarchy, artist, or coverage
promotion.
The completed release-group candidate is local research. Its verified archive,
receipt, final evidence database, and artifact are bound in
`docs/MUSICBRAINZ_EVIDENCE_CHECKPOINT.md`. Direct artist claims and
release-group support remain separate. The prior staging SQLite database is
malformed and is not an input. MSD/Last.fm remains an offline, metadata-only
adapter awaiting the three verified SQLite files (or an already verified local
cache receipt); no live MSD result is claimed.

An optional Last.fm reverse-tag adapter is review-only. It writes its
credential-free query manifest before any network request and exits 2 without
`LASTFM_API_KEY`; no live Last.fm artifact is sealed in this checkout. A claim
requires a Last.fm-provided MusicBrainz artist ID plus exact normalized tag
corroboration for that same ID. Name-only rows and all noncorroborated results
remain review data and cannot promote identities, memberships, taxonomy, or
hierarchy facts.

The historical peer compatibility evaluator name-matches 6,289 H3 genre names.
Only 1,580 have a constructed candidate neighborhood and are peer-supported;
the other 4,709 are retained as abstentions. The 1,580 figure is an evaluation
subset, not genre, catalog, or hierarchy coverage. H3 has unranked,
positive-only samples, so this remains a neighborhood check rather than a
ground-truth reconstruction.

The separate bridge-backed membership experiment maps 120,288 of 306,136 H3
observations to 78,954 MusicBrainz artists using receipt-bound identities and
an 88,328-artist, 212,696-row open-tag matrix. Its open-only Recall@50 is
0.01582 micro and its H3 edge-holdout Recall@50 is 0.03059 micro; 1,172 whole
cold-label genres deliberately abstain. It is a local, positive-only baseline,
not complete membership, ranked relevance, Every Noise parity, or a serving
model.

The bounded representative catalog currently contains 51 retained releases
and 491 unique track records across 40 genres. These are metadata records only.
They are not claims about the defining or most important works for a genre.
A separate local run hydrated 55 releases and 660 tracks from already selected
metadata examples. It replays both accepted and rejected API results offline,
but it is not the published catalog or a complete MusicBrainz crawl.

A bounded local album-context query now links native release-group examples
to exact credited artists' direct observations, separate album-supported seed
evidence, and optional exact playlist occurrences. It verifies the source
bindings, retains proper-genre and tag facets separately, and reports missing
playlist inputs and unmatched release groups explicitly. It does not infer
artist membership from credits or playlists and has no publication or model
promotion path. See [the local query contract](serving/LOCAL_ALBUM_DISCOVERY_CONTEXT.md).

Generated genre labels and catalog identity bridges have separate review
queues. The current local candidate queue has 484 unreviewed genre proposals
bound to 189 retained source claims. The bridge audit has 101 non-exact
catalog mappings and 95 conflicting or ambiguous mappings awaiting review.
Neither queue publishes a genre or changes an
artist membership by itself.

OpenNoise never downloads, stores, serves, embeds, or trains on audio or music
files. Links and playback placeholders remain separate from metadata.

McDonald documented broad inputs and behavior. He described overlapping music
communities, cultural and acoustic signals, listener based discovery, human
review, and readability adjusted map positions. The public record does not
give the private feature vectors, complete source code, weights, thresholds,
candidate rules, or final layout transform. OpenNoise labels experiments as
approximations and reports what is observed, disclosed, inferred, or unknown.

The pipeline is: immutable source snapshot, typed source claim, SQLite
projection, versioned derived graph, evaluation, and public publication. Each
adapter writes provenance and each model run records its inputs, parameters,
code revision, seed, and content hash. Local object storage and future object
stores use the same small abstraction.

The retained 62-object source vault passes byte verification. A completed
combined local replay verifies all 62 objects and writes a fresh candidate
database with the 54 Wikidata objects and seven ListenBrainz dailies. The
candidate is not byte-identical to, and is not a certified replacement for,
the sealed public cache. See [the source replay checkpoint](checkpoints/SOURCE_VAULT_REPLAY.md).

The deployed v2 static-discovery bridge is a promoted, presentation-only
QID-position projection; it does not change the sealed source database. The
older v3 projection and source-vault replay outputs remain local candidates and
are not promoted into the sealed database or static release.

Keep the stack small: Python 3.13.14, uv, mise, Poe, Pydantic, SQLite, and
Cloudflare Pages. Offline tools construct source-bound artifacts, then one
static exporter writes the complete browser surface. The browser receives
precomputed HTML, JSON, CSS, and JavaScript only: it has no OpenNoise API,
application server, server-rendered route, or graph-layout calculation.
