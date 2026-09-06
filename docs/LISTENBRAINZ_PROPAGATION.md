# ListenBrainz direct-anchor propagation

`build_listenbrainz_propagation.py` builds a sealed, local, review-only
artifact. It propagates accepted direct MusicBrainz or Wikidata artist--genre
anchors over the existing privacy-thresholded ListenBrainz co-listen graph.
It does not state a new factual artist membership and it never reads H3,
historical artist observations, audio, recordings, previews, or Spotify data.

The builder streams the full local MusicBrainz seed-target artifact and keeps
only its artist MBIDs present in the bounded ListenBrainz graph. It unions
those `musicbrainz_genre` and `musicbrainz_tag` anchors with accepted
`wikidata_p136` anchors after an exact, unique name-universe bridge. The union
is source-facet preserving and monotonic: a duplicate source-evidence row
fails rather than silently changing weights. Its only graph edges are
aggregated ListenBrainz artist MBID pairs. The catalog and ListenBrainz
database hashes, MusicBrainz source-artifact logical and byte hashes,
public-input hash, and 6,291-name vocabulary source hash are recorded in the
artifact and object-store receipt.

Run it against the one content-addressed local qualified snapshot. Both roles
must name the same SQLite path and the same expected SHA-256; the CLI hashes it
before loading either repository and fails closed on a path or byte mismatch.
The sealed v2 input is
`.cache/listenbrainz-qualified-input/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite`.

```sh
uv run python scripts/build_listenbrainz_propagation.py \
  --seed-artifact data/model/open-construction-graph-v1.json \
  --musicbrainz-seed-target-artifact .cache/musicbrainz-full-seed-targets/musicbrainz-seed-targets-v1.json \
  --catalog-db .cache/listenbrainz-qualified-input/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite \
  --catalog-db-sha256 282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866 \
  --listenbrainz-db .cache/listenbrainz-qualified-input/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite \
  --listenbrainz-db-sha256 282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866 \
  --output .cache/listenbrainz-propagation/artifact.json \
  --object-store .cache/listenbrainz-propagation/objects \
  --receipt .cache/listenbrainz-propagation/receipt.json
```

The default bounds require at least 15 listener-days in two windows, remove
artists with more than 250 eligible co-listen neighbours, retain at most 2,500
candidates per genre and eight paths per candidate, and fail before exceeding
two million propagation visits. Edges use `log1p(listener_day_support)` divided
by the square root of the incident artists' retained weighted strengths.
This degree/popularity normalization and the hub cap prevent popular artists
from creating a general-purpose genre shortcut.
For artists with more than 32 direct anchors, propagation deterministically
retains the highest-weight anchors (then stable genre/evidence order); the
coverage ledger records every omitted propagation seed while preserving the
complete direct union for factual-exclusion and held-out evaluation.

The artifact includes the full candidate set plus a deterministic 1/5
direct-anchor holdout. Held-out source claims are removed from the seed set;
positive-only recall is then measured when propagation independently retrieves
the `(artist, genre)` pair. It does not treat missing pairs as negative labels,
does not use any external gold set, and does not use historical membership for
construction or evaluation. Coverage reports both direct and new candidate
genres against the fixed 6,291-name vocabulary. Names map only through unique
normalized matches; ambiguous names are counted and not promoted.

## Published local v2 run

The current full-union local run is at
`.cache/listenbrainz-propagation-v2/artifact.json`; its receipt and byte-identical
object-store copy are beside it. The logical artifact SHA-256 is
`54b14133256c5cecee0bd21ba9732e7d9ed5ab8eddb2397bbd6c1ea97b42dcd8`; the
published file SHA-256 is
`37fffe650a2111ddab8a663c643dd53378ccc0be474823d16084ea09e37bb20e`.
Both input roles were the same hash-locked 153,231,360-byte SQLite snapshot,
SHA-256 `282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`.
It records the verified full MusicBrainz source logical hash
`1cfe14b7dfce41c5f1b45c423407c7c1ad528abbafa3b3b859770e49c8debe46` and
source byte hash `481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe`.

The v2 union has 8,717 direct anchors across 1,419 artists and 593 seed
genres: 5,672 MusicBrainz-only, 1,052 Wikidata-only, and 1,993 overlapping
source-facet anchors. Of 13,175 input artist pairs, 4,273 passed support
thresholds and were retained; no artist met the degree hub cap, no seed anchor
was capped, and the run used 77,204 propagation visits. It yields 23,497
review candidates for 640 artists across 425 incremental names in the fixed
6,291-name universe. The deterministic one-fifth positive-only holdout held
out 1,763 direct anchors and recovered 597 (recall `0.338627339762`).

This supersedes the earlier qualified-catalog baseline, which had only 4,434
direct anchors across 468 seed genres and should not be used as the final
seed set. V2 still produces derived review evidence only: it is not factual
membership, and it did not read or construct H3/historical membership data.
