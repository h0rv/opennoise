# ListenBrainz directional aggregate holdout

This bounded, local-only sensitivity experiment reverses the ordering of the
same seven retained, privacy-filtered daily ListenBrainz aggregate windows
before applying the already fixed four-window train / three-window held-out
split. It changes no source row, privacy threshold, model, static asset, or
deployment.

## Receipt and boundary

The input qualified aggregate is pinned to SHA-256
`282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`; the
fixed public artist/genre snapshot is pinned to SHA-256
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`. The
new local report is
`.cache/listenbrainz-directional-holdout-20260923/reverse-report.json`, with
file SHA-256 `93d6e85988fe19de1dbccca9362e901646387259d283ac4961083019dc888cb7`.

Only the existing qualified aggregate is read. It already retains
co-listen support after its minimum distinct-user rule; this experiment never
opens a daily dump or emits listener IDs, artist IDs, pairs, rankings, or a
neighbor lookup. The reverse arm is a split-sensitivity check, not a
backwards-in-time prediction claim. It is local-only, export disabled, and
serving disabled. Listener co-occurrence does not establish genre,
membership, or musical similarity. No playlist input is used, so it makes no
claim about account independence, repetition across accounts, or human/manual
curation.

## Fixed held-out comparison

The reversed arm has 8,792 train pairs, 7,311 held-out pairs, 2,621 novel
held-out pairs, and 848 novel-heldout query artists. On the common scored
cohort (623 queries and 4,858 directed reference pairs), train-only
common-neighbor cosine reaches Recall@10 `0.152532` and Recall@25 `0.299506`.
The train-degree popularity null reaches `0.142857` and `0.265336`; fixed
direct-genre IDF reaches `0.062166` and `0.117538`.

This preserves the earlier directional decision: on the equal-capacity common
cohort, the train-only aggregate-neighbor ranker exceeds both comparators at
10 and 25 in the reversed split. Its Recall@10 advantage over popularity is
`0.009675` (0.9675 percentage points), so the observed effect is modest. It
does **not** authorize a production change, prove generalization, or measure
precision. The earlier chronological arm and this reverse arm have different
cohorts and are therefore not a significance test or a claim of exact
performance stability.

## Reproduction

```sh
.venv/bin/python scripts/evaluate_listenbrainz_offline_experiment.py \
  --listenbrainz-db .cache/listenbrainz-qualified-input/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite \
  --expected-listenbrainz-sha256 282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866 \
  --public-db data/public.sqlite \
  --expected-public-sha256 240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc \
  --reverse-window-order \
  --output .cache/listenbrainz-directional-holdout-20260923/reverse-report.json
```

The script verifies both required input hashes, refuses existing or symlinked
outputs, and permits output only under `.cache`.
