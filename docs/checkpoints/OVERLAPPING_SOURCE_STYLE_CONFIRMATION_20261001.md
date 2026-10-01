# Overlapping source-style confirmation, 2026-10-01

A fixed rare-oriented association lens improves rare source-tag reconstruction
on two disjoint target sets. The confirmation gains **2.17 percentage points**
on rare tags while losing **0.05 points** overall against existing enrichment.
Retain it as an optional local research lens. It does not replace the default
model, establish independent listening relevance, or close the semantic parity
gap with Every Noise.

## Construction and frozen comparison

The model uses only `.cache/microgenre-features-primary-v4/artist-features.jsonl`
(198,409 artists; SHA-256
`2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`).
There is no historical reference membership/name/geometry input and no audio
training. Names and geographical/time metadata do not enter this model.

Each retained musical value seeds a potentially overlapping sparse association
neighborhood. These neighborhoods are source metadata hypotheses, not discovered
or independently validated genres. Unlike adaptive hard partitions, an artist
can receive proposals from several observed neighborhoods. Unlike the previous
negative fine-style experiment, candidates need no proper-genre anchor, maximum
share gate, or high lift gate. Rare values with two distinct training artists
can retain support. This change addresses coverage loss without inventing
missing observations.

Canonical identities use normalized musical values with punctuation and spaces
removed. This conservative duplicate safeguard can also merge distinct strings;
it is not an asserted linguistic alias ontology. Duplicate facets share one
canonical artist/value with maximum authority: artist genre 1.0, artist tag
0.8, release genre/tag 0.2. Source votes cannot multiply authority. The fixed
existing musical-value filter applies before canonicalization.

Associations use a binary distinct-artist joint-support floor of two,
artist-degree correction `degree**-0.5`, typed weighted joint mass, additive cue
denominator smoothing four, and joint-support shrinkage `joint/(joint+2)`.
Only 128 strongest outgoing neighbors per cue are retained; self-edges are
excluded. Target-prior rarity powers **0.15 and 0.35** were frozen before the
exploratory split. The existing enrichment baseline remains smoothing four.
All scoring uses training-only vocabulary, frequencies, and associations.
Known canonical values are excluded, and primary-cold artists abstain. Scores
remain uncalibrated. No absence is treated as a negative label.

The split groups all canonical artist/value facets together and globally joins
shared release-group evidence. Removing a target removes every source facet,
including punctuation/spacing-shaped duplicates. Release groups crossing artist
credits cannot leak a target across the split. Cold and unseen positives remain
in denominators. Source roles used for evaluation strata are read separately
from fitted evidence; they do not become model cues.

## Exploratory fixed comparison

Salt: `overlapping-source-style-signature-components-fixed-20261001-v1`.
The two candidates and baseline are reported without choosing a default model.

| Method | Overall Recall@10 | Tag-only Recall@10 | Rare tag hits / positives | Rare Recall@10 |
| --- | ---: | ---: | ---: | ---: |
| Enrichment, smoothing 4 | 47.634% | 36.164% | 5,408 / 23,795 | 22.727% |
| Overlap, rarity 0.15 | 47.449% | 34.070% | 4,985 / 23,795 | 20.950% |
| Overlap, rarity 0.35 | 47.401% | 35.880% | 5,858 / 23,795 | 24.619% |

Overall there are 109,320 positive targets. Rare tag-only means a source artist
tag outside all source proper-genre signatures, with training artist-tag
support at most 0.5% of artists, including zero. This is a reconstruction task,
not precision or semantic truth. Both overlap variants retain 25,434 training
vocabulary identities and 81,911 directed associations. Vocabulary size must
not be advertised as a count of validated communities.

The initial run `...fixed-20261001-v1` and serialization-only rerun
`...fixed-20261001-v2` have identical methods and results. The latter freezes
deterministic compressed outcome writing and formatting corrections; it did
not retune the model.

## Disjoint confirmation

After the exploratory result, rarity 0.35 and the unchanged baseline were
frozen for a second test. Salt:
`overlapping-source-style-disjoint-confirmation-fixed-20261001-v1`.
Entire canonical/release components assigned to the first test are excluded
from the second target set. Saved outcomes verify **zero target overlap**.
All targets are removed before fitting the corresponding model. Because the
same corpus had already been explored, this is a frozen disjoint-target
confirmation, not an untouched new corpus or independent source gold.

| Stratum | Positives | Enrichment Recall@10 | Overlap 0.35 Recall@10 |
| --- | ---: | ---: | ---: |
| All | 87,349 | 48.818% | 48.769% |
| Artist tag-only | 24,575 | 37.180% | 37.070% |
| Rare artist tag-only | 19,000 | 23.737% | **25.911%** |
| Source proper genre | 62,765 | 53.382% | 53.356% |
| Training-seen value | 83,624 | 50.993% | 50.941% |
| Training-unseen value | 3,725 | 0.000% | 0.000% |
| Primary-cold artist | 16,083 | 0.000% | 0.000% |
| No observed proper genre | 22,385 | 18.718% | 18.302% |

The rare improvement repeats: 4,923 versus 4,510 hits, a net 413 additional
rare positives. Overall the lens recovers 42,599 versus 42,642, 43 fewer hits.
No further rarity retuning or selection followed confirmation. This supports
an optional rare-oriented lens, not replacing general-purpose enrichment.

Observed-family diagnostics use the 20 most common **training** proper-genre
cues. Rows overlap and count held positive pairs, not independent artists.
These are source-conditioned coverage diagnostics, not historical genre-family
accuracy. Their presence does not qualify inferred values as genre facts.

| Observed family signature | Positives | Enrichment Recall@10 | Overlap Recall@10 |
| --- | ---: | ---: | ---: |
| alternativerock | 3,214 | 49.81% | 50.65% |
| ambient | 2,413 | 42.77% | 42.73% |
| blackmetal | 1,544 | 49.55% | 50.00% |
| boombap | 4,238 | 96.30% | 96.44% |
| chillwave | 4,314 | 94.97% | 95.09% |
| classical | 1,400 | 34.86% | 36.36% |
| deathmetal | 1,392 | 67.24% | 68.46% |
| downtempo | 5,038 | 87.14% | 87.44% |
| folk | 2,188 | 42.37% | 42.92% |
| hiphop | 7,935 | 70.65% | 71.10% |
| indierock | 2,636 | 48.33% | 48.37% |
| instrumentalhiphop | 4,234 | 96.69% | 96.79% |
| jazz | 2,573 | 48.93% | 47.96% |
| lofi | 4,749 | 88.27% | 88.44% |
| metal | 3,829 | 55.13% | 56.62% |
| pop | 6,838 | 47.12% | 47.24% |
| punk | 2,086 | 51.20% | 51.01% |
| rock | 7,674 | 48.16% | 48.03% |
| singersongwriter | 2,307 | 43.39% | 44.95% |
| visualkei | 381 | 76.90% | 76.12% |

## Optional full-source research lens

Following confirmation, the unchanged rarity-0.35 scorer was fitted to the
full source. It retains 30,092 canonical values, **6,513 active overlapping
neighborhoods**, and 111,466 sparse associations. It supplies up to ten inferred
values for 198,348 of 198,409 artists, totaling 1,978,974 proposals. This does
not mean 6,513 discovered microgenres: neighborhoods include proper genres,
styles, weak source tags, and other values passing the existing source filter.
Most artists receiving ten proposals is output coverage, not measured precision.

The lens is an 11 MB local artifact at
`.cache/overlapping-source-style-lens-full-20261001-v1`. Its receipt binds
associations, canonical vocabulary and original source display labels, compressed
artist proposals, code snapshots, source identity, and confirmation report.
Proposals are explicitly inferred, uncalibrated, and local research only. It
neither edits current projections nor exports to the product. MusicBrainz source
attribution/share-alike obligations remain applicable.

The adaptive bulk and expanded coarse models remain unchanged. Their broad,
sub, and micro hierarchy cannot be replaced by counting association
neighborhoods. Independent human/listener relevance, reliable musical names,
new source coverage, and validation for cold/unseen artists remain unresolved.
No suitable sealed independent co-listen gold was used in this experiment;
within-source recovery must not be relabeled as independent musical relevance.

## Verification and retained artifacts

Six tests cover support-two rare recovery without a genre anchor, singleton and
cold abstention, known-value suppression, relative typed authority, frozen
candidate bounds, punctuation-facet/release-group isolation, disjoint
confirmation targets, deterministic compressed ranks, and unseen denominators.
Targeted Ruff formatting/lint and type checks pass.

A full-source output audit checked all 198,409 artist identities and 1,978,974
proposals: no known-value leaks or unknown vocabulary targets, bounded unique
top-ten lists, and every receipt file hash matched. Audit:
`.cache/overlapping-source-style-lens-full-20261001-v1-audit.json`.

Independent streaming arithmetic (without importing model scoring) reproduced
all 12 exploratory and 56 confirmation metric cells exactly. It verified
unique target pairs, zero target overlap, compressed outcome identity,
declaration identity, and frozen code hashes. This replays saved ranks; it does
not claim an independent model refit or reranking. Audit:
`.cache/overlapping-source-styles-20261001-outcome-audit.json`.

Retained reports:

- Exploratory: `.cache/overlapping-source-styles-fixed-20261001-v2/report.json`,
  SHA-256 `a839eccbcd5674c40c7a982700a844e6ae9dcb381be0b5fdb72f03ea0c638208`.
- Confirmation: `.cache/overlapping-source-styles-confirmation-20261001-v1/report.json`,
  SHA-256 `8431513a8cc48da15059417d7454f645b54f169f36cbca27bc2eae20b4c18244`.
- Full-source lens: `.cache/overlapping-source-style-lens-full-20261001-v1/receipt.json`.

Runs refuse to overwrite their destinations. In-memory partitioning avoids
large duplicate feature files; all new artifacts together consume under 25 MB.
The maintained evaluator adds confirmation strata to exploratory reruns, so
future report hashes differ from the frozen exploratory snapshot; model and
split settings remain fixed. Frozen code snapshots retain the exact old run.

```sh
.venv/bin/python -m scripts.evaluate_overlapping_source_styles \
  --features .cache/microgenre-features-primary-v4/artist-features.jsonl \
  --output .cache/overlapping-source-styles-new-exploratory

.venv/bin/python -m scripts.evaluate_overlapping_source_styles \
  --features .cache/microgenre-features-primary-v4/artist-features.jsonl \
  --output .cache/overlapping-source-styles-new-confirmation --confirmation

.venv/bin/python -m scripts.build_overlapping_source_style_lens \
  --features .cache/microgenre-features-primary-v4/artist-features.jsonl \
  --confirmation .cache/overlapping-source-styles-new-confirmation/report.json \
  --output .cache/overlapping-source-style-lens-new-full
```
