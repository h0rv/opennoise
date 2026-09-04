# Public graph validation

Validation measures the public graph against its own sealed evidence. It does
not use Every Noise as model input and does not use audio.

## Inputs

The graph combines approved Wikidata claims, policy-permitted MusicBrainz
metadata, and privacy-thresholded ListenBrainz artist co-listens. Direct claims,
one-hop propagation, taxonomy, and similarity are separate inputs and outputs.

The listener adapter processes pinned files as one bounded run. It discards
listener identity and raw event content before persistence. A privacy threshold
is part of the input manifest.

## Checks

- Verify artifact, settings, source, and eligibility hashes.
- Verify taxonomy is a DAG and preserve every source parent edge.
- Verify direct and one-hop membership components retain their evidence.
- Verify neighbor ranking, support, metric, and score are deterministic.
- Measure top-10 local-neighbor quality against the sealed source graph and a
  per-query random null.
- Verify display-parent and semantic-zoom choices do not invent graph facts.
- Verify the map's label, geometry, interaction, and accessibility evidence.

A production map must meet the acceptance thresholds in
[`PRODUCTION_MAP_ACCEPTANCE.md`](PRODUCTION_MAP_ACCEPTANCE.md). A failed
candidate remains an experiment. It cannot be selected by a serving release.

Historical Every Noise data can be compared only after an open model is sealed.
It is a benchmark, not a tuning label or a substitute for public evidence.
