# Saved FMA recording → artist retrieval

`replay_fma_memberships.py --query-track-id ID` now retrieves artist profiles
using that recording's own saved rank evidence. Repeat the flag for up to 100
positive uint32 native track IDs. Request order and duplicates are preserved.
The option requires both `--export-artists` and `--rank-artists`;
`--artist-neighbors` independently includes the existing artist graph.

The query vector contains the first ten saved genre IDs with reciprocal-rank
weights. Artist vectors retain their existing top-ten mean reciprocal track
ranks. Cosine normalization includes every query coordinate, including genres
absent from the candidate vocabulary. Candidates come only from the query's
named historical calibration, confirmation or diagnostic partition; none is
relabeled as training. Retrieval excludes the complete query component, requires
positive overlap, selects at most one artist per candidate component and emits
at most six artists. Ordering uses descending raw computed cosine scores and
native artist IDs for exact score ties. Reported distances clamp floating-point
roundoff to [0, 2]; distance clamping does not change ordering.

`recording_artist_queries` retains each track's native artist/component/fold,
partition, query profile, saved abstention and candidate artist references,
shared genres, support counts and distances. The candidate's complete profile
and nominated track IDs remain available in its same-partition artist row.
Unknown native IDs, IDs without saved predictions, unresolved identities, empty
profiles and no eligible overlap abstain explicitly. Original saved abstention
reasons survive unchanged. There is no feature, genre or identity fallback.
`eligible_candidate_artists` and `eligible_candidate_components` count nonempty
other-component profiles before positive-overlap filtering; they are pool counts,
not selectable-neighbor counts. Unsupported recording queries report zero for
both because retrieval was not attempted. Empty profiles processed by retrieval
can still report a nonempty candidate pool while emitting no neighbors.

Query provenance binds the rank files, native ledger and both retrieval modules;
the existing export also binds source and membership receipts. Calibrated
memberships, artist rankings and artist-neighbor fields remain unchanged.

## Reproduce the frozen request batch

`protocol.json` has SHA256
`7ee032991f48dd8f3fb219fcb00eb734a0e72e47838c26bfc818b38b4d0f6e20`.
The 100 requests were fixed before implementation/results: the first 25 native
IDs from each historical partition, ten other saved abstentions, ten native IDs
without saved predictions and five unknown positive uint32 contract fixtures.
Protocol v2 supersedes preimplementation v1 SHA256
`25c03a421f563a107abcc8003f32ee9eafd3ea15b91497fbebe3b626b67db9d7`.
It clarified raw-score ordering without changing requests or observing results.

Materialize the existing offline membership recipe into a fresh directory:

```sh
.venv/bin/python scripts/materialize_fma_membership_example.py \
  --output /tmp/fma-recording-artists-members
```

Then invoke the existing replay CLI with all exact frozen requests:

```sh
.venv/bin/python - <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

protocol = Path('data/recipes/fma44-recording-artists-20261018/protocol.json')
if hashlib.sha256(protocol.read_bytes()).hexdigest() != '7ee032991f48dd8f3fb219fcb00eb734a0e72e47838c26bfc818b38b4d0f6e20':
    raise ValueError('Frozen request protocol hash differs')
requests = json.loads(protocol.read_bytes())['requests']
args = [sys.executable, 'scripts/replay_fma_memberships.py',
        '--saved-pack', 'data/examples/fma-acoustic-baseline',
        '--memberships', '/tmp/fma-recording-artists-members',
        '--export-artists', '/tmp/fma-recording-artists.json',
        '--rank-artists', '--artist-neighbors',
        '--saved-pack-receipt-sha256', '3e1651c136f5ae0c588e6dd6930a7a8f68fc7b332d1e423d29d1657e20cd0106',
        '--membership-receipt-sha256', 'ad54dc99a09e0c0f492dd97ac21e216a4a70bfd39a7749932a6f1a1a45646c1d']
args += [value for row in requests for value in ('--query-track-id', str(row['track_id']))]
subprocess.run(args, check=True)
PY
```

The CLI retains its 120-second CPU/wall, 1 GB address-space, 110,000-native-row
and total 24 MB export bounds. Candidate pools retain the 2,000-artist cap.
Outputs must be fresh and outside source custody. No acquisition or fitting is
performed. Omit the query flags to retain the prior export schema.

## Actual retained-data outcome

All 100 requests remained in their original order. There were 75 emitted
queries, exactly 25 in each historical partition, producing 450 directed
recording-to-artist edges. Ten retained the original `missing_feature_row`
abstention, ten returned `no_saved_prediction`, and five returned
`unknown_native_track_id`. These are engineering outcomes, not quality metrics.

The checked export, including the unchanged artist graph, is 7,018,634 bytes,
SHA256 `c6545f0545522a93f4f2ae32452c8d2851d20751d715f77d4983426533d3efc1`.
Every partition, artist rank/membership and artist-neighbor field exactly matched
the pre-refactor retained artist-graph export. Independent dictionary-intersection
tests reconstruct query vectors and every candidate ordering/distance from the
retained saved ranks. Synthetic fixtures cover recording-specific differences,
request duplicates/order, exact ties, component exclusions, query-only genre
coordinates, source-label independence, abstentions and request bounds.

A separate source-based audit matched every ordered candidate ID with zero
mismatches; maximum independently computed cosine-distance error was 3.33e-16.
It also verified native identity/fold/component fields, original abstentions,
query vectors and all three saved-input file pins. `results.json` retains this
audit and the pinned artifact/protocol identities.

This is historical model-rank-profile similarity only. No fresh-feature
inference, acoustic similarity, listener relevance, held-out quality, FMA518
result, generalization or product promotion is established. Source targets are
not inputs to retrieval. The ordinary membership replay retains its existing
separate verification of historical metrics; evaluation gates are unchanged.
