# Frozen source recovery event calibration: development result

The one authorized offline experiment completed successfully on 2026-10-03.
The conditional rule improves raw multilabel source recovery over frequency,
but the frozen abstention rule emits suggestions for only 8.59% of development
queries. Its rate describes recovery of a masked **observed source positive**,
not individual membership confidence or musical relevance. All individual
membership and musical probability fields are null. No acceptance gate passed.

## Frozen inputs and producing code

- Source receipt:
  `5571f22953cfdc0c4003d855139bb4bbf1aadd97cbf2d3428495062eacaa0b6a`.
- Already selected training rule receipt:
  `399812f1e129272472d65312c873a150249fd5da99d606d903ef4d65a094c273`.
- Separately prepared, independently reviewed pre-fit receipt:
  `7a75bda3fe4f80776250e9ac651ac65a418feaf49cf154f4aaebdf12a1bf0c2b`.
- Frozen policy:
  `0e2404e4462adfd22bac3591a9aa3134c41b213a8d5dd43f4a11729b77f0204f`.
- Producing module:
  `50acd7dc3e5326ebeac8618a2aef0ecc51b215f6f322a793a8895fdd49c155aa`.
- Producing CLI:
  `15aa611cf778462bb5398e785129060d5dfc143fbedc21c71c86ef267be6f2ce`.

The [predeclared plan](WIKIDATA_SOURCE_RECOVERY_CALIBRATION_PLAN_20261003.md)
defines fixed bins, minimum support, lower-bound threshold, masks and role
routing. No statistical policy changed, no original outer labels decoded, and
no model refit followed calibration. The disjoint original-training roles are
3,611 fit artists, 1,189 calibration artists and 1,176 development-assessment
artists, totaling 5,976. The fixed fitted vocabulary has 178 source QIDs.

## Development results

Every raw metric uses the same 1,176 development queries and all 1,574 held
observed-positive labels. The target denominator retains 55 unseen labels and
104 labels outside the fitted vocabulary. Actual missing-source queries are
zero; this source-positive-selected cohort does not represent unlabelled
artists.

| Metric | Conditional rule | Frequency prior |
| --- | ---: | ---: |
| Raw micro recall at ten | 0.666455 | 0.520966 |
| Raw macro recall at ten | 0.735884 | 0.629308 |
| Raw mean nDCG at ten | 0.498098 | 0.391155 |
| Queries with emitted suggestions | 101 / 1,176 | 0 / 1,176 |
| Positive labels recovered after abstention | 118 / 1,574 | 0 / 1,574 |

Only the conditional score bin [.4, 1] meets the frozen calibration criterion:
90 event hits among 97 calibration artists, adjusted approximate Wilson lower
event rate 0.826366, and Beta(1,1)-smoothed source recovery event estimate
0.919192. In development it emits 101 queries, with 93 event hits (0.920792).
The unconditional frequency arm has no accepted bin. These intervals and rates
are descriptive evidence under the stated artist-exchangeability approximation,
not distribution-free risk guarantees.

Conditional abstentions comprise 708 queries with no observed seed, 103 with
unsupported seeds, 50 with insufficient calibration-bin support, and 214 whose
bin lower bound falls below the frozen threshold. Raw overlapping ranks and
support remain available for all of them. No hidden target values decide
whether suggestions are emitted.

Reported source-event Brier scores are 0.170467 on 315 conditional queries and
0.246513 on 365 prior queries. Those original denominators differ because of
minimum bin-support abstention. Independent replay separately matched the same
315 exact development UUIDs: conditional event Brier 0.170467 versus prior
0.249116, a difference of -0.078649. Each arm's observable event is whether its
own top ten recovers a held source positive; this comparison does not calibrate
individual memberships. The lower conditional bins also overestimate
development event rates; they remain rejected by the frozen emission policy.
The supplemental audit changed no policy and performed no producer refit.

## Retained artifacts and verification

The result pack is
`/dev/shm/opennoise-wikidata-source-recovery-calibration-20261003-v1`.
It retains all 2,365 calibration/development queries, full raw candidate ranks
and scores, training support, targets, masks, abstention decisions, exact role
UUIDs, complete code snapshots, fit/calibration seals, coupled reusable fit and
calibrator, report and closed receipt.

- Result receipt:
  `0d12f70648d242d44b989b7eb0c6cd092d47814b3fd0b3929f9bf2d7c9f34a49`.
- Report:
  `3c05cb798f9d25441aade17ef995271ef678f8e27ea0ccce8646d2b7c2f0f6d8`.
- All-query artifact:
  `2fc8008b2aa9b6f61b6bfd58e329bc274642e7a7ab7005d61d649e8722aacfb2`.
- Fitted model:
  `0b8dd7764ac6da061958d7333aa483ac6db05c15796497c6dc91bc72aaf8cc33`.
- Fixed-fit calibrator:
  `e5ddfbc69b0a4130fd38574b275e74a2f37cd0d451fdd0ca190b4078d4fc5cd3`.
- Sibling execution proof:
  `e1e1abd6315af12d269c84eac68e1e5ddc99b782b9a406a36b6441543e312a86`.
- Retained actual `/proc/76317/cmdline` bytes:
  `d0d457c366f15d14cb1b39bea6a471f3d7dba68ff56fd2d9130e4c3b68103336`.

The worker exited zero between 09:56:52.968626 and 09:56:55.243115 UTC.
Conservative observed actual Linux VmHWM was 29,630,464 bytes, below 35 MiB;
the final self-report was 29,532,160 bytes. Result size was 1,691,251 logical
and 1,728,512 allocated bytes, below five million. No new cgroup OOM events
occurred. Six expanded synthetic tests, Ruff and scoped type checks passed;
failed earlier checks remain preserved separately. Independent complete native
replay passed: 2,365 query rows, 4,730 rankings and all 839,700 scores, masks,
support counts, unknowns, bin decisions and metrics matched. Its report is
`/dev/shm/opennoise-source-recovery-calibration-independent-audit-20261003-v1.json`,
SHA256 `65aedc3c9624c9e3257269d40ac5e54e7a754f96a63f20c09d8b01761943e071`;
the independent process exited zero at actual Linux VmHWM 27,148,288 bytes,
without importing model implementations or decoding original outer JSON labels.
The finalized source, normalized dataset and model were preserved in an outside
Library ZIP: 8,238,577 bytes, SHA256
`55ed4bc7769f7f33e5c8c5e5e6ccce5de3a90425a46db40c605b72e9ef659626`.
Its 2,038-byte manifest has SHA256
`5b017c5b261ebbb691a03e104848f532edcc1e435b1415341dbec886ba65aa47`.
The upload reported matching storage byte counts and SHA256 values, and complete
UTF-8 manifest readback matched. This is storage confirmation; no independent
binary download is claimed. The result document in that ZIP predates this
storage-confirmation paragraph. No promotion or deployment occurred.

The score rule was previously selected using this original training cohort,
and original outer results were already inspected. This remains post-selection
development evidence. Genuine musical membership calibration still requires
independent source coverage and a freshly frozen external evaluation with
blinded, overlapping listener judgments and explicit unknown cases.
