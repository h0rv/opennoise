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

The current open graph contains 7,037 nodes and 3,317 edges. It contains all
6,291 historical names and 746 public catalog anchors. It has 441 exact
identity edges, 853 factual taxonomy edges, 1,940 compositional review edges,
and 83 ambiguous review edges. It connects 2,418 historical names through
review links. It has no inferred artist memberships and no promoted review
links.

The current public membership candidate has 4,948 direct Wikidata observations,
30,903 privacy safe listening observations, and 13,175 normalized aggregate
pairs. It produces 3,049 direct candidate pairs and 9,256 one hop candidate
pairs across 292 named genres. It abstains on 5,999 names. It is a candidate
artifact, not a serving model. Its historical comparison reaches 37.05 percent
positive only recall on the mapped evaluation subset, and the historical data
is not an independent public gold set.

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
