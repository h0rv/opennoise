# Conservative MusicBrainz peer candidate

This local candidate is a fixed, non-serving edge artifact built from open
MusicBrainz direct-tag evidence only. It did not read the Last.fm archive,
historical Every Noise data, a public database, or static discovery. It did not
write a map, public database, or static asset.

The materializer is bound to the baseline peer logical SHA-256
`15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd`, the
baseline settings SHA-256
`88a708cd5d0745c87a6c4f164fe8c0d306345ffaa59b87a87aa1b929255eef0f`, and the
direct-membership input SHA-256
`3c2c8b23e00c0201f1505be6851bc392258665cb11fc353949c1a332ebc9dd1c`.

It applies the already fixed rule: an overlap-one edge is retained only when
its sole shared artist appears in fewer than ten seeds. The resulting artifact
contains 1,497 edges, reaches 414 of the 495 scoped unplaced seeds, and retains
the exact direct evidence references for both endpoints plus the sole artist
and artist seed degree. Its byte SHA-256 is
`b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028`; its
logical output SHA-256 is
`05eae8b22a94fffddd30e25c29d4629257a611956d9b59a21440e862c80436d2`.

## Terminal historical evaluation

Only after materialization, the pinned Last.fm ArtistTags2007 archive
(`b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f`) was used
as a terminal, positive-only check. It joins the edge witness artist by exact
MusicBrainz ID and compares each endpoint to its literal reconciled seed name.
It does not tune, build, select, or remove any edge.

There are 20 exact positive witness-tag overlaps among 1,497 fixed candidate
edges. Forty-eight edges have only one observed witness tag and 1,429 have no
observed witness tag; both groups are abstentions, not negatives. The 1.3360%
ratio is therefore only a global candidate-coverage lower bound, not recall or
precision. The 29.4118% ratio among the 68 edges with any witness tag is a
co-observation diagnostic that assumes one-tag-only means not jointly observed;
it is not recall or precision. These are coverage observations, not specificity,
release, or musical-quality claims.

The hardened evaluation replay receipt byte SHA-256 is
`9b39fcdbd1ea1e339ad8ad58ec64b9c715e50ae3b9e7ced6fa4958311632a395` and its
logical output SHA-256 is
`1f37d44bc7a0d554fe24427310c594728cfda5e8230477f415972c1ecbeb18d5`.

Reproduce construction, then terminal evaluation:

```sh
.venv/bin/python scripts/materialize_conservative_musicbrainz_peer_candidate.py \
  --baseline-candidate .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity.json \
  --public-input .cache/musicbrainz-full-seed-targets/pipeline/public-model-input.json \
  --layout .cache/semantic-map-layout-v2/artifact.json \
  --sensitivity-report .cache/musicbrainz-peer-threshold-sensitivity-v1/report.json \
  --output .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json

.venv/bin/python scripts/evaluate_conservative_peer_lastfm_positive_only.py \
  --archive .cache/lastfm-artisttags2007/source.tar.gz \
  --candidate .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --output .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-lastfm-positive-only-v2.json
```
