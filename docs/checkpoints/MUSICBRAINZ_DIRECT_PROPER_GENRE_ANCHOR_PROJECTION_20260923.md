# MusicBrainz direct proper-genre anchor projection

This local-only review projection asks one deliberately narrow question about
the 11 identity-safe, unplaced MusicBrainz proper-genre seeds: does an exact
artist record occur in exactly one of those unplaced seeds and exactly one
currently positioned seed? It does not construct a layout or membership.

The replayed artifact is
`.cache/musicbrainz-direct-proper-genre-anchor-projection-v1/report.json`.
Its logical hash is
`34866c9b1959fd416b0c032dd37c4e9867df21c0ca268fac30cc8a83afbf3afa`.

It byte-binds the portable proper-genre custody receipt
`41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615`
and uses the supplied v3 layout only to partition seed IDs into 2,945
positioned and 3,346 unplaced IDs. Coordinate values are never retained or
emitted. The embedded layout logical hash is recorded but not independently
certified by this experiment.

## Result

Two of the 11 frontier seeds have exactly one exclusive positioned anchor:

| Unplaced seed | Positioned anchor | Exact MusicBrainz artist MBID |
| --- | --- | --- |
| `item2467` (`tallava`) | `item166` (`folk`) | `966de8b0-0c41-46ac-947d-e5749b7165a9` |
| `item4482` (`marching band`) | `item2595` (`brass band`) | `ac1f0959-c578-4042-a947-0483df296e9e` |

Each proposed row carries both exact source-record IDs, record hashes, and
evidence references. The remaining nine seeds are preserved as abstentions:
eight have multiple positioned anchor seeds and one (`item5741`,
`guggenmusik`) has no positioned artist overlap. An artist shared by more than
two retained seeds is never used as an anchor. This prevents a hub or a
competing neighborhood from being silently chosen.

The report fixes `public_export_authorized=false`,
`historical_assignments_read=false`, and
`tags_or_release_or_peer_rows_used=false`. It is not an input to public data,
serving, or layout placement.

Reproduce locally:

```sh
.venv/bin/python scripts/build_musicbrainz_direct_proper_genre_anchor_projection.py \
  --custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --layout .cache/semantic-map-layout-v3/artifact.json \
  --output .cache/musicbrainz-direct-proper-genre-anchor-projection-v1/report.json
```

The writer refuses an existing output and any path outside `.cache`.
