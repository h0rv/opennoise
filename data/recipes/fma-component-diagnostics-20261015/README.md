# Fixed-ranking component diagnostics

The frozen Gaussian's test observed-label Recall@10 advantage over training-label
popularity is 2.965 percentage points. A paired whole-component bootstrap gives a
95% percentile interval of −1.292 to +6.553 points. This diagnostic does not
establish a stable advantage across component compositions. It does not establish
equivalence or the absence of an effect either.

Test MRR remains worse by 0.00615 (interval −0.04635 to +0.03588). Equal weighting
of labeled components gives Recall@10 0.377318 for the acoustic model and 0.377422
for popularity, and MRR 0.270551 versus 0.301817. These are different estimands
from track/positive-weighted metrics, not replacements chosen to improve a score.
The 703 test components have positive-weight effective count 51.10; one component
contains 12.53% of observed positives. Deleting each individual component keeps the
recall advantage positive, between 2.183 and 3.491 points: the effect is not solely
one component, although broader composition uncertainty remains substantial.

Validation has 753 components, effective count 117.54, and recall advantage
0.720 points (interval −5.021 to +6.946). Its MRR difference is −0.02529 (interval
−0.07989 to +0.02926). Both folds were previously inspected. These are retrospective
diagnostics of incomplete annotation recovery, not fresh blind confirmation,
model retraining uncertainty, unknown-alias leakage detection, musical relevance,
or proof that playback recommendations work well.

## Frozen method and checks

`declaration-v2.json` freezes input hashes, both folds, 2,000 paired whole-component
resamples using PCG64 seed 20261015, percentile intervals, mass concentration,
component-equal metrics, and exhaustive single-component deletion sensitivity.
All queries, missing-feature abstentions and positive labels retain the original
denominators. Unlabeled queries are counted, but cannot supply a positive-recall
or MRR denominator. Rows with unresolved artist identity are excluded exactly as
in the original evaluation, even when their ledger records a tentative fold.

The original `declaration.json` accidentally expressed resource caps in binary
units. Before computation, v2 narrowed these to the inherited decimal 1 GB RAM and
10 MB output; the original declaration remains intact. CPU and wall time stay
120 seconds. No model, rank, split, parameter or label selection changed.

The standalone first implementation reproduced saved Recall@10, MRR, per-label
hits/training support, query counts and abstentions before diagnostics. An
independent reviewer recovered all counters from native metadata and ranks, then
replayed all intervals with a separate weighted-count implementation. This does
not claim to replay unselected metrics such as Recall@5. Two early failed checks
(null unlabeled tags and tentative unresolved-artist folds) were corrected before
producing results; logs remain in the retained evidence directory.

## Reproduce from retained inputs

With the locked project environment installed, run:

```sh
PYTHONPATH=src .venv/bin/python scripts/analyze_fma_components.py \
  --declaration data/recipes/fma-component-diagnostics-20261015/declaration-v2.json \
  --baseline /workspace/opennoise-rebuild-20261013/baseline44 \
  --metadata /workspace/opennoise-rebuild-20261013/metadata \
  --output /workspace/component-diagnostic-replay
```

Output must be fresh. Absolute input paths are part of this evidence declaration.
For another machine, preserve the frozen original and write a new declaration
with relocated absolute paths and identical byte/hash bindings; do not overwrite
the historical declaration or silently change the analysis fields. The CLI
rejects altered analysis settings. Git contains code, small declarations and
results, not the source metadata, ranks or fitted model required for execution.

The checked-in `results.json` binds the initial standalone implementation. The
reusable module is independently rerun and compared with those numerical results;
its source hash and resource timing naturally differ. Full evidence remains in
`/workspace/opennoise-component-diagnostics-20261015/`.
