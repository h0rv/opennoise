# Roadmap implementation checkpoint

This checkpoint records the local state on 2026-09-21. It separates work that
has passed a local test from work that still needs data or a release check.

## Verified locally

The static export contains 6,291 names, 2,945 placed genres, 260 genres with
direct artist observations, and 1,008 artists. The local Pages certification
rebuilt `dist` and passed the browser checks. Every boolean acceptance field in
`artifacts/semantic-map/browser.json` is true. The report and screenshots are
generated files and are not part of the Git commit.

Artist search and the genre-specific artist view are in commit `63c7e03`.
The view orders artists by shared direct genre observations. It does not claim
to measure learned artist similarity.

The local export was deployed to Cloudflare Pages as commit `ee9e1e1` after
the local browser gate passed. The deployment URL and `opennoise.horv.co`
served a manifest with SHA-256
`eec1c5a761ff5bda0235f4b1bc011092c2421b051a191a384c9740eb4652c3db`,
the same as the certified local `dist`. This verifies asset identity, not
every interaction on the public domain.

## Still open

The release manifest names 62 raw source inputs. The source vault replay gate
verified every object's byte count and SHA-256 in the retained Phase 3 vault.
The 62 objects total 1,541,940,352 bytes. The gate also supports a checked
restore from a supplied local object store. A raw-source-to-certified-database
replay remains unproven.

The public artist membership promotion gate has no independent public gold
set. The existing MusicBrainz tag comparison is a diagnostic and cannot serve
as a production quality gate. A bounded catalog expansion has now materialized
55 releases and 660 tracks in a local copied database. Its successful and
failed endpoint results both replay offline with zero requests. The MusicBrainz
catalog is much larger, so that run does not close the full-catalog item.

A source-bound, versioned review queue holds 484 generated genre candidates
from 189 immutable source claims. All 484 remain pending. The workflow cannot
publish a generated genre or alter source data; a separate publication gate
and actual independent reviews are still needed.

A read-only direct bridge audit found 441 claimed catalog identity edges,
including 277 exact label matches and 164 non-exact review-only mappings. It
estimates 1,520 potentially reachable direct observations summed across
unbridged edges, with possible repeated counts. It has not promoted any bridge
or changed the static map.
