# Roadmap

## Current product

The default static map retains 6,291 immutable names; 2,945 have placed map
coordinates and 3,346 remain preserved but unplaced. It has one landscape
surface with stable neighborhoods, semantic zoom, genre detail, search, pan,
zoom, and dark mode.

Static discovery is a separate, lazy JSON asset, not a backend API. The current
sealed public catalog has 4,948 export- and display-authorized direct Wikidata
P136 observations. The deployed combined v2 bridge puts 3,859 of them on 344
map genres for 1,126 artists: the 260 exact-label v1 genres plus 84
QID-position additions. The earlier exact-label v1 baseline put 2,900
observations on 260 map genres for 1,008 artists. Artist overlap is explicitly
shared direct mapped genres, never an unexplained similarity claim. See
[static discovery status](evidence/STATIC_DISCOVERY_STATUS.md) for the current
source coverage and exclusions.

The local static export now searches artists as well as genres. An artist opens
within a directly observed genre, with links back to that genre and to other
artists observed there. It links to exact MusicBrainz and Wikidata artist
records. The artist order uses shared direct genre counts, not a learned
similarity model.

The historical Every Noise result is a separate local reference. It preserves
dated observed output for blind evaluation and does not provide inputs to the
open model.

The [source and signal inventory](checkpoints/SOURCE_SIGNAL_INVENTORY.md)
separates adapters, retained receipts, model inputs, and evaluation-only data.
It records which public claims are factual and which local signals are still
research candidates.

## Release gates

- Verify the sealed source cache and provenance manifest.
- Rebuild or verify the public model and its logical hash.
- Build and verify the production map and browser evidence.
- Serve only the certified database and map artifact.
- Keep historical reference data separate from open model inputs.

The public release bundle is portable and cache only. It carries the sealed
derived cache, release configuration, model, map, and evidence. Raw source
replay is separate. A fresh checkout can rebuild a selected bounded local vault
from declared, network verifiable pins or restore a supplied source cache
receipt. Raw bytes with local only or non redistributable policy never enter a
portable store. A full local candidate replay completed from the release
manifest source vault, but it is not a byte-identical replay of the sealed
derived database. A separate local replay check now
verifies all 62 raw objects named by the Phase 3 manifest, a total of
1,541,940,352 bytes, and can restore a supplied verified object store. A
second local step replays the 54 Wikidata SPARQL objects into a fresh, explicitly
uncertified local candidate SQLite database. A separate, strictly offline
ListenBrainz candidate replay now consumes the seven retained daily objects
into its own fresh database. It checks the recovered fixed-window configuration
against the sealed generated joint receipt before scanning the daily archives,
then requires its generated joint receipt to match the sealed object. A
versioned declaration replay now reproduces all 62 retained historical
declaration hashes. The controlled combined replay at `46cfc23` completed
locally: it verified all 62 retained objects, replayed 54 Wikidata objects and
seven ListenBrainz dailies, and wrote the receipt-bound candidate documented in
`docs/checkpoints/SOURCE_VAULT_COMBINED_CANDIDATE_REPLAY.md`. That candidate
remains local only, non-byte-identical, and explicitly uncertified; it does not
replace or certify the Phase 3 public database.

The audited historical-declaration replay mode also completed one separate
local candidate at `4a76c76`: it verified the same 62 vault objects and all 62
historical declaration hashes before first write, then produced 603 modelable
genres and 4,948 embed-authorized direct Wikidata rows. Its original receipt
remains explicitly non-certified and non-byte-identical. A versioned detached
local binding now rehashes and binds the retained candidate, receipt, and
manifest, while rechecking the 62 declarations, source/artifact pairs, schema,
integrity, foreign keys, and historical policy/provenance state. That permits
only a fresh local experimental projection; it neither authorizes publication
nor certifies or replaces any sealed/public database.

One such attested local projection was run once and stopped before publication:
its constructed model input hash did not match the sealed manifest boundary, so
no model, gate, layout, graph, serving database, or report exists. The retained
candidate and binding remain unchanged; see
[the local projection checkpoint](checkpoints/PHASE3_HISTORICAL_RUN2_LOCAL_PROJECTION_20260921.md).

An opt-in compact-reference v3 local projection completed from the same
attested candidate. It verified 62 source artifacts, wrote a 30,031,286-byte
model, passed the public-model gate, and persisted four layouts. The result is
local, non-certified, and undeployed. It does not change any sealed, public,
static, or deployed artifact. See [the v3 projection result](checkpoints/PHASE3_HISTORICAL_RUN2_LOCAL_PROJECTION_20260921.md).

A read-only, hash-pinned comparator finds matching bounded model semantics:
all 62 source identities, 603 genre identities, 4,434 direct memberships,
13,175 artist pairs, 22,091 one-hop memberships, 34,348 neighbors, 3,344
representatives, and 2,002 layout coordinates match after canonicalization.
However, one of 37,017 normalized provenance binding fingerprints differs, so
full semantic replay and certification remain unproven. This is not
byte-identical replay, certification, or publication authorization; see the
[semantic comparison correction](checkpoints/PHASE3_V3_SEMANTIC_COMPARATOR_DISCREPANCY_20260921.md).
The comparator remains strict: the sealed completion provenance cannot be
deterministically replayed because its adapter-byte hash and runtime telemetry
are different; see the [replay diagnosis](checkpoints/PHASE3_V3_LISTENBRAINZ_PROVENANCE_REPLAY_DIAGNOSIS_20260921.md).
Future offline candidate replays instead emit a v2 semantic-completion receipt
that binds source artifacts, fixed-window configuration, and result counts,
with adapter-build and runtime measurements separately auditable. This changes
neither v1 receipts nor the strict historical comparator; see the
[future receipt checkpoint](checkpoints/PHASE3_LISTENBRAINZ_FUTURE_SEMANTIC_COMPLETION_RECEIPT_20260922.md).

The bounded replay comparison found equal logical source and evidence
projections, but candidate source metadata and the public derived stage differ.
The candidate remains local and uncertified; see [the replay comparison checkpoint](checkpoints/PHASE3_HISTORICAL_REPLAY_BOUNDED_COMPARISON_20260921.md).

The v3-to-static-map bridge remains local and audit-only. Of 603 v3 Wikidata
genre references, 314 have unique non-ambiguous reconciliation links and 305
already point to positioned canonical map seeds; none changes the 6,291 seed
names, 2,945 positions, or 3,346 abstentions. The local-only adapter audit
reads these facts without writing output; it remains pending final integration
review and is neither a map overlay nor a release input. See [the bridge audit](checkpoints/PHASE3_V3_STATIC_MAP_BRIDGE_AUDIT_20260921.md).

A historical sealed-public-DB direct-bridge precursor abstained from 25 catalog
genres that resolve to multiple positioned seeds. Its remaining local-only
frontier contains 84 newly positioned direct genres, 862 grouped artist-genre
memberships across 959 retained P136 observations, and 118 net-new artists with
exactly one authorized MusicBrainz ID. This precursor was not itself published
or promoted; see [the pinned checkpoint](checkpoints/PUBLIC_DIRECT_BRIDGE_FRONTIER_20260921.md).

The historical production direct-bridge stage-one receipt pinned 84 positioned
genres and 862 grouped direct memberships. That receipt wrote no static asset
and was not itself exported, certified, or deployed; see the
[receipt](checkpoints/PUBLIC_DIRECT_PRODUCTION_BRIDGE_RECEIPT_20260921.md).

The clean local chain uses QID map hash
`dd5cf7cf33898a76c1e85e95351e25e7303933f4524e2776097c20fd0d73a449` and
sealed bridge output hash
`c488223b34afcd59596072d4623e3190cfff1941cfdccb4da3e286e7ccebef5b`. It
contains 84 positioned genres, 862 grouped memberships, 959 direct P136
observations, 536 artists, and 118 net new artists. A terminal comparison
found exact membership equality with the older bridge. The clean sidecar has
hash `dfc4c74915ddc72df831a350d3fd420c9b14ff24c1f99e3758b6cdbb8257da73`.
The merged local v2 candidate has 344 genres, 1,126 artists, and 3,859 bound
observations, with hash
`9ee2a464de74e0b681ea347163fda94afa6eb28e3189a4fa4e6d0ee3d708232b`. These
outputs no longer consume the old v3 bridge or reconciliation, and the base v1
asset is unchanged. The tracked promotion receipt now makes the public v2
promotion gate explicit. The local static v2 build and browser certification
now pass with 344 genres, 1,126 artists, and 3,859 observations. The v2
discovery asset file SHA-256 is
`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`.
`poe deploy` deployed commit `2721688` to
[`https://opennoise.horv.co`](https://opennoise.horv.co). A read-only
production manifest check returned v2 with promotion receipt hash
`955ac09ab3534754810da8929709722cfcc739e20055201adc9be0a61e878f74` and the
same discovery asset hash. Fetching the public asset again produced the same
SHA-256 value. The nested static v1 compatibility payload is not a release
schema. See the [local batch checkpoint](checkpoints/SEALED_QID_DIRECT_BRIDGE_LOCAL_BATCH_20260921.md).

The fixed v3 candidate also has one terminal observed-positive-only comparison
to the retained historical signal. It accepts only one-to-one exact normalized
name matches: 288 matched names, 315 candidate abstentions, and 6,003
historical abstentions. Membership presence overlaps 257 of 6,289 historical
observed positives; canonical neighborhoods overlap 532 of 37,517. These are
coverage diagnostics with no precision, negative inference, parity, or release
claim. Its adapter pins the reviewed v3 and evaluation-only historical custody
hashes and permits only fresh local report files. See [the terminal evaluation
checkpoint](checkpoints/PHASE3_V3_TERMINAL_HISTORICAL_EVALUATION_20260921.md).

A single subsequent local-only public-model/layout projection attempt used a
fresh copy of that candidate and stopped before artifact or database output.
The replay candidate has 4,948 direct-source evidence rows, but its intentionally
local-only policies deny embedding/export and it has zero modelable genres, so
the public model loader fails closed on empty inputs. No retry or policy change
is authorized by that result; see
`checkpoints/PHASE3_PUBLIC_MODEL_LAYOUT_PROJECTION_FEASIBILITY_20260921.md`.

## Static Pages delivery status

The deployed static release is commit `2721688` and is available at
[`https://opennoise.horv.co`](https://opennoise.horv.co). Its certified v3
atlas has 2,945 placed nodes and 34,937 structural edges. The Pages manifest,
HTML, JavaScript, JSON, asset names, and rendered focus links contain no
retired identifier text. A clean `open_focus=item…` bookmark works, while an
old prefixed bookmark is accepted only as input and immediately canonicalized
to its clean URL.

The deployed static Pages release has a deterministic, offline label atlas rather
than a per-frame label grid. It uses finite, data-derived reveal scales and
one stable near-dot placement per public map node. Disclosure can only be
delayed to smooth density; it does not rerank labels while navigating. A
selected genre offers `Zoom here`, which enters the same static browse view at
its exact world position and preserves Back to the structural detail.

The release passed a fresh sealed-layout rebuild, all-scale
label-box clearance for 2,945 labels, and strict loopback browser certification. The
browser evidence covers one-pixel pan anchoring, equivalent button and pinch
paths, gradual fixed-center admission, deep selected-label readability,
hierarchy landmarks, structural focus and Back, direct artist discovery, and
mobile pinch. The v3 deterministic separation removes all near-coordinate
groups at `1e-4`. Every placed label now has a reveal scale below `1e6`;
the maximum is about 835,120. The stricter label gate allows a still-visible
dot to lose its caption only at a clipped viewport edge or under visible UI.
This improves legibility without claiming that all genre relationships are
correct or that every name has a placed coordinate.

The deployed fingerprinted export has been checked against the manifest,
clean public IDs, the static discovery asset, and the same browser flows.
The artist-search export now carries exact, source-backed MusicBrainz and
Wikidata links for all 1,126 exported artists. The production manifest reports
the v2 promotion receipt hash
`955ac09ab3534754810da8929709722cfcc739e20055201adc9be0a61e878f74`, and its
public discovery asset matches file SHA-256
`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`.

The deployed static artist detail includes a `Similar artists` section,
explained solely by shared directly observed genres and navigable within the
existing local discovery data.

Temporary rejected zoom/review worktrees and merged clean-ID worktrees were
pruned on 2026-09-16. A read-only worktree check on 2026-09-21 found only the
main tree and the Phase 3 public-evidence worktree. The latter retains the
sealed raw source vault needed for replay and must not be removed while that
gate is open.

## Next data work

- The [direct P136 static v2 audit](checkpoints/DIRECT_P136_STATIC_V2_ZERO_LIFT_20260923.md)
  finds no safe, unambiguous, positioned addition to the deployed bridge.
  The 1,089 unrepresented observations are blocked by ambiguous labels,
  multiple positioned seeds, unplaced exact links, or no unique exact link.
  This corrects a possible reading of the two observation `safe_exact` graph
  review result. Both map nodes are unplaced in the canonical layout and
  remain pending human review.
- A bounded local-only ListenBrainz recording-ID probe inspected 250,000
  retained raw listens: 2,176 submitted recording UUIDs, zero server-resolved
  recording UUIDs, six exact catalog overlaps, and zero pairs at the
  five-listener privacy floor. It is not representative or evaluative and
  cannot enter the model; see the [recording signal checkpoint](checkpoints/LISTENBRAINZ_RECORDING_SIGNAL_20260922.md).
- The resulting exact local recording-ID cohort has 2,098 UUIDs, but the union
  of five retained local MusicBrainz catalog slices covers only eight. This is
  a receipt-bound readiness result, not a missing-recording claim; see the
  [catalog coverage checkpoint](checkpoints/LISTENBRAINZ_RECORDING_CATALOG_COVERAGE_20260922.md).
- A separate bounded local-only artist-session approximation uses exact artist
  MBIDs with a documented fixed-duration assumption, 300-second sessions,
  per-user cap five, and score threshold above ten. It is not a reproduction
  of ListenBrainz production similarity and has no model or serving use; see
  the [session checkpoint](checkpoints/LISTENBRAINZ_ARTIST_SESSION_APPROXIMATION_20260922.md).
- The matched local-only direct-custody/aggregate-co-listen holdout is
  receipt-bound and evaluation-only. Its capacity follow-up expands direct
  peers beyond top ten and keeps a declared co-listen cap sensitivity; neither
  is a factual membership claim or model input. See the [matched
  holdout](checkpoints/MUSICBRAINZ_DIRECT_CUSTODY_COLISTEN_HOLDOUT_20260923.md)
  and [capacity follow-up](checkpoints/MUSICBRAINZ_DIRECT_CUSTODY_COLISTEN_CAPACITY_HOLDOUT_20260923.md).
- A local-only MusicBrainz Album query now returns up to five ranked examples
  per seed for an exact genre name or credited artist MBID from the verified
  release-group report. Genre rows remain native proper-genre observations;
  albums are source-context examples, and credited artists are not direct
  artist-genre membership. This query has no track or listening evidence yet.
  Next, link release-group context to the existing direct and album-supported
  artist evidence and playlist evidence while preserving each source role. See
  the [Album query checkpoint](checkpoints/MUSICBRAINZ_ALBUM_DISCOVERY_QUERY_20260923.md),
  [release-credit audit](checkpoints/MUSICBRAINZ_RELEASE_TRACK_DISCOVERY_SIGNAL_AUDIT_20260923.md),
  and [playlist role audit](checkpoints/LISTENBRAINZ_PLAYLIST_SIGNAL_QUALITY_AUDIT_20260923.md).
- A reverse-order sensitivity arm over the same seven privacy-filtered daily
  aggregate windows retains the train-only common-neighbor advantage on its
  fixed common scored cohort (Recall@10 `0.152532` versus popularity
  `0.142857` and direct-IDF `0.062166`). It is a local retrieval diagnostic,
  not a genre, membership, similarity, playlist, or promotion claim; see the
  [directional holdout checkpoint](checkpoints/LISTENBRAINZ_DIRECTIONAL_HOLDOUT_20260923.md).
- A fixed 10,000-record-per-day user-disjoint raw ListenBrainz slice abstained:
  its separately privacy-filtered test arm had no five-distinct-user artist
  pairs. The bound will not be expanded post hoc; see the [user-disjoint
  abstention checkpoint](checkpoints/LISTENBRAINZ_USER_DISJOINT_HOLDOUT_ABSTENTION_20260923.md).
- A separate Last.fm 360K >=5-user exact-artist aggregate retrieves 610 of
  6,818 endpoint-matched direct-custody positives at 20 (8.9469%). On the
  identical endpoint cohort, fixed-fold direct popularity retrieves 7,
  direct-IDF retrieves 226, and Last.fm graph weighted degree retrieves 40.
  On the 873 common Last.fm and ListenBrainz endpoints, Last.fm retrieves 257,
  direct popularity 0, direct-IDF 42, and graph weighted degree 39. The two
  graphs remain separately ranked. Their top-20 hits are 94 both, 163 Last.fm
  only, and 40 ListenBrainz only. This is a local source-bound retrieval
  diagnostic with no merged ListenBrainz model or membership claim. See the
  [Last.fm holdout](checkpoints/LASTFM_DIRECT_CUSTODY_HOLDOUT_20260923.md).
- A fixed local-only reciprocal-rank fusion of separate Last.fm and
  ListenBrainz top-20 lists is rejected. It recovers 238 of the same 873
  common endpoint targets, below Last.fm alone at 257. The separate 40-item
  candidate union contains 297 targets, but it is coverage only and does not
  authorize tuning, a graph merge, model use, or publication. See the [rank
  fusion holdout](checkpoints/LASTFM_LISTENBRAINZ_RANK_FUSION_HOLDOUT_20260923.md).
- The UPF Last.fm 360K user and artist play matrix is now checksum-verified in
  ignored local custody through its creator-attributed Zenodo record. Its
  completed streaming aggregate read 17,559,530 rows and retained 485,840
  exact artist pairs only at a >=5-user floor. The ignored aggregate SQLite is
  receipt-hashed local custody, not a counts-only artifact; it carries no user
  identifiers and has no public, model, factual-membership, or genre-gold role.
  A separate ignored order receipt found no play-count increases in 17,200,181
  adjacent rows within the contiguous user blocks. The cap therefore selects
  the first ten unique valid exact artist MBIDs in non-increasing play-count
  order. It is not a top-ten-overall-rows rule when non-exact or malformed rows
  appear before valid exact MBIDs.
  The observed strict-parser counts (359,349 contiguous blocks; 160,131 exact
  artist UUIDs) remain distinct from the source page's published user and
  artist figures. See the [source feasibility checkpoint](checkpoints/LASTFM_360K_SOURCE_FEASIBILITY_20260922.md).
  A separate matched local holdout compares 171 repeated playlist pair
  potentials from 46 anchor artists against the privacy-filtered aggregate.
  It recovers 41 of 171 pairs, with Recall at 10 of 36 of 342 directed ranking
  events versus 6 of 342 for the seeded baseline. This one-account comparison
  is descriptive only, not independent truth, a model input, or a quality
  gate; see the [matched holdout](checkpoints/LISTENBRAINZ_PLAYLIST_LASTFM_360K_MATCHED_HOLDOUT_20260922.md).
- A local-only ListenBrainz playlist probe can fetch explicit public playlist
  MBIDs into receipt-bound raw JSPF objects and exact recording UUID snapshots,
  with source order, curator uncertainty, and normalized pair support. A
  ten-playlist single-discovery-cohort observation has 527 unique recordings,
  11 exact overlaps with the current 623-recording local catalog, and no model
  use. The route establishes only that the service lists the cohort as created
  by one account; all curator states, human curation, and manual/editorial
  selection remain unestablished. Its source-pinned, round-robin 24-recording
  exact MusicBrainz artist-credit bridge reached 23 exact lookups and 27
  distinct within-playlist cross-recording artist-pair potentials. A separate
  50-recording disjoint follow-up selected exact IDs only, with selection
  SHA-256 `2bac1641dad3201d77086344de5824f39f7f6ed6ae523dd91c043a9c32ee74f1`.
  Its first response stalled, the attempt was interrupted, and it retained no
  artist-credit result or custody object; see the [source research
  checkpoint](checkpoints/OPEN_LISTENING_PLAYLIST_SOURCE_RESEARCH_20260922.md).
  Another local JSPF extension parse found 603 syntactically valid source-claimed
  artist URIs across all 557 occurrences (344 distinct IDs); its claimed ID sets agree
  with the 23 checked exact MusicBrainz credits only. Its 13,584 cross-track
  artist-pair potentials, including 171 repeats across playlists, describe one
  account cohort only, not independent account, curator, or privacy-floor
  support. The first bounded cross-account acquisition attempt retained no
  response body, so no cross-account measurement exists. None of these results
  has genre, model, serving, or public use. See the [playlist probe](checkpoints/LISTENBRAINZ_PLAYLIST_PROBE.md),
  [user-created route cohort](checkpoints/LISTENBRAINZ_USER_CREATED_PLAYLIST_COHORT_20260923.md),
  [JSPF source-claim receipt](checkpoints/LISTENBRAINZ_PLAYLIST_JSPF_EMBEDDED_ARTIST_IDENTIFIERS_20260923.md),
  [cross-account feasibility checkpoint](checkpoints/LISTENBRAINZ_CROSS_ACCOUNT_PLAYLIST_FEASIBILITY_20260923.md),
  and [artist-credit bridge](checkpoints/LISTENBRAINZ_PLAYLIST_MUSICBRAINZ_ARTIST_BRIDGE_20260923.md).
  The retained listing custody has one 7,013-byte body with 20 playlist IDs
  and SHA-256 `564cacb56623cd13b6760abcf18b9ac5c645e6e863bfc2ab9cea0891656bcfd2`.
  Even a future pair of listing receipts could establish only distinct
  service-declared account strings, not independently sourced people, human
  curation, listener support, or genre evidence.
  See the [listening and playlist signal synthesis](checkpoints/OPEN_LISTENING_PLAYLIST_SIGNALS_20260923.md)
  for the source comparison and bounded next test.
- Expand direct artist and catalog coverage, preserving source claims and
  rejecting ambiguous presentation identity bridges.
- The identity-safe MusicBrainz proper-genre frontier has 11 seeds and 130
  rows. The 544-seed loose-tag frontier remains nonfactual review evidence;
  see [the proper-genre checkpoint](checkpoints/MUSICBRAINZ_DIRECT_PROPER_GENRE_FRONTIER_20260921.md).
  A further local-only exact-artist review route finds two exclusive positioned
  anchors among those 11 seeds and retains the other nine as abstentions. It
  reads seed-ID placement state only, not coordinates, and cannot alter the
  public layout or serving; see [the anchor projection checkpoint](checkpoints/MUSICBRAINZ_DIRECT_PROPER_GENRE_ANCHOR_PROJECTION_20260923.md).
- The newer all-seed MusicBrainz direct-claim gate measures 697
  reconciliation-safe seeds, including 423 not in the current 344-genre static
  discovery asset. Its compact filtered projection is now portable custody,
  but the original ignored 682 MiB archive is still required for raw-source
  replay; public export remains policy-blocked. See [the publication-gate
  checkpoint](checkpoints/MUSICBRAINZ_DIRECT_PUBLICATION_GATE_20260922.md) and
  [portable custody checkpoint](checkpoints/MUSICBRAINZ_DIRECT_PROPER_GENRE_PORTABLE_CUSTODY_20260922.md).
- A separate local-only canonical-name custody projection covers 164,404 of
  198,409 exact direct artist MBIDs. It is not serving input or public export;
  see [the canonical-name custody checkpoint](checkpoints/MUSICBRAINZ_DIRECT_CANONICAL_ARTIST_NAME_CUSTODY_20260922.md).
- The exact direct artist and genre positive recovery check found 7,945
  overlaps among 22,159 H3 positive pairs in the custody scope. It remains an
  evaluation-only, positive-only diagnostic. See [the exact pair
  checkpoint](checkpoints/MUSICBRAINZ_DIRECT_ARTIST_GENRE_H3_POSITIVE_RECOVERY_20260922.md).
- The separately constructed direct-custody peer graph has one terminal H3
  top-10 recovery check: 1,840 of 4,075 positive reference edges. It is
  positive-only and cannot provide precision; see [the peer holdout
  checkpoint](checkpoints/MUSICBRAINZ_DIRECT_CUSTODY_PEER_H3_HOLDOUT_20260922.md).
- A bounded source-only audit found 13 candidate pairs where at least 1,000
  shared artists are at least 90% one exact sorted seed-membership signature.
  These require review and do not suppress candidates or delete facts; see
  [the signature concentration checkpoint](checkpoints/MUSICBRAINZ_DIRECT_CUSTODY_SIGNATURE_CONCENTRATION_20260922.md).
- A follow-up local-only exact-signature ablation recomputes a shadow peer
  graph after removing only complete dominant-signature cohorts. It is a
  review tool and cannot alter the baseline graph or public output; see [the
  ablation checkpoint](checkpoints/MUSICBRAINZ_DIRECT_CUSTODY_EXACT_SIGNATURE_ABLATION_20260922.md).
- The local custody-only delta report confirms 274 shared IDs and 423
  candidate-only IDs. Of the candidate-only IDs, 412 are placed and 11 are
  unplaced. It retains 139,398 candidate observations and abstains from artist
  display names and static UI sizing. See [the delta checkpoint](checkpoints/MUSICBRAINZ_DIRECT_DISCOVERY_DELTA_20260922.md).
- The exact-MBID local name-join checkpoint finds canonical names for 115,269
  of 139,398 distinct candidate-only direct artist pairs (82.69%). Its 12.2 MB
  figure is only an uncompressed minimal candidate-shape estimate, not a
  production asset or publication authorization; see [the name-join
  checkpoint](checkpoints/MUSICBRAINZ_DIRECT_NAME_JOIN_FRONTIER_20260922.md).
- The completed local-only exact-MBID recovery supplies 34,005 unique names
  with no conflicts or missing targets. Its receipt is bound to the same direct
  and canonical-name custody cohort; it is not serving input or publication
  authorization. A fresh local name-join report uses it to cover all 139,398
  candidate-only direct pairs (100%, up from 115,269 / 82.69%), without
  changing `dist` or the public asset. See [the recovery checkpoint](checkpoints/MUSICBRAINZ_DIRECT_ARTIST_NAME_RECOVERY_20260922.md) and
  [the name-join checkpoint](checkpoints/MUSICBRAINZ_DIRECT_NAME_JOIN_FRONTIER_20260922.md).
- A receipt-checked local source replay matched 139,268 direct MusicBrainz rows
  across 412 placed candidate-only seeds in both directions. The ignored
  candidate remains local-only and is not serving input; see the
  [source replay checkpoint](checkpoints/MUSICBRAINZ_DIRECT_LOCAL_STATIC_SOURCE_REPLAY_20260923.md).
- A future static release needs a separately reviewed MusicBrainz source role,
  payload revision, promotion receipt, quality report, and browser gate. The
  existing custody and v2 release contracts remain unchanged; see the
  [publication readiness checkpoint](checkpoints/MUSICBRAINZ_DIRECT_STATIC_PUBLICATION_READINESS_20260923.md).
- A pending local policy-review input now pins the exact 412 placed MusicBrainz
  seeds, source wording, and required quality-report fields. It remains
  unapproved and does not change the public v2 release; see the
  [policy-review input checkpoint](checkpoints/MUSICBRAINZ_DIRECT_STATIC_POLICY_REVIEW_INPUT_20260923.md).
- A local quality report now rechecks the pinned custody object against the
  exact 412-seed candidate. It records coverage, exclusions, exact-ID checks,
  per-genre counts, and generated review links. It is not human approval and
  does not allow public export or serving; see the [quality report
  checkpoint](checkpoints/MUSICBRAINZ_DIRECT_STATIC_QUALITY_REPORT_20260923.md).
- A read-only static-packaging audit distinguishes that exact 12.2 MB minimal
  JSONL boundary from the much larger current-v2 extrapolation and proposes
  bounded lazy genre shards only for a future authorized release; see [the
  packaging frontier](checkpoints/MUSICBRAINZ_DIRECT_STATIC_PACKAGING_FRONTIER_20260922.md).
- The conservative singleton peer candidate has no placed-to-placed edges, so
  it has no placed holdout or proposed coordinates. The separate minimum-two
  placed-peer diagnostic does not transfer to this candidate; see [the peer
  layout holdout](checkpoints/CONSERVATIVE_MUSICBRAINZ_PEER_LAYOUT_HOLDOUT_20260921.md).
- The local, non-publishing identity-bridge audit now separates 245 one-to-one
  exact label matches, 101 non-exact mappings needing review, and 95
  conflicting or ambiguous edges. Its append-only typed review ledger does not
  auto-promote exact matches or change the public bridge. A deterministic
  human-review packet now ranks all 441 edges by potential direct-observation
  lift and carries source-bound artist evidence. The fresh current-v2 audit
  finds 29 unbridged exact matches, but their combined eligible direct
  observation lift is only 2. See [the current v2 checkpoint](checkpoints/DIRECT_BRIDGE_CURRENT_V2_FRONTIER_20260922.md).
  It does not publish anything.
- Add independently evaluated, versioned promotion paths for derived
  memberships and similarity; keep direct observations separate until then.
- Complete the MusicBrainz release and track catalog chain. A larger local
  bounded run now has 94 releases and 1,115 tracks, up from 55 and 660. It
  passed offline-identical success and failure replay with zero upstream
  requests; one stale recording stayed an explicit abstention. This is a
  metadata-only candidate, not yet the published catalog or a full crawl. See
  the [candidate checkpoint](checkpoints/MUSICBRAINZ_CATALOG_EXPANSION_CANDIDATE.md).
  A separate local materialization retains 87 distinct releases, 94 media,
  1,032 tracks, and 1,031 recordings. Artist credits remain absent from the
  original retained source cache. A separate, bounded MusicBrainz refresh now
  retains 1,118 exact release and recording artist-credit relations from 87
  responses. Its v2 cache verifies all 87 source projections offline; no
  public database changed. A separate fresh SQLite candidate now retains
  those credits for 352 exact-MBID artists with two source-bound provenance
  records; it is not serving input. See the
  [materialized credit checkpoint](checkpoints/MUSICBRAINZ_ARTIST_CREDIT_MATERIALIZED_CANDIDATE.md),
  [artist-credit checkpoint](checkpoints/MUSICBRAINZ_ARTIST_CREDIT_REFRESH_CANDIDATE.md) and
  [materialization checkpoint](checkpoints/MUSICBRAINZ_CATALOG_MATERIALIZATION_CANDIDATE.md).
  The local-only [exact-ID static-overlap checkpoint](checkpoints/MUSICBRAINZ_ARTIST_CREDIT_STATIC_OVERLAP_20260921.md)
  measures 121 public-direct and 101 static-discovery artist overlaps without transferring memberships.
  A separate pinned diagnostic found 87 release groups, 284 release-group
  support claims, and 3,132 exact credit matches. The genre or tag support
  remains release-group context and is not an artist-direct claim; see the
  [release-credit diagnostic](checkpoints/MUSICBRAINZ_RELEASE_CREDIT_GENRE_DIAGNOSTIC_20260922.md).
  A separate bounded entity-native observation adapter pins recording, release,
  and release-group response bytes while keeping proper genres and positive-count
  tags separate. It is local-only and cannot propagate artist memberships; see
  the [entity observation checkpoint](checkpoints/MUSICBRAINZ_ENTITY_GENRE_OBSERVATION_20260923.md).
  A separate local archive-order pilot retains 10,000 native release-group
  observations with exact record hashes and separate proper genres and positive
  tags. It is not a full-corpus estimate or an artist source. See [the native
  release-group checkpoint](checkpoints/MUSICBRAINZ_RELEASE_GROUP_NATIVE_OBSERVATION_20260923.md).
  Its exact archive-order replay now preserves release-group title, type,
  first-release date, ordered exact artist credits, and native genre UUID/votes
  in a separate local support receipt. Only positive-vote genres form
  credited-artist contextual support; all native facts remain retained and no
  row is artist membership. See [the credited-artist support checkpoint](checkpoints/MUSICBRAINZ_RELEASE_GROUP_NATIVE_ARTIST_SUPPORT_20260923.md).
  A separately pinned aggregate-only full-corpus native census completed in a
  persistent local process. It counted 4,499,286 parsed release groups,
  4,596,870 proper-genre observations, and exact normalized overlap with 911
  seeds, including 68 unplaced seeds. It remains local-only and makes no
  extrapolation from the 10,000-record sample. A pinned aggregate decision
  report finds positive native-genre observations for all 68 exact unplaced
  name matches, but it cannot create artist membership, relations, or map
  placements. See [the census checkpoint](checkpoints/MUSICBRAINZ_RELEASE_GROUP_NATIVE_CENSUS_20260923.md).
  A separate full-corpus tag census over the same pinned archive found 1,954
  exact normalized seed-name matches, including 385 unplaced names. It retains
  only aggregate tag vote signs and exact seed names, and all observed counts
  in this archive were positive. Tags remain distinct from proper genres and
  cannot assert membership, relations, or placements. See [the tag census
  checkpoint](checkpoints/MUSICBRAINZ_RELEASE_GROUP_TAG_CENSUS_20260923.md).
  The local MusicBrainz derived entity-tag adapter has fixture coverage for
  recording, release, and release-group aggregate tags. It remains local-only and
  has not replayed the absent declared archive. See
  [the derived tag checkpoint](checkpoints/MUSICBRAINZ_DERIVED_ENTITY_TAGS_20260923.md).
  The already verified release-group JSON archive can support a separate native
  release-group observation pass sooner. Neither path propagates tags to artists.
  A local v2 static-export gate now verifies source policy, report quality, and
  exact MBIDs before producing 961 credit-metadata rows for 116 artists. Its
  exact candidate and source projections are now
  [portable under custody](checkpoints/MUSICBRAINZ_CREDIT_PORTABLE_CUSTODY_20260922.md),
  but the asset is not deployed: a real UI approval binding, artist-detail
  integration, and browser-certified build remain required. An isolated local
  renderer can export one selected artist's source-bound credit metadata under
  `.cache`; it is a non-public preview seam, not UI approval, static-page
  integration, browser certification, or deployment. See the
  [local render checkpoint](checkpoints/MUSICBRAINZ_CREDIT_ARTIST_DETAIL_LOCAL_RENDER_20260922.md).
  A separate local HTML preview wrapper checks a separately supplied typed
  approval declaration and the already-gated asset before writing its `.cache`
  output. It cannot recheck the candidate report or policy without the original
  database and report, and it does not approve public UI integration. See the
  [HTML preview checkpoint](checkpoints/MUSICBRAINZ_CREDIT_ARTIST_DETAIL_LOCAL_HTML_20260922.md).
- Keep metadata candidates separate from published metadata examples.
- Review the 484 source-bound genre candidates now queued by the versioned
  workflow. The local promotion preflight binds review and triage receipts,
  blocks lexical-only or ambiguous presentation rows, and always requires a
  separate source-publication authorization; none is published.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate. The new
  evaluator abstains on its synthetic fixture; no retained source or accepted
  threshold policy qualifies yet. FMA metadata is an independent candidate,
  but exact artist and genre bridges are not present, so it cannot yet score
  the model. The separate AcousticBrainz Genre Dataset offers recording-level
  metadata labels, but its labels were imported into MusicBrainz recording
  tags, so it is diagnostic only without a source-level leakage audit and an
  exact recording-to-artist bridge. The completed isolation audit has 63
  exact recording rows with a single primary artist, but abstains because no
  retained prediction artifact and construction receipt proves exclusion of
  MusicBrainz tag/recording/release inputs and historical Every Noise. Its
  frozen Wikidata-only feasibility arm has only three literal `jazz` positives
  and zero matching predictions, a coverage observation rather than a quality,
  negative-label, artist-gold, or promotion result. See the
  [gold-set workflow](evidence/INDEPENDENT_ARTIST_GENRE_GOLD.md),
  [source audit](checkpoints/INDEPENDENT_GOLD_SOURCE_AUDIT.md), and
  [AcousticBrainz audit](checkpoints/ACOUSTICBRAINZ_GENRE_DATASET_EVALUATION_AUDIT.md),
  and [source-isolation checkpoint](checkpoints/ACOUSTICBRAINZ_RECORDING_GOLD_ISOLATION_20260922.md).
  The existing source-isolation gate remains a no-go for artist gold and
  promotion. A separate local diagnostic freezes 63 Wikidata-only recording
  predictions before parsing or using AcousticBrainz labels. Its label pass
  finds three unique literal `jazz` positives and zero exact prediction
  overlaps. This positive-only recording observation is not a quality result,
  artist gold, or promotion gate; see the
  [Wikidata recording diagnostic](checkpoints/ACOUSTICBRAINZ_WIKIDATA_RECORDING_DIAGNOSTIC_20260923.md).
  A positive-only [Last.fm 2007 overlap check](checkpoints/LASTFM_ARTISTTAGS2007_STATIC_OVERLAP.md)
  is diagnostic, not independent gold or a release gate.
- A separate Last.fm ArtistTags2007 blind review packet contains 100 positive-tag
  questions. The rows remain unlabeled, and missing tags are not negative claims.
- A second local-only [exact-MBID/literal-v2 review packet](checkpoints/LASTFM_ARTISTTAGS2007_STATIC_GENRE_REVIEW.md)
  binds the deployed static-v2 asset and source-row hashes. It is unreviewed,
  abstaining candidate selection only, not a genre bridge, label set, or gate.
- The local-only Last.fm ArtistTags2007 literal candidate has 192,614 rows
  across 1,317 seeds. It is neither factual membership nor gold, model input,
  or release evidence; see the [literal candidate checkpoint](checkpoints/LASTFM_ARTISTTAGS2007_LITERAL_SEED_CANDIDATES.md).
- Expand source cache replay until every selected release manifest input can be
  acquired or restored, ingested, and replayed into the certified database.
  Historical declaration replay does not provide that database certification.
- Treat the recorded v3 versus sealed semantic comparison as documentation
  only until the existing reusable, hash-pinned comparator passes the
  normalized provenance-binding equality check; model and artist-pair
  projections already match, but one provenance fingerprint differs. See the
  [semantic comparison discrepancy](checkpoints/PHASE3_V3_SEMANTIC_COMPARATOR_DISCREPANCY_20260921.md).
- Before any v3 promotion, require a reviewed local overlay adapter report,
  an independently reviewed artist identity/display bridge, a fresh sealed
  source-cache replay, and the existing public-model, static-export, and
  browser certification gates. Terminal historical coverage is not a substitute
  for any of these gates.

## Later experiments

- The [ListenBrainz account cohort pilot](checkpoints/LISTENBRAINZ_INDEPENDENT_ACCOUNT_PLAYLIST_PILOT_20260923.md)
  is the next conditional playlist experiment. It can measure exact recording
  membership across up to three service-declared accounts, but it cannot
  establish independent people or human curation. It runs only after a
  compliant discovery response or independently supplied public identifier.
- Improve semantic neighborhoods and overview landmark choices against open
  graph evidence. The [layout navigation audit](checkpoints/LAYOUT_NAVIGATION_AUDIT.md)
  records the v2 baseline; the [v3 selection](checkpoints/LAYOUT_NAVIGATION_SEPARATION_SWEEP.md)
  records the measured geometry change. Better placement does not substitute
  for more artist and genre evidence. Of the 3,346 unplaced names, 2,635 have
  no proposal in either the current hierarchy review or open label graph.
  The [unplaced source frontier](checkpoints/UNPLACED_SOURCE_FRONTIER_20260921.md)
  records the exact split and input hashes. The current MusicBrainz contextual
  tag extract has zero exact unplaced-name matches by construction; the
  [coverage checkpoint](checkpoints/MUSICBRAINZ_CONTEXTUAL_UNPLACED_CHECKPOINT_20260921.md)
  records why a pre-filter source slice is needed. The retained direct-tag
  lower bound nevertheless has positive rows for 577 unplaced seeds. The
  [direct-tag audit](checkpoints/MUSICBRAINZ_PREFILTER_UNPLACED_AUDIT_20260921.md)
  separates those positives from publishable membership and records their
  current peer-edge abstentions. A local Last.fm-supported review produced
  109 proposed edges for 43 unplaced seeds. Forty-two seeds overlap the
  existing review frontier and one is new; these remain proposals, not
  membership or placement claims. See the
  [unplaced co-listen review](checkpoints/MUSICBRAINZ_UNPLACED_COLISTEN_REVIEW_EDGES_20260922.md).
  A local reviewer packet now groups 3,104 hierarchy-review rows for 492
  unplaced seeds with 109 co-listen context rows for 43 seeds. It pins all
  inputs and keeps every row as an abstention. See the [structural relation
  review](checkpoints/UNPLACED_STRUCTURAL_RELATION_REVIEW_20260923.md).
  A [streamed peer-threshold
  audit](checkpoints/MUSICBRAINZ_PEER_THRESHOLD_SENSITIVITY_20260921.md)
  finds a review-only hub-filtered route to 414 of the 495 overlap-abstained
  unplaced seeds; it has not changed the public layout.
- The [final conservative peer candidate](checkpoints/CONSERVATIVE_MUSICBRAINZ_PEER_CANDIDATE_20260921.md)
  is local-only: 1,497 fixed source-only edges reach 414 scoped seeds. Its
  terminal Last.fm diagnostic is coverage evidence, not a quality gate or a
  publication decision.
- A source-family calibration now replays the same eligible singleton-witness
  rule over the full pinned direct MusicBrainz membership input. Its
  target-excluded placed holdout improves mean peer-centroid error by 0.0289
  over the leave-one-out global centroid baseline, then permits 405 explicitly
  local-only candidate positions from the frozen sparse frontier. It is neither
  a factual placement claim nor a serving or publication path; see the
  [calibrated candidate checkpoint](checkpoints/FULL_DIRECT_PEER_CALIBRATED_UNPLACED_CANDIDATE_20260923.md).
- A source-isolated sparse cosine reranking ablation improves Recall@20 from
  188 to 315 on the same 960 aggregate-supported held-out targets. It does not
  broaden aggregate graph reach, create memberships, alter serving, or
  authorize export; see [the sparse cosine transfer checkpoint](checkpoints/SPARSE_GENRE_COSINE_TRANSFER_20260923.md).
- The five-fold sparse cosine robustness result remains underpowered for niche
  genres, so it is a local experiment rather than a promotion input. See [the
  robustness checkpoint](checkpoints/SPARSE_GENRE_COSINE_ROBUSTNESS_20260923.md).
- A fixed direct-peer and cosine rank fusion loses to the best control on both
  full and endpoint-matched cohorts. Direct-peer full-holdout reach is a
  candidate-coverage result, while cosine has the stronger matched ranking.
  See [the hybrid transfer checkpoint](checkpoints/SPARSE_GENRE_HYBRID_TRANSFER_20260923.md).
- Keep historical output as a terminal, evaluation-only reference after each
  open-model checkpoint is sealed; it must never become a construction input.
- The [2026-09-23 provenance audit](checkpoints/OPEN_MODEL_PROVENANCE_AUDIT_20260923.md)
  confirms no direct Every Noise coordinate, artist, or similarity value flow
  into the certified static release. It also records that local Phase 3 v3
  remains unpromotable until a field-level, transitive construction receipt
  proves the names-only boundary.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
