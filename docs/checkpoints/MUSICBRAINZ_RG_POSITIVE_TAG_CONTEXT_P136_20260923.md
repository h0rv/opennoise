# MusicBrainz release group tag context and Wikidata P136 positives

This local checkpoint measures whether positive MusicBrainz release group tags
recover source isolated Wikidata P136 artist and genre positives. It does not
change a model, static output, serving data, source policy, or release.

## Inputs and limits

The run reads `.cache/musicbrainz-rg-genre-recovery-hash-sample-v2/report.json`.
It has 10,009 sampled release groups. Its file hash is
`7eb345375b4fea9d8f09c6be9c9286068ad87d04ea7576c4d3049eb69c6df987` and its
logical output hash is
`132f265926724d8a46756bd4056264f927d7602b40d498ca339cad7b51bc96fe`.

The positive source is `data/public.sqlite`. Its hash is
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`. The
run accepts direct `wikidata_p136` evidence with an exact MusicBrainz artist ID
and a Wikidata genre QID. A QID is retained only when the pinned reconciliation
maps it to one reconciled seed. The reconciliation hash is
`c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022`.

The code rejects a release group report above 64 MiB, a public database above
512 MiB, a reconciliation file above 16 MiB, and more than eight optional gold
files. Each optional gold file has a 32 MiB limit.

## Result

The source has 4,490 distinct direct P136 artist and genre pairs. The one to
one reconciliation rule retains 3,133 pairs. That is the global positive
denominator, and it is not a completeness claim.

The sampled tags include 10,529 credited artists. Their overlap with retained
P136 positives has 781 artist and seed pairs, 248 artists, and 170 seeds.
Exact normalized positive tags recover 133 of the 781 pairs, or 17.0294
percent. The recovered pairs cover 53 seeds.

The fixed ranking comparison freezes a 248-seed candidate universe from exact
normalized sample tag names and the pinned reconciliation before it opens the
P136 positives. It fixes `k = 5`, orders equal scores by seed ID, and never
tunes either choice from the P136 result. Artist-local tag context recovers
132 of the conditional 781 positive pairs at top five (16.9014 percent),
covering 52 seeds. This is a positive-recovery count, not precision.

The comparator is global tag popularity: positive tag vote counts summed once
per release group across all 10,009 sample groups. Its candidate universe and
ordering are fixed before the P136 target pairs are read, so it is P136-label-
blind. It shares MusicBrainz tag groups, and potentially artists, with the
artist-local arm. It is therefore neither artist-disjoint nor an independently
held-out baseline. Its one fixed top-five list recovers 107 of 781 conditional
pairs (13.7004 percent), covering five seeds. The 3,133 one-to-one P136 pairs
remain the global positive denominator; 781 is explicitly the conditional
denominator after requiring an artist in the fixed local tag sample.

The sample has 11,062 positive tag observations on 3,727 groups. It has 10,317
native proper genre observations on 3,641 groups. The evaluator records the
native genre counts only. It never uses native proper genres as targets because
the tags and genres come from the same MusicBrainz release group source.

Wikidata P136 provides direct positives from a separate source family. It is
not a complete gold set, and it does not establish statistical independence
from MusicBrainz tags. Missing P136 claims and missing tags are unknown, not
negative labels. The checkpoint reports positive recovery only. It does not
calculate precision or a full quality score.

The fixture gold file remains fixture only and is not a quality gate. A future
full evaluation needs a sealed independent artist and genre gold set, an
accepted judgment policy, and a reviewed exact bridge to MusicBrainz artist
MBIDs and pinned seed IDs.

## Reproduction

Run this command against the retained local inputs. The script writes a new
cache report and refuses to replace an existing output.

```sh
.venv/bin/python scripts/audit_musicbrainz_rg_positive_tag_context.py \
  --sample-report .cache/musicbrainz-rg-genre-recovery-hash-sample-v2/report.json \
  --wikidata-p136-database data/public.sqlite \
  --seed-reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --output .cache/musicbrainz-rg-positive-tag-context-readiness-v2/report.json
```

The generated report has logical output hash
`13d3e8260d3fd359731763e6636389f1a43cbd044049731ba5e8224fe6898853`.
