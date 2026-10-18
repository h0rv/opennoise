# Fixed artist rank evidence from historical FMA44 predictions

The optional ranked artist view addresses a limitation of the saved-membership
export: eleven calibrated labels yield broad, often tied frequency counts. It
uses full existing saved track ranks to expose at most ten artist-level source
annotation candidates. It leaves calibrated memberships, source predictions,
identity joins, all abstentions and original partitions unchanged.

For each artist/genre, the fixed score is the sum of reciprocal saved track ranks
divided by **all nominated tracks** for that artist. Abstained tracks contribute
zero through the denominator. Ties break by native genre ID. The scores are not
probabilities, the candidates have no membership calibration, and no labels are
added to calibrated `genre_evidence`. An entirely abstained artist stays empty.
Only saved model rankings enter the scorer; target tags enter the separate audit.

## Use the existing export command

Follow the membership materialization and externally pinned export command in
[the membership recipe](../fma-source-memberships-v1/README.md), adding
`--rank-artists` and choosing a fresh output path. The flag requires
`--export-artists`; omitting it retains the prior export view.

Each artist gains `ranking_supported_track_count` and
`ranked_source_annotation_candidates`, including genre ID, mean reciprocal track
rank and contributing track count. The opt-in artifact has its own revision and
records the ranking implementation and fixed protocol hashes. The same 24 MB,
110,000-native-row and 120-second/1-GB CLI bounds apply.

The checked export has SHA256
`e47508c2ef02315714a003aaf727abbffada3f7dcc96152679fcd3e35c1bdf1b`
and is 4,836,095 bytes. All 1,714 artist identities and their calibrated evidence
match the unranked view. The 95 artists whose saved tracks all abstain keep empty
rankings; query coverage is unchanged. Ranked candidates span 144, 142 and 145
distinct source genre IDs in the three respective partitions; these are
uncalibrated candidates, while calibrated memberships retain eleven labels.

## Reproducible historical diagnostic

`protocol.json` was frozen before the diagnostic computation, with SHA256
`971efc50e483c189b0fbabe68ae29840704675c8f48a980cccb99f60d2b294c8`.
It specifies one reciprocal-rank rule, one baseline, top ten, native-ID ties,
source-positive target union and all three original partitions. No parameter
search or retuning was performed. The baseline ranks genres by existing saved
calibrated-membership track count, with the same ID tie-break and top ten.

The audit uses the union of observed source track genre IDs per artist as
incomplete weak positives. Macro recall averages over artists with any observed
positive; positive-weighted recall counts those positive genre associations.
Artist coverage includes every nominated artist, including unlabeled artists and
abstentions. No precision or verified-negative claim is made.

| Historical partition | Artist-averaged recall@10: counts → ranks | Positive-weighted recall@10: counts → ranks | Artist coverage, both |
| --- | ---: | ---: | ---: |
| Calibration | 36.68% → 42.86% | 37.33% → 39.33% | 94.70% |
| Confirmation | 38.95% → 41.10% | 39.53% → 38.61% | 94.63% |
| Previously observed diagnostic test | 34.44% → 42.74% | 35.08% → 39.55% | 94.23% |

The confirmation positive-weighted result regresses (387 → 378 recovered source
associations). This is a mixed tradeoff, so the ranked view is opt-in and does
not replace the calibrated output. Historical FMA44 source-annotation recovery
is neither listener-quality evidence nor a result for the FMA518 five-fold model.
The diagnostic test and earlier aggregates were previously observed; no fresh
heldout claim, generalization guarantee, model selection or promotion follows.

Recompute all values from the generated ranked export and the checked-in targets:

```sh
.venv/bin/python data/recipes/fma44-artist-ranking-20261018/audit.py.source \
  --export /path/to/ranked-export.json \
  --export-sha256 e47508c2ef02315714a003aaf727abbffada3f7dcc96152679fcd3e35c1bdf1b \
  --saved-pack data/examples/fma-acoustic-baseline
```

`results.json` retains all counts and denominators. The independent audit reads
the consumer export rather than invoking the ranker again, validates its external
hash and protocol, replays the target pack and checks the complete artist track
sets before counting positives. No raw feature download, waveform, refit, new
calibration, Library transfer, UI or service cost is involved.
