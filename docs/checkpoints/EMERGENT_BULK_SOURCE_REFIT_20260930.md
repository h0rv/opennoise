# Frozen adaptive model: bulk-source refit

This experiment refits the existing adaptive lexical community method after
verified bulk MusicBrainz artist-tag evidence becomes available for the complete
primary cohort. It uses no artist names for training, historical memberships or
coordinates, or audio. Statistical settings and all fitter logic remain fixed.
The new source does not by itself establish Every Noise parity.

## Resource admission correction

The first bulk preflight, primary-v3 feature SHA-256
`41fae3b043d9de3e885fde75ca33cd4dded6b7d6a2495ea506a596b407e6895c`,
contains 1,012,661 feature observations for 198,409 artists. The frozen model's
filter leaves 35,267 namespace/value identities. The original loader checks its
30,000-identity resource limit *before* applying the existing two-artist minimum
support rule, although only 9,951 facets / 7,969 canonical musical values qualify
for fitting. Maximum artist feature degree is 255, below the unchanged 512 limit.
No source features were silently truncated or removed to get past the guard.

The sole authorized code change is `MAX_FEATURES: 30_000 → 50_000` in the loader.
Every function and class AST across the base, graph, lexical, and adaptive model
modules remains unchanged (34 functions, three classes). Default settings are
identical. Loading the old valid primary-v2 source before and after the change
produces byte-identical CSR buffers, arrays, identities, profiles, counters, and
source hash. This changes input resource admission, not fitting or ranking.

The old base module SHA is
`95123d96aadc23af326081d916161effab8501d99d6e32ec152a8434579550d0`;
the new SHA is
`78de0ec6f3eb848746a05a219af95dc8addfb1489d1f43b4125118d106caba37`.
The equivalence receipt is
`.cache/emergent-topics/resource-bound-extension-20260930-v1/report.json`, identity
`37b9562169cced38a154624399a765b98af55a6212ef919402d686cce74f68fc`.
It preserves old/new source snapshots and component fingerprints. All prior
model artifacts and their receipts remain immutable and retain their original
code bindings. Twenty-four model/projection tests, lint, and types pass.

The new fit waited for corrected primary-v4 source features. It does not use the
superseded primary-v3 preflight as its final input. The research builder at
`.cache/emergent-topics/build_adaptive_bulk.py` records the resource-policy
revision, equivalence identity, and its own source hash in the new model receipt.
The target is a single fit at
`.cache/emergent-topics/adaptive-lexical-bulk-20260930-v1`.

## Annotation quality boundaries

Native tags include role, ensemble, and geographic compounds as well as styles.
The initial source-only review queue identifies 202 supported values matching
possible role/ensemble language after excluding values already observed in
native genre facets. Examples include film composer, nationalities followed by
conductor, and named orchestra types. This is a review queue, not an additional
training filter or an automatic rejection list; some ensemble terms can convey
useful musical context. The final fitted descriptors will be audited separately.
No threshold or statistical-method changes are selected from those examples.

## Final source and completed fit

The final source is `.cache/microgenre-features-primary-v4/artist-features.jsonl`,
SHA-256 `2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`.
Its receipt SHA is
`281a0cdcf87498bad50f6e2fe9b145cf0e010c1ed7c3b48a832ae0b8a094f6d7`.
It contains 1,010,929 observations for the same 198,409 primary artists. The
actual final loader retains 9,946 facets, 984,816 observations, and 59,668 distinct
musical profiles. There are 84,988 singleton-profile artists and no empty profiles.
Maximum qualified row degree is 247. These final figures supersede the initial
primary-v3 preflight counts. The pre-fit receipt is
`.cache/emergent-topics/bulk-source-final-preflight-20260930-v1.json`, identity
`e402d1509f9e46decc52009aa323c7a1ea0a190874d386feb96899239a1e060e`.

The single completed fit has model identity
`8bc5488c8861aaa89e88ea05513b9a9b6beb94b0ba63969ddb04d70d861d9556`;
report bytes SHA-256 is
`fddf372eb89d4282ff77a6d87981236868e0bc7f872afbb674b27db70c2ae782`.
Bound output files total 220,197,903 bytes. The report explicitly records zero
native membership additions, no historical or name-based training, the resource
extension proof, the research builder, and all model code bindings.

| Measure | Bulk fit |
| --- | ---: |
| Broad / sub / micro nodes | 128 / 157 / 1,048 |
| Artists assigned broad / sub / micro | 198,409 / 86,453 / 98,531 |
| Broad nodes passing construction gates | 74 |
| Broad nodes stopped by the 128-node cap | 54 |
| Core artists in capped, unsupported parents | 98,277 |
| Overlapping memberships in those parents | 183,672 |
| Source-core cosine broad / sub / micro | 0.598 / 0.737 / 0.791 |

Micro assignment coverage is 15,689 artists higher than the preceding clean
product snapshot. That is a product-snapshot comparison, not the controlled
paired-source evaluation: source filtering policy and the feature space differ.
Similarly, source cosine values are not directly comparable between sparse old
profiles and the richer new profiles. The independent paired evaluation uses
an old source rebuilt under the same policy, with identical target pairs and
fixed model settings.

The broad safety cap is now binding. Almost half the source artist cores fall
under a parent that did not meet the declared coherence gates before the cap.
These parents retain `abstained_coarse_budget_exhausted`; they must not be shown
as having passed the construction evidence checks. The increase in artist
coverage does not establish an overall quality improvement. This default-cap
artifact remains unchanged. A separately declared process-local safety-budget
experiment is recorded in `EMERGENT_EXPANDED_COARSE_BUDGET_20260930.md`.

## Named benchmark and remaining annotation queue

All ten exact-ID electronic benchmark artists retain micro memberships. Aphex
Twin, Autechre, and Boards of Canada share an inferred warp / idm /
moogsploitation candidate. Four Tet has tech house / progressive house / house,
deep tech / tech house / house, and breaks / breakbeat / electronica candidates.
Aphex Twin's branch skips the sub level in this fit; Four Tet has all three
levels. Neither these descriptors nor membership affinities establish listening
relevance or Every Noise correspondence. Names were joined only after fitting.

The bound post-fit audit is
`.cache/emergent-topics/bulk-adaptive-postfit-audit-20260930-v1.json`, identity
`a2cc49cf24e97a8b390b9d0446a6ca140614a259d697cf0a77ec93b9fe094d0f`.
The current metadata filter matches zero published tag-descriptor occurrences,
but the broader review queue contains 45 occurrences from 30 possible role or
ensemble values, including nationality-plus-composer/conductor terms,
bass-baritone, and orchestra types. Publisher-like terms such as warp also need
entity-type review before treating them as musical styles. The separate queue
is `.cache/emergent-topics/bulk-descriptor-quality-review-queue-v1.json`.
It is a post-fit review aid, not an automatic rejection list, additional training
filter, or evidence that every queued term is musically useless. The later
safety-budget experiment retains these same input features and quality filters.

## Controlled source-increment evaluation

The independent paired comparison retains the on-disk 128 coarse-node default.
It rebuilds both sources under the same filtering policy and evaluates the same
110,027 held-out canonical positive artist/value pairs. The receipt is
`.cache/paired-bulk-source-increment-20260930-v1/report.json`, identity
`e62b92d6c6324b7256d79a1a274c5a0ee20b3da35170a57f1e342a7ba0c8bd33`.

| Recall@10 | Same-policy old source | Bulk-augmented source |
| --- | ---: | ---: |
| Adaptive communities, all 110,027 positives | 30.249% | 36.205% |
| Adaptive communities, 31,836 tag-only positives | 14.584% | 26.954% |

The augmented proper-genre conditional baseline remains higher at 50.074%
overall and 28.103% on tag-only positives. The additional source evidence helps
the fixed adaptive method, including changes to source-facet weights, but this
does not establish a baseline victory, listening quality, or genre truth.
These results do not evaluate the separate expanded-budget construction fit.
