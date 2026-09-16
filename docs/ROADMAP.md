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
are not yet reproducible from this workflow.

## Static Pages delivery status

The currently deployed static release is main commit `aabda66`. Its certified
atlas has 2,945 placed nodes and 34,937 structural edges. The Pages manifest,
HTML, JavaScript, JSON, asset names, and rendered focus links contain no
retired identifier text. A clean `open_focus=item…` bookmark works, while an
old prefixed bookmark is accepted only as input and immediately canonicalized
to its clean URL.

The offline static-label-atlas experiment is not released. Its initial lint,
type, and focused unit checks passed, but the canonical export did not finish
within an independent 120-second bounded run and it predates the strict
public-ID boundary. It must be rebased and made bounded before it can enter a
release candidate.

Before any such deployment, require all of the following evidence:

- a completed canonical export and static/browser certification from the
  rebased candidate;
- all-scale label-box clearance over the emitted atlas, including cross-tier
  labels, with finite numerical zoom bounds;
- runtime measurements showing one-pixel pan preserves retained label
  screen offsets, world-anchor label identity remains invariant, and equivalent
  zoom paths yield the same admitted labels and placements;
- desktop and mobile/pinch captures that show the deepest revealed labels
  remain readable, attached to their dots, and clear of search/detail/control
  overlays; and
- a fresh custom-domain manifest/hash scan before release.

Temporary rejected zoom/review worktrees and merged clean-ID worktrees were
pruned on 2026-09-16. Active offline-atlas, discovery, and data worktrees are
retained until their own evidence gates conclude.

## Next data work

- Expand direct artist and catalog coverage, preserving source claims and
  rejecting ambiguous presentation identity bridges.
- Add independently evaluated, versioned promotion paths for derived
  memberships and similarity; keep direct observations separate until then.
- Complete the MusicBrainz release and track catalog chain beyond the current
  bounded 51 release and 491 track metadata slice.
- Keep metadata candidates separate from published metadata examples.
- Add a reviewed, versioned genre candidate workflow before publishing any new
  generated genre.
- Replace calibration only artist membership evidence with an independent
  public gold set before using it as a production quality gate.
- Expand source cache replay until every selected release manifest input can be
  acquired or restored, ingested, and replayed into the certified database.

## Later experiments

- Evaluate alternative graph and hierarchy aware layouts against fixed
  evidence, then expose accepted layouts through the versioned public map
  contract.
- Evaluate historical output only after the open model is sealed and the local
  rights and rebuild gates pass.
- Add optional user reviewed ML experiments in isolated modules. No audio files
  or audio derived data enter the default pipeline.
