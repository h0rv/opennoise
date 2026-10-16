# Diagnostic evaluation of the reviewed 55-recording waveform model

This follow-up investigates the zero top-three source-tag matches among six test
queries from the existing waveform experiment. It does not fit another model,
change serving neighbors, acquire recordings, or tune against those queries.
All six test queries and both validation queries were already inspected. They
remain diagnostic cases, not an untouched confirmation set.

## Coverage and ranking are different limitations

Five test queries have eligible training candidates sharing observed source tags.
Their first matching candidates in the saved raw-descriptor ranking occur at
positions 15, 6, 5, 24 and 20. The sixth query has no matching candidate. Eligibility
and component exclusion do not remove any globally known query tags in this cohort.
The zero top-three result therefore involves ranking as well as missing coverage.

Across the six queries, the candidate pools can recover eight of fourteen observed
tag incidences. An exact component-diverse selection of at most three candidates
per query can recover those eight. This label-informed ceiling is not a retrieval
method or model score. Source tags are incomplete positives: missing overlap does
not establish dissimilarity, and shared tags do not establish musical relevance.

## Prespecified comparisons

- The existing 52-column standardized cosine ranking remains unchanged.
- A simple comparator uses the four saved training-standardized RMS and
  zero-crossing-rate mean/standard-deviation columns with squared Euclidean
  distance. This is a simple-feature comparison, not an isolated feature ablation:
  the distance function also differs. It introduces no additional fit.
- A query-independent training annotation-prevalence prior averages each
  candidate's observed-tag training frequencies. It is explicitly a label-prior
  baseline, not audience popularity.
- A historical-popularity comparator ranks the native FMA `track_listens` counts.
  A separate bounded offline projection verifies the previously captured metadata
  ranges and the full raw member, retaining only the 55 IDs and integer counts.
  Missing or invalid counts fail closed. These are historical snapshot counts,
  not current popularity; exposure, age and platform selection can bias them.
- An exact random reference samples distinct eligible components uniformly, then
  one recording uniformly within each chosen component. It respects component
  exclusion and diversity. Uniform sampling of tracks would define another null.

Every method uses the frozen original eligibility and query component exclusions.
Results retain unsupported cases and both all-observed and globally known tag
denominators. The random reference describes uncertainty in this artificial
retrieval procedure conditional on this fixed cohort. It is not a population
confidence interval, a musical-quality test, or a post-hoc significance claim.
No comparison selects a new serving method.

## Human evaluation remains necessary

The listening instrument compares the original top candidate with the prespecified
simple-feature top candidate for all six test queries. Two listener slots receive
opposite A/B assignments, yielding twelve planned responses but only six query
components. Repeated responses are not independent query observations. Identical
candidates, missing comparisons, ties, neither, uncertainty and playback failures
remain explicit. Required recording identities and credits remain visible, so
this is method-blinding only. A separate coordinator key stays outside each served
participant directory. Blank packets and an empty response summary are not human
judgments or evidence of improved recommendations.

This small selected sample can test the instrument and reveal failure modes. A
planning target of roughly 100 independent representative query components would
give about a ten-percentage-point worst-case 95% half-width for a simple binary
proportion under independent sampling. This approximation does not automatically
apply to multicategory outcomes, conditional win rates, missing responses or
clustered ratings. Two distinct listeners per query help measure disagreement;
they do not double the independent query count. A useful subsequent study needs
separate development queries, a frozen untouched evaluation roster, permitted
recordings, relevant candidate coverage and actual independent listening responses.
Additional acquisition and public deployment are outside this recipe.

## Reproduction and evidence

The frozen protocol, commands, independent replay and recorded results accompany
the completed evaluation. The existing waveform inventory is pinned to
`829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729`.
The original source/audio artifacts remain unchanged. Evaluation runs use the
existing 120-second CPU/wall, 1 GB memory and 100 MB output limits.
