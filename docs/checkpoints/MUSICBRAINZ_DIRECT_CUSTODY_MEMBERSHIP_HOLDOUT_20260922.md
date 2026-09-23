# MusicBrainz direct-custody membership holdout

This local-only, source-bound test asks whether the two existing peer-edge
rankings can recover artist--genre memberships that were withheld before a
peer graph was constructed. It is not an H3 comparison, a historical
reconstruction, a coverage report, a publication gate, or a serving approval.

## Fixed source cohort and split

The evaluator verifies the local direct-custody peer-graph receipt before
reading its SQLite database. The graph database SHA-256 is
`1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69`; its
receipt SHA-256 is
`a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0`. The
receipt binds direct proper-genre custody receipt
`a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9` and
custody object
`b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e`.

For each seed with at least five unique direct artists, the evaluator holds
out the lowest hash-selected fifth of `(seed_id, artist_mbid)` pairs using
`SHA-256(seed_id, NUL, artist_mbid)`. It retains at least four artists for
training. The held-out pair is absent from every train graph calculation.
The fixed cohort has 697 direct-custody seeds: 687 eligible seeds, 10
ineligible seeds, 77,206 held-out positives, and 310,229 train memberships.
This is not coverage of the full 6,291-name catalog: the remaining 5,594 names
are outside the direct-custody source cohort and are not inferred or scored.

## Comparison

Each ranker is scored on the identical 77,206 positive denominator. A seed's
top ten train-only peers vote for their train artists. The proposed pipeline
selects peers by IDF-weighted Jaccard and weights votes by that score; the
baseline selects peers by shared-artist count and weights votes by that count.
Thus this fixed test compares end-to-end peer-ranking pipelines, not the
isolated effect of IDF vote weighting with a fixed neighbor set. A
non-relational baseline ranks every artist by its train-only global seed
degree. Metrics are Recall@20, macro Recall@20 over the 687 seeds, and
MRR@20. A withheld positive missing from a ranker's candidates is separately
reported as unsupported; it is not treated as negative evidence about the
source claim.

| Ranking | Recall@20 | Macro Recall@20 | MRR@20 | Target support | Recall@20, supported |
| --- | ---: | ---: | ---: | ---: | ---: |
| IDF-weighted Jaccard peer vote | 679 / 77,206 (0.8795%) | 3.3914% | 0.1706% | 39,056 (50.5867%) | 1.7385% |
| Shared-artist-count peer vote | 550 / 77,206 (0.7124%) | 2.4073% | 0.1422% | 41,651 (53.9479%) | 1.3205% |
| Global train artist degree | 139 / 77,206 (0.1800%) | 0.6417% | 0.0527% | 50,608 (65.5493%) | 0.2747% |

The IDF-ranked and IDF-weighted pipeline recovers 129 more positives than the
shared-count pipeline, a 23.45% relative Recall@20 improvement, despite lower
candidate support. On the common 37,740 supported targets, the IDF pipeline
recovers 679 (1.7992%) and shared-count recovers 548 (1.4520%), so the
end-to-end advantage is not solely a different support cohort. The absolute
Recall@20 remains below 1% on the full held-out denominator; this is not
production-ready and is not evidence of musical similarity, precision, or
deployability.

This v1 diagnostic permits artists already known to a source seed in train to
remain in its candidate lists. The later matched co-listen holdout removes
those known train artists uniformly from every arm. Its Recall@20 values are
therefore not directly comparable with this v1 result; this checkpoint is
preserved unchanged as the original fixed diagnostic.

The local receipt is
`.cache/musicbrainz-direct-custody-membership-holdout-v1/report-v2.json`, logical
SHA-256 `59d29e365a571b269b5cd567587e84661b5107a6ea3620ac717762cb766a5c76`.
It records that H3, historical, tag, Last.fm, and release-row inputs were not
used and that export and serving are unauthorized.
