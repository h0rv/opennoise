# Source taxonomy neighborhoods, 2026-10-03

A separate CC0 source-graph experiment replays the retained 1,000-entity Wikidata
cohort. It produces 717 distinct undirected P279 edges, 357 connected components,
611 component-local positions and 389 explicit positional abstentions. There are
317 isolated nodes, 67 nodes in components smaller than four and five nodes whose
spectral boundary is ambiguous. The largest connected component has 576 nodes.
Every selected genre remains searchable; no component is packed into a combined
musical coordinate system.

The protocol was frozen in commit `64d33eb` before these measurements. Its exact
bytes hash to `9ac488b93c448e94583388f9125c853a77ad2b334a87997fdc374a1c4d26b526`.
Only actual P279 links with both endpoints selected enter graph construction.
The 1,549 P31 claims and 825 P279 claims whose targets lie outside the selected
cohort are excluded. Labels, generic type anchors, historical coordinates,
artist memberships and sonic descriptors do not contribute to graph scores.
Directed subclass claims stay separately inspectable; undirected graph walks do
not assert that subclasses are interchangeable.

Retrieval sums degree-normalized random-walk probabilities at depths one through
three with weights `0.5 ** depth`, then ranks by descending score and QID. This
uses common paths but is not a separately tuned common-neighbor experiment.
Coordinates use the normalized Laplacian's second and third eigenvectors within
each component. Fixed anchors canonicalize repeated axes and signs. Components
smaller than four or with an inseparable third/fourth eigenvalue boundary abstain.
Numeric rounding makes replay deterministic in the verified runtime; cross-version
floating-point equivalence is not asserted. Dense overlap in the largest component
also limits the usefulness of its picture, so complete name links remain primary.

## Held-out result

Five SHA256-assigned folds hold out undirected edges. Queries exclude their own
identity and observed training neighbors. The degree baseline uses training degree
only, with the same exclusions. Every one of the 1,000 source nodes remains in each
macro/stability denominator, including cold nodes, nodes without held-out targets
and empty neighbor sets. The micro denominator contains all 1,434 directed targets.

| Metric | Graph walk | Training-degree baseline |
| --- | ---: | ---: |
| Micro recall at 10 | 4.1841% (60/1,434) | 17.2245% (247/1,434) |
| All-node macro recall at 10 | 0.8415% | 4.3506% |
| All-node full/deleted-fold top-10 Jaccard | 40.9086% | not defined by protocol |

511 directed targets have a cold training query. 1,122 directed targets become
separated into different training components and cannot be recovered by a graph
walk; the cold targets are a subset of those disconnected targets. Each fold has
408–414 cold training nodes and 782–804 nodes without held-out positives. No empty
nodes or impossible targets are removed to improve these measurements. The graph
walk underperforms the degree baseline. These results measure source-edge recovery
and structural stability only; independent musical judgments, recommendation
quality, sonic similarity, and full Every Noise coverage remain unvalidated.

The machine evidence at
[`open-taxonomy-neighborhoods-20261003.json`](../foundation/evidence/open-taxonomy-neighborhoods-20261003.json)
retains per-fold measurements, source/protocol/implementation bindings and the
browser report. No experiment-specific acceptance threshold was chosen afterwards.

## Optional local explorer

The default portable and sealed release paths retain their behavior. This optional
profile builds a genre explorer at its root and an unchanged portable 150-artist
explorer under `artists/`. Genre details link artists only when the independently
replayed native direct artist claim has the exact same QID. No artist membership
is inherited through the taxonomy. Observed artist labels outside the taxonomy's
selected cohort remain accessible in the separate artist explorer.

```sh
.venv/bin/python scripts/build_open_foundation.py build \
  --profile portable-taxonomy --output .cache/open-foundation-taxonomy-v1
.venv/bin/python scripts/build_open_foundation.py validate \
  --profile portable-taxonomy --output .cache/open-foundation-taxonomy-v1
.venv/bin/python scripts/run_dev.py --directory .cache/open-foundation-taxonomy-v1
TMPDIR=/dev/shm node scripts/capture_open_taxonomy.mjs \
  http://127.0.0.1:3000/ .cache/open-taxonomy-browser-v1
```

Build requires a fresh output and uses no network. Validation replays the native
source pack, reconstructs every graph score, coordinate and fold metric, checks
static bytes and validates the nested artist export. Editing the graph and then
rehashing its export receipt still fails source replay. The browser check exercised
all 1,000 genre links, exact-ID keyboard search, an isolated genre with no position,
component-local SVG keyboard links and their equivalent complete list, exact direct
artist navigation, Back/Forward, reload and mobile layout. Requests stayed within
the local static origin; no audio or private API was used. This is a local partial
research/profile export, not a deployment or a full-foundation acceptance result.

## Acquiring a larger vocabulary

1,000 is this frozen cohort's cap, not an intrinsic vocabulary limit. The current
capture adapter intentionally pins its exact query plan and cannot silently accept
a changed limit or selection query. A larger independent capture needs a new plan
version, a fresh pack directory, its own budgets and raw receipts, and a separately
frozen evaluation protocol before measuring that new cohort.

Wikidata Query Service supports bounded native keyset pages. A new selection plan
can retain `?genre wdt:P31 wd:Q188451`, order by `STR(?genre)`, use
`FILTER(STR(?genre) > "last returned entity URI")`, and apply a fixed page limit.
This orders URI strings lexicographically, not numeric QIDs. Persist each exact
cursor and returned-ID page, prohibit duplicate or non-increasing IDs, stop on an
empty/short page, preserve failed requests, and mark a budget-limited scan incomplete.
Follow up only the resulting exact IDs in bounded P279/English-label batches. This
keeps P31 as selection metadata, never a graph distance. Live pages are captures at
different times and do not constitute one immutable dump snapshot.

Alternative acquisition can stream an official Wikidata JSON dump and project the
same exact property predicates into a versioned CC0 SQLite/source pack. This avoids
live-query latency and supplies a dump-wide snapshot boundary, at substantially
higher download/storage cost. A new, explicitly wider source policy could additionally
include entities typed through music-genre subclasses, but must retain those class
paths separately; generic music/type anchors still must not connect all genres in
the distance graph. P279-to-external endpoints can motivate subsequent exact-ID
selection only after their genre status is established under that new policy. None
of these expanded captures were run or folded into the present 1,000-node results.
