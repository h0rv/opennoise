# Nested temperature diagnostic for historical human genre votes

This exploratory follow-up addresses the original genre NB's worse log loss despite better Brier than its training prior. The original outer results were known. The protocol was committed before any new inner fit or temperature score; it truthfully records the earlier descriptive diagnostics and the single inspected inner-hash support census. The hash was not selected among reseeds. This is nested reuse of the same historical cohort, not a fresh confirmatory experiment, retrieval validation or a general calibration guarantee.

The [frozen protocol](protocol.json), SHA256 `012af3ed3453c5157d3a5bce79323bdb086da2d8b18a594bca8c76e981b74eff`, preserves the [original task](../jamendo-human-genre-20261019/README.md), its nine classes, source serialization amendment, 11,565 metadata identities, artist+album components and five outer folds. Original runtime files and three baseline payload files remain unchanged. Existing fresh source capture is reused; this follow-up made zero acquisition requests and incurred $0 external cost.

Before this freeze, saved NB component-weighted top confidence was 85.26%, versus 63.35% human-vote agreement. It gave probability below 0.1% to classes carrying 10.43% of human vote mass. Saved vocabulary checks matched training-only genre/instrument tags and found no outer-component overlap or forbidden namespaces. These checks do not establish semantic independence or rule out all leakage. Genre/instrument co-occurrence can violate NB conditional independence; it is a possible explanation, not a demonstrated cause. Class imbalance and nonrandom label availability remain: 1,024 eligible rows among 1,757 nonempty taxonomy nominations and 11,565 metadata rows; 403 disagreements remain included. Only these 1,024 rows in 368 components are scored. Missing/invalid annotations are retained, not assigned targets.

Within each fixed outer training partition, three inner component folds use SHA256(`opennoise-jamendo-human-genre-temperature-inner-v1|{outer}|{component}`), integer modulo three. All 15 training gates passed with minimum eight positive-vote components per class. Each inner model uses training-only vocabulary and component-unit training weights. Temperatures `{1,2,4,8}` are compared using complete inner OOF fractional log loss, averaged within component then across components. Exact ties select smaller T. No outer labels enter this selection. If any inner training gate or complete OOF coverage fails, calibrated NB uses T=1 identity fallback with an explicit reason; original predictions and availability remain intact.

Temperature acts on raw nine-class NB logits divided by T, normalized with logsumexp. Empty-vocabulary logits are log prior. T=1 returns the original NB probability list exactly, including the empty-vocabulary case. Probabilities are never clipped for the transformation or Brier. Only log loss uses the fixed `1e-15` clip; inner selection clipping counts are reported. There are 15 inner fits and five original full-outer verification fits per execution, at most 20. The baseline models and every original method probability must reproduce exactly before output publication. The producer ran one measured evaluation (20 fits) and one separate exact replay (20 verification fits). The cap applies per bounded invocation, not to the combined experiment/audit workflow; repeated verification uses the same frozen candidates, not new tuning. There was no subsequent grid, feature, gate or model change based on outcomes.

## Actual result

All five folds independently selected T=4, with no fallback. All 11,565 original metadata predictions and 1,024 scored outcomes remain available. Component-equal fractional log loss changed from **2.007334 to 1.346745**; calibrated-minus-unscaled difference **−0.660590**, fixed paired component bootstrap interval **[−0.842453, −0.482926]**. This is the prespecified primary endpoint.

Component Brier changed from **0.562462 to 0.569056**, a small worsening: difference **+0.006594**, interval **[−0.025534, 0.037724]**. Compared with the direct uploader predictor, calibrated component Brier difference is **−0.024684**, interval **[−0.060382, 0.012492]**, still uncertain. Selected-temperature mean confidence is **43.09%**, versus unchanged human top-label agreement **63.35%**: the confidence gap is now **−20.26 percentage points**, compared with the original **+21.91 points**. Thus the log-loss improvement coexists with pronounced aggregate underconfidence; this is not a calibration guarantee. Inner selection losses describe smaller training models, so transfer to the full outer model is a limitation, not an established causal explanation. No unchosen outer temperatures were evaluated or used to retune. These mixed outcomes do not establish general superiority over uploader tags. No method was changed after seeing them. [Checked aggregates](results.json) include all four methods, both weighting scopes, all six paired comparisons, class masses/log-loss contributions, fixed confidence bins and missingness/tag sampling.

The fixed 2,000 bootstrap draws (seed 20261019) resample shared scored components and condition on existing OOF predictions. They do not estimate retraining uncertainty or population confirmation. Diagnostics use confidence=max probability, class-order argmax ties and fractional human-vote agreement; fixed bins `[0,.2,.4,.6,.8,1]`, last right closed. Eligible scored rows have global weights `1/n_component`; bin statistics renormalize within each bin. Diagnostics/ECE never select a temperature.

## Reproduce locally

Use Python 3.13 and `poe sync`. Source and original pipeline stages are deliberately local research inputs; obtain them by the original checked recipe or restore the exact verified retained bytes with an honest externally pinned custody receipt. A newly generated baseline receipt may differ, but the three baseline payload hashes must equal the historical payloads in this protocol's evidence. Do not relabel old custody as a new network capture. Raw/model/per-track files are not included in this repository.

From the repository root, the following uses the retained original local stages. All output directories must be fresh. Substitute honest fresh stage envelope pins when rebuilding the original pipeline; no acquisition is performed by this CLI.

```bash
.venv/bin/python - <<'PY'
import json
import subprocess
import sys
from pathlib import Path

original = Path('/workspace/opennoise-jamendo-human-genre/.cache/jamendo-human-genre-20261019')
output = Path('.cache/jamendo-genre-temperature-reproduction')
common = [
    '--protocol', 'data/recipes/jamendo-genre-temperature-20261019/protocol.json',
    '--protocol-sha256', '012af3ed3453c5157d3a5bce79323bdb086da2d8b18a594bca8c76e981b74eff',
    '--prepared', str(original / 'prepared'),
    '--identity-sha256', 'ba8891f1cef6c8fa02cd1af311db1ddf67da4563bf719ed1debe258095fb9cff',
    '--census', str(original / 'census'),
    '--census-sha256', '19a9c02c775db42ece4001ac4598be8da4b760bcda4660adfea5c3a91baf9b60',
    '--baseline', str(original / 'results'),
    '--baseline-sha256', '397d68414fd6d75ba2db5889b64eec85b5d881b3431f7d405941c9039ae5b9aa',
]
def run(stage, extra):
    command = [sys.executable, 'scripts/run_jamendo_genre_temperature.py', stage, *common, *extra]
    return json.loads(subprocess.check_output(command, text=True))
inner = run('census', ['--output', str(output / 'inner-census')])
# This publishes the complete no-fit roles/support census before fitting.
extra = ['--inner-census', str(output / 'inner-census'), '--inner-census-sha256', inner]
result = run('evaluate', [*extra, '--output', str(output / 'results')])
print(run('replay', [*extra, '--output', str(output / 'results'), '--result-sha256', result]))
PY
```

Every invocation enforces 240 seconds CPU/wall, 1 GB address space, one numerical thread and a combined 20 MB output cap. Fresh publication is atomic; input/output overlap, extra files, wrong external pins, physical whitespace mutations, runtime changes and historical baseline-payload mismatches fail closed. Inner roles and support must replay before fitting. Replay reproduces all 20 fits, models, raw inner logits, selections, predictions and aggregate diagnostics.

The measured fresh evaluation took 5.653 seconds with peak child RSS 160,727,040 bytes on this host; this is one bounded engineering observation, not a universal latency claim. Result files total 14,719,387 bytes including their receipt, under the cap. Local artifact pins, exact sizes and measurement are in `results.json`.

## Verification evidence

The independent calculation imported no production code. It matched all 15 inner models, 36,864 raw OOF logits, 20 candidate losses, five selected temperatures, 416,340 outer method/class probabilities, all original baseline fields/target outcomes, six paired 2,000-draw comparisons and fixed-bin/class diagnostics. Inner/outer component overlap is zero. Maximum absolute errors were `7.11e-14` for raw logits, `9.83e-15` for probabilities and `5.33e-15` for bootstrap interval endpoints. The local comparison receipt is `/workspace/jamendo-genre-temperature-20261019/independent-production-comparison.json`, SHA256 `f41041bf4e8173741ffbcb22cb02ab4a9d14dcc67a453936babd0581481fa87c` (1,369 bytes). Its separate audit used 15 independent inner fits and previously verified outer models. Producer exact CLI replay also passed as a separate 20-fit verification invocation.

Ten focused tests pass, covering independent nine-class logits/math, empty-vocabulary prior softening, exact T1 identity, class gates/fallback without fitting, inner/component isolation, component-weighted candidate selection, outer-label independence, bin boundaries, paired aggregation and physical-byte/closed-inventory failures. Original runtime modules are unchanged. Full `poe check` passed: format/lint/type checks, 166 Node tests (122 passes, 44 skips, zero failures) and 2,232 Python tests in 165.097 seconds (36 skips). Full log: `/tmp/opennoise-jamendo-genre-temperature-check.log`. Independent Luna source review found no material blockers.

An actual copied-input three-stage CLI run accepted the earlier honestly rebound baseline envelopes, with every original source/producer path and network access denied by hooks whose denial was explicitly probed. Census made zero fits; evaluation and replay each made their separate fixed 20 fits. Production made zero forbidden reads and zero network attempts; all three result payloads were byte-identical to the original run, while fresh custody envelope pins differed as expected. This is a new census/evaluation/replay from verified copied inputs, not a claim that old path-bound source seals work without their declared inputs. The local proof `/workspace/jamendo-genre-temperature-20261019/relocated-proof/proof.json` is SHA256 `df0a8e7777e49dba22c17bb682574e049fd6e672e3e110d3c66e2ec88ae9ab5f` (5,999 bytes), and includes exact commands and envelope pins. Checked aggregates retain its supporting counts and pins. Exact-head and merge/main CI status belongs to the associated pull request, avoiding an unknown future-hash claim here.

## Attribution and limits

Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra (2019), *The MTG-Jamendo Dataset for Automatic Music Tagging*; [Music Classification Annotations documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md), [pinned root README/license](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md). Source terms are **CC-BY-NC-SA-4.0**, noncommercial research only. Code, protocols and restrained attributed aggregates are committed; raw sources, inner models/logits and per-track results remain local. Annotation blinding/independence is not established. No audio/descriptors, deployment, serving, fresh cohort confirmation, causal diagnosis, retrieval usefulness or EveryNoise parity claim.
