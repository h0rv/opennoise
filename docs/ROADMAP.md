# Roadmap

## Current product

The default static map retains 6,291 immutable names; 2,945 have placed map
coordinates and 3,346 remain preserved but unplaced. It has one landscape
surface with stable neighborhoods, semantic zoom, genre detail, search, pan,
zoom, and dark mode.

Static discovery is a separate, lazy JSON asset, not a backend API. The current
sealed public catalog has 4,948 export- and display-authorized direct Wikidata
P136 observations. An exact, one-to-one label bridge puts 2,900 of them on 260
map genres for 1,008 artists. Artist overlap is explicitly shared direct mapped
genres, never an unexplained similarity claim. See
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
portable store. The full release manifest source vault and derived database
are not yet reproducible from this workflow. A separate local replay check now
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

A single subsequent local-only public-model/layout projection attempt used a
fresh copy of that candidate and stopped before artifact or database output.
The replay candidate has 4,948 direct-source evidence rows, but its intentionally
local-only policies deny embedding/export and it has zero modelable genres, so
the public model loader fails closed on empty inputs. No retry or policy change
is authorized by that result; see
`checkpoints/PHASE3_PUBLIC_MODEL_LAYOUT_PROJECTION_FEASIBILITY_20260921.md`.

## Static Pages delivery status

The deployed static release is main commit `592fe7c`. Its certified v3
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
Wikidata links for all 1,008 exported artists. The Pages deployment URL
and `opennoise.horv.co` both serve the same SHA-256 manifest as the certified
local `dist`: `99f2079f85b8889501d40dfb0a98bcb48e98c036655bd4369c8c102a4f33e3aa`.

Temporary rejected zoom/review worktrees and merged clean-ID worktrees were
pruned on 2026-09-16. A read-only worktree check on 2026-09-21 found only the
main tree and the Phase 3 public-evidence worktree. The latter retains the
sealed raw source vault needed for replay and must not be removed while that
gate is open.

## Next data work

- Expand direct artist and catalog coverage, preserving source claims and
  rejecting ambiguous presentation identity bridges.
- The local, non-publishing identity-bridge audit now separates 245 one-to-one
  exact label matches, 101 non-exact mappings needing review, and 95
  conflicting or ambiguous edges. Its append-only typed review ledger does not
  auto-promote exact matches or change the public bridge. A deterministic
  human-review packet now ranks all 441 edges by potential direct-observation
  lift and carries source-bound artist evidence. It does not publish anything.
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
- Keep metadata candidates separate from published metadata examples.
- Review the 484 source-bound genre candidates now queued by the versioned
  workflow, then design a separate publication gate. None is published.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate. The new
  evaluator abstains on its synthetic fixture; no retained source or accepted
  threshold policy qualifies yet. FMA metadata is an independent candidate,
  but exact artist and genre bridges are not present, so it cannot yet score
  the model. The separate AcousticBrainz Genre Dataset offers recording-level
  metadata labels, but its labels were imported into MusicBrainz recording
  tags, so it is diagnostic only without a source-level leakage audit and an
  exact recording-to-artist bridge. See the
  [gold-set workflow](evidence/INDEPENDENT_ARTIST_GENRE_GOLD.md),
  [source audit](checkpoints/INDEPENDENT_GOLD_SOURCE_AUDIT.md), and
  [AcousticBrainz audit](checkpoints/ACOUSTICBRAINZ_GENRE_DATASET_EVALUATION_AUDIT.md).
  A positive-only [Last.fm 2007 overlap check](checkpoints/LASTFM_ARTISTTAGS2007_STATIC_OVERLAP.md)
  is diagnostic, not independent gold or a release gate.
- Expand source cache replay until every selected release manifest input can be
  acquired or restored, ingested, and replayed into the certified database.
  Historical declaration replay does not provide that database certification.

## Later experiments

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
  current peer-edge abstentions. A [streamed peer-threshold
  audit](checkpoints/MUSICBRAINZ_PEER_THRESHOLD_SENSITIVITY_20260921.md)
  finds a review-only hub-filtered route to 414 of the 495 overlap-abstained
  unplaced seeds; it has not changed the public layout.
- The [final conservative peer candidate](checkpoints/CONSERVATIVE_MUSICBRAINZ_PEER_CANDIDATE_20260921.md)
  is local-only: 1,497 fixed source-only edges reach 414 scoped seeds. Its
  terminal Last.fm diagnostic is coverage evidence, not a quality gate or a
  publication decision.
- Keep historical output as a terminal, evaluation-only reference after each
  open-model checkpoint is sealed; it must never become a construction input.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
