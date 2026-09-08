# Local peer neighborhood audit

## Scope

This report queries the completed local research index at
`.cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite`.
It does not read the 817 MiB peer JSON or any release group staging database.
The index is bound to candidate hash
`15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd`.
Its metadata marks it `non_production_candidate=true` and
`all_inputs_export_allowed=false`.

The score is weighted Jaccard over direct artist memberships. An edge needs at
least two shared direct artists. The index contains no aggregate listening
component. Every one of its 28,508 edges has `direct_only` sufficiency and
`direct_artist_overlap` as its only component.

Overlap is evidence about this source graph. It does not establish musical
similarity, user preference, historical accuracy, or artist membership beyond
the input observations.

## Reproducible queries

Use the bounded CLI for an individual neighborhood:

```bash
uv run python scripts/local_peer_similarity.py neighbors \
  --index .cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite \
  --seed item94 --limit 10
```

Use SQLite for the support histogram:

```sql
SELECT
  COUNT(*) AS edges,
  SUM(shared_direct_artist_count BETWEEN 1 AND 3) AS shared_1_3,
  SUM(shared_direct_artist_count BETWEEN 4 AND 10) AS shared_4_10,
  SUM(shared_direct_artist_count BETWEEN 11 AND 100) AS shared_11_100,
  SUM(shared_direct_artist_count >= 101) AS shared_101_plus
FROM peer_edge;
```

## Coverage and support

The index has 6,291 retained seeds. It has an edge for 1,580 seeds, and 4,711
seeds have no peer evidence in this index.

| Shared direct artists | Edges |
| --- | ---: |
| 1 to 3 | 13,558 |
| 4 to 10 | 8,614 |
| 11 to 100 | 5,540 |
| 101 or more | 796 |

There are 22,172 edges with ten or fewer shared artists, or 77.8 percent of
the graph. Small intersections therefore make up most of the graph. They do
not necessarily control a given top ten list.

## Representative neighborhoods

The table shows the first five results for each retained source seed. `Shared`
is the number of directly shared artists, and `Score` is the stored weighted
Jaccard score.

| Source seed | Neighbor | Score | Shared |
| --- | --- | ---: | ---: |
| hip hop | boom bap | 0.168051 | 4,574 |
| hip hop | instrumental hip hop | 0.168025 | 4,605 |
| hip hop | lo-fi | 0.158422 | 4,443 |
| hip hop | chillwave | 0.151618 | 4,196 |
| hip hop | downtempo | 0.148380 | 4,263 |
| house | deep house | 0.195217 | 838 |
| house | tech house | 0.163341 | 687 |
| house | techno | 0.133263 | 846 |
| house | edm | 0.132721 | 766 |
| house | electronica | 0.124860 | 700 |
| post-punk | new wave | 0.125082 | 374 |
| post-punk | gothic rock | 0.090875 | 249 |
| post-punk | art punk | 0.060164 | 107 |
| post-punk | coldwave | 0.056083 | 159 |
| post-punk | dark wave | 0.053127 | 161 |
| jazz | jazz fusion | 0.042411 | 800 |
| jazz | free jazz | 0.031285 | 600 |
| jazz | contemporary jazz | 0.029866 | 585 |
| jazz | hard bop | 0.029076 | 471 |
| jazz | swing | 0.026273 | 485 |
| cumbia | tropical | 0.043333 | 26 |
| cumbia | cumbia peruana | 0.032051 | 9 |
| cumbia | salsa | 0.031630 | 25 |
| cumbia | cumbia sonidera | 0.024911 | 3 |
| cumbia | cumbia villera | 0.021053 | 5 |

Hip hop also has `rap` at rank eight, with score 0.047056 and 2,148 shared
artists. House has `edm` and `electronica` at ranks four and five. Cumbia has
`tropical` at rank one. These broad labels appear in some results, but they do
not dominate all of the audited neighborhoods.

The cumbia results are the weakest case. Its entire degree is 72, its highest
shared count is 26, and several top ten results have only 3 to 10 shared
artists. A global shared-count cutoff would remove many of those results, so
the current data does not justify one.

## Ranking decision

Keep the direct-only baseline unchanged. The completed index contains no
album-supported membership component, so it cannot show that a third component
would improve neighborhoods. Adding that component now would change sparse
results without a measured gain.

After the receipt-bound release group candidate is accepted, evaluate a
separately normalized album-support component against this frozen baseline.
Compute support through bounded SQLite aggregation by `(seed, artist)` rather
than loading support rows into tuples. Compare supported and sparse
neighborhoods separately, measure broad-label density, and report the direct
component alongside any new component. Keep direct artist evidence visible and
do not treat a missing direct claim as a negative label.

Before that evaluation, the smallest safe improvement is confidence reporting.
Expose the shared direct artist count or a low-support tier to local research
consumers, without changing rank order or dropping sparse regional results.

## Follow-up provenance check

The hip hop links to `chillwave` and `downtempo` each have about 4,200 shared
artists. That is much larger than the shared counts for the top jazz subgenre
links. The counts alone do not show an error. Once a completed, receipt-bound
candidate is available, inspect a small deterministic sample of exact shared
artist IDs and their source claims for those two hip hop edges, then compare it
with the house to deep house edge. The sample should test for a broad tagging
cohort or duplicated evidence, without reading the 714 MiB archive, scanning
the peer JSON, or treating names as a correctness label.
