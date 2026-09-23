# Last.fm and ListenBrainz rank fusion holdout

This local-only ablation uses the fixed 873 held-out direct custody positives
that are endpoints in both the retained Last.fm 360K aggregate and the
ListenBrainz aggregate. It writes no membership, genre, serving, export, or
model input. It does not merge source graph edges or source scores.

The report is at
`.cache/lastfm-listenbrainz-rank-fusion-holdout-v1/report.json`. Its logical
output SHA-256 is
`5e3fe3b4c9d06b6561a0fa8d4620dc581b9fc4ff464f6c44c0898e7ff7e744f8`.
The file SHA-256 is
`dbf2ac01c146017c205115240cf418d9670b98cf3c2fb51773b3aeb251b8a5b4`.
It pins the same direct custody, Last.fm artifact and aggregate database, and
ListenBrainz receipt and aggregate database hashes as the v2 Last.fm holdout.

First, each source independently scores candidates from only the seed's fixed
fold training artists. Known training artists are removed. Second, each source
keeps its top 20 candidates. Third, the fixed rule gives every retained
candidate `1 / rank` from each source list where it appears, sums those rank
scores, breaks ties by artist ID, and keeps the final top 20. The rule was set
before this fusion run. This is an exploratory follow-up on a cohort whose
separate-source results were already examined in the v2 holdout, not an
untouched confirmatory holdout. No source list has more than 20 candidates, so
the combined candidate set has at most 40 artists.

Last.fm alone recovers 257 of 873 targets at 20, or 29.4387%. ListenBrainz
alone recovers 134, or 15.3494%. The fixed reciprocal-rank fusion recovers 238,
or 27.2623%. It does not beat the best single source, Last.fm, so this rule is
rejected for this local ablation.

The union of the two separate 20-candidate lists contains 297 targets, or
34.0206%. This is a 40-candidate coverage upper bound, not a 20-candidate
ranker and not a merged graph. It shows that the two lists contain additional
separate positives, but the fixed reciprocal-rank rule did not preserve enough
of them in its final top 20. This does not authorize rule tuning, source graph
combination, model use, or publication.

Run the local report with:

```bash
.venv/bin/python scripts/evaluate_lastfm_listenbrainz_rank_fusion_holdout.py \
  --direct-database .cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite \
  --direct-receipt .cache/musicbrainz-direct-custody-peer-graph-v1/receipt.json \
  --lastfm-artifact .cache/lastfm-360k-full-aggregate-v1/artifact.json \
  --lastfm-companion-receipt .cache/lastfm-360k-full-aggregate-v1/receipt.json \
  --lastfm-database .cache/lastfm-360k-full-aggregate-v1/aggregate.sqlite \
  --listenbrainz-database .cache/listenbrainz-dual-overlay-v1/colisten.sqlite \
  --listenbrainz-receipt .cache/listenbrainz-dual-overlay-v1/colisten.receipt.json \
  --output .cache/lastfm-listenbrainz-rank-fusion-holdout-v1/report.json
```
