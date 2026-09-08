# Public artist navigation API

The local API exposes only direct, display-authorized artist-to-genre claims from
`displayable_artist_genre_evidence`. It does not use Open construction review
anchors, H3 historical memberships, one-hop model memberships, or learned artist
similarity.

With `uv run poe dev` running, begin from an existing catalog genre ID:

```sh
curl 'http://127.0.0.1:3001/api/genres/2/artists?limit=20'
```

Each member includes typed IDs such as `catalog:artist:1`, direct source evidence,
and source method/version. Follow the numeric `entity_id` in the response:

```sh
curl 'http://127.0.0.1:3001/api/artists/1'
curl 'http://127.0.0.1:3001/api/artists/1/genres?offset=0&limit=20'
curl 'http://127.0.0.1:3001/api/artists/1/related?offset=0&limit=20'
```

`related` results always state `method: "shared_direct_genre"` and list the exact
shared catalog genres. They are not a learned-similarity or listener-behavior claim.
Known artists or genres with no display-authorized direct claims return `200` with an
empty list; unknown catalog IDs return `404`. Page limits are 1 through 50.
