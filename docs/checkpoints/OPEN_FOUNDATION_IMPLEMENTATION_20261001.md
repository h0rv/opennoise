# Open foundation implementation, 2026-10-01

The implementation adds reusable modeling and evaluation tools, portable CC0
examples, and a simpler static discovery export. It does not complete Every
Noise parity. Seven isolated agent workstreams covered semantic modeling, sonic
metadata, historical evaluation, credited music, interface design, foundation
packaging, and independent cultural evidence. Integration review corrected
source-scope wording, identity handling, artifact replay, and missing-input
validation.

## Model evidence

The [overlapping source-style lens](OVERLAPPING_SOURCE_STYLE_CONFIRMATION_20261001.md)
improves rare-tag Recall@10 from **23.737% to 25.911%** on a frozen confirmation
with targets disjoint from the exploratory test. Overall recovery changes from
48.818% to 48.769%. The optional full-source lens produces suggestions for
198,348 artists and retains 6,513 active association neighborhoods. Those
neighborhoods are not 6,513 validated genres. Primary-cold artists and unseen
values remain unrecovered. The existing product suggestions remain unchanged.

The [acoustic representation](ACOUSTIC_REPRESENTATION_20261001.md) aggregates
exact-credit recording descriptors with explicit missingness and sample counts.
The expanded capture supplies **55 descriptor-bearing recordings of 100
selected** across ten artists; the other 45 returned HTTP 404. It made 70 new
requests and retained 2,057,439 new bytes. Independent raw replay checks source
lineage, credit selection, identity, descriptors, inventory, and budgets. Sonic
distances and inferred cultural overlap are separate outputs. This selected
electronic-focused sample cannot establish general retrieval quality.

## Reference evaluation

The [North Star benchmark](../analysis/everynoise-reference-benchmark.md)
projects the pinned 6,291-genre historical reference, including 6,226 parsed
representative observations and 65 quarantined rows. Candidate name matches,
representatives, positive memberships, and display-coordinate neighbors are
separate criteria. Historical absences do not become negative labels.

The actual bulk atlas comparison matches 2,112 reference names, including weak
raw candidates, and only 16 of 62,910 reference display-neighbor edges. Neither
measure establishes semantic genre equivalence. Full archived artist membership
remains unavailable; live and public-mirror probes returned HTTP 403. Reference
coordinates and memberships do not enter open model construction.

## Product and portable examples

The final local export is
`.cache/opennoise-discovery-minimal-20261001-v5/`, with receipt
`f06f6d884d41847838de8e1241ff962a58c788c330878ed6338202e53d37c80e`.
It reduces decorative styling and repeated copy, puts advanced filters behind a
disclosure, and preserves search, maps, complete lists, evidence roles, deep
links, history, and mobile/keyboard access. Styles and communities lazily show
[credited music examples](REPRESENTATIVE_MUSIC_20261001.md), including recordings
and independently credited release context for Aphex Twin and Four Tet.
External MusicBrainz links provide metadata navigation, not playback.

The refresh verifies the parent, hardlinks 97,466 unchanged artifacts, replaces
six UI assets, and binds the CC0 examples and their receipt. Earlier generated
display clones were removed to recover filesystem metadata space; original
sealed parents and browser evidence remain intact. There is no deployment.

Both real-export Chromium captures passed: 18 style screenshots and eight
community screenshots. The style capture verifies twelve credited work links
for each of Aphex Twin and Four Tet, mobile filter bounds, complete cohorts,
history, reload, and all three explorer routes. No external fetches, media
requests, HTTP errors, or runtime errors occurred. Evidence:

- `.cache/minimal-style-browser-20261001-v5/browser-report.json`
- `.cache/minimal-community-browser-20261001-v5/browser-report.json`

The [foundation inventory](../foundation/README.md) exposes stage input hashes
and missing dependencies. `validate --stage portable-examples` can succeed
without the absent canonical database/layout or optional tag pack. Checked-in
CC0 projections let a fresh checkout replay recording metadata ranking and
numeric acoustic comparisons without private credentials or ignored caches.
The full source-tag models still carry optional noncommercial/share-alike
source obligations; open code does not override those terms.

## Remaining acceptance

Broader independent musical judgments, calibrated overlapping memberships,
diverse sonic coverage, stable acoustic/cultural neighborhoods, defining music
selection, listening and playlists, and a fully reproducible full-corpus release
remain unresolved. This checkpoint provides concrete building blocks and
measured progress, not an overall completion percentage. Follow the
[foundation acceptance contract](../foundation/GOAL.md).

Validation at integration: `poe check` passed 1,473 Python tests (36 explicit
input-dependent skips) and 39 JavaScript/browser tests. The separate real-export
captures and raw metadata replay supply evidence beyond the checkout fixtures.
