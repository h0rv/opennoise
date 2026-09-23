# Last.fm direct custody retrieval holdout

The v2 report at `.cache/lastfm-direct-custody-holdout-v2/report-v2-controls.json`
is local only. It uses the same fixed MusicBrainz direct custody membership fold
as the ListenBrainz comparison, with the privacy filtered Last.fm 360K exact
artist pair aggregate. It reads no Last.fm tags, historical data, playlists, or
public artifact, and it writes no membership, serving, or export output.

The report pins the Last.fm artifact `6d311156…`, companion receipt
`c81d9bd8…`, aggregate DB `a63ae002…`, and direct custody graph receipt and
database. Its logical output SHA-256 is
`ea15b7ebc135684c300139be2504e157c77c5cb12940844179aeac814e2ada8d`.
The file SHA-256 is
`79fa9acf791f14f475f33c440904338f75cc0d37c662c1b75977ec293d91a011`.

Every arm ranks at 20 and removes the seed's train artists before ranking.
The direct controls use only the fixed fold's training memberships. Direct
popularity ranks by global training artist degree. Direct IDF votes through at
most ten direct custody peers, selected by the established train only IDF
weighted Jaccard rule, then ranks all artists found in those peers' training
memberships. This declared ten peer cap applies before candidate artist voting.

The Last.fm graph popularity control uses no direct custody membership as a
score. It assigns each Last.fm endpoint the sum of `log(1 + distinct_user_count)`
over its retained aggregate pairs, ranks all Last.fm endpoints by that score,
and removes the seed's train artists only at ranking time. It is a popularity
control for the Last.fm graph, not a similarity, membership, or genre claim.

On the 6,818 Last.fm endpoint targets, Last.fm pair transfer recalls 610 at 20
(8.9469%). Direct popularity recalls 7 (0.1027%), direct IDF recalls 226
(3.3148%), and Last.fm graph weighted degree recalls 40 (0.5867%). On the same
873 targets that are endpoints in both Last.fm and ListenBrainz, Last.fm pair
transfer recalls 257 (29.4387%). Direct popularity recalls 0, direct IDF
recalls 42 (4.8110%), and Last.fm graph weighted degree recalls 39 (4.4674%).
The direct controls show that the Last.fm result is not explained by these
fixed fold alternatives, but this remains a local retrieval measurement only.

The common cohort scores the two source graphs separately. Their top 20 hits
partition the 873 targets into 94 recovered by both, 163 by Last.fm only, 40
by ListenBrainz only, and 576 by neither. These counts do not combine scores,
edges, or source populations. The shared denominator is availability
conditioning, not a source population comparison, precision result, or merged
signal.

Run the local report with:

```bash
.venv/bin/python scripts/evaluate_lastfm_direct_custody_holdout.py \
  --direct-database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --direct-receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json \
  --lastfm-artifact .cache/lastfm-360k-full-aggregate-v1/artifact.json \
  --lastfm-companion-receipt .cache/lastfm-360k-full-aggregate-v1/receipt.json \
  --lastfm-database .cache/lastfm-360k-full-aggregate-v1/aggregate.sqlite \
  --listenbrainz-database .cache/listenbrainz-dual-overlay-v1/colisten.sqlite \
  --listenbrainz-receipt .cache/listenbrainz-dual-overlay-v1/colisten.receipt.json \
  --output .cache/lastfm-direct-custody-holdout-v2/report-v2-controls.json
```
