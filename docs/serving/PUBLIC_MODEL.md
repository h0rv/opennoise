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

The historical, direct, community, and taxonomy layouts are independent
artifacts. An accepted visualization may be offered through a simple product
switcher only when its exact model input, coordinates, evidence, and release
acceptance are available. The historical option remains separate from the
public model and is local-only until its source rights and integration gates
are satisfied.

## Publication

The archived direct implementation `scripts/build_public_model.py` creates a versioned model artifact from local,
verified inputs. It remains offline tooling. The public website is built only
from the sealed semantic-layout artifact by `poe build`; Pages
serves the resulting files without a database or application server.

The offline catalog database persists names, representatives, profile
memberships, neighbor rows, and evidence for model construction and auditing.

Publication is deterministic for the logical model output. File-level runtime
measurements are recorded separately because elapsed time and peak memory vary.

## Independent publication gate

Run the archived direct implementation `scripts/evaluate_public_model_gate.py` before
publishing a model. The gate accepts only the typed public sources above and
rejects historical or Every Noise vocabulary in the artifact. It recomputes
every directed neighbor score and shared-artist count from the sparse profile
rows, checks that each neighbor has source references through its common
memberships, and reports direct versus one-hop coverage.

The report has separate hashes for model evidence, coordinate data, and layout
version settings. Coordinates therefore cannot be mistaken for evidence or
for a semantic axis. It also records per-lens coverage and deterministic rerun
checks. The command reads a bounded JSON artifact and returns nonzero on any
failed check; its report is suitable for a release cache and does not contain
the model blob itself.
