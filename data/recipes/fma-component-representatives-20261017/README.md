# Two recordings per candidate component

This fixed exploratory experiment asks whether a second descriptor-diverse
recording helps represent each existing candidate component. It reuses frozen
44-feature geometry and changes neither the encoder nor the number of retrieved
components. It does not establish musical similarity or replace serving data.

## Evidence and choice

PR #59 located the largest observed-positive loss between candidate-label
availability and selection of ten neighbors. Pool-label reach is not the same as
an attainable ten-neighbor recovery rate. Missing source annotations are unknown,
and absence of shared tags does not establish that two recordings sound unlike
one another.

A read-only preflight found that unlabeled recordings account for 6.087% of
selected raw44 neighbors. The top 100 candidates receive 15.64–18.28% of each
fold's selections; effective candidate counts are 1,129–1,311 out of roughly
2,048. There is concentration, but not collapse onto a handful of recordings.
These descriptions alone do not diagnose the cause of missed annotations.

Separately, 81–82% of the existing nominated components have another recording
eligible under the frozen raw-feature support rules. Adding one per component
produces 3,712–3,732 recordings, within the 4,096 cap. This establishes an
opportunity to test representation, not an expected improvement. The giant
component 2 is absent from every candidate pool; it affects query composition,
not candidate dominance. This experiment cannot fix its candidate absence or
represent its full heterogeneity.

## Fixed comparison

For each fold, preserve the exact original component roster and representative.
Among its other eligible training recordings, add the one with lowest cosine
similarity to the original, breaking ties by native track ID. Always add a
different eligible record if available, including identical-vector cases, which
are counted separately. No genre label is consulted for this selection. The
inherited original component roster was shared with a supervised ridge
experiment and is not claimed to have wholly label-free history.

A component's query score is the greatest cosine similarity among its one or two
representatives. Ties choose the lowest winning track ID. Return the winning
recording from each of ten distinct best components. Transfer unweighted positive
source-genre votes exactly as before. Preserve all query support checks and
abstentions. No recording or component outside the fixed original-training fold
partition enters a candidate roster.

Adding a second recording mechanically gives a component another chance to
match a query. Components with only one eligible record do not receive that
chance, and a farthest record can be an outlier. Higher maximum cosine alone is
therefore not evidence of useful improvement; observed-positive recovery and
coverage are evaluated on unchanged denominators.

The controls are the saved single-representative raw44 neighborhoods and
training-recording popularity. Recompute every raw neighborhood and its complete
vote ranking, and derive popularity separately within each training fold.
Original source bytes, summary and fold receipts bind those controls. There is
no new fit, feature set, encoder, neighbor count, parameter search or relabeling.

The primary quantity is the difference in component-equal source-positive
Recall@10 against raw44. Report all arms' absolute results and the popularity
comparison, positive-weighted recall, labeled-query MRR, component-equal MRR and
coverage. Keep the giant component intact and report it separately from the
others, as well as all five folds. Components combine source artist, album and
exact-descriptor links; they are not guaranteed independent musicians.

## Distinguishing effects

An extra recording may add tags to a candidate pool as well as change its
geometry. Report the five ordered loss categories from PR #59 for each arm,
paired 5-by-5 transitions and new hits divided between labels already available
in the old pool and newly available labels. These joint counts describe the
combined change; they do not causally isolate coverage, geometry or annotation
quality. Report empty annotations, annotation-count distributions, candidate
usage and second-representative availability. Empty-label queries retain their
coverage denominator, and absent tags never become verified negatives.

The same folds have already been inspected. This is one prospectively specified
challenger within an exploratory workflow, not a fresh independent evaluation.
No new significance test or population-confidence claim is made. Any proxy gain
would still require a genuinely unexamined evaluation and human relevance
judgments before a musical-usefulness claim or serving promotion. Negative
results are retained without trying another parameter or arm in this run.

## Bounds and provenance

Each stage retains 120 CPU/wall seconds, 1,000,000,000 bytes of address space,
one numerical thread and a combined 100,000,000-byte new-output cap. A synthetic
worst-fold geometry benchmark used 50,105 queries, 4,096 candidate recordings and
44 features; raw and new selection took 13.51 seconds and 95,883,264 peak RSS
bytes. This excludes actual source loading, verification, votes and output
serialization; actual process guards remain unchanged.

The numeric manifest is
`4344e609efd7442bf2c598fefb9d1f5abb08884b59f922a53a05643c60d0a323`.
The original summary is
`ccf1b98b3e4ca7602f253484f5025964cadefab0e792a98968661f3d490f65e4`;
its fold receipts bind the saved geometry and predictions. Input inventories,
implementation, protocol and numerical versions must be sealed before new
outcomes. Independent source review and a separately frozen verifier precede
execution. Results and replay evidence are retained separately from original
inputs.

This is offline reuse of retained FMA features from the receipted official
capture, not fresh acquisition or fabricated historical replay receipts. No
audio, new credentials, paid compute, Library retry, public research-data release
or deployment is part of this experiment.

## Results and decision

The fixed challenger did not improve the primary metric. Component-equal
Recall@10 declined by **0.113 percentage points**; three of five fold differences
were negative. The point estimate is descriptive, not proof of population harm.
The small improvement in positive-weighted recall does not justify promotion.

| Arm | Component-equal Recall@10 | Positive-weighted Recall@10 | Query MRR | Component-equal MRR |
| --- | ---: | ---: | ---: | ---: |
| Original raw44 representatives | 42.230% | 40.321% | 0.38414 | 0.34846 |
| Two representatives | 42.118% | 40.731% | 0.38631 | 0.34736 |
| Training-recording popularity | 39.458% | 37.861% | 0.39214 | 0.31326 |

All 94,953 queries, 92,677 labeled queries and 227,441 observed positives remain
in their declared denominators across 5,883 components. Both neighbor arms
retain exactly 92,222 descriptor-supported queries, nonempty neighborhoods and
genre rankings. The 2,276 unlabeled queries remain in coverage counts. Training
popularity has full query ranking coverage. Raw44 and popularity controls
reproduce their original results; the challenger's advantage over popularity
on recall is not new evidence for adding representatives because raw44 already
has that advantage. Popularity remains higher on pooled query MRR.

The challenger gains 16,409 previously missed positives whose labels were already
available in the old pool and 19 whose labels are newly available. It also loses
15,495 previous hits, leaving 933 net additional positive incidences. Giant
component queries contribute 670 of that net gain (71.8%); all other components
contribute 263. Giant positive recall rises from 41.321% to 41.977%, while other
components rise from 39.505% to 39.715%. Component-equal recall outside the giant
falls from 42.230% to 42.118%. These are fixed-prediction influence descriptions,
not a deletion-and-refit study.

| Ordered positive category | Raw44 | Two representatives |
| --- | ---: | ---: |
| Descriptor/retrieval abstention | 5,864 | 5,864 |
| Absent from candidate-label union | 1,420 | 1,159 |
| Available in pool, not retrieved | 116,045 | 114,047 |
| Retrieved label below vote cutoff | 12,406 | 13,732 |
| Recovered in top ten | 91,706 | 92,639 |

Expanded candidate availability moves 261 previously pool-absent positives into
availability, but only 19 into recovery; 235 remain unretrieved and seven fall
below the vote cutoff. Overall, the unretrieved category shrinks while the
vote-excluded category grows. The complete paired transition matrix is retained.
This does not identify a causal benefit of geometry or a reason to tune the vote
cutoff on these same inspected queries.

Unlabeled selected recordings fall from 56,131 to 40,609 of 922,220 neighbor
slots (6.087% to 4.403%). Pooled record-use concentration falls, with inverse
Herfindahl count increasing from 1,544 to 2,629. Component-use effective count
increases more modestly, from 1,544 to 1,652. These changes accompany a worse
primary metric; more record diversity or fewer empty tags is not by itself
proof of better retrieval. The per-fold candidate pools remain distinct, and
pooled use summaries are not independent-pool estimates.

The evidence supports retaining the original baseline and closing this fixed
challenger without a serving change. It does not support automatically adding
more representatives, changing votes or searching another encoder against these
same examined folds. The unresolved question is musical relevance, for which
missing tags cannot supply negative judgments. A next promotion decision needs
prospectively fixed independent evaluation and human relevance evidence, not
another retrospective metric choice.

The aggregate result SHA256 is
`8062c64b1ebfb9d4dcb15b817ffcd79de8090495d6bf74da3db3201556e0c459`.
The execution seal is
`f7ca8f298f84af961bd780fe9db1c88696fc2eeb6f0d9d50c72451ce4197242a`,
binding reviewed source commit `8861f8f84447a503d7276e3ad801b250da5f8031`
and protocol `7ce59e1c4ef85e2f38f0e0224e8aa39a28a0186f73027a301ec1246a4ac3f949`.

## Verification

All five producer folds and the summary passed exact byte-for-byte replay.
Producer fold stages took 9.74–39.47 seconds, with peak RSS at most 311,808,000
bytes; summary took 3.54 seconds. The complete producer run is 42,366,400 bytes,
within the unchanged 100 MB bound.

The independently written, separately frozen verifier reproduced all 94,953
queries, 5,883 components and 8,361 second-representative choices across folds.
Candidate identities, neighbor order, complete vote rankings, integer statistics,
paired transitions, sparsity and usage counts matched exactly. All eight summary
scopes matched within 1e-12; maximum selected cosine-score error was
8.881784197001252e-16. Independent folds took 8.16–29.21 seconds at approximately
304 MB peak RSS; the complete schema comparison took 30.96 seconds and
372,551,680 bytes. It imports no producer implementation and fits no model.

Source and interpretation reviews passed. Full `poe check` passed with 2,091
Python tests (36 skipped), 112 JavaScript passes and 44 optional skips, plus
formatting, lint and type checks. Final exact-head and main CI records are kept
with the completion receipt. Detailed inputs remain in their existing separate
custody pack; this recipe publishes only code, protocol and aggregate counts.

The producer and logs are retained under
`/workspace/opennoise-component-representatives-run-20261017`; independent
implementation, comparison and resource receipts are under
`/workspace/opennoise-representatives-independent-20261017`. No original capture,
model or prediction artifacts were overwritten, and no Library upload was
retried.

## Reproduce

Run `poe sync`, then the guarded script directly as permitted by AGENTS.md:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_fma_component_representatives.py freeze \
  --protocol data/recipes/fma-component-representatives-20261017/protocol.json \
  --original-seal /workspace/opennoise-embedding-run-20261016/execution-seal.json \
  --source /workspace/opennoise-clean-inputs-20261015/candidate \
  --run /workspace/opennoise-embedding-run-20261016/run \
  --output /workspace/new-representatives-seal.json
PYTHONPATH=src .venv/bin/python scripts/run_fma_component_representatives.py fold \
  --seal /workspace/new-representatives-seal.json \
  --output /workspace/new-representatives-run --fold 0
```

Execute folds 1–4 serially with the same seal and output root, then `summary`
with the same `--seal` and `--output`. Each new fold and summary directory must
be absent. `replay-fold --fold N` and `replay-summary` regenerate deterministic
artifacts in fresh temporary space and compare their bytes against the retained
pack. Replays validate the existing outputs without overwriting them. Changed
source, protocol, inputs or runtime requires a new explicit freeze.
