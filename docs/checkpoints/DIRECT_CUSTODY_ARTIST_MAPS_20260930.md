# Offline artist maps from direct genre overlap

The local explorer can build a separate artist map for every observed source
genre. The retained v2 portable-source batch produced **697 map artifacts**, with
**69,219 positioned artist occurrences** across **683 genres**. Jazz and rock
each selected a 200-artist cohort, drawn from source cohorts of 18,239 and 17,873 artists.
The maps use exact MusicBrainz artist identities and direct proper-genre profiles;
artist names are joined only after coordinates are fixed.

These are inferred overlap maps, not reproduced Every Noise artist geometry.
Their payloads retain `role: inferred_artist_overlap_map` and
`quality_evaluated: false`. Artist membership comes from direct source observations;
relative placement is a separate, unevaluated inference.

Current v3 corrects one geometry limitation: a cohort containing only one
identical source profile abstains from placement entirely. In particular, the
v2 jazz cohort does not support 200 distinct positions. Earlier v2 positions and
counts below are retained historical experiment results, not current coverage.

## Cohort and evidence rules

[`direct_custody_artist_maps.py`](../../src/opennoise/ml/direct_custody_artist_maps.py)
accepts the verified source `ObservationIndex` used by the reconstruction model.
The encompassing explorer reconciles these pairs against its exact-ID catalog
before using them. No names, historical coordinates or memberships, model
proposals, release credits, or audio enter artist-map geometry.

For each genre, the helper selects at most **200 source artists**, placing
multi-genre profiles before singleton profiles, then ordering by descending mean
source affinity to the target and canonical artist MBID. The affinity is:

```
affinity(target, artist) = mean over the artist's other direct genres g of
                          shared_source_artists(target,g) / (source_artists(g)+5)
```

The target genre is excluded from both numerator and denominator. Other genres
with fewer than two shared source artists contribute zero; they still count in
the mean's denominator. Singleton profiles have affinity zero and remain an
explicit abstention fallback. Adding unrelated genres cannot improve affinity
merely by increasing profile degree. Shrinkage 5 and minimum shared support 2
were fixed before running the v2 batch. No artist names or historical judgments
were used to fit or tune this rule.

This is a source-association sampling objective, not an evaluated relevance or
representative artist ranking. Every map explicitly reports source total,
selected, positioned, abstained, and omitted counts, together with `truncated`
and the selection rule. Each artist retains `source_affinity_score`, allowing
its selection to be explained without using its display name.

Within that bounded cohort, similarity is IDF-weighted cosine over each artist's
complete direct genre profile:

```
w[g] = 1 + log((source_artist_count + 1) / (source_genre_artist_count[g] + 1))
score(a,b) = sum(w[g] for shared direct genres g)
             / sqrt(sum(w[g] for a) * sum(w[g] for b))
```

An artist pair must share at least **two direct genres**. The map's target genre
counts as one, so sharing only that genre cannot create a relationship. Singleton
profiles abstain. A multi-genre artist without another qualifying artist in the
selected cohort also abstains; this does not claim the artist lacks a qualifying
neighbor elsewhere in the full source corpus.

Each artist retains at most ten highest-scoring neighbors, resolving equal scores
by MBID. The spectral graph uses the undirected union of these lists. Each displayed
neighbor includes its exact shared seed IDs, shared count, and similarity score.
Only vertices connected by qualifying evidence receive coordinates. The existing
weighted spectral layout and rectangular atlas place those vertices offline in
a 16:9 coordinate space. If the spectral solver does not converge, the map records
an explicit abstention instead of substituting positions.

No global artist-pair matrix is allocated. Overlap computation is limited to
200-by-200 artist cohorts, using the source sparse profile matrix. Browser clients
receive precomputed coordinates and can load one genre artifact at a time.

## Real source run

The completed standalone run is
`.cache/direct-custody-artist-maps/run-20260930-v2/`. It used the verified matrix
from `.cache/direct-custody-reconstruction/run-20260930-final2/`, whose underlying
direct custody object SHA-256 is
`b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e`.

| Measure | Count |
| --- | ---: |
| Source genres / map files | 697 |
| Selected artist occurrences | 78,755 |
| Positioned artist occurrences | 69,219 |
| Selected abstained artist occurrences | 9,536 |
| Genres with positioned artists | 683 |
| Truncated source cohorts | 254 |
| Spectral failures | 0 |

Counts above are artist occurrences across genre maps, not distinct artist IDs.
The full direct source has 387,435 pairs; the bounded maps omit 308,680 occurrences
from their selected cohorts. Omission does not delete direct observations or deny
membership. The batch completed in 35.6 seconds with one OpenBLAS thread. The 697
JSON files total 111,417,883 bytes before the explorer's display-name join; most
of these bytes retain exact per-neighbor shared-seed explanations.

| Example | Seed ID | Source artists | Selected | Positioned | Layout edges |
| --- | --- | ---: | ---: | ---: | ---: |
| Jazz | item379 | 18,239 | 200 | 200 | 1,945 |
| Rock | item3 | 17,873 | 200 | 200 | 1,559 |
| Pop | item1 | 12,174 | 200 | 200 | 1,755 |
| Classical | item151 | 6,770 | 200 | 200 | 1,725 |

These source labels were joined after generation using the retained native UUID
dictionary. The standalone artifacts have no artist names or inferred memberships.
The explorer may join exact-ID labels afterward and bind the resulting bytes in
its encompassing preview receipt.

## Cohort selection change and limits

The retained v1 run used highest direct-genre count first. That rule explicitly
favored broadly tagged profiles; inspection of its sample motivated the fixed
source-affinity alternative. All original v1 artifacts and its implementation
snapshot remain under `.cache/direct-custody-artist-maps/`.

The v2 source-only comparison replaces all 200 selected IDs for jazz, rock, pop,
and classical. Mean direct-genre count falls from 11.75 to 2.00 for jazz, 15.82 to
3.035 for rock, 17.955 to 2.09 for pop, and 7.115 to 2.195 for classical. Across
all maps, positioned occurrences rise by 33, and source cohort sizes and selection
caps are unchanged. These describe how the selection objective changed; they are
not independent evidence of improved relevance.

The full comparison is retained in
`.cache/direct-custody-artist-maps/cohort-selection-comparison-v2.json`. It records
old/new mean source affinity, profile degree, retained IDs, positioned counts,
and selected profile diversity for every source genre without reading names.
The new rule can favor a narrow, highly target-associated profile. Jazz's selected
cohort contains one identical two-genre profile across all 200 artists, so every
within-cohort similarity score ties. Pop has 11 selected profiles, classical 7,
and rock 54. Exact ties and limited profile diversity constrain what this
geometry can express. Spectral positions and tie
separation do not establish fine musical differences among identical profiles.
The payload retains `cohort_relevance_evaluated: false`.

## API and verification

`build_genre_artist_maps(index, output_directory=...)` writes `<seed_id>.json` for
every source genre and returns aggregate coverage counts. The output directory
must be new and inside the checkout's `.cache`; existing files and unsafe source
filenames are rejected. `genre_artist_map(index, seed_id)` provides the same
bounded computation for one genre without writing files.

Each `artists` row includes `id`, `x`, `y`, `state`, `abstention_reason`,
`direct_genre_count`, `supported_neighbor_count`, and `neighbors`. Abstained
artists remain in the payload with null coordinates. The map also carries
`world_width`, `world_height`, source role, construction method, and explicit
coverage counts.

Twelve focused tests cover singleton and identical-profile abstention, exact shared-seed explanations,
IDF weighting against the complete profile, coherent versus broad-profile
selection, self-observation exclusion, the minimum affinity support floor,
deterministic bounded selection,
cohort-specific abstention, source-order invariance, spectral failure handling,
batch writing and overwrite refusal, unsafe source IDs, unknown genres, and
public destination refusal. The tests, Ruff, formatting, and type checks pass.

## Current v3 geometry correction

The new immutable batch `.cache/direct-custody-artist-maps/run-20260930-v3`
contains all 697 genre files. Cohort selection remains fixed, with 78,755 selected
artist occurrences. Identical-profile geometry abstention reduces positioned
occurrences to 69,019 and increases explicit abstentions to 9,736. There are 682
genres with positions and six cohorts marked
`abstained_identical_source_profiles`; five already lacked qualifying pairs.
Jazz accounts for the 200 removed positions. There are no spectral failures.
The aggregate receipt is `report-20260930-v3.json` beside the batch directory.
These counts describe honest available geometry, not a relevance improvement.
