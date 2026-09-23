# MusicBrainz direct static publication readiness

## Decision

The 412 placed candidate-only genres have a source-replayed local preparation
path, but they have no public release path under the current policy. A future
release must use a new, reviewed discovery revision and promotion receipt. It
must not change the existing `static-direct-discovery-v2` contract or treat the
local candidate as an approval.

MusicBrainz describes genres as a selected part of its tag system. Its API can
return the genres proposed for an artist with `inc=genres`, and describes
genres as subjective. The public source label should therefore say
"MusicBrainz proper-genre observation on this artist record." It should not
claim an independently verified genre assignment or use release, recording,
peer, non-genre tag, alias, or inferred evidence as an artist observation. [MusicBrainz
Genre documentation](https://musicbrainz.org/doc/Genre) and the [MusicBrainz
API documentation](https://musicbrainz.org/doc/MusicBrainz_API) describe this
scope.

## Current evidence and boundary

The local candidate is derived from 697 reconciliation-safe source seed IDs.
It has 412 placed candidate-only seed IDs, 139,268 exact artist and genre rows,
and 503 bounded JSONL shards. The other 11 candidate-only seed IDs are
unplaced and remain absent. The candidate checks its complete direct source
and exact-name scope against the custody objects before it writes.

The source record for every included row is exactly
`musicbrainz:artist:<MBID>`. The row retains its source record SHA-256 and
source evidence reference. The candidate schema cannot represent non-genre tag
rows, release rows, peer rows, aliases, or inferred rows. Those properties support a
future direct-observation source role, but do not authorize it today.

The current portable custody receipt fixes `public_export_authorized` to
`false`. The candidate manifest separately fixes public export, serving,
membership claims, and its release gate to `false`. The current public v2
adapter is also intentionally fixed to the sealed public database, the 260
exact-label genres, the 84 QID-position genres, and their pinned bridge chain.
Its promotion receipt has literal coverage values of 344 genres, 1,126 artists,
and 3,859 observations. It cannot accept the MusicBrainz candidate without a
new contract.

## Required approvals and checks

Before any implementation writes a public asset, a reviewed policy decision
must authorize a separate source role named for literal MusicBrainz artist
proper-genre observations. The decision must state the public wording, allow
the three portable custody objects to be used for static discovery, and keep
them excluded from the public model, map layout, and release or recording
membership paths. It must also say whether MusicBrainz genre tags are shown as
source observations only, which matches the source's own scope.

The future builder must perform all of the following checks.

- Verify the direct custody receipt and compressed claim object, then verify
  the canonical and recovered exact-MBID name receipts and their binding to
  the same direct claim object.
- Recompute `(direct custody IDs minus current public discovery IDs) intersect
  placed atlas IDs` and require exactly the approved seed set. Require every
  emitted pair to have one exact artist MBID, one exact artist record identity,
  one reconciled MusicBrainz genre ID, one source record hash, one evidence
  reference, and one display name. Reject duplicates, unplaced IDs, and every
  excluded evidence role.
- Keep the semantic atlas bytes and all map positions unchanged. Verify each
  served node against the certified atlas and record the atlas pin.
- Add a reviewable quality report before approval. The report should include
  source coverage, duplicate and exclusion counts, names rejected for
  ambiguity, per-genre row counts, and a manually sampled set of public source
  links. A coverage increase alone is not a quality approval.

## Required payload and browser gates

The new discovery revision must retain the v1 and v2 payloads unchanged. It
needs a typed evidence variant for the MusicBrainz source role, a source-count
partition that replays every evidence row, reciprocal artist and genre
memberships, and a self-hashed promotion receipt that pins the three custody
receipts and objects, the approved candidate manifest, the base discovery
asset, and the semantic atlas. It must reject a receipt whose policy approval,
source role, coverage, or payload bytes differ from the reviewed values.

Static export must consume the new payload only when its promotion receipt
replays. The manifest must bind the payload logical hash, file hash, byte
count, revision, coverage, and promotion receipt hash. Browser certification
must cover a MusicBrainz-sourced genre, artist search, a deep artist link,
Back to the genre, direct-overlap peers, and the source wording and MusicBrainz
artist link. The test must also prove that a v1 or v2 release does not display
the new source role.

## Next implementable step

Write a policy-review input, not an exporter. It should pin the existing direct
custody receipt `a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9`,
the local candidate manifest
`a8f0059e7c53c802af88f27d473f6fec35b8e2f137218470e9fc3bee1b71ee70`,
the exact 412 seed IDs, the proposed public source wording, and the required
quality report. A reviewer can then approve or reject the new source role
without modifying custody policy, `dist`, deployment, or the sealed v2 chain.
