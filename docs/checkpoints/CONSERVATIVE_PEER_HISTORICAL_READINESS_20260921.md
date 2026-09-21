# Conservative peer historical-evaluation readiness

> Superseded by [the materialized candidate checkpoint](CONSERVATIVE_MUSICBRAINZ_PEER_CANDIDATE_20260921.md).
> The prior missing-artifact barrier was resolved: a hash-bound source-only
> candidate now exists and was evaluated terminally. This document records only
> the earlier readiness state and must not be read as the current status.

The requested historical evaluation cannot run without creating or selecting a
new peer artifact, so this checkpoint abstains. It does not regenerate the
threshold replay, materialize the conservative edge set, tune a threshold, read
historical rows for model selection, or modify public/static data.

The pinned Last.fm ArtistTags2007 archive is present and has SHA-256
`b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f`.
The available sensitivity report has SHA-256
`8391ebccb7f37f7dd9d784bb8045f9ca066a649d054f0a3a3dd4a68c83808d54` and
binds the baseline peer logical hash
`15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd`.

However, there is no serialized conservative peer-edge artifact at the expected
local candidate path. The available JSON report also lacks a machine-readable
`conservative_variant` receipt, so it does not bind the documented
`sole_shared_artist_seed_degree_below_10` rule to a fixed edge set. The prose
checkpoint's counts are therefore insufficient to calculate exact pair overlap
or positive-only recall reproducibly.

Accordingly, overlap and recall are **abstained** (not zero). No precision,
negative, specificity, release, or musical-similarity claim is made. A future
evaluation must consume a separately materialized, hash-bound conservative
artifact and use the archive only after that artifact is fixed; it must not use
historical results to choose edges, hub limits, or thresholds.

The compact readiness receipt has SHA-256
`012b667893f565ea4e6fccee1f9896ab634053e4426d131117eb975e8b33132c`.

```sh
.venv/bin/python scripts/audit_conservative_peer_historical_readiness.py \
  --archive .cache/lastfm-artisttags2007/source.tar.gz \
  --sensitivity-report .cache/musicbrainz-peer-threshold-sensitivity-v1/report.json \
  --conservative-candidate .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-candidate.json \
  --output .cache/musicbrainz-peer-threshold-sensitivity-v1/conservative-peer-historical-readiness-v1.json
```
