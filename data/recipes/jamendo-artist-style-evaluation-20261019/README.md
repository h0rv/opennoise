# Jamendo artist style development evaluation

This protocol is frozen before any new style retrieval metrics. It asks whether the two unchanged artist-neighbor orders cohere with five preselected historical human style attributes: aggressive, electronic, party, relaxed and sad. It adds human-target coverage rather than another model or packaged prediction lookup.

Development uses original component folds 0–3 only: 558 metadata artists, 547 complete five-attribute targets and 446 with at least two eligible tracks per attribute. Count-only support gates were inspected before this freeze and pass. Original fold 4 (155 metadata artists; previously counted 152 complete/129 multi-track) is reserved for a separately frozen future style-model confirmation. The role mask must precede selected-style parsing and artist aggregation; this slice creates no fold-4 style profiles or scores.

This is a **label-held-out, transductive target reservation**. The fixed PR86 geometry already includes unlabeled fold-4 covariates in development gallery IDF. It remains unchanged and must reproduce all original matrix hashes and 713 full-top10 outcomes. Development galleries then exclude the query fold and fold 4 before filtering for complete human targets. Future style modeling requires a separate train-only feature context and frozen confirmation contract.

The endpoint is macro expected binary-vote agreement@10, with positive-positive and negative-negative terms and prevalence reported separately. Missing/invalid targets are never negatives; annotator independence is unverified. Results will be developmental historical human-style coherence, not listener relevance, recommendation utility, artist membership or a fresh cohort. The exact support, geometry, role, metric, bootstrap and failure rules are in [protocol.json](protocol.json).

No acquisitions, audio, supervised fits, UI or serving changes. Source, artist profiles, ranks and human ledgers remain local CC-BY-NC-SA-4.0 noncommercial research artifacts. Only code, this immutable protocol and attributed aggregates may be committed. Attribution: Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra (2019), The MTG-Jamendo Dataset for Automatic Music Tagging; Music Classification Annotations documentation. See the [pinned source license](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md) and [annotation documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md).

No style scores or implementation outcomes exist at this freeze. Reproduction commands, aggregate results and independent checks will be added after implementation without editing the frozen protocol.

## Reproduction and custody

From the repository root after `.venv/bin/poe sync`, use the exact retained raw files and a closed historical proof directory containing **only** `indices.json` and `rankings.json` from the PR86 result. The hashes required for these two files are frozen in the protocol. No historical genre targets/metrics are consumed: the reconstruction compares only feature matrices, original positive orders and all 713 full top-ten identities/reasons/scores. No old supervised model or saved predictions are inputs.

```bash
style_cache=.cache/jamendo-artist-style-reproduction
mkdir -p "$style_cache/historical"
cp /workspace/opennoise-jamendo-artist-coherence/.cache/jamendo-artist-coherence-20261019/results/indices.json "$style_cache/historical/"
cp /workspace/opennoise-jamendo-artist-coherence/.cache/jamendo-artist-coherence-20261019/results/rankings.json "$style_cache/historical/"
style_args=(
  --metadata /workspace/jamendo-human-genre-20261019/source/autotagging-test.tsv
  --human /workspace/jamendo-human-genre-20261019/source/music-classification-annotations-raw.tsv
  --protocol data/recipes/jamendo-artist-style-evaluation-20261019/protocol.json
  --protocol-sha256 dd0ee95db87b418d111d318312945c1a3c32c4511562a16ba43dd425b7fe7f59
  --historical "$style_cache/historical"
)
.venv/bin/python scripts/run_jamendo_artist_style.py census "${style_args[@]}" --output "$style_cache/census"
style_census_pin=$(.venv/bin/python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$style_cache/census/seal.json")
.venv/bin/python scripts/run_jamendo_artist_style.py run "${style_args[@]}" --census "$style_cache/census" --census-sha256 "$style_census_pin" --output "$style_cache/results"
style_result_pin=$(.venv/bin/python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$style_cache/results/receipt.json")
.venv/bin/python scripts/run_jamendo_artist_style.py replay "${style_args[@]}" --census "$style_cache/census" --census-sha256 "$style_census_pin" --output "$style_cache/results" --result-sha256 "$style_result_pin"
```

The absolute paths above are examples from the **current executor**, not repository inputs or a promise of future availability. Raw sources and historical proof files are untracked NC-SA research data. If missing, regenerate the two exact historical files using the [PR86 recipe](../jamendo-artist-coherence-20261019/README.md) from approved pinned source bytes, or report the dependency blocked; do not invent custody or assume these paths remain readable. Relocated copies with the same physical pins are accepted.

Census/run outputs must be fresh. Existing stage/output overlap, extra files, runtime/source/pin mismatches and changed physical bytes fail closed. Each CLI invocation has 120-second CPU/wall, 1 GB address-space and single-thread numerical bounds. The **15 MB combined census/result cap includes both custody envelopes**, and applies to replay as well as publication. Census has zero index builds; each run or replay reconstructs five frozen unsupervised IDF banks, with zero supervised fits. Separate replay invocations repeat computation for verification; they are not new candidate searches.

The final production stages are local `.cache/jamendo-artist-style-evaluation-20261019/census-final-reviewed` and `results-final`. The earlier count seals and initial result remain preserved. Before the first new metric call, the production census was externally sealed; the final reporting/privacy-bound census preserves exactly the same support. Per-track serialized selected-style evidence is limited to reason and vote count; positive/negative vote counts are retained only as artist aggregates. Reserved track/artist rows have native identity/status and no style probability or attribute container.

## Observed development result

The source-only census skipped all **2,716 reserved tracks before style extraction**. Development has 8,849 tracks: each selected attribute has 8,095 eligible three-vote tracks and 754 wrong-count tracks, with zero missing or unrecognized tokens. The same 547/558 development artists are complete across all five attributes; 446 have at least two eligible tracks per attribute. Each of the four galleries has 405–416 complete artists, at least 306 positive-evidence and 323 negative-evidence artists for every attribute. All planned gates passed. All 713 original outcomes and 20 normalized matrix hashes were reproduced unchanged; the new output retains 558 development and 155 reserved statuses.

| Primary 547-query agreement@10 | Positive-positive | Negative-negative | Total |
|---|---:|---:|---:|
| Genre only | 0.167723 | 0.477314 | 0.645037 |
| Genre + instrument | 0.166358 | 0.475240 | 0.641597 |
| Analytic random, same complete gallery | 0.133329 | 0.443478 | 0.576807 |

The frozen candidate-minus-genre primary total difference is **−0.003439**, paired fixed-gallery interval **[−0.005170, −0.001590]**. Positive and negative contributions both decrease (−0.001365 and −0.002074). The 446-query secondary difference is also negative: **−0.003379 [−0.005282, −0.001460]**. Genre-minus-random is 0.068229 [0.063249, 0.072865]; candidate-minus-random is 0.064790 [0.059922, 0.069685]. These are descriptive intervals on the reused historical cohort; no representation was changed after observing them.

All five attribute results remain visible rather than selecting the favorable attribute:

| Attribute | Genre only | Genre + instrument | Random |
|---|---:|---:|---:|
| aggressive | 0.684640 | 0.676559 | 0.630288 |
| electronic | 0.654359 | 0.653455 | 0.506439 |
| party | 0.702326 | 0.695149 | 0.642722 |
| relaxed | 0.587324 | 0.584652 | 0.524833 |
| sad | 0.596534 | 0.598172 | 0.579754 |

Primary query artist-equal positive prevalences are 0.244671 / 0.559636 / 0.232662 / 0.387507 / 0.300077, macro 0.344911; explicit negative complements and all fold-gallery denominators are in [results.json](results.json). Gallery prevalence is artist-equal within a fold and then query-weighted across fold galleries, **not a unique-gallery pooled prevalence**. Pooled eligible-track counts are support information, never metric weights. Large negative-negative contributions demonstrate why total agreement alone cannot establish positive style coherence.

For primary queries, role-filtered development top-ten coverage is 5,377 judged / 90 unjudged / 3 missing slots for genre, versus 5,394 / 73 / 3 for the candidate. This is annotation availability, not quality. The old full-catalog top tens contain 1,506 and 1,487 **reserved** neighbor slots respectively; they remain distinct from ordinary unjudged slots and are never graded with fold-4 targets. Conditional observed agreement is reported only where a judged neighbor exists, with no unjudged-as-negative substitution.

## Verification and limitations

Independent raw-source verification matched all 547 development target profiles, 558 development plus 155 reserved outcomes, all 22,308 selected role-filtered full/condensed edges and raw cosines, the old 20 matrix hashes, coverage, analytic random controls, all attribute/macro positive/negative/total metrics, robust/fold/instrument strata, prevalence/support and paired bootstrap intervals. There were 4,428 compared numeric arrays; maximum error was below 1.7e−15. The independently run copied-input CLI census/run/replay used active denial probes for original source/protocol/cache/oracle/old-model trees, network and supervised fit calls. Production had zero forbidden operations; index-build counts were 0/5/5, and all three result payloads plus both custody envelopes reproduced byte-for-byte. Exact final audit/proof hashes are recorded in [results.json](results.json).

The final local run took 2.651 seconds with Linux child peak RSS 175,840 KiB; exact replay took 2.928 seconds / 187,832 KiB. These single-run measurements are engineering evidence, not universal latency claims. No acquisitions or new external cost occurred. The source rights and attribution above apply to all derived local profiles, rankings and target artifacts.

This result supports retaining the meaningful genre baseline rather than promoting the added-instrument arm. It tests an expected independent-draw human-vote agreement functional; independence of annotators/draws is unverified, and negative agreement is not positive similarity. Historical annotation sampling, shared collection process, native-identity/audio-duplicate uncertainty and coarse attribute scope limit generalization. Fold 4 remains **style-label-held-out with known counts and transductive metadata exposure**. A future style model needs its own frozen training-only feature context and candidate before reserved-style evaluation. No fold-4 style probability or score was created here.

Final independent comparison SHA256 `16c938a041aeef02cb3f7f370fcf6403a59a008421f7615165df8537c8287e00`; relocated final proof `5ef655080714620b658cfee97e7288546b7902592ece268432f55a5ced1cc798`. Final census seal `1109fb14059d1980c041dfd5ede57d096c7cfdd6de515863d878e1ced61c7124`; result receipt `a7d4cefdc4ae6cfa214e0f86f450c4e9360d1eeaefa3218f715b91d0cfbf2665`. Combined final census/result size is **7,562,851 bytes**. Luna reviewed final module `3f352293…` / CLI `24a6583a…` without material blockers and reran all fourteen focused tests successfully.
