# Public graph model

The public model uses approved catalog metadata and privacy-safe aggregate
listening evidence. It does not read Every Noise coordinates, Every Noise
memberships, music files, audio features, previews, or audio-derived values.

The qualified public release currently contains 603 independently built genre
identities. Historical Every Noise data is a separate reference for evaluation
and compatibility work.

## Evidence

- Wikidata contributes typed genre, hierarchy, and artist-to-genre claims.
- MusicBrainz can contribute typed metadata only under a policy that permits
  the relevant use.
- ListenBrainz contributes time-bounded, privacy-thresholded artist co-listen
  counts. Raw listening events, track text, and listener identity do not enter
  the public database.

Direct membership and one-hop propagated membership remain distinct profiles.
Each profile member stores its component kind, raw and normalized value, and
source references. Similarity rows record the profile, metric, score, shared
artist count, rank, input hashes, and model version.

## Graph and map

The model publishes a taxonomy DAG and a similarity graph. Taxonomy is not
similarity. A genre may have multiple taxonomy parents.

The production-map artifact chooses an explicit display parent only for map
navigation. That choice is versioned, explainable, and non-canonical. It never
rewrites or removes the source DAG.

The one production renderer uses semantic zoom:

1. Overview communities or umbrellas.
2. Genres within the visible umbrella.
3. Subgenres and deeper descendants.

Earlier visible context remains available while zooming. The map artifact owns
coordinates, LOD membership, labels, placement reasons, and evidence hashes.
The renderer must not infer them.

The historical, direct, community, and taxonomy layouts are research or
compatibility artifacts. They are not product view switches.

## Publication

`poe build-public-model` creates a versioned model artifact from local,
verified inputs. `poe release-certify` is the release boundary. It validates the
qualified cache, serving database, model artifact, production-map artifact, and
their manifests before a server can use them.

The serving database persists names, representatives, profile memberships,
neighbor rows, and evidence. Genre detail exposes a compact `Signals` section:
direct and one-hop membership components plus ranked similarity scores.

Publication is deterministic for the logical model output. File-level runtime
measurements are recorded separately because elapsed time and peak memory vary.
