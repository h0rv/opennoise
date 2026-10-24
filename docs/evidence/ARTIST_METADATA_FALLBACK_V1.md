# Suggestions for artists without source relationships

Artists with no source relationships can now browse inferred neighbors from
genre, instrument and record-label metadata. The candidate adds suggestions
for 30,789 isolated artists, bringing total suggestion coverage to 55,330 of
the 86,253 artist records. Twenty-four isolated artists have no other artist
with shared metadata and correctly receive no suggestions.

Existing graph suggestions and all connected artist data remain unchanged.
Artists with one or two source relationships keep those relationships and genre
links. The metadata fallback applies only when the source graph has no
relationships for the artist. Its Suggested map/list remains visibly distinct
from observed Related artists; Sources explains the inference.

## Decision

A whole-artist holdout tests the relevant missing-information case. A fixed
hash selects 17,133 artists and removes every incident edge before fitting graph
features, degree or a learned model. It removes 34,699 undirected pairs, leaving
62,018. All heldout graph rows and columns are zero. Source metadata and artist
identities remain known transductively.

The test has 10,088 eligible artists, including low-degree artists, and keeps
all 86,253 identities in the candidate gallery. Positive gallery coverage is
100%. The complete 76,165-row exclusion ledger and all 1,366 overlapping genre
strata are retained with the independent report.

| Method | Recall at 10 | Recall at 50 |
| --- | ---: | ---: |
| Exact metadata cosine | 7.1585% | 13.4283% |
| Metadata SVD, 64 dimensions | 3.0840% | 6.2159% |
| Metadata-to-graph ridge embedding, 64 dimensions | 2.9152% | 6.3073% |
| Training-degree popularity | 0.23285% | 0.93416% |
| Uniform expectation | 0.01159% | 0.05797% |

The learned embedding failed the frozen improvement criterion. It is rejected
and is not used by the product. Exact metadata beat popularity by 6.9257
percentage points at ten; the descriptive paired-query bootstrap interval is
6.5047 to 7.3286 points. Independent replay reconstructed the split, training
graph and ridge fit and reproduced all query metrics and method top-ten lists.

The accepted fallback computes TFIDF separately for canonical genre names,
instruments and record labels, normalizes each block, then normalizes their
combination. It ranks exact positive cosine scores, excludes self, rounds to
eight decimals and uses native source URI order for ties. It displays at most
ten results. It uses the same metadata method as the independently replayed
benchmark, without a new fit or parameter search.

These results measure source-association recovery when an artist's relationships
are unknown. They do not measure listener preference, acoustic similarity or
Every Noise parity. Known metadata is an explicit condition; the result does
not promise recommendations for a fully unknown artist or a new source domain.
The earlier partial-edge recovery scores use a different task and cannot be
compared directly with this whole-artist holdout.

## Evidence and release scope

[Frozen evidence](wiki-artist-cold-start-v1/) includes the protocol, original
report, independent numerical/source checks, query results, exclusions, strata
and the reporting clarification. Original MRR covers the full positive ranking;
the independent supplement separately reports MRR at fifty and served-at-fifty.
Original values are preserved. Exact metadata MRR at fifty is 0.0974935751.

The source remains the same accepted Wikipedia V6 projection, with the same
artist identities, genre memberships, native statements, source pins and
licenses. The original catalog and Connections data remain frozen. New model
weights, provisional identity joins, MusicBrainz validation responses and
restricted research are not served.

The separate identity-bridge investigation stopped when the MusicBrainz core
API returned HTTP 503. It has no role in this feature and was not retried.
Only accepted local inputs are needed to reproduce this static build.

An independent output audit proved every new top-ten list, all 24 abstentions,
all 55,440 unchanged connected rows, and unchanged genre pages and global
indexes. Local artist maps now fit their selected coordinates to the viewport;
the root genre map and stored coordinates are unchanged.
