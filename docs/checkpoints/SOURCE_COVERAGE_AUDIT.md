# Source coverage audit

This checkpoint inventories implemented adapters and sealed artifacts without
promoting any candidate into an artist membership. Rebuild the machine-readable
receipt with:

```bash
uv run poe audit-source-coverage
```

It rehashes the graph database and five small receipts, validates the
frontier, release-group, artist-metadata, and full-graph artifacts, and then
recomputes graph membership aggregates from SQLite. It also preserves all
eight byte/logical bindings declared by the verified v2 graph receipt:
frontier, MusicBrainz evidence database and artifact, reviewed alias context,
factual Wikidata hierarchy, and direct/support/filtered peer artifacts. Those
upstream payloads are receipt-declared here, not individually reread. The JSON
output is written to `.cache/source-coverage-audit-v1.json` by default.

[`SOURCE_COVERAGE_AUDIT.json`](SOURCE_COVERAGE_AUDIT.json) is the checked-in
receipt from the current replay. It contains hashes and counts only, not a
cache payload; rerunning the task against the same sealed inputs must replay
its `output_sha256`.

## Scope-safe coverage

| Scope | Seeds | Artists | Pairs or claims | Meaning |
| --- | ---: | ---: | ---: | --- |
| Release direct anchors | 2,377 | not an artifact field | 421,427 pairs | MusicBrainz direct-anchor pairs in the release-group receipt. |
| Direct graph claims | 2,377 | 207,328 | 815,723 claims | Current `artist_direct` claims only. |
| Complete graph union | 2,570 | 552,283 | 1,773,093 distinct pairs | `artist_direct`, `release_group_support`, and reviewed alias context combined. |
| Pair-split train matrix | 2,435 | 552,283 | 1,416,893 pairs | Active train-matrix columns only; 356,200 pairs are held out. |

The sealed frontier has 2,378 direct-observed seed labels: 2,377 MusicBrainz
labels plus one Wikidata-only label. This is a source-frontier count, distinct
from graph and matrix counts.

In particular, **2,435 and 552,283 are full-graph matrix/pair-split coverage,
not direct or factual artist coverage**. The audit model rejects a receipt that
tries to use the matrix count as a wider scope than the complete graph union,
loses the one Wikidata-only direct frontier label, or fails to partition
1,773,093 graph-union pairs into 1,416,893 train plus 356,200 held-out pairs.

## Adapter and signal inventory

| Adapter/artifact | Signals contributed | Verification scope and current boundary |
| --- | --- | --- |
| Wikidata resolver, public source rows, taxonomy expansion, sealed frontier | identity, direct artist membership, releases, hierarchy, external links | Receipt-declared by the graph; QID/P136/P279 provenance is retained; only accepted hierarchy edges are factual. |
| MusicBrainz artist/tag extraction | artist membership, tags | Repository-documented only in this audit; exact anchors differ from contextual rows. |
| MusicBrainz release-group evidence | releases, tags, artist membership support | Receipt-declared; release-group labels are credited-artist support, never direct artist facts. |
| MusicBrainz release-credit metadata | identity, releases, external links | Rehashed by this audit; exact MBID/name metadata only, not a membership signal. |
| Reviewed alias context | tags, artist membership context | Receipt-declared; separate evidence kind, not direct source-row coverage. |
| ListenBrainz qualified aggregate / co-listen overlay | co-listen | Repository-documented only; no artist-level similarity is in the full graph. |
| Last.fm reverse tags | tags, candidate membership | Repository-documented adapter; no sealed cache or receipt. |
| MSD/Last.fm offline reader | tags, candidate membership, co-listen | Repository-documented adapter; required SQLite inputs and receipt are absent. |
| MusicBrainz-to-Spotify bridge | external links | Repository-documented evaluation-only artifact, prohibited from construction. |

## Ranked enrichment gap

The first bounded experiment should calibrate the MusicBrainz contextual
artist-tag matrix, not broaden Wikidata first. The 212,696-row / 88,328-artist
inventory is repository documentation, **not an input independently verified
by this audit**. It is therefore an unverified but low-acquisition hypothesis,
with review-only contextual precision. Its new-seed and new-artist lift is not
measured; its maximum seed ceiling is the 3,914 labels outside the 2,377
direct-anchor set. A receipt-bound held-out exact-label calibration must bind
the source artifact and report lift before any queue or promotion.

Broader Wikidata P136 is fourth: the current reconciliation found only one
Wikidata-only direct seed, which is evidence of low observed marginal seed
yield, not high yield. MSD/Last.fm and live Last.fm remain unmeasured until
custody inputs or a response cache exist. Discogs has no adapter, receipt,
measurement, or policy decision and is deferred.

The generated JSON carries the same ranking with acquisition cost,
reproducibility, and label-precision fields so proposals cannot be confused
with currently sealed evidence.
