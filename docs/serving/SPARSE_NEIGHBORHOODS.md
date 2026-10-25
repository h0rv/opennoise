# Sparse artist neighborhoods

The update fills missing listening neighborhoods in the existing 11,894-artist
catalog. A frozen sample of 1,000 artists with one to four known neighbors adds
51,407 observed pairs. Of the sampled artists, 918 gain at least five neighbors.
Across the catalog, the number with at least five links rises from 5,895 to
8,457. The artist identities, names and 149,588 previous pair scores stay the
same.

Selection uses the prior public graph and request history. The two degree
groups receive 648 and 352 requests through proportional allocation and a fixed
SHA256 order. Every prior attempt, including the two held references, is
excluded. There is one request per selected artist, and no neighbor expansion
queue. All 1,000 responses count in the coverage denominator.

The [manifest](../../data/examples/native-artist-neighborhoods-sparse-20261025/manifest.json)
binds the previous source, its contract, selection and exact response bodies.
The packet contains aggregate scores and core artist fields under the retained
CC0 source scope. Its 69,510 rows produce 69,406 admitted observations, 96
quarantined rows and eight duplicate rows. New identities outside the fixed
catalog are excluded. Earlier provenance and quarantine totals are retained.

After `poe sync`, reproduce the source with Python 3.13:

```sh
.venv/bin/python scripts/build_sparse_artist_source.py --output .cache/sparse-source-replay
```

The navigation geometry and sparse context method are unchanged. The result
measures source coverage and supplies no new independent listener relevance
result or claim of Every Noise parity. The API caps each neighborhood, so the
graph is an observed slice of the provider's relationships.
