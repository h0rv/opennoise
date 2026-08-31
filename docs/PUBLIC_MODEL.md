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

Fourth, the model computes two graph coordinates from the direct weighted Jaccard graph. It
uses the normalized graph Laplacian and a sparse eigenvalue solver. Fixed input order, solver
settings, axis signs, component order, and rounding make repeated builds stable. The axes do not
claim to measure a music property.

Artist, album, and track rankings use direct metadata evidence only. The first source slice has
artist and album facts. It publishes no track ranking when no public track evidence exists.

## Run

Both database arguments can point to one integrated database. They can also point to separate
catalog and ListenBrainz databases.

```sh
uv run poe build-public-model -- \
  --catalog-db data/public-catalog.sqlite \
  --listenbrainz-db data/listenbrainz.sqlite \
  --output data/model/public-model-v1.json
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
