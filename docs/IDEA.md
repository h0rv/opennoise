# Musix

Build an open music map from public metadata and privacy safe aggregates.

The historical Every Noise result is a local reference. It preserves 6,291
immutable genre name seeds and dated observed map output. It does not claim to
recreate Spotify's private data or McDonald's private model.

The open result keeps the source records immutable. Each source claim keeps its
source, license, snapshot, method, and observed time. A versioned derived graph
adds public identities, explicit taxonomy, overlapping review communities,
artist membership, genre similarity, and representative album and track
metadata. A derived record never replaces its source claim.

The first model is simple. Explicit parent and subclass statements provide the
hierarchy. Shared artists, public listener aggregates, and approved metadata
provide separate relation signals. Similarity combines those signals only in a
named model run. An artist can belong to several genres. A candidate relation
stays a review candidate until evidence or a human review promotes it.

The map uses stable neighborhoods. The overview shows broad connected groups.
Zooming reveals their child genres and nearby related genres. Further zooming
reveals artists and representative metadata. The map does not treat a denser
flat batch of points as a more detailed neighborhood.

The current full-corpus hierarchy checkpoint retains all 6,291 immutable names
and 66,132 directed public-evidence candidates: 160 accepted, 59,911 review,
and 6,061 abstained. The separately sealed all-seed frontier is built from the
restored public catalog snapshot. Neither artifact inherits artist memberships
through the hierarchy or uses historical data during construction.

The historical peer compatibility evaluator name-matches 6,289 H3 genre names.
Only 1,580 have a constructed candidate neighborhood and are peer-supported;
the other 4,709 are retained as abstentions. The 1,580 figure is an evaluation
subset, not genre, catalog, or hierarchy coverage. H3 has unranked,
positive-only samples, so this remains a neighborhood check rather than a
ground-truth reconstruction.

The separate bridge-backed membership experiment maps 120,288 of 306,136 H3
observations to 78,954 MusicBrainz artists using receipt-bound identities and
an 88,328-artist, 212,696-row open-tag matrix. Its open-only Recall@50 is
0.01582 micro and its H3 edge-holdout Recall@50 is 0.03059 micro; 1,172 whole
cold-label genres deliberately abstain. It is a local, positive-only baseline,
not complete membership, ranked relevance, Every Noise parity, or a serving
model.

The bounded representative catalog currently contains 51 retained releases
and 491 unique track records across 40 genres. These are metadata records only.
They are not claims about the defining or most important works for a genre.

Musix never downloads, stores, serves, embeds, or trains on audio or music
files. Links and playback placeholders remain separate from metadata.

McDonald documented broad inputs and behavior. He described overlapping music
communities, cultural and acoustic signals, listener based discovery, human
review, and readability adjusted map positions. The public record does not
give the private feature vectors, complete source code, weights, thresholds,
candidate rules, or final layout transform. Musix labels experiments as
approximations and reports what is observed, disclosed, inferred, or unknown.

The pipeline is: immutable source snapshot, typed source claim, SQLite
projection, versioned derived graph, evaluation, and public publication. Each
adapter writes provenance and each model run records its inputs, parameters,
code revision, seed, and content hash. Local object storage and future object
stores use the same small abstraction.

Keep the stack small: Python 3.13.14, uv, mise, Poe, Litestar, Pydantic,
SQLite, HTMX 4, and vendored Cytoscape.js 3.34. The graph library handles
direct map manipulation. HTML links, forms, and server rendered fragments
handle the rest.
