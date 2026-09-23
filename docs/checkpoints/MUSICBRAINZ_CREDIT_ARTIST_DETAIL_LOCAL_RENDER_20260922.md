# MusicBrainz credit artist-detail local render

The isolated local renderer is an operational preview seam for the next
artist-detail step. It consumes an already approval-gated
`musicbrainz-credit-static-metadata-v1` asset and the exact v2 static-discovery
bytes named by that asset, then exports one caller-selected artist to an
explicit, new local JSON path under a caller-supplied existing `.cache` root.
It does not read candidate SQLite, custody
scope, or an approval file, and cannot create an approval or choose `dist`.

Before rendering, it replays the v2 discovery parser and requires all of the
following:

- the credit asset's static-discovery SHA-256 equals the supplied bytes;
- the credit asset and discovery bind the same public database SHA-256;
- every credit row has an exact static artist ID to MusicBrainz artist-ID
mapping, with no name or genre fallback;
- row accounting and deterministic source order replay; and
- the requested artist has at least one retained source-bound credit row.

The JSON payload labels its only content `MusicBrainz credit metadata` and
declares `local-candidate-only-not-authorized-for-publication`. It includes
a release or recording title, ordered credited names, and the exact entity,
artist, and provenance identifiers that bind those source rows. It contains no
genre, membership, map, score, rank, representative, selection, or discovery
content. The export rejects output outside that explicit `.cache` root and a
`.cache` directory under this repository's `dist` tree.

After `poe sync`, an operator who already has a separately approved local
credit asset can render a non-public preview with:

```sh
.venv/bin/python scripts/render_local_musicbrainz_credit_artist_detail.py \
  --credit-metadata /path/to/musicbrainz-credit-metadata.json \
  --static-discovery /path/to/static-discovery.json \
  --static-artist-id artist:123 \
  --local-root .cache \
  --output .cache/musicbrainz-credit-artist-detail.json
```

The focused integration fixture first runs the existing strict gate and then
renders its resulting asset. It additionally rejects a static-ID-only row with
a different MusicBrainz ID and a credit asset bound to different discovery
bytes. This is local rendering evidence only: UI approval, public static-page
integration, browser certification, and deployment remain separate.
