# Frozen retrieval-loss diagnostic

The retained raw-feature and ridge-8 neighbor experiments recovered about 40%
of observed positive genre annotations, despite an eligible candidate-label
union covering more than 99%. This diagnostic asks where those source positives
are lost: descriptor support, pool coverage, neighbor selection or vote ranking.
It analyzes saved predictions; it does not train or select another model.

The earlier outcomes were already inspected. This is an explicitly post-hoc,
descriptive census of the same fixed predictions, not an untouched evaluation.
The protocol and diagnostic implementation are separately sealed before this
new decomposition. No parameter, neighbor roster, ranking, fold or source label
is changed.

## Accounting

Every observed positive receives exactly one category, in this order:

1. The query has a validated descriptor or retrieval abstention.
2. Its label is absent from the fold's eligible candidate-label union.
3. Its label is in that pool but absent from the ten selected neighbors.
4. The selected neighbors supply its label, but the original vote ranking puts
   it below the top ten.
5. The original top-ten ranking recovers it.

The order is deliberate. Counts locate stages in the existing computation;
they do not identify causal effects or achievable gains from changing a stage.
In particular, the union of labels on all eligible candidates is not an oracle
that can recover every label using only ten neighbors. Source annotations are
incomplete, and their recovery is not musical similarity or recommendation
usefulness.

Positive-weighted fractions retain all observed positives, including unsupported
queries. Component-equal fractions first divide each component's category counts
by its observed positives and then average over components with a defined
denominator. Empty annotations remain in query-coverage counts. Both weightings,
each fixed fold, giant component 2 and the remaining components are reported;
none is selected after seeing these results. Native components join artists,
albums and duplicate descriptors; they are not proven independent musicians.

Queries with neighbors whose labels are all empty remain retrieval-available
but genre-ranking-unavailable. Their missing annotations do not become negative
labels. Saved Gaussian and recording-popularity controls retain their original
full-denominator Recall@10; the training-popularity ranking is independently
recomputed within each fold.

## Custody and verification

The exact original summary is pinned by SHA256
`ccf1b98b3e4ca7602f253484f5025964cadefab0e792a98968661f3d490f65e4`.
Its five fold-receipt hashes bind the candidate and prediction files. The
original execution seal is
`e4351cfa8fb0f89d69c6984d63d7456510c78d39a2ba84aaa90c01134b5975e9`;
the minimized numeric input manifest is
`4344e609efd7442bf2c598fefb9d1f5abb08884b59f922a53a05643c60d0a323`.
Closed inventories and file hashes are checked before analysis.

The diagnostic reconstructs the native component/fold ledger, verifies that
queries appear exactly once with their source labels, and requires candidates
and neighbors to stay outside the query's held-out component fold. It rebuilds
the candidate label union and every neighbor-vote ranking using native genre-ID
tie breaks. Recovered positives must equal the original saved hit counts for
every component and arm. These checks validate the retained computation, not
new acoustic geometry or human relevance.

Per-stage bounds remain 120 seconds CPU/wall, 1,000,000,000 bytes address space,
one numerical thread and 10,000,000 bytes of new diagnostic outputs. Prior
75 MB experiment artifacts remain unchanged. There is no new acquisition,
audio processing, serving integration, public deployment or paid service.

The original protocol bytes and a pre-execution custody amendment are retained
separately. The amendment added the historical summary/fold-receipt bindings;
it did not change any metric, category, cohort or model. The final protocol
SHA256 is `e9b3d7a63b28f0ea87365f2f2a89cd5269db5befe7c865f17cc9d7affeae1018`.

Interpretation remains conditional on these previously inspected predictions
and overlapping training folds. No new confidence interval, significance claim,
population generalization or Every Noise parity claim follows from this census.

## Results

All 94,953 original-training queries were accounted for across 5,883 native
components. There are 227,441 observed positive incidences, 92,677 labeled
queries and 5,621 components with a defined positive-recovery denominator. The
2,276 unlabeled queries remain in query coverage. Both neighbor arms produce
neighbors and genre rankings for 92,222 queries; 2,683 queries lack descriptors
and 48 fall outside training support.

| Ordered category | Raw count | Raw positive fraction | Ridge-8 count | Ridge-8 positive fraction |
| --- | ---: | ---: | ---: | ---: |
| Descriptor/retrieval abstention | 5,864 | 2.578% | 5,864 | 2.578% |
| Absent from eligible pool labels | 1,420 | 0.624% | 1,420 | 0.624% |
| Available in pool, not retrieved | 116,045 | 51.022% | 115,087 | 50.601% |
| Retrieved label below vote cutoff | 12,406 | 5.455% | 11,931 | 5.246% |
| Recovered in top ten | 91,706 | 40.321% | 93,139 | 40.951% |

The largest loss is between eligible pool-label coverage and selection of ten
neighbors. Expanding taxonomy-label coverage alone does not address this
dominant observed loss category. This is not evidence that the current pool has
sufficient musical or artist coverage, nor that a different retrieval method
could gain 51 percentage points. The same pooled category remains largest both
within giant component 2 (raw 50.062%, ridge 49.281%) and outside it (raw 51.806%,
ridge 51.678%).

Weighting changes the interpretation of the small difference between arms.
Component-equal unretrieved-label loss rises from 44.380% to 44.491%, while
vote-excluded loss falls from 5.054% to 4.516%; recovered labels rise from
42.230% to 42.657%. These are marginal accounting differences, not evidence that
the same labels moved from a particular loss category to recovery. The vote
algorithm is unchanged, so the difference cannot be credited causally to a
vote-ranking change. Component-equal abstention loss is 7.722%, substantially
larger than the positive-weighted 2.578%; small components remain consequential.

All original control hit counts and coverage counts reproduce exactly. On the
same positive denominator, recording popularity recovers 37.861%, recording
Gaussian 32.778% and component Gaussian 33.741%. Their component-equal recalls
are 39.458%, 37.647% and 39.550%, respectively. This diagnostic adds no evidence
that overrides the prior embedding experiment's interval spanning zero for its
primary learned-versus-raw recall difference. No arm is promoted.

The next quality question concerns retrieval relevance within a prospectively
fixed evaluation, rather than another claim based solely on pool-label reach.
This accounting cannot establish which representation or candidate-selection
change would help. Musical usefulness still requires independent human relevance
judgments; another evaluation on these inspected predictions is not confirmation.

The producer completed in 23.886 seconds using 307,220,480 peak RSS bytes. Its
own exact-output replay passed in 22.105 seconds using 307,109,888 bytes. The
two result payloads total 2,004,513 bytes, below the 10 MB bound. Results SHA256:
`cb3a14310937bf9e1902a2bb63160bc7cc15342461c7be9899acedac381a1de9`.
The separately sealed execution SHA256 is
`3ff8bccb2aa4f6f73d15fca8530325c87db721436a8af79752b446b340f20178`.

An independently written verifier, frozen before the new results, reproduced
all 94,953 queries, 5,883 components and 227,441 positive incidences. Integer
categories, control hits, coverage and abstention reasons matched exactly;
all eight summary scopes matched within 1e-12. Its replay took 35.41 seconds
and 304.55 MB; a separate schema-comparison adapter took 5.34 seconds and
45.7 MB. The independent core remained unchanged. This verifier imports no
producer code and fits no model.

Full `poe check` passed: 2,080 Python tests ran with 36 skips; 112 JavaScript
tests passed with 44 optional skips. Independent source and interpretation
reviews found no remaining issues. Source attribution and rights remain bound
to the retained FMA provenance pack; no new source permission is asserted.

## Reproduce

After `poe sync`, invoke the guarded CLI directly, as permitted by AGENTS.md:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_fma_retrieval_loss.py freeze \
  --protocol data/recipes/fma-retrieval-loss-20261017/protocol.json \
  --original-seal /workspace/opennoise-embedding-run-20261016/execution-seal.json \
  --source /workspace/opennoise-clean-inputs-20261015/candidate \
  --run /workspace/opennoise-embedding-run-20261016/run \
  --output /workspace/new-retrieval-loss-seal.json
PYTHONPATH=src .venv/bin/python scripts/run_fma_retrieval_loss.py run \
  --seal /workspace/new-retrieval-loss-seal.json --output /workspace/new-retrieval-loss
PYTHONPATH=src .venv/bin/python scripts/run_fma_retrieval_loss.py replay \
  --seal /workspace/new-retrieval-loss-seal.json --output /workspace/new-retrieval-loss
```

The seal and run destinations must be fresh. The replay command verifies the
existing result pack. Source, runtime or prediction changes require an explicit
new protocol rather than weakening pins. Full per-component counts, all fold
summaries and resource logs are retained under
`/workspace/opennoise-retrieval-loss-run-20261017`; independent implementation
and replay evidence are under `/workspace/opennoise-retrieval-loss-independent-20261017`.
