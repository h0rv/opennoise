# Diagnostic evaluation of the reviewed 55-recording waveform model

This follow-up investigates the zero top-three source-tag matches among six test
queries from the existing waveform experiment. It does not fit another model,
change serving neighbors, acquire recordings, or tune against those queries.
All six test queries and both validation queries were already inspected. They
remain diagnostic cases, not an untouched confirmation set.

## Coverage and ranking are different limitations

Five test queries have eligible training candidates sharing observed source tags.
Their first matching candidates in the saved raw-descriptor ranking occur at
positions 15, 6, 5, 24 and 20. The sixth query has no matching candidate. Eligibility
and component exclusion do not remove any globally known query tags in this cohort.
The zero top-three result therefore involves ranking as well as missing coverage.

Across the six queries, the candidate pools can recover eight of fourteen observed
tag incidences. An exact component-diverse selection of at most three candidates
per query can recover those eight. This label-informed ceiling is not a retrieval
method or model score. Source tags are incomplete positives: missing overlap does
not establish dissimilarity, and shared tags do not establish musical relevance.

## Prespecified comparisons

- The existing 52-column standardized cosine ranking remains unchanged.
- A simple comparator uses the four saved training-standardized RMS and
  zero-crossing-rate mean/standard-deviation columns with squared Euclidean
  distance. This is a simple-feature comparison, not an isolated feature ablation:
  the distance function also differs. It introduces no additional fit.
- A query-independent training annotation-prevalence prior averages each
  candidate's observed-tag training frequencies. It is explicitly a label-prior
  baseline, not audience popularity.
- A historical-popularity comparator ranks the native FMA `track_listens` counts.
  A separate bounded offline projection verifies the previously captured metadata
  ranges and the full raw member, retaining only the 55 IDs and integer counts.
  Missing or invalid counts fail closed. These are historical snapshot counts,
  not current popularity; exposure, age and platform selection can bias them.
- An exact random reference samples distinct eligible components uniformly, then
  one recording uniformly within each chosen component. It respects component
  exclusion and diversity. Uniform sampling of tracks would define another null.

Every method uses the frozen original eligibility and query component exclusions.
Results retain unsupported cases and both all-observed and globally known tag
denominators. The random reference describes uncertainty in this artificial
retrieval procedure conditional on this fixed cohort. It is not a population
confidence interval, a musical-quality test, or a post-hoc significance claim.
No comparison selects a new serving method.

## Human evaluation remains necessary

The listening instrument compares the original top candidate with the prespecified
simple-feature top candidate for all six test queries. Two listener slots receive
opposite A/B assignments, yielding twelve planned responses but only six query
components. Repeated responses are not independent query observations. Identical
candidates, missing comparisons, ties, neither, uncertainty and playback failures
remain explicit. Required recording identities and credits remain visible, so
this is method-blinding only. A separate coordinator key stays outside each served
participant directory. Blank packets and an empty response summary are not human
judgments or evidence of improved recommendations.

This small selected sample can test the instrument and reveal failure modes. A
planning target of roughly 100 independent representative query components would
give about a ten-percentage-point worst-case 95% half-width for a simple binary
proportion under independent sampling. This approximation does not automatically
apply to multicategory outcomes, conditional win rates, missing responses or
clustered ratings. Two distinct listeners per query help measure disagreement;
they do not double the independent query count. A useful subsequent study needs
separate development queries, a frozen untouched evaluation roster, permitted
recordings, relevant candidate coverage and actual independent listening responses.
For fresh confirmation, budget roughly 100 previously uninspected query components,
not 100 total tracks or 94 additions to these six inspected queries. Keep a separate
training candidate pool and development cohort; multiple excerpts from one connected
artist/album component do not create additional independent queries. A fixed recording
count alone cannot guarantee useful musical coverage. Candidate availability and
permission, representativeness and the intended similarity question need review
before sampling. At least two distinct listeners per query implies about 200
responses for one paired comparison, with missingness and disagreement retained.
Additional acquisition and public deployment are outside this recipe.

## Reproduction and evidence

The frozen protocol, commands, independent replay and recorded results accompany
the completed evaluation. The existing waveform inventory is pinned to
`829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729`.
The original source/audio artifacts remain unchanged. Evaluation runs use the
existing 120-second CPU/wall, 1 GB memory and 100 MB output limits.

Use the locked environment (`poe sync` first) and fresh output paths. The metadata
source below is the existing verified capture; the commands perform no acquisition.
For numerical reproduction without the original metadata, reuse the evaluation
pack's pinned `listens.json` directly. The original capture is needed only to replay
the separate count projection, which was independently checked from the full stream.

```sh
FRESH=/path/to/new-diagnostic-run
SOURCE=/path/to/retained-metadata-source
CANDIDATE=/path/to/reviewed-55-candidate
WAVEFORM=/path/to/reviewed-waveform-pack
mkdir "$FRESH"
PYTHONPATH=src .venv/bin/python scripts/project_fma_waveform_popularity.py \
  --source "$SOURCE" --manifest "$CANDIDATE/manifest.json" \
  --output "$FRESH/historical-listens.json"
PYTHONPATH=src .venv/bin/python scripts/evaluate_fma_waveform.py freeze \
  --source "$WAVEFORM" --candidate-manifest "$CANDIDATE/manifest.json" \
  --listens "$FRESH/historical-listens.json" \
  --protocol data/recipes/fma-waveform55-evaluation-20261016/protocol-v2.json \
  --declaration "$FRESH/declaration.json"
PYTHONPATH=src .venv/bin/python scripts/evaluate_fma_waveform.py run \
  --declaration "$FRESH/declaration.json" --output "$FRESH/pack"
PYTHONPATH=src .venv/bin/python scripts/evaluate_fma_waveform.py run \
  --declaration "$FRESH/declaration.json" --output "$FRESH/replay"
```

The same declaration must reproduce every pack file byte-for-byte. An independent
implementation checks the numerical results before the output inventory is approved
for listening-packet use. Validation requires that externally reviewed inventory pin:

```sh
PYTHONPATH=src .venv/bin/python scripts/evaluate_fma_waveform.py verify \
  --output "$FRESH/pack" --candidate-manifest "$CANDIDATE/manifest.json" \
  --inventory-sha256 "$REVIEWED_EVALUATION_SHA256"
PYTHONPATH=src .venv/bin/python scripts/build_fma_listening_pilot.py freeze \
  --candidate "$CANDIDATE" --baseline "$FRESH/pack" \
  --baseline-inventory-sha256 "$REVIEWED_EVALUATION_SHA256" \
  --design data/recipes/fma-waveform55-evaluation-20261016/listening-protocol.json \
  --output "$FRESH/listening-seal.json"
```

After checking the seal against the reviewed implementation and inputs, supply its
exact hash to `build_fma_listening_pilot.py build` with `--candidate`, `--baseline`,
`--seal`, `--seal-sha256` and a fresh `--output`. Distribute participant roots
separately; never serve their parent directory or coordinator mapping. Each root
contains launch instructions. The summarizer accepts zero, one or two actual slot
response files; absent responses remain missing. Confirm distinct participants only
when the coordinator has established that fact. Browser-generated test responses
must never be included as actual listening evidence.

## Recorded diagnostic results

All six rankings have zero test hits at both one and three neighbors. Mean test
source-tag recall is zero using either all observed labels (six defined queries)
or training-known labels (five defined queries). The validation results are retained
separately rather than pooled into the test result:

| Ranking | Test hits @1 / @3 (six queries) | Validation hits @1 / @3 (two queries) |
| --- | --- | --- |
| Original 52-column cosine | 0 / 0 | 0 / 1 |
| Original PCA2 | 0 / 0 | 1 / 1 |
| Native ID | 0 / 0 | 0 / 0 |
| Four simple audio features | 0 / 0 | 0 / 0 |
| Training annotation prevalence | 0 / 0 | 0 / 0 |
| Historical listen popularity | 0 / 0 | 0 / 0 |

For the six test queries, the exact component-balanced random procedure has
expected hit counts of 0.336 at one neighbor and 0.943 at three. Its central 95%
conditional hit-count bands are respectively 0–2 and 0–3. Expected mean all-tag
recall is 0.0333 and 0.0953; known-tag recall is 0.0549 and 0.1572, with the same
six/five defined-query denominators. These describe the specified random mechanism
on this fixed sample. They neither establish an underperforming population model
nor excuse the observed ranking failures against recoverable labels.

For validation, random expected hit counts are 0.0833 and 0.2359; both conditional
bands are 0–1. The original raw/PCA validation hits concern the same one supported
query. They are not evidence for choosing a model. The simple comparator provides
no measured tag-overlap improvement, and no serving change follows these results.
