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
artists observed there. The artist order uses shared direct genre counts, not
a learned similarity model.

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
then requires its generated joint receipt to match the sealed object. Current
source declarations still do not reproduce the retained historical declaration
hashes, and neither candidate database is byte-identical or certified.

## Static Pages delivery status

The deployed static release is main commit `ee9e1e1`. Its certified
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

The release candidate has passed a fresh sealed-layout rebuild, all-scale
label-box clearance for 2,945 labels, and loopback browser certification. The
browser evidence covers one-pixel pan anchoring, equivalent button and pinch
paths, gradual fixed-center admission, deep selected-label readability,
hierarchy landmarks, structural focus and Back, direct artist discovery, and
mobile pinch. The known remaining layout debt is extremely near-coincident
source coordinates; it is documented as a model/readability limitation rather
than hidden by detached labels.
The acceptance gate is mechanical, not a claim that every deep label is easy
to reach: 117 of the 2,945 label entries require a reveal scale above `1e6`,
40 require above `1e9`, and the worst requires above `1e12`. A new layout
needs a human-scale navigation check before replacing this one.

The deployed fingerprinted export has been checked against the manifest,
clean public IDs, the static discovery asset, and the same browser flows.
The artist-search export was deployed on 2026-09-21. The Pages deployment URL
and `opennoise.horv.co` both serve the same SHA-256 manifest as the certified
local `dist`: `eec1c5a761ff5bda0235f4b1bc011092c2421b051a191a384c9740eb4652c3db`.

Temporary rejected zoom/review worktrees and merged clean-ID worktrees were
pruned on 2026-09-16. Active offline-atlas, discovery, and data worktrees are
retained until their own evidence gates conclude.

## Next data work

- Expand direct artist and catalog coverage, preserving source claims and
  rejecting ambiguous presentation identity bridges.
- The local, non-publishing identity-bridge audit now separates 245 one-to-one
  exact label matches, 101 non-exact mappings needing review, and 95
  conflicting or ambiguous edges. Its append-only typed review ledger does not
  auto-promote exact matches or change the public bridge.
- Add independently evaluated, versioned promotion paths for derived
  memberships and similarity; keep direct observations separate until then.
- Complete the MusicBrainz release and track catalog chain. A larger local
  bounded run has 55 releases and 660 tracks, with offline-identical success
  and failure replay; it is not yet the published catalog or a full crawl.
- Keep metadata candidates separate from published metadata examples.
- Review the 484 source-bound genre candidates now queued by the versioned
  workflow, then design a separate publication gate. None is published.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate. The new
  evaluator abstains on its synthetic fixture; no retained source or accepted
  threshold policy qualifies yet. FMA metadata is an independent candidate,
  but exact artist and genre bridges are not present, so it cannot yet score
  the model. See the [gold-set workflow](evidence/INDEPENDENT_ARTIST_GENRE_GOLD.md)
  and [FMA source audit](checkpoints/INDEPENDENT_GOLD_SOURCE_AUDIT.md).
- Expand source cache replay until every selected release manifest input can be
  acquired or restored, ingested, and replayed into the certified database.
  The 54-object Wikidata candidate replay is not this certification.

## Later experiments

- Evaluate alternative graph and hierarchy aware layouts against fixed
  evidence, including a practical maximum zoom and stable readable labels,
  then expose accepted layouts through the versioned public map contract. The
  measured baseline and candidate gate are in
  [the layout navigation audit](checkpoints/LAYOUT_NAVIGATION_AUDIT.md). An
  [unpublished candidate](checkpoints/LAYOUT_NAVIGATION_CANDIDATE.md) sharply
  reduces near-overlap and extreme reveal scales. Its isolated browser QA
  passes the identity-based gate with explicit viewport and overlay exemptions,
  but eight labels still need more than `1e6` reveal scale. It has not replaced
  the deployed map.
- Keep historical output as a terminal, evaluation-only reference after each
  open-model checkpoint is sealed; it must never become a construction input.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
