# MusicBrainz unplaced co-listen review edges

This local-only experiment uses retained MusicBrainz source tag rows and the sealed Last.fm 360K aggregate to make review proposals. It makes no artist membership, genre relation, coordinate, or placement claim. It does not read historical Every Noise relationships or coordinates. It uses layout IDs only.

The report is [`.cache/musicbrainz-unplaced-colisten-review-edges-v1/report.json`](../../.cache/musicbrainz-unplaced-colisten-review-edges-v1/report.json). Its logical hash is `284e1e43d224a24934b92ba3a4f44f39d463dc1041a4093e082f4d3ff6f9cc24`.

## Inputs and controls

The experiment pins the v3 layout byte hash `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`, the retained MusicBrainz source tag artifact byte hash `481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe`, and the fixed 414-seed review candidate byte hash `b605e855681bab1c8b17a7e67dd66f128b00dd4acc6ba1bcde05a9629361c028`. It verifies the Last.fm artifact, companion receipt, and aggregate database before reading pair rows.

The earlier [MusicBrainz pre-filter audit](MUSICBRAINZ_PREFILTER_UNPLACED_AUDIT_20260921.md) records 577 retained tag-positive unplaced names from this source. This experiment remeasures that 577 count from the same separately pinned source artifact. Only literal `match_kind=exact` tag rows with identical source tag and seed names enter a proposed route. This leaves 546 of the 577 retained source-positive unplaced names and 952 exact MusicBrainz artist IDs. The 577 figure is not a hardcoded input.

The hub control excludes any source artist with ten or more retained seed labels. This keeps 901 source artists. A route must have two distinct exact artist-pair supports in the sealed Last.fm aggregate. Each pair already meets the receipt's >=5 distinct-user privacy floor. The rule does not claim independent users beyond that aggregate floor, and it is not curator evidence.

The score is the sum of `log2(1 + pair_user_count)` divided by the product of the two artists' retained source-label degrees. Results are sorted by score and IDs. The report keeps at most three proposals per unplaced seed and ten per placed seed.

## Measured result

Of all 3,346 unplaced names, 45 have any retained sealed-pair join after the hub filter. Forty-three have two distinct exact artist-pair supports, producing 1,269 qualifying review routes before caps. The caps retain 109 proposed review edges for 43 unplaced names and 52 placed names.

The fixed 414-seed MusicBrainz review candidate is a comparison frontier only. Forty-two of the 43 co-listen proposal names overlap that frontier, and one is outside it. This is coverage comparison, not acceptance or placement of either kind of review edge.

## Limits

The MusicBrainz artifact was already matched to the seed vocabulary, so this experiment is a retained lower bound and cannot measure missing source support. The Last.fm aggregate is local-only and is not allowed as model input. Its all-time, privacy-filtered co-listen counts are association evidence, not a music similarity validation. The fixed 414-seed candidate supplies no ground truth and is not used to score or select co-listen proposals.

Run the measurement with:

```sh
.venv/bin/python scripts/audit_musicbrainz_unplaced_colisten_review_edges.py \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --source-tag-artifact .cache/musicbrainz-full-seed-targets/musicbrainz-seed-targets-v1.json \
  --lastfm-artifact .cache/lastfm-360k-full-aggregate-v1/artifact.json \
  --lastfm-companion-receipt .cache/lastfm-360k-full-aggregate-v1/receipt.json \
  --lastfm-database .cache/lastfm-360k-full-aggregate-v1/aggregate.sqlite \
  --review-candidate .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate-v2.json \
  --output .cache/musicbrainz-unplaced-colisten-review-edges-v1/report.json
```
