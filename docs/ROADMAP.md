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
1,541,940,352 bytes, and can restore a supplied verified object store. It does
not yet ingest those objects into a new certified SQLite database.

## Static Pages delivery status

The last documented deployed static release is main commit `c8a908d`. Its certified
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

The deployed fingerprinted export has been checked against the manifest,
clean public IDs, the static discovery asset, and the same browser flows.
The newer local artist-search export has passed the loopback browser gate, but
its Cloudflare deployment has not been verified.

Temporary rejected zoom/review worktrees and merged clean-ID worktrees were
pruned on 2026-09-16. Active offline-atlas, discovery, and data worktrees are
retained until their own evidence gates conclude.

## Next data work

- Expand direct artist and catalog coverage, preserving source claims and
  rejecting ambiguous presentation identity bridges.
- The local, non-publishing identity-bridge audit now separates 277 exact
  label matches from 164 non-exact mappings needing review. It estimates
  potential direct-observation coverage but does not change the public bridge.
- Add independently evaluated, versioned promotion paths for derived
  memberships and similarity; keep direct observations separate until then.
- Complete the MusicBrainz release and track catalog chain. A larger local
  bounded run has 55 releases and 660 tracks, with offline-identical success
  and failure replay; it is not yet the published catalog or a full crawl.
- Keep metadata candidates separate from published metadata examples.
- Review the 484 source-bound genre candidates now queued by the versioned
  workflow, then design a separate publication gate. None is published.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate.
- Expand source cache replay until every selected release manifest input can be
  acquired or restored, ingested, and replayed into the certified database.

## Later experiments

- Evaluate alternative graph and hierarchy aware layouts against fixed
  evidence, then expose accepted layouts through the versioned public map
  contract.
- Keep historical output as a terminal, evaluation-only reference after each
  open-model checkpoint is sealed; it must never become a construction input.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
