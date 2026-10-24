# Artist discovery from listening context

The new artist browser covers 11,894 native artist identities. It uses artist metadata and public aggregate listening relationships, with no audio, lyrics or per-user histories. The original genre map remains the entry point, and its 701 pinned JSON files are unchanged.

The browser supports complete search, paginated lists, local artist maps and context suggestions. The main search also reaches the larger catalog. There are 11,811 artists with observed connections, 4,292 with at least five connections, and 5,770 with context suggestions. These are measures of available evidence, not counts of independently judged good recommendations. Of the existing 151 genre pages, 148 offer suggested artists based on co-listening with observed members. Suggestions do not assert new genre memberships.

The source snapshot contains 119,586 undirected artist pairs from 1,647 successful reference responses, including 1,564 nonempty neighborhoods. Two other responses were excluded during local validation. Some rows had missing reference attribution, and they were excluded. Capture stopped after a response contained a missing artist name. No failed request was retried. The public source projection is 5.37 MB compressed and has a fixed SHA-256 contract.

The source is the [ListenBrainz public aggregate artist endpoint](https://labs.api.listenbrainz.org/similar-artists), using its advertised 1,800-day session algorithm. [ListenBrainz's own listening data](https://listenbrainz.org/data/) and [MusicBrainz core identities](https://musicbrainz.org/doc/About/Data_License) have CC0 terms. The projection contains native artist identifiers, names, aggregate scores and derived layout. It contains none of the restricted local genre graphs, noncommercial research annotations or audio corpora. The exact deployed upstream algorithm revision is not known; the advertised algorithm name and capture hashes are retained.

The selected representation is a sparse vector of log-weighted artist-neighbor scores, normalized to unit length. Cosine similarity finds shared listening context. Known connections and the query artist are excluded from model suggestions. A 64-dimensional spectral representation performed worse, so it is used only to supply frozen navigation coordinates. The browser does not run a model server or fetch third-party data.

## Measured relationship recovery

The protocol removes 20% of artist pairs, including both reciprocal directions, before constructing features or baselines. All identities remain known. Queries require at least five withheld neighbors and ten training neighbors, giving 1,487 evaluable references. Ranking excludes known training connections. No genre labels are used.

| Method | Recall@10 | Recall@50 |
| --- | ---: | ---: |
| Sparse shared context | 25.49% | 56.65% |
| 64-dimensional spectral representation | 9.77% | 27.64% |
| Training-degree popularity | 5.16% | 13.17% |
| Uniform expectation | 0.085% | 0.424% |

The complete benchmark took 16.11 seconds with a peak resident memory of 153 MiB on the laptop. An independent implementation reconstructed the source graph and every training edge, verified reciprocal holdout removal, and reproduced all reported method metrics for all 1,487 queries. Scores are rounded consistently to eight decimal places to make floating-point ties reproducible.

The result measures recovery of observed co-listening relationships. It is not an independent listener preference test, a perceptual music similarity benchmark, or evidence of Every Noise taxonomy parity. The source has a top-neighbor cutoff and a captured-reference bias. Unknown relationships are not proven irrelevant. The project has demonstrated thousands of artist contexts; it has not demonstrated coverage of hundreds of thousands.

## Release checks

The artist source has its own input and promotion contracts. The old catalog's input contract, counts and data digest still pass their original approval. The extended build regenerates suggestions from the pinned public graph and reproduces the closed output with network access forbidden. A separate browser gate checks main-page search, desktop maps, phone lists and maps, 44-pixel map targets, zoom, history and offline browsing. No audio or video request is permitted.

The served interface keeps source details behind Sources and labels inferred links Suggested. The optional Song Describer audio experiment remains local research and is not an input to this release.
