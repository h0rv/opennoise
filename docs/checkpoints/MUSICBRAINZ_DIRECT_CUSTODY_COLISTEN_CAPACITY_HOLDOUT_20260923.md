# MusicBrainz direct-custody co-listen capacity holdout

This is a local-only, receipt-bound follow-up to the matched co-listen
holdout. It tests one question: does expanding the direct IDF peer arm beyond
its former top-ten peer limit account for the observed retrieval gap? It does
not use historical Every Noise observations, H3, tags, Last.fm, Spotify,
playlists, release rows, audio, raw listens, or listener identifiers. It
authorizes neither a factual membership claim nor export, serving, or a model
change.

The evaluator verifies both the direct-custody graph receipt/database and the
aggregate ListenBrainz overlay receipt/database before querying either. The
overlay declares no historical construction input and the exact five-distinct-
user privacy threshold; inputs above 50,000 aggregate relations are refused.
It uses the same fixed pair-heldout split and matched co-listen-endpoint cohort
as the prior checkpoint, with known train artists removed from every ranking.

## Predeclared arms and cohort

The fixed cohort is 1,453 held-out seed--artist positives across 268 seeds.
It is endpoint-conditioned: a direct-custody held-out artist appears only when
it is an endpoint in the sealed aggregate co-listen relation set. Thus it is
not a custody-coverage estimate. The pair split leaves 1,400 targets whose
artist has another seed label in train and 53 artist-cold targets with no train
membership. This is not artist-disjoint; the strata describe remaining label
availability rather than independent generalization.

Five ranking arms were fixed before running:

| Arm | Candidate route |
| --- | --- |
| Full co-listen | All aggregate co-listen neighbors of the source seed's train artists, scored by summed `log(1 + distinct_user_count)`. |
| Capped co-listen sensitivity | The ten strongest aggregate neighbors per train artist before the same transfer score. |
| IDF peers, top ten | The prior train-only IDF-ranked peer-seed expansion. |
| IDF peers, all | Every train-only IDF peer pair sharing at least two artists: 15,839 undirected candidate pairs. |
| Global degree | Train-only artist degree, excluding source-seed train artists. |

The all-peer arm is the capacity test. The cap-ten co-listen arm is a
predeclared sensitivity test, **not** capacity-equivalent to ten peer seeds:
each peer seed and each source train artist can expand to different numbers of
artists. No arm is reranked on an equal candidate set.

## Fixed-run results

| Arm | Recall@10 | Recall@20 | Macro Recall@20 | MRR@20 | Supported targets |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full co-listen | 129 (8.8782%) | 188 (12.9387%) | 16.0544% | 3.7054% | 960 (66.0702%) |
| Capped co-listen sensitivity | 152 (10.4611%) | 219 (15.0723%) | 18.5875% | 3.9520% | 426 (29.3187%) |
| IDF peers, top ten | 44 (3.0282%) | 74 (5.0929%) | 7.2813% | 1.0458% | 1,160 (79.8348%) |
| IDF peers, all | 49 (3.3723%) | 85 (5.8500%) | 8.6887% | 1.1736% | 1,395 (96.0083%) |
| Global degree | 2 (0.1376%) | 9 (0.6194%) | 1.1593% | 0.0434% | 1,400 (96.3524%) |

Expanding the IDF peer route from ten to all accepted train-only peers added
11 Recall@20 hits (74 to 85) on the identical 1,453-target denominator. Full
co-listen still recovered 188. This rules out that particular top-ten direct
peer truncation as a sufficient explanation for the observed gap; it does not
establish independent-source superiority, musical similarity, or factual
genre membership.

Full co-listen and all-peer IDF jointly support 923 targets. Without reranking
or equalizing candidate lists, full co-listen recalls 181 and all-peer IDF 57
at 20 on that shared-support intersection. This conditions only on targets
each route can nominate. The routes' support counts are not comparable raw
source coverage: they mean an aggregate co-listen path, a direct peer
expansion, or a train-seen global artist, respectively.

For artist-seen targets, full co-listen recalls 181/1,400 (12.9286%) and
all-peer IDF recalls 85/1,400 (6.0714%) at 20. For the 53 artist-cold targets,
co-listen recalls 7/53 (13.2075%); this is descriptive only and too small for
a general claim. Direct peer and global arms score zero there structurally:
an artist absent from every train membership cannot be nominated by a
train-membership expansion. Co-listen's seven hits therefore demonstrate
out-of-custody candidate reach, not a factual genre label.

The sealed local receipt is
`.cache/musicbrainz-direct-custody-colisten-capacity-holdout-v1/report.json`,
logical SHA-256 `39c853472514dd547bf196bd434cd9fe1a11668f7b426164f17cb13acb7d7cb4`.
Its verified input hashes are direct receipt
`a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0`, direct
database `1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69`,
co-listen receipt `bdda6ec7629f87592ee5385babfc21ca91e78ad03819237b9b8765bc262169ae`,
and co-listen database `bea7666d073cc0caaef44042a893b9551ea9cadf189a72a6b8eaf7272b05bd5f`.
