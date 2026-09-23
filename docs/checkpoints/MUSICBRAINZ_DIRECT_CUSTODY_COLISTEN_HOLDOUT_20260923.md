# MusicBrainz direct-custody co-listen holdout

This local-only evaluation tests artist retrieval for a fixed subset of the
direct MusicBrainz custody positives. It does not use Every Noise historical
observations, H3, tags, Last.fm, release rows, audio, Spotify, or playlist
data. It does not authorize factual membership, export, serving, or a model
change.

The direct custody graph database and receipt are verified before reading
memberships. The co-listen overlay receipt and database are also verified
before reading its aggregate relations. The overlay receipt declares no
historical construction input, no raw-listen or listener-identifier access,
and a minimum privacy threshold of five distinct users. The evaluator refuses
another threshold and caps the input at 50,000 aggregate relations.

## Matched cohort and leakage rule

The split is fixed before any retrieval score: for each direct-custody seed
with at least five artists, the lowest `SHA-256(seed_id, NUL, artist_mbid)`
fifth is withheld and at least four artists stay in train. The matched
denominator keeps only held-out artists that are exact endpoints of the
sealed co-listen relation set. It contains 1,453 positives over 268 seeds.

For every arm, artists already known to the source seed in train are removed
from its candidate list. Co-listen ranks candidate artists by the sum of
`log(1 + distinct_user_count)` over co-listen neighbors of the source seed's
train artists. The direct baseline ranks artists from train-only IDF peer
neighborhoods; the non-relational baseline uses train-only artist degree. All
three rank artists for the same seed and use the same 1,453-positive
denominator. Absence from a candidate set is reported as unsupported, not as
negative source evidence.

Of the matched positives, 1,400 have the same artist attached to another seed
in train; 53 are artist-cold after the pair split. This is a pair-level split,
not an artist-disjoint split: most test targets still have another train label.
These strata are descriptive only and are not separately tuned or scored.

| Arm | Recall@10 | Recall@20 | Macro Recall@20 | MRR@20 | Support |
| --- | ---: | ---: | ---: | ---: | ---: |
| Aggregate co-listen transfer | 129 (8.8782%) | 188 (12.9387%) | 16.0544% | 3.7054% | 960 (66.0702%) |
| Direct IDF peer retrieval | 44 (3.0282%) | 74 (5.0929%) | 7.2813% | 1.0458% | 1,160 (79.8348%) |
| Global train artist degree | 2 (0.1376%) | 9 (0.6194%) | 1.1593% | 0.0434% | 1,400 (96.3524%) |

All three arms support 796 matched positives. On that fixed common-support
intersection, co-listen recovers 170 at 20, IDF peers recover 48, and global
degree recovers 5. This intersection conditions only on targets that every
arm can nominate; it does not rerank the arms over an equal candidate set.
Support also has different meanings by arm: an aggregate co-listen path, a
top-ten peer expansion, or an artist observed elsewhere in train. It is not
comparable raw source coverage. This is a substantial source-bound retrieval
lift, but it does not estimate precision or prove musical similarity or
factual genre membership. It is endpoint-conditioned: only held-out artists
already present in the co-listen overlay enter the 1,453-positive denominator,
so it does not establish general direct-custody coverage or independent-source
superiority. The co-listen arm can vote through every retained relation of a
seed's train artists, while the IDF arm is capped at ten peer seeds; their
candidate capacities therefore differ. The cohort is only 1,453 positives
from the 697 direct-custody seeds, not coverage of the 6,291-name universe,
and is not production-ready.

The local receipt is
`.cache/musicbrainz-direct-custody-colisten-holdout-v1/report.json`, logical
SHA-256 `cb24f568922f056c7c39178891b8e641dac5dd5a5059d649793c654994627a0b`.
