# Authority-aware fine-style candidate: fresh nested result, 2026-09-30

The candidate **does not beat the existing artist feature enrichment model** on
the prespecified rare artist-tag task. Keep it as a reproducible local research
hypothesis. Do not replace the current model, refit it for product use, or export
its proposals into the explorer on the strength of this result.

The earlier paired source-increment experiment improved enrichment overall
Recall@10 from 39.86% to 47.06% and tag-only recall from 19.92% to 35.03%, while
the proper-genre-conditioned baseline still reached 50.07% overall. Those are
different folds and target sets. The fresh experiment below tests a narrower
authority/anchor heuristic against strong baselines on the same new targets;
it does not revise those earlier results.

## Frozen design

Input is `.cache/microgenre-features-primary-v4/artist-features.jsonl`, containing
198,409 artists. Source SHA-256 is
`2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`.
This corpus had already been explored. New deterministic outer and inner salts
were declared before partitioning or fitting:

- `authority-aware-fine-style-outer-v1-fixed-20260930`
- `authority-aware-fine-style-inner-v1-fixed-20260930`

The shared partitioner holds out whole normalized artist-value components and
globally connected release-group components. It removes every duplicate source
facet of a held value. The inner partition uses only the outer training file.
Vocabulary, frequencies, thresholds, anchors, and associations are fitted from
the corresponding training partition. This tests missing-value reconstruction
for partially observed artists, not generalization to entirely unseen artists
or independent source gold. Other values from the same artist response can
remain observed.

Targets must be artist tags with at least five training artists and at most
0.5% training artist share. Values matching the alphanumeric signature of a
training proper genre are excluded. A target needs a training proper-genre
anchor with coverage and lift gates. This anchor is a source association, not
a taxonomy parent. Release-only values cannot enter the target pool.

Proper-genre cues have authority 1.0, artist-tag cues 0.8, and both release
genre and release tag cues 0.2. Duplicate facets share one canonical cue with
the maximum authority. Ranking sums only the strongest one or two canonical
cues, excludes known values and their punctuation/spacing duplicates, and
abstains without artist-primary evidence. Sparse associations use source-degree
correction, smoothed lift, raw joint-support confidence, cue specificity, and
at most 64 targets per cue. Scores are uncalibrated.

All three candidates were frozen before this fresh run:

| Candidate | Smoothing | Target support | Joint support | Anchor coverage | Association lift | Strongest cues |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Default | 16 | 5 | 3 | 0.50 | 2.0 | 2 |
| Moderate | 24 | 5 | 4 | 0.55 | 2.5 | 2 |
| Strong | 32 | 10 | 5 | 0.60 | 3.0 | 1 |

All retain anchor lift 2, conditional fraction 0.05, and maximum share 0.005.
Inner rare artist-tag-only Recall@10 selects the maximum, with candidate order
breaking ties. On 19,420 inner rare positives, default scored 7.5901%
(1,474 hits), moderate 5.8136% (1,129), and strong 3.5376% (687). Default was
selected and saved before any outer scoring. There was no outer reselection.

## One outer result

Outer evaluation retains all 110,431 held artist-value positives. The rare
artist-tag-only stratum has 24,566 positives: original artist-tag source roles,
outside source proper-genre duplicate signatures, with training tag support
at most 0.5% of artists, including zero. Source-role stratification uses the
pre-partition source only after rankings are frozen; model eligibility uses
training evidence only. This distinction is deliberate.

| Scorer | Overall Recall@10 | Source artist-tag-only Recall@10 | Rare artist-tag-only hits | Rare Recall@10 | Rare MRR per positive |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fine-style candidate | 3.16% | 11.06% | 3,485 | 14.19% | 0.11366 |
| Existing enrichment, smoothing 4 | 47.28% | 35.72% | 5,573 | 22.69% | 0.12200 |
| Proper-genre conditioned | 49.88% | 28.35% | 3,235 | 13.17% | 0.06462 |
| Global frequency | 22.78% | 8.63% | 0 | 0.00% | 0.00000 |

The candidate narrowly beats the conditioned baseline on rare recall and MRR,
but loses both measures to enrichment. It predicts no proper-genre positives
by design. Its poor overall recall cannot establish that all fine-style
approaches fail; its loss on the prespecified narrow task is sufficient to
reject promotion of this particular heuristic.

The selected outer model has 1,329 targets, 3,428 sparse associations, and
60,161 artists with at least one proposal. It produces 148,573 ranked proposals
across those artists, up to ten each. Cold and unseen positives remain in
every relevant denominator: 21,181 positives have no observed artist-primary
value, and 5,068 have no training musical support. The candidate recovers zero
of both. Enrichment also abstains on primary-cold positives here; conditioned
and global baselines retain their existing frequency fallback, recovering
9,500 primary-cold positives. All four recover zero unseen musical values.

For the rare task, 5,025 positives have zero training artist-tag support,
7,718 have tag support below five, and 858 are primary-cold. A post hoc
coverage diagnostic, without changing any ranks or selection, finds 8,362 rare
positives inside the selected target pool, including 440 primary-cold cases.
Of 16,204 rare positives outside the pool, 8,486 meet support five but fail
other target gates. Even inside the selected pool, unchanged enrichment ranks
recover 3,736 positives versus the candidate's 3,485; the conditioned baseline
recovers 2,482. This diagnostic is descriptive, not a new selection criterion.

## Verification and retained evidence

Nine tests cover source-role authority, artist-tag-only targets, support/share
and anchor gates, known duplicate suppression, bounded strongest-cue scoring,
primary-cold abstention, connected release-group and duplicate-facet isolation,
unseen denominators, serialization identity, and saved-rank metric replay.
Association lift must exceed one so exact-independence cues cannot create
zero-score proposals or contradict the serialized model contract. Targeted
formatting, Ruff, type checks, and all nine tests pass.

The run at `.cache/authority-aware-style-nested-v1` retains the declaration,
both training partitions, implementation snapshots, inner selection, selected
model, ranking hash receipts, held-positive pair identity, and 30 bounded
source-explanation examples. Deterministic compressed outcomes preserve ranks
by scorer and every source/support/cold slice needed to replay Recall and MRR.
Inner outcomes occupy 2,599,905 bytes and outer outcomes 3,438,438 bytes; full
artist-wide predictions and full proposal evidence were not exported.

Independent streaming aggregation exactly reproduced all 33 inner and 44 outer
metric cells, every reported support/cold count, and the default selection.
All 154 Recall/MRR values have zero replay discrepancy. It verified report,
artifact, source, current/frozen implementation, and selected-model identities.
It did not independently refit or rerank the full corpus from the hash-only
prediction receipts. Audit:
`.cache/authority-aware-style-nested-v1-independent-audit.json`.

- Report output identity:
  `dc0d76437c3eb8b49893a208c6cb36fd362ec8578b0f65cd34abfa033a7770b6`
- Selected model output identity:
  `9312d7f33d0e7817ae859a1eb984d0cbeca50cc9d94f694eab6546a4c4d585b6`
- Independent audit output identity:
  `625483fb564ed463f1b794fcecb11d23a091eb566a9c0fc61000501aa6d57095`

The frozen enrichment code and earlier baseline artifacts are unchanged.
No full-source candidate fit or product export followed this evaluation.
Metadata absence is not a negative label. Source recovery does not establish
sonic similarity, independent microgenre identity, or listening relevance;
independent source or listener evidence is still needed. MusicBrainz source
tag associations and derived research artifacts remain local and noncommercial
under their existing attribution/share-alike obligations.

To reproduce the fixed procedure, use a fresh output path; the script refuses
to overwrite the frozen run:

```sh
.venv/bin/python -m scripts.evaluate_artist_style_associations \
  --features .cache/microgenre-features-primary-v4/artist-features.jsonl \
  --output .cache/authority-aware-style-nested-new-run
```
