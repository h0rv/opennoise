# MusicBrainz name-seed research graph

This is a deliberately local research artifact, not an addition to OpenNoise's
exportable public model. It is built from the completed prefix-0 MusicBrainz
research artifacts:

- `coverage-prefix0.json` supplies the 724 name-matched legacy labels as a
  vocabulary seed, with match provenance.
- `reconstruction-inputs-prefix0.json` supplies only aggregated positive direct
  MusicBrainz artist--genre evidence and its source evidence references.
- `musicbrainz-v3.sqlite` is opened read-only with stdlib `sqlite3` to verify
  every retained evidence reference against the declared MusicBrainz source key.

The graph has one typed genre record per match, direct evidence memberships,
both weighted Jaccard and weighted cosine for every retained artist-overlap
pair, and deterministic bounded neighbor rankings. Its landscape begins from
SHA-256-derived `(genre_id, seed_name)` coordinates and repeatedly diffuses over
the bounded weighted-Jaccard graph. It has no historical layout input channel.

## Policy and sealing

The artifact declares `CC-BY-NC-SA-3.0-local-research`,
`publication_scope=local_research_only`, and
`exportable_public_model=false`. It contains metadata IDs, labels, weights, and
evidence references only. No audio, recordings, previews, or music files enter
the process.

Construction fails if `historical_artifact`, `historical_points`, or
`historical_neighbors` is present in the reconstruction input. H2/H3
coordinates, historical artist assignments, and historical neighbor rankings
are never used by graph construction or landscape generation.

`output_sha256` is a canonical logical hash of every artifact field except the
hash field itself. The post-build gate repeats the boundary claims. Replaying a
build with identical inputs and configuration is idempotent.

## Sealed evaluation

The separate `evaluate` command requires the expected `output_sha256`, validates
the sealed artifact, and only then opens a historical benchmark. It selects only
historical `nodes[].genre_id`, `nodes[].name`, and
`neighbors[].genre_id/neighbor_genre_id/rank`; it does not read coordinates or
artist assignments. Its report is limited to name overlap and top-k neighbor
topology recall, and it never modifies the graph artifact.

Use the two Poe tasks from the README. Keep the logical hash from the build
output in `OPENNOISE_MB_RESEARCH_GRAPH_SHA256` for evaluation.
