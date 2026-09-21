# Phase 3 v3 terminal historical evaluation

## Result

One local terminal evaluation compared the already-fixed v3 candidate with the
retained `historical-signal-v1` reference. It did not construct, modify, tune,
certify, or publish the candidate. The historical reference was opened only
after the adapter verified the candidate model, v3 projection receipt, and
read-only serving database.

The report is an observed-positive coverage measurement, not a release-quality,
precision, parity, or negative-label result. Historical absence remains an
abstention.

## Exact bindings

| Input | SHA-256 | Bytes |
| --- | --- | ---: |
| v3 model | `c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba` | 30,031,286 |
| v3 projection receipt | `3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af` | 3,706 |
| v3 serving database | `1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9` | 184,463,360 |
| held-out historical signal | `9f77b3aff73f8a2ca0d201e4e7ad3931f7778815b9788917df52c871cd984d82` | 23,804,446 |

The pinned held-out reference is
`.cache/historical-signal-hierarchy/historical-signal-hierarchy-v1.json`.

The terminal report is at
`/tmp/phase3-historical-v3-terminal-evaluation-20260921-r2/report.json`; its
file SHA-256 is `0ac44068f8122afcea8f8c13bfcd83d94ad4cd60d2da7cdddae5250e67e49572`,
its byte count is 2,784, and its logical output SHA-256 is
`6cc921dac355904cb8f0e77097ca93f68005b876be79e0a7d312e86fc58156cc`.

## Positive-only accounting

Exact IDs did not overlap. The adapter accepted only one-to-one, Unicode-NFKC,
case-folded exact name matches. Duplicated candidate or historical normalized
names were abstained rather than converted into a crosswalk.

| Axis | Candidate positives | Mapped positives | Historical observed positives | Overlap | Historical observed-positive coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Membership seed presence | 468 | 257 | 6,289 | 257 | 0.04086500238511687 |
| Canonical undirected neighborhoods | 11,886 | 4,206 | 37,517 | 532 | 0.014180238291974305 |

The name accounting is 603 candidate genres, 6,291 historical genres, 288
one-to-one exact-name matches, 315 candidate-name abstentions (including the
duplicate-name cases), and 6,003 historical abstentions. Candidate precision
is unavailable and is recorded as `null`; no missing historical item is a
negative.

## Boundary checks

The adapter verifies model bytes and logical hash, receipt bytes and logical
hash, serving-database bytes, schema, integrity, foreign keys, and presence of
the bound public-model output. It rejects historical reference tokens anywhere
in the serialized v3 model. The receipt's v3 source-artifact attestation and
passing public-model gate remain the construction-custody evidence; this
terminal adapter does not make a release gate decision.

The adapter now pins the exact v3 model, v3 receipt, serving database, release
manifest, replay candidate, detached candidate binding, source-artifact set,
and historical-signal file SHA-256 recorded above. It rejects a self-consistent
substitution before evaluating it. Optional report writing is limited to two
distinct, fresh, non-symlinked paths under the local temporary or project cache
directory, and uses no-replace publication; candidate, database, static, and
release paths cannot be overwritten.

Focused tests cover pinned-custody substitutions, tampered candidate bytes,
tampered report receipts, output-path guards, historical-token leakage,
ambiguous historical labels, duplicated candidate labels, and the no-precision
observed-positive boundary. Ruff and Ty both passed for the adapter and CLI.
