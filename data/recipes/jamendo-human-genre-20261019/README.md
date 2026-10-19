# Prospective human nine-class genre-vote diagnostic

This noncommercial research experiment predicts separately collected human
`genre_dortmund` votes from uploader genre/instrument tags. It uses a new target
and new label-blind folds on the same historical metadata identities used by the
completed happiness/calibration studies. It is not a new untouched cohort,
audio model, artist-genre membership model or serving integration.

The original protocol was committed before capture as `6d5a193`, SHA256
`994399146138008c4329946315d9ac8f7b78021c03dbf2bd87fa515fcf83796b`.
Two official GitHub metadata requests then succeeded, totaling 9,080,731 bytes;
exact published lengths, SHA256 and Git blob hashes matched. No retry, redirect,
audio, descriptors, credentials or paid service was used. The fresh capture
receipt is checked here, SHA256
`3125263a9c7a3fbdc80c53ad10f60648801681b0737bbc7002720dc2b3d82b75`.
Raw bytes remain local, not in this recipe.

Before fitting, independent identity-only preparation froze all 11,565 metadata
identities, 713 artist/album components and new fivefold assignments. Both
implementations produced cohort SHA256
`788895cd621fa69e086a9cc0dada206157130d54226c684610d65aca0484befb`.
Target-only inspection then found a source serialization mismatch: three raw
class tokens contain underscores, while documentation displays friendly names.
A separate, independently reviewed amendment was committed as `420365b`, SHA256
`09ef671b841afb7d7b29e6ac6daa526b09beb369ce16a3b5ea38c56ac01612c4`.
Original protocol bytes and the initial strict-spelling census remain preserved.
Only `folk_country→folkcountry`, `funk_soul_rnb→funksoulrnb` and
`rap_hiphop→raphiphop` are amended; six other native spellings are unchanged.
No generic normalization or unmatched conversion is allowed. Empty target cells
are missing and not taxonomy nominations. Local outcomes retain raw payloads,
raw votes, canonical votes and recognition failures separately. No model output
or fitting existed when this technical correction was accepted.

The corrected no-fit census found 1,757 nonempty taxonomy nominations, rather
than the documentation's stated 1,500. Exactly 1,024 tracks across 368
components have three recognized votes; 403 of those tracks have disagreement,
which remains fractional. All 11,565 metadata nominations remain visible: 9,808 targets
are missing, 195 have the wrong vote count and 538 contain unrecognized votes.
These are unscored, not negative labels. Eligible coverage is 58.28% of taxonomy
nominations and 8.85% of all metadata nominations. Eligible fold sizes are
215/173/214/183/239, across 76/59/75/75/83 components. All five training-only
class gates pass; the minimum positive-class training support is 15 components.

The model uses all nine fixed classes, training-only vocabulary and fractional
Bernoulli presence/absence likelihoods with alpha-one smoothing. Each eligible
training component has unit total weight. Controls are the same training human
prior and a fixed literal uploader-genre mapping, uniform over distinct mapped
classes present or the training prior when none map. Uploader genres are
predictors, not human truth. Mood tags, human taxonomies, IDs, names, titles,
paths and duration are excluded from predictive features. All 11,565 metadata
queries receive probabilities from their own fold-excluded model; missing or
invalid heldout targets never determine probabilities. Scoring uses only the
1,024 eligible targets, with all methods sharing availability.

| Fixed method | Component-equal vote Brier | Track-weighted vote Brier | Component-equal log loss |
| --- | ---: | ---: | ---: |
| Training human prior | 0.752562 | 0.746442 | 1.724660 |
| Genre/instrument Bernoulli NB | 0.562462 | 0.563348 | 2.007334 |
| Fixed uploader-genre mapping | 0.593739 | 0.608343 | 6.826562 |

Lower proper scores are better. The primary NB-minus-prior Brier difference is
−0.190100, with fixed-prediction paired component-bootstrap interval
[−0.227913, −0.149465]. Against the direct mapping, NB differs by −0.031277,
with interval [−0.074863, 0.016805], which includes zero. **NB log loss is worse
than the human prior.** The direct mapping has exact zero probabilities;
log-loss-only clipping at 1e-15 affects 435 positive-target class cells across
350 tracks. Brier uses the original probabilities without smoothing or clipping.
No calibration or tuning follows these mixed results. Per-class one-vs-rest
vote-Brier channels are descriptive, null if positive support is zero, and never
reweight the nine-class primary score. All results and all paired comparisons
are in `results.json`; intervals condition on fixed predictions and do not
establish population significance or retraining uncertainty.

## Local preparation, census, evaluation and replay

From a synchronized checkout, use fresh output paths. Source locations are
execution inputs: use the recorded capture only if it exists, or an honestly
externally pinned local-custody rebinding of the same verified source bytes.
Preserve original request facts when relocating; do not claim a new capture.
Any genuine new capture requires its own truthful receipt. The implementation
accepts changed receipt paths/local source locations under a new external receipt
pin, while enforcing exact source bytes, official URLs, provenance flags and
rights. The amendment's receipt pin records its historical evidence association.
Keep the amendment adjacent to the original protocol.

```sh
.venv/bin/poe sync
.venv/bin/python scripts/run_jamendo_human_genre.py prepare \
  --protocol data/recipes/jamendo-human-genre-20261019/protocol.json \
  --receipt /workspace/jamendo-human-genre-20261019/acquisition-receipt.json \
  --receipt-sha256 3125263a9c7a3fbdc80c53ad10f60648801681b0737bbc7002720dc2b3d82b75 \
  --output .cache/jamendo-human-genre-reproduction/prepared
.venv/bin/python scripts/run_jamendo_human_genre.py census \
  --prepared .cache/jamendo-human-genre-reproduction/prepared \
  --seal-sha256 IDENTITY_SEAL_SHA \
  --output .cache/jamendo-human-genre-reproduction/census
```

Each stage prints a JSON string containing its external seal hash. Review the
no-fit support census before evaluation; never alter folds, classes or gates.

```sh
.venv/bin/python scripts/run_jamendo_human_genre.py evaluate \
  --prepared .cache/jamendo-human-genre-reproduction/prepared \
  --seal-sha256 IDENTITY_SEAL_SHA \
  --census .cache/jamendo-human-genre-reproduction/census \
  --census-seal-sha256 CENSUS_SEAL_SHA \
  --output .cache/jamendo-human-genre-reproduction/results
.venv/bin/python scripts/run_jamendo_human_genre.py replay \
  --prepared .cache/jamendo-human-genre-reproduction/prepared \
  --seal-sha256 IDENTITY_SEAL_SHA \
  --census .cache/jamendo-human-genre-reproduction/census \
  --census-seal-sha256 CENSUS_SEAL_SHA \
  --output .cache/jamendo-human-genre-reproduction/results \
  --result-receipt-sha256 RESULT_RECEIPT_SHA
```

The checked run's identity seal is
`ba8891f1cef6c8fa02cd1af311db1ddf67da4563bf719ed1debe258095fb9cff`;
its corrected census seal is
`19a9c02c775db42ece4001ac4598be8da4b760bcda4660adfea5c3a91baf9b60`.
Census bytes have SHA256
`32ecb723a20f4743b3a9d3f06093c48dd238eabb2341b6bc454dcad714e0eeb9`.
The result receipt is
`397d68414fd6d75ba2db5889b64eec85b5d881b3431f7d405941c9039ae5b9aa`.
Exact model, prediction and metric/bootstrap producer replay passed. Results
occupy 10,788,192 bytes; all local stage outputs occupy 12,846,281 bytes. A single
fresh evaluation child took 3.941 seconds and 110,993,408 peak RSS bytes. Each
CLI stage enforces 120-second wall/CPU, 1 GB address space, one numerical thread
and 20 MB output bounds. Fresh atomic publication, closed inventories, physical
file hashes/sizes, runtime/code/source/protocol/amendment pins and semantic
replay reject altered research artifacts.

An independent implementation imported no production code and reconstructed
all five models, 11,565 identity/outcome rows, 312,255 probabilities, 1,024
eligible targets, proper scores and 2,000 paired bootstrap intervals. Maximum
probability error was 9.83e-15, score error 1.78e-15 and interval error 5.33e-15;
zero fold leakage was found. Its local receipt
`/workspace/jamendo-human-genre-20261019/independent-production-comparison.json`
has SHA256 `d8950abbafa02be768543ad644ec60d53f8eea9f2a70753aec8010d3903f547a`.

## Rights and limits

MTG-Jamendo metadata and Music Classification Annotations remain
**CC BY-NC-SA 4.0, noncommercial research/academic use only**. Attribute Music
Technology Group and cite Bogdanov, Won, Tovstogan, Porter and Serra (2019),
*The MTG-Jamendo Dataset for Automatic Music Tagging*, and the pinned
[dataset README and license terms](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md)
and [Music Classification Annotations documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md).
Code licensing does not relicense source data or derived research outputs.
Raw sources, fitted artifacts and per-track predictions remain local; only
protocol, custody metadata and restrained attributed aggregates are committed.
No deployment or product integration is authorized.

Annotator identities, blinding and cross-record listener independence are not
established. Grouping exact native artist/album identities and rejecting repeated
track/path IDs does not detect reissues under different native identities.
Upstream tag-frequency preprocessing used its corpus; this fit's vocabulary and
parameters remain training-only. The result measures this fixed human-category
task, not musical similarity, recommendation usefulness, artist style or
EveryNoise parity.

A separate actual CLI proof copied only source bytes, protocol and amendment,
then used an honestly new externally pinned local-custody receipt. It ran all
four stages with independently pretested hooks denying the original raw files,
receipt, protocol/amendment, original producer cache and networking. There were
zero forbidden reads or network attempts. All three new result files were
byte-identical to the original. This proves fresh preparation/reproduction under
new custody; it does not claim that the original path-bound identity seal is a
portable bundle. The local proof receipt is
`/workspace/jamendo-human-genre-20261019/relocated-proof/proof.json`, 4,500 bytes,
SHA256 `10e3f519031aec7328491998e5817fced5fccd2c2c6a0da08ae346fc6a684dc2`.

Final verification passed: all ten focused synthetic tests; full `poe check`
with format/lint/type checks, 166 Node tests (122 passed, 44 skipped, zero
failures), and 2,222 Python tests in 161.543 seconds (36 skipped). Independent
Luna review confirmed the final source hashes and found no material blocker.
The associated pull request records exact-head and merge-head CI/publication
status; this recipe does not predict future CI results.
