# Own genre metadata custody in source navigation

Artist/genre navigation previously selected `genres.name` after authorizing the
relationship evidence. On the complete retained CC0 catalog, suppressing all own
English-name provenance for one genre left zero displayable names and six eligible
claims, yet the backend still returned the cached English label. The cache did
not carry the name's independent source permission or suppression decision.

Genre objects now choose an independently authorized own source name, or an
unambiguous typed QID with its own authorized source custody. `name` remains a
string and additive `name_status` distinguishes `source_name` from
`source_identifier`. No fabricated NameClaim is inserted. Unsupported, suppressed
or ambiguous identity metadata fails closed; QID links return no mapping. Private
identity observations can veto ambiguous ownership but cannot supply labels.
The genre-member, artist-genre, related-artist/shared-genre and direct-peer paths
use the same check. Direct-peer ordering no longer reads raw cached names.

The existing export eligibility helper accepts an explicit display operation.
Export remains its default; v2 adapter/policy/receipt serialization is unchanged.
Display checks use display permission and all/display suppression, independently
of export permission. Names and identifiers must have their own CC0/public-domain,
non-local policy, active permission, matching source/snapshot/artifact custody and
eligible provenance. Missing artifact custody is a denial. No provider family is
guessed for display; the export operation still requires declared source families.
Per-request provenance checks and repeated shared genre labels are cached.

This closes a genre metadata disclosure gap. It does **not** expand the existing
`displayable_artist_genre_evidence` view's claim-level snapshot/artifact/reference
suppression coverage, change relationship eligibility, validate listener relevance,
classify genres or add hierarchy. Artist sourced-name handling is unchanged.
There are no public default, UI or deployment changes.

The validation uses the ordinary catalog from the
[complete retained CC0 source recipe](../cc0-cultural-catalog-20261019/README.md):
433 artists, 151 genres, 278 canonical direct facts, 287 raw P136 observations and
580 directed source co-genre links. All relationships remain unchanged. Baseline
labels comprise 150 own English names plus Q3071's explicit identifier label.
The checked-in source bytes are attributed to MusicBrainz and Wikidata contributors
under their structured-data CC0 licenses; no NC/research models, annotations,
new source acquisition or fitting participate. Cost is $0.

From the repository root, after `poe sync`, reproduce the full retained-data
regressions with:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest \
  tests.serving.public.test_navigation_genre_metadata \
  tests.serving.public.test_artist_navigation_store \
  tests.serving.public.test_artist_membership_adapter -q
```

These tests build fresh fully migrated catalogs from the same pinned raw CC0 packs
and native portable core source; no preexisting SQLite cache is required. They
exercise label-only suppression, poisoned raw cached labels, shared/direct-peer
labels, both QID-link directions, denied display versus allowed export (and the
reverse), missing artifact custody, private duplicate identities and ambiguous
name-chain error handling. The real retained source census and graph counts are
preserved. Existing unit navigation fixtures retain their relationship roles and
add explicit metadata custody for the new checks.

`results.json` binds actual code, aggregate outcomes and local independent evidence.
Local proof paths describe current executor custody, not promised future artifacts;
rebuild the source catalog from the linked recipe if absent, or report missing
approved source bytes. Twenty focused tests passed with one historical skip;
format/lint/types passed. Full checks are pending.


Independent guarded ordinary API replay checked every artist, genre, direct fact,
neighbor and exact QID link in three complete-catalog variants. Poisoning all 151
cached genre names left the entire output byte-identical to baseline. Suppressing
all 150 own English-name provenance observations produced 151 authorized QID
labels, including Q3071, without changing source relationships. Baseline, poisoned
and suppressed runs took 8.0, 8.1 and 10.7 seconds on this executor; these are single
bounded engineering measurements, not universal latency claims. Five active denial
probes verified the guard; backend operations made zero forbidden original-source,
network, research-model or fit accesses. The published-profile peer table is empty
in this source catalog; populated peer labeling is covered by the migrated fixture
integration test. Proof SHA256:
`c9ee060349b254c7f2befb9730f9b91d7b9c6b370e22a27e30264b786d076a31`.
Luna independently passed 13 navigation tests and reviewed the exact runtime hashes.
