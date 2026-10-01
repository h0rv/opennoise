# MusicBrainz source-label quality review, 2026-09-30

This bounded review inspects the labels added by the current aggregate artist
tag source and the 2,226 default-visible labels in the retained primary-v2
style atlas. It adds an analysis-only overlay. It changes no feature filters,
predictor inputs, fitted model, atlas, public artifact, or deployment.

The exact feature inputs are the policy-matched baseline
`.cache/microgenre-features-primary-v2-policy-v2/artist-features.jsonl`
(`70f8dd0de2853b2d927eeaa8a92fbcc4a3f7c968c0d54476d473e8a347abc4b2`) and the
augmented primary-v4
`.cache/microgenre-features-primary-v4/artist-features.jsonl`
(`2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`). The
increment assessment is
`.cache/bulk-feature-increment-assessment-20260930-v2.json`
(`2b5870f81ddf142e2824cc36f32a110f453e9923c7883bc673667b823a44322a`). The
official current MusicBrainz genre-name dictionary is
`.cache/musicbrainz-native-genre-labels/labels.json`
(`dd0d201c0942d55d423a6af4f45c2bee15675c4182b1d076c61c13b0773a9577`, 2,209
names, CC0). The retained atlas input is
`.cache/named-style-atlas-20260930-v3/data.json`
(`b9c46915c714528d0de55a4313accaff30c94fb9156628a1bc38419745064828`).
Canonicalization is pinned to
`src/opennoise/ml/emergent_topics.py`
(`78de0ec6f3eb848746a05a219af95dc8addfb1489d1f43b4125118d106caba37`).

The baseline-to-v4 increment has 114,889 canonical artist/value pairs and
17,807 new labels. Their augmented distinct-artist support is 15,644 labels at
one artist, 1,987 at two to five, 165 at six to nineteen, and 11 at twenty to
ninety-nine. Support is not genre confidence. The overlay includes all 17,807
new labels and all 2,226 previous default-visible labels, with support, exact
dictionary membership, native genre UUID references where the atlas already
had them, weak lexical margin, category, and rationale. It contains no artist
UUIDs or canonical artist names; source tag strings are assessed as labels and
may happen to spell an artist or brand name.

The seven categories have conservative meanings: `musical_style_candidate` is a
review suggestion, `performance_role` is a role or ensemble context,
`biography` is an explicit biographical phrase, `pure_place_language` is a
standalone location or language label, `editorial_technical` is record,
subscription, platform, or catalogue metadata, `thematic` is an ideological or
topic annotation, and `unknown` means the string does not support a reliable
semantic category. Model score alone never assigns a category. Exact native
dictionary names and the small, explicitly reviewed candidate list can enter
`musical_style_candidate`, but neither represents a validated genre fact.

The retained review file keeps `visual kei`, `soft visual`, `comfy synth`,
`denpa`, `instrumental`, and geographic compounds such as `french metal`,
`prairie hip hop`, and `latin jazz` available as candidate labels. It keeps
`string quartet` as `unknown` with an explanation that musical-form/ensemble
context is not automatically a genre. `countertenor`, `english conductor`, and
`french orchestra` are marked as performance context, not style. `romanticism`
remains unresolved because it can refer to musical era or theme; `hololive`
remains unresolved as an entertainment brand/music-scene term; and `tge24`
remains opaque. Subscription, catalogue/profile, and record-label strings are
marked editorial/technical. Geographic compounds are not reduced to the
standalone place-language category.

For a cheap lexical signal, the review uses 2,209 exact native dictionary names
as weak positives and 123 negative strings: the existing `NOISE` and
`NONMUSICAL_TAGS` policy values plus eleven explicitly reviewed nonstyle
metadata/context strings. This source-same distinction is trained and scored
using five folds grouped by Unicode final-word families. Labels that become
identical after punctuation and spacing removal are unioned with their word
families, which groups forms such as `hiphop`/`hip hop` and
`bluegrass`/`blue grass`. This does not guarantee that semantic synonyms,
transliterations, or all aliases stay in one fold. Unicode tokenization retains
labels such as `Norteño`, Greek, and Cyrillic words. The v8 receipt reports ROC
AUC 0.818746, balanced accuracy 0.702499, precision 0.969441, recall 0.933454,
and F1 0.951107 at a zero cosine margin.
The high precision/F1 partly reflects the 2,209-to-123 class imbalance; the
weaker balanced accuracy shows limited transfer to the negative class. Margins
are uncalibrated. The dictionary and negatives share MusicBrainz
lineage, so these scores measure same-source weak-label registry-name
discrimination across held-out word families. They do not measure musical
genre validity, Spotify genre validity, or independent genre accuracy. The
margin is reported for manual ordering only and does not assign categories,
filter features, or promote labels to native facts.

For later modeling, the retained examples show why source support and lexical
similarity need separate treatment from semantic category. Higher-support
candidate labels include `neoprog` (38 artists), `french metal` (36),
`melodic death` (28), and `progressive deathcore` (25); plausible niche styles
such as `denpa` and `comfy synth` remain available even though they have only
17 and 16 artists. Meanwhile, `modern` (25) and `folk-hop` (20) remain unknown,
and role labels such as `countertenor` (22) are not styles. Some unresolved
labels have positive lexical margins while a retained candidate such as
`ostschlager` has a negative margin. Future training targets should therefore
keep style candidates, performance roles, editorial values, themes, and
unresolved atoms distinct, and use independently reviewed semantic or
listening evidence before treating a candidate as genre truth.

Root reviewed the initial support-stratified sample before classifier
construction. It clarified that `comfy synth` is a plausible dungeon-synth
candidate, `denpa` a Japanese music-scene candidate, and `countertenor` a
musical performance context. It also kept `romanticism` unresolved and treated
`hololive` as an entertainment brand/music-scene context rather than a
biographical trait. That review is documented as AI review, not independent
human genre ground truth.

The initial v7 overlay remains preserved as an exploratory receipt; its ASCII
tokenizer did not correctly group non-Latin labels. The corrected final local
artifact is `.cache/musicbrainz-source-label-quality-20260930-v8/`. Its report
binds review script SHA-256
`2938a8ac96507c00a7824b32d4e167c8bb2d1f26de27b04b591f93b507aa3d6a`. Its
`output_sha256` is
`4e4cc47d657469ca1c6cbf83e13e19d7a8592ac05fc4b04e613c112140393bdf`.
The exact v8 reproducer is preserved at
`.cache/musicbrainz-source-label-quality-codefreeze-20260930-v8/review_musicbrainz_source_label_quality.py`
with the report-bound SHA-256 above. The maintained script now has SHA-256
`fac34d2d47fa0ada24d1ba67796660e5a4bf04c7b54bd833406a444c04bcad92`; its
changes are formatting, lint cleanup, and type-only casts for values already
produced as strings, integers, and floats. They include equivalent
adjacent-token iteration and named pinned thresholds. The v8 report remains
bound to the frozen reproducer. These maintenance changes do not alter
calculations or review categories, so no v9 artifact was created.
The `label-review.jsonl` stream is 7,748,233 bytes with SHA-256
`937bdf43e85bdaf4f175f56b3f543b2ed035f19fb396fed0ec108ccd74cc7c04`. New-label
categories are 155 musical-style candidates, 176 performance roles, 6
biography phrases, 181 editorial/technical values, 7 thematic values, and
17,282 unknowns; no new label is assigned pure place/language. For the prior
default-visible labels: 1,446 are candidate labels, 20 performance roles, 1
editorial/technical value, 1 thematic value, and 758 unknown. No default-visible
label is assigned pure place/language or biography. These are review categories,
not pipeline actions. The seven categories are `musical_style_candidate`,
`performance_role`, `biography`, `pure_place_language`, `editorial_technical`,
`thematic`, and `unknown`.

Rebuild with a new output directory; the script verifies every retained source
hash before scanning the two feature caches:

```sh
.venv/bin/python scripts/review_musicbrainz_source_label_quality.py \
  --output-directory .cache/musicbrainz-source-label-quality-20260930-replay
```

No artist-name join, historical Every Noise labels, audio, deployment, or
independent human genre gold is used. Artist support and dictionary matching
cannot establish listening relevance or microgenre validity.
