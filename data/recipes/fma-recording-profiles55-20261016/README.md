# Recording profiles and source genre connections

This bounded derivative connects the reviewed 55-recording waveform pipeline to
artist and genre discovery. It uses only the existing candidate and frozen model:
no acquisition, refit, new dependencies, classifier or heldout model selection.
The previous waveform and evaluation artifacts remain independently valid.

## Why this is the next functional step

The current explorer groups recordings by artist, but its numerical artifact has
only recording and genre positions. It cannot reproduce an artist profile or
artist-level suggestions. Genre pages also omit direct connections to other tags
on the same recordings, leaving most unplaced genres disconnected from map-based
exploration. A small, explicit derived index connects these existing pieces.

There are 53 native artists: 51 have one recording and two have two recordings.
These are profiles of the available excerpts, not estimates of an artist's entire
style. Ten distinct artist IDs share one original leakage component, so excluding
only the query artist ID would be insufficient for training-candidate suggestions.

## Fixed artist calculation

For each native artist, retain every member track, its original component and fold,
and its source-tag evidence. Require a single component/fold for the artist. Average
the saved training-standardized 52-column vectors with equal weight per recording;
do not average unit vectors or fit another normalization. If any member has an
original unsupported vector, retain the artist with an explicit abstention rather
than silently dropping the member or averaging it back into support.

Project a supported mean with the existing PCA axes. A zero-mean vector cannot
support cosine suggestions but can still have a valid projected position; those
statuses stay separate. Suggest only eligible training artist profiles, excluding
the query's entire component, with at most one artist per candidate component.
Cosine distance and native-ID ties are fixed before computation. Recording-level
suggestions and the original genre anchors remain unchanged.

The artifact retains membership counts, singleton status, invalid-member reasons,
candidate artist/component counts and all artists without usable positions or
suggestions. The interface provides list access and playable member recordings.

## Genre relationships preserve the actual evidence

Two genres connect only if the same reviewed recording carries both source tags.
Every relationship retains its exact shared track IDs and distinct artist/component
IDs. Combining tags from different recordings by the same artist does not create
an edge. All 93 source genres remain present, including those without connections.
Ordering uses shared-recording count and then native genre ID, not a fitted score.

This graph describes already-visible catalog annotations across all 55 recordings.
It is not a training input, heldout evaluation, taxonomy, acoustic relationship,
prediction or evidence of musical similarity. The interface calls it “Also tagged
on these excerpts” and makes shared recordings inspectable. Inferred artist
neighbors carry the separate “Suggested” label.

## What PR #47 established

The recording retrieval comparisons are reproducible, but their scope is narrow.
Five of six test queries have matching source-tag candidates below the top three;
one has no matching coverage. Original raw/PCA/ID rankings, fixed four-feature
distance, historical listen popularity and training annotation prevalence all
produced zero test hits at one and three neighbors. They used the same frozen
eligible candidate pool and component exclusions. Historical listen counts measure
past platform exposure, not present-day popularity. Annotation prevalence is a
separate source-label prior, not audience popularity.

The exact component-balanced random reference expects 0.943 hit queries out of six
at three neighbors, with a central 95% conditional range of 0–3. That range describes
the specified random retrieval procedure on this sample, not population uncertainty
or musical quality. Independent implementations verified the numerical results.
Incomplete source tags and previously inspected queries prevent stronger claims.

The listening pilot remains blank. Human feedback is still required, but it does
not prevent reproducible data aggregation and navigation improvements. This
derivative does not rerun genre-overlap evaluation at the artist level or select
settings using those six queries.

## Why there is no new multilabel classifier

The waveform sample has 47 training recordings and 93 observed source labels; 56
labels occur only once across the entire sample. Another classifier would have
little independent evaluation support. The historical 44-feature Gaussian model
is separate retained evidence, not a model of these newly extracted 52 features.
The source-tag evidence and co-tag graph preserve multiple labels without
misrepresenting them as predicted artist genres. A meaningful predictive extension
needs adequate independent label support, a development cohort and untouched
confirmation queries, alongside real listening judgments.

## Reproduction and verification

The protocol is frozen before computing the new profiles. Inputs are pinned to
candidate manifest `242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf`
and waveform inventory `829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729`.
The stage retains the existing 120-second CPU/wall, 1 GB memory, 100 MB output and
200 KB view limits. The derived pack has a closed inventory. Independent numerical
replay and an externally reviewed pack pin precede site generation. The versioned
site preserves the original candidate/model subtrees and old export validators;
no public deployment is authorized.
