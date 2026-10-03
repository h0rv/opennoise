# Training-only source recovery event calibration, version 1

This separately named experiment calibrates the event
`top10_recovery_of_masked_observed_source_positive`. The event rate describes
recovery of at least one withheld **observed Wikidata source positive**. It is
not an individual genre membership probability, a musical probability, or a
claim that an unmatched label is false. Raw overlapping candidate ranks and
training support remain separately available.

The source cohort has 9,992 original UUIDs, including 5,976 original training
artists. This experiment decodes labels from those original training artists
only. The source-positive-selected cohort has no representative unlabelled
artist sample. The approximately 2.99 million global source artists remain an
excluded coverage census; unknown source memberships stay unknown. Earlier
outer calibration and confirmation results were inspected and are preserved.
They cannot become fresh confirmation of this experiment. The score rule was
also selected previously on these original training artists; development
assessment here is conditional on that historical selection, not unbiased
assessment of the original rule-selection procedure.

## Frozen experiment

- Authenticate source receipt
  `5571f22953cfdc0c4003d855139bb4bbf1aadd97cbf2d3428495062eacaa0b6a`
  and selection receipt
  `399812f1e129272472d65312c873a150249fd5da99d606d903ef4d65a094c273`.
  Re-derive the original exact-UUID split and mask from authenticated sealed
  source constants and the immutable training implementation. Route source
  bytes before label decoding; decode no original outer labels.
- Freeze policy, input/selection hashes and complete executable source bytes
  using the separate CLI `prepare` stage before any fit-role labels decode.
  Its exclusive directory includes a closed externally pinned receipt and
  flags that no fitting or source label decoding occurred. The CLI `run` stage
  requires that exact preparation directory and receipt pin, authenticates its
  complete code/policy/input contract, and copies its bytes into a new exclusive
  result directory before admitting fit labels. Assign original training UUIDs using
  SHA256(`opennoise-source-recovery-disjoint-roles-20261003-v1:<UUID>`) modulo
  five: buckets 0–2 fit, bucket 3 calibrate, bucket 4 development-assess.
- Within each non-fit artist, hash-sort all observed source-positive QIDs using
  `opennoise-source-recovery-multilabel-mask-20261003-v1:<UUID>:<QID>`.
  Even positions are held positives; odd positions are observed seeds. This
  keeps multilabel overlap and leaves singleton rows as explicit no-seed
  queries. Empty observations remain unknown queries.
- Fit source vocabulary and counts on fit-role labels only (minimum support
  five exact artists). Seal the complete fixed fitted model before either
  later role decodes. The two arms are the already selected alpha-one,
  mean-supported-seed conditional score and unconditional frequency prior.
  Both arms receive identical queries, targets and denominator rules.
- Use the same fixed six intervals for each arm's highest eligible score:
  [0,.02), [.02,.05), [.05,.1), [.1,.2), [.2,.4), [.4,1]. Infer recovery-event
  rates from calibration-role artists only. Use Beta(1,1) smoothing for the
  displayed empirical event estimate. Select an accepted bin only if it has
  at least 50 unique calibration artists and its adjusted Wilson lower event
  rate is at least .80. The one-sided normal critical value 2.638257273476751
  adjusts .05 across twelve fixed arm/bin checks. This approximate interval
  is descriptive evidence under an exchangeable-artist approximation; it
  does not provide a distribution-free risk guarantee.
- Missing source observation, no observed seed, any unsupported observed
  seed, empty candidate vocabulary, insufficient calibration evidence and a
  lower event rate below the fixed threshold cause explicit abstention.
  Requested unseen or outside-vocabulary QIDs have explicit unknown coverage
  states. Held target labels never decide whether a query emits suggestions.
  OOV and unseen targets remain in development recovery denominators.
- Seal the calibrator and its exact model/policy hashes before development
  labels decode. Assess once with no tuning, threshold changes or refit.
  The reusable inference artifact remains coupled to this original fit;
  fitting on all original training artists would invalidate its calibration.

## Evidence retained

Retain every calibration/development query, target set, raw candidate rank and
score, candidate training support, event estimate and abstention reason. Keep
the exact disjoint role UUID lists, policy, fitted counts, seals, source/selection
provenance, executable dependency bytes, report and closed hash inventory.
Policy and seal files flush and fsync both file bytes and directory entries
before subsequent role labels decode. Each compressed block is rejected before
it can exceed the five-million-byte artifact cap, and metadata writes obey the
same cap. Actual cumulative Linux VmHWM is checked after fitting, periodically
through query processing, and at completion against the existing 35 MiB bound.
The reusable loader also requires exact current inference policy and executable
dependency pins, so an edited inference implementation cannot silently reuse
an earlier calibrator. Output creation rejects source/selection subtrees and
symlink ancestors. Checks and the actual
experiment require separate serial resource grants; no run is authorized by
this document.

Report raw and abstained multilabel micro/macro recall at 1/5/10, nDCG at ten,
observed-positive recovery yield, complete positive denominators, unknown
targets, query emission coverage, event Brier score and event reliability bins
against the frequency arm. Unmatched candidate memberships remain unknown;
these are source retrieval metrics. Missing targets never become Brier
observations. Cold and unsupported queries remain in unconditional recovery
denominators and have no event-rate assertion.

## Missing membership evidence

Genuine overlapping musical-membership calibration still needs a separately
frozen external artist sample covering both source-observed and source-unknown
artists, independent source coverage measurements, and blinded listener
judgments for multiple plausible styles per artist. Listener disagreements,
insufficient familiarity and unassessed pairs must remain explicit unknowns.
Only that evidence can support per-label musical calibration or an acceptance
decision. This development experiment supplies a reproducible source-completion
abstention artifact while keeping that missing evidence visible.

Implementation: `src/opennoise/ml/wikidata_source_recovery_calibration.py`.
CLI: `scripts/calibrate_wikidata_source_recovery.py`.
Synthetic verification: `tests/test_wikidata_source_recovery_calibration.py`.
