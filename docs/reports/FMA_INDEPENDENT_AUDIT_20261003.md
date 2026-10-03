# Independent FMA source, leakage and acoustic model audit

The retained native FMA experiment passes independent source, grouping,
parameter, ranking and metric replay. It establishes a bounded acoustic signal
for recovering FMA's observed track annotations. It does not establish artist
genre facts, calibrated genre probabilities, independent musical relevance,
EveryNoise parity, or a case for default product promotion.

The audit was declared before results in
[the audit declaration](fma_independent_audit_declaration_20261002.json)
(commit `8abe551`). The source-only album probe and revised split acceptance
were sealed in `56aaa69`, also before fitting. The model author sealed the
component declaration in `416f1c2` and implementation/addendum in `02bf447`;
the single fit and saved replay evidence are in `90424ff`. This audit neither
changes the frozen model nor selects thresholds using its results.

## Native custody and source quality

The independent replay read every retained raw metadata CSV byte and compared
every projected entity row: 109,727 tracks, 16,916 artists and 164 genre records.
Seven metadata range hashes, decompressed lengths, native ZIP CRCs and observed
SHA256 hashes agree. The independent feature replay read the complete
951,117,185-byte, 518-column CSV, checked CRC32 `e8eb7a19` and SHA256
`a035d04941e15fc3240aadd6880c519471d218329bbfe0e82c17553ba50e9e16`,
and compared all 4,689,256 selected float32 cells and native track IDs.
The complete remote ZIP's published archive hash was not verified.

The final 44-channel feature projection has 106,574 rows, all inside the raw
metadata population. Those row counts must remain distinct: the raw API
snapshot is not the published cleaned 161-label FMA benchmark. Of 164 raw
taxonomy IDs, 162 occur on tracks, yielding 260,586 positive track/genre pairs.
There are 2,609 missing/unparseable target lists and no observed empty lists.
The saved targets preserve missing lists as null.

| Source coverage | Tracks | Observed positive pairs |
| --- | ---: | ---: |
| Raw metadata | 109,727 | 260,586 |
| Feature intersection | 106,574 | 253,869 |
| Missing features | 3,153 | 6,717 |
| Unresolved primary artist | 974 | 2,075 |
| Known primary artist, missing features | 3,035 | 6,434 |

The unresolved artist rows comprise 250 native IDs absent from the artist
master. Exact native IDs remain distinct; 38 normalized names shared by
different IDs are diagnostics only. Neither source names nor feature
duplicates create a MusicBrainz bridge or factual artist membership.

Native receipts and the retained official README identify metadata licensing
as CC-BY-4.0 and describe features computed with Librosa. Attribution is
Michaël Defferrard, Kirell Benzi, Pierre Vandergheynst and Xavier Bresson,
*FMA: A Dataset For Music Analysis*, ISMIR 2017,
<https://github.com/mdeff/fma>. The README hash is
`54148723ff06c19374c368499f1e97afb3d10f58646d20a221e4d9c7ab63fac9`.
EchoNest, pickle and audio payloads are excluded. Metadata licensing does not
grant the separately declared audio rights. No historical genre reference or
NC artist-tag input participates in this experiment.

Full source evidence is recorded in
[metadata replay](fma_native_source_independent_audit_20261002.json) and
[feature replay](fma_acoustic_source_independent_audit_20261002.json).
The feature replay audited projection-v2. Final projection-v3 retains exactly
the same numeric, identity and duplicate-group bytes, adding explicit native
`zcr`/conceptual `zero_crossing_rate` alias evidence. The final model audit
checks the v3 receipt and all its file hashes. The initial header failure and
earlier projections remain preserved; the alias correction preceded fitting.

## Leakage prevention and remaining limits

The pre-fit native probe found 1,126 multi-primary-artist albums, spanning
17,487 tracks. The originally proposed artist-only folds would have split
776 of those albums, spanning 14,704 tracks, across folds. Before fitting,
the author replaced that partition with connected native artist, known album
and exact full-native-feature-cell duplicate components. The full 518-column
duplicate test finds 1,689 groups containing 3,800 tracks; it does not merely
compare the selected 44 channels.

An independent bipartite traversal reproduces all 7,410 components and all
109,727 saved track folds. Unresolved positive native artist IDs remain graph
bridges, even though those tracks are excluded from fit/evaluation. No null
artist receives a fabricated identity. Component minimum native artist ID is
hashed with the frozen split revision into 80/10/10 buckets. The largest
component contains 39,750 tracks, producing realized known-artist train,
validation and test counts of 94,953 / 7,332 / 6,468
(87.31% / 6.74% / 5.95%); there was no balance reshuffling.

This proves separation for supplied native primary-artist IDs, known albums
and exact feature duplicates. It cannot establish complete performer or
recording independence: 1,041 album IDs are missing/invalid; multi-performer
credits, nonexact recording duplicates and artist aliases remain unresolved.
Duplicated observations within training still count as source track support;
five positives do not necessarily mean five independent recordings/artists.

## Frozen fit and source-positive evaluation

Independent direct conditional-subset calculations reproduce normalization
from 92,270 finite training rows and all 164 label parameter rows. All 44
dimensions are active; 158 labels satisfy the fixed five-feature-positive
support gate. Gaussian variance shrinkage is 50% toward training global
variance, minimum variance 0.1, and the query support gate is maximum absolute
standardized offset 12. Priors and comparator vocabulary use all known-artist
raw training metadata, including tracks without features. Unsupported acoustic
labels receive no ranking credit. Validation is diagnostic and did not select
the scorer, split or thresholds.

Training-only popularity and fixed native-ID order are the prespecified
no-acoustic controls. There was no permuted-feature arm; the evidence therefore
does not isolate every source confound or establish causal musical content.
No source annotation absence becomes a verified negative. Precision and
probability calibration are unavailable under this positive-only contract.

Independent quadratic/linear scoring reproduces every saved full ranking and
abstention for 13,800 held queries. Plain-counter evaluation reproduces all
six fold/arm metric sets, including each label's support/hits and rare/cold/
unseen denominators. All seven model artifacts and every tracked replay-pack
file are byte-bound; the 13,800 pack target rows exactly match native metadata.
The audit evidence is
[model replay](fma_acoustic_model_independent_audit_20261003.json).

| Fold / arm | Recall@5 | Recall@10 | Macro Recall@10 | First-positive MRR |
| --- | ---: | ---: | ---: | ---: |
| Validation / acoustic | 24.41% | 37.05% | 25.33% | 0.30261 |
| Validation / popularity | 23.64% | 36.33% | 7.19% | 0.32789 |
| Validation / constant | 7.47% | 10.22% | 6.47% | 0.13431 |
| Test / acoustic | 26.50% | 39.59% | 27.40% | 0.31296 |
| Test / popularity | 25.82% | 36.63% | 7.35% | 0.31911 |
| Test / constant | 5.40% | 8.12% | 7.35% | 0.11533 |

Validation retains 7,332 queries, 7,253 labeled queries and 16,668 positives;
test retains 6,468 queries, 6,369 labeled queries and 14,402 positives.
The 79/99 unlabeled queries remain query counts, with no invented relevance
labels or positives. Acoustic abstains on 170 missing-feature and three
out-of-support validation queries; test has 182 missing-feature and one
out-of-support query. Test accepted-query coverage is 6,285/6,468 (97.17%).
Every observed positive on an abstained eligible query stays in recall's
denominator. The 974 unresolved-artist rows and their 2,075 positives are
explicitly outside the eligible fit/evaluation population.

Test rare labels (training support at most 100) recover 13/263 positives at
10 (4.94%); validation recovers 17/366 (4.64%). All 14 cold test positives have
seen training support below five and recover zero. Neither held fold contains
training-unseen positives: synthetic regressions verify unseen accounting,
but this native split supplies no empirical evidence of unseen-label recovery.
Missing/unresolved artists are not recovered. Higher aggregate recall alongside
lower MRR and weak rare/cold recovery does not justify default promotion.

## Stage boundary and replay

The current portable partial foundation remains a separate CC0 native-evidence
build. FMA's attributed native IDs have no exact bridge into its artist cohort;
the portable builder imports neither this scorer nor the separate local NC
source-reobservation calibration. The small portable acoustic example has a
projection-only custody claim. This audit authorizes no UI or default promotion.

The tracked saved pack supports offline ranking/metric replay, not raw-source
replay by itself. Native audit replay requires the retained acquisition files.
The following command performs independent model/target replay without fitting
again; use a fresh output path. Run from the repository with Python 3.13 and
the existing environment. Source paths below are read-only.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src \
  /workspace/opennoise/.venv/bin/python -m scripts.audit_fma_acoustic_model \
  --metadata /workspace/opennoise-next-20261002/listening/.cache/fma-native-metadata-20261002-v1/projection-v2 \
  --features /workspace/opennoise-next-20261002/review/.cache/fma-native-features-20261002-v1/projection-v3 \
  --model /workspace/opennoise-next-20261002/review/.cache/fma-acoustic-baseline-20261003-v1 \
  --saved-pack /workspace/opennoise-next-20261002/review/data/examples/fma-acoustic-baseline \
  --output /dev/shm/fma-independent-model-audit.json
```

Five focused independent-auditor tests cover native parsing, CRC rejection,
unresolved album/duplicate bridges, and missing/unseen/cold denominators.
The author separately reports 11 model/saved-pack tests and seven native
metadata adapter tests, confirmed by root. No dependencies were installed,
source artifacts changed, second fit executed or public output promoted.
