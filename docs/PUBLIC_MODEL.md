# Public graph model

The first open model uses public catalog facts and privacy safe listening counts. It does not
read Every Noise coordinates, memberships, artists, tracks, or samples. It does not read music
files, audio features, or any values derived from audio.

The model accepts direct artist and genre facts from Wikidata. It can accept MusicBrainz genre
tags only when the active source policy allows embedding. The normal MusicBrainz mixed data
policy does not allow that use. A local research policy can allow it, but any output from that
policy remains local and cannot be exported. The output records that restriction.

ListenBrainz contributes artist pair counts. The ingestion job has already removed listener
identities and track names. A listener can count once for an artist pair in one day. The model
calls the total listener day support because the same listener can appear on another day.

## Method

First, the model keeps MusicBrainz tags and Wikidata P136 claims as separate evidence facets.
It scales each facet within a genre and takes the larger direct score. The method does not fit
source weights.

Second, the model normalizes each artist pair by the total edge strength of both artists. It
passes direct genre evidence across one artist edge. Direct and inferred memberships remain in
separate profiles, and every inferred result lists its direct seed and ListenBrainz evidence.

Third, the model computes weighted Jaccard and cosine neighbors from sparse artist profiles.
It keeps a fixed number of neighbors per genre. The result includes the shared artist count.

Fourth, the model publishes four separate layout lenses. `public` uses the one-hop weighted
Jaccard graph and is the default. `public-direct` uses direct memberships only.
`public-community` finds bounded communities in the one-hop graph, then lays out each community
with the same sparse spectral method. `public-taxonomy` uses only Wikidata subclass links. The
taxonomy links never change membership or similarity scores.

Each lens records its method and version, input kind, metric, seed, input and output hashes,
coordinates, unplaced reasons, quality checks, repeat stability, elapsed time, and peak memory.
Fixed input order, solver settings, axis signs, component order, and rounding make repeated builds
stable. The axes do not claim to measure a music property.

Artist, album, and track rankings use direct metadata evidence only. The first source slice has
artist and album facts. It publishes no track ranking when no public track evidence exists.

## Run

Both database arguments can point to one integrated database. They can also point to separate
catalog and ListenBrainz databases.

```sh
uv run poe build-public-model -- \
  --catalog-db data/public-catalog.sqlite \
  --listenbrainz-db data/listenbrainz.sqlite \
  --output data/model/public-model-v2.json
```

The command opens both databases in read only mode. It writes the result through a temporary
file in the output directory and then replaces the target path. The command reports the output
hash, coverage counts, elapsed time, and peak memory.

The loader checks the embed permission for every source policy. It also removes evidence when an
active suppression blocks embedding for an entity, provenance record, or source. A normalization
permission does not grant embedding permission.

## Limits and validation

The loader applies a row limit to direct memberships, artist pairs, and metadata candidates.
The model also limits artists, genres, propagation visits, similarity pair visits, neighbors,
and representative items. It stops when a limit is exceeded.

Each result records all input artifact hashes, a settings hash, a logical output hash, coverage,
and local resource use. Source agreement compares MusicBrainz tag pairs with Wikidata P136 pairs
when both policies allow the model to use them. Historical Every Noise data can be compared only
after the result hash has been fixed. It is not part of this build command.

The seven day event-time split, map checks, hierarchy check, and community experiment are documented
in [`GRAPH_VALIDATION.md`](GRAPH_VALIDATION.md). The measured four-lens run is documented in
[`reports/LAYOUT_LENSES_20260831.md`](reports/LAYOUT_LENSES_20260831.md).

## Publish and serve

Publish a completed artifact into a catalog whose selected policy allows display and export:

```sh
uv run poe publish-public-model -- \
  data/model/public-model-v2.json \
  --database data/public-catalog.sqlite \
  --policy-id 1

uv run musix serve --database data/public-catalog.sqlite
```

Publication opens the artifact once, enforces a 32 MiB limit, verifies both its file hash and
logical output hash, and resolves every declared input to an exact source artifact and provenance
record whose policies allow export. It resolves every genre by one exact Wikidata QID or
MusicBrainz ID, then commits the derived output, model, four layouts, representatives, input
lineage, and current selections in one SQLite transaction. Repeating the same publication is
idempotent and does not alter the selection timestamp. A layout can be selected only when it
belongs to the current public model. The default is `public`. Direct, community, and taxonomy
lenses remain independently selectable.

Every lens accounts for every genre in the artifact. A genre is either placed or has a bounded
reason key such as `no_similarity_edges` or `no_hierarchy_edges`. Serving views expose points and
unplaced reasons only for the current model and selected layout.

The public model's own genre names take precedence over local display names. Local catalog
artists, albums, and recordings never act as serving fallbacks because their display permission
does not imply export permission. Active suppression of any contributing source, provenance
record, source artifact, or derived output immediately retracts its public layout and
representatives.

Genre pages show at most six representative artists, release groups, and recordings. Links are
derived at render time only from exact MusicBrainz or Wikidata identifiers and lead to ordinary
metadata pages. Empty sections are omitted. The serving model contains no audio, preview, image,
player, or waveform fields.

The project is pinned to Python 3.13.14 through mise, uv's Python range, and `.python-version`.
Cross-thread event-loop wakeups used by Litestar's test client can hang under the restricted test
sandbox on both Python 3.13 and 3.14; the same checks pass outside that isolation boundary. This is
an environment limitation rather than an application or Python-version incompatibility.
