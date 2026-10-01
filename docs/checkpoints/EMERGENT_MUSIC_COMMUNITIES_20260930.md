# Emergent music communities, 2026-09-30

The product goal is to learn broad, subgenre, and microgenre discovery from open
metadata. The 697 retained MusicBrainz proper genres are source observations,
not the construction vocabulary or an upper bound on discovered communities.
Matching historical Every Noise names remains an evaluation measure, not a
training objective. Community labels describe their strongest source features;
they are inferred group descriptors rather than factual taxonomy statements.

The verified artist metadata acquisition retains 38,985 exact artist identities,
124,740 positive native tag observations, and 14,241 raw tag labels. Fifty new
batched official searches cover 5,000 source artists. The feature cache used for
the first evaluated rich model is `.cache/microgenre-features-rich-v2`:
198,409 artists, 558,467 source-faceted features, 7,769 explicit rejections,
198,390 display names, and 19 explicit missing-name cases. Nonpositive votes are
rejected. Exact names are joined for display after model construction.
MusicBrainz core metadata is CC0; supplementary tags are CC BY-NC-SA 3.0 and
these research outputs carry attribution, noncommercial, and share-alike
obligations. They are not promoted into a public release.

The v3 model at `.cache/emergent-topics/rich-20260930-v3` produces 844 communities:
16 broad, 240 subgenre, and 588 microgenre groups. Broad assignments cover
198,409 artists; subgenre assignments cover 86,061; microgenre assignments cover
71,145. It groups identical canonical musical value profiles before fitting,
requires source support and positive musical split gain, filters pure metadata
tags, and enforces membership ancestry. Context facets cannot independently
justify a fine musical community. Scores are uncalibrated cosine affinities.

The independently frozen artist-by-musical-value holdout removes each withheld
value across every duplicate facet before fitting support, vocabulary, IDF,
and communities. It includes cold positives in the denominator. On 85,109
withheld positive pairs, v3 Recall@10 is 29.19%, versus 28.26% for global training
frequency and 57.01% for a conditioned proper-genre baseline. On 7,868 tag-only
positives, v3 is 12.46% versus 15.65% for the conditioned baseline. The community
model has not demonstrated predictive improvement over existing genre context.
This is within-source reconstruction, not independent listening relevance.

Three fixed 80% artist refits have broad ARI 0.660–0.705, subgenre ARI
0.730–0.766, and microgenre ARI 0.777–0.797. Microgenre jointly assigned coverage
is only 25.9–26.6% of the complete cohort. A synthetic capacity check produces
1,024 micro communities while preserving identical musical profiles; the model
has no fixed 697-community ceiling. Capacity does not establish real-world
semantic quality. Evaluation artifacts are retained in `.cache/emergent-evaluation`.

The immutable first community explorer at `.cache/community-explorer-20260930-v1`
adds hierarchical navigation, overlapping artist memberships, exact source
observations, complete artist search, history, and mobile navigation. Sibling
positions are computed offline from musical centroid cosine; repeated musical
centroids abstain instead of implying distinct geometry. All input and output
bytes are receipt-bound. Seven real Chromium screenshots and an acceptance
report are retained in `.cache/community-ui-browser-20260930-v1`.

Aphex Twin, Four Tet, Boards of Canada, Autechre, Burial (UK), Squarepusher,
Floating Points, Caribou, Brian Eno, and Jon Hopkins are present by exact native
ID. Aphex Twin and Four Tet have broad and subgenre assignments in v3; neither
has a qualified microgenre assignment. Their presence does not by itself prove
adequate fine-grained enrichment. Mixed broad descriptors and limited fine
coverage remain modeling problems to improve.

The first evaluated model and UI snapshots remain immutable. Optimizer fixes,
richer release-group evidence, and further feature filtering must produce new
artifacts. Reusing the fixed holdout is a diagnostic comparison, not a new
unseen test. No research preview is deployed, and 100% Every Noise parity has
not been established.

The v4 optimizer correction completes nonempty k-means iterations before
checking minimum child support and evaluates fixed mass/square-root-mass
initializations using the training objective. It fixes a premature-abstention
bug without tuning on test outcomes. On unchanged rich-v2 features, v4 produces
16 broad, 245 subgenre, and 922 microgenre communities, with assignment coverage
198,409 / 86,230 / 78,811 respectively. Aphex Twin and Four Tet now have supported
memberships at all three resolutions. The full model receipt is
`b29069eea8b2f0920b8906445f96ac74377f3c4d46ee9b51816e2370524a9532`.

An independent refit verifies all 198,409 artist identities and 36,085 canonical
musical profiles. Every fine core and direct cosine membership meets the
musical-overlap and child-enrichment gates; no identical profile is split.
Three fixed refits have micro ARI 0.8391–0.8455, with jointly assigned coverage
29.64–30.26%. Broad ARI varies more widely, 0.5420–0.7485.

The reused fixed holdout is a diagnostic comparison: overall v4 Recall@10 is
29.06%, still below the conditioned baseline's 57.01%. Tag-only Recall@10 rises
to 14.20%, below that baseline's 15.65%; tag-only MRR rises to 0.08087 versus
0.07146 for the baseline. These mixed results do not establish overall
predictive improvement. They motivate a separately versioned musical feature
graph experiment rather than declaring convergence from community counts.

The v2 explorer uses the v4 model and improved artist branch focus. Its receipt
is `015d37e99184ff8a110511cd33504612515c5a78d4140f4aba0239581e338b97`.
It verifies every consumed model/source artifact and all nine feature-source
bindings, preserves license obligations, and positions 1,161 communities from
musical centroids only. Chromium acceptance is in
`.cache/community-ui-browser-20260930-v2`: seven screenshots, full hierarchy,
artist journeys, deep links/history, list sorting, zoom, and mobile checks;
34 local requests and no external, media, or runtime errors. The observed local
ready time was 357 ms, not a measured production percentile. Some descriptors
still combine musically remote styles. The preview explicitly remains an
unevaluated community-quality research product.

Reproduction uses the existing Python environment and direct research scripts:

```sh
.venv/bin/python scripts/build_emergent_music_topics.py \
  --features .cache/microgenre-features-rich-v2/artist-features.jsonl \
  --output .cache/emergent-topics/new-run
.venv/bin/python scripts/build_local_community_preview.py \
  --source .cache/parity-explorer-release-20260930-final \
  --model .cache/emergent-topics/new-run \
  --features .cache/microgenre-features-rich-v2/artist-features.jsonl \
  --output .cache/community-explorer-new-run
```

Use fresh cache paths: builders refuse to overwrite existing runs. The richer
release-group feature cache is a separate, unevaluated follow-up; it is not the
training input for either reported model.
