# Last.fm reverse tag evidence

`build-lastfm-reverse-tag-evidence` is an optional, review-only long-tail
source adapter. It selects only `review_only`, `ambiguous`, and `unresolved`
seed dispositions from a sealed reconciliation artifact. It does not read H3,
Every Noise historical construction data, audio, Spotify, or a catalog artist
name index.

For every selected seed label it records a credential-free `tag.getTopArtists`
query in an immutable query manifest. A source claim is retained only when the
top-artist response supplies a valid MusicBrainz artist ID and
`artist.getTopTags`, queried with that same ID, contains an exact normalized
copy of the seed label. The adapter does not turn a Last.fm artist name into an
MBID. Missing or invalid MBIDs remain name-only review rows; noncorroborated
MBID rows abstain. No result promotes an observed identity, membership,
taxonomy fact, or hierarchy edge.

The adapter is async-first and bounds concurrent request starts, request rate,
response bytes, retry attempts, selected labels, and artists/tags per
response. The response-byte limit is checked for cache hits before any parser
reads them, including offline replay. It first uses its local response cache. Every parsed raw JSON
response is then pushed under a content-addressed ObjectStore key, and the
publication receipt binds the raw objects, query manifest, and review artifact.
The API credential is never written to a manifest, cache path, artifact,
receipt, or command output.

```bash
export MUSIX_LASTFM_REVERSE_TAG_QUERY_MANIFEST=.cache/lastfm-reverse-tag/query-manifest-v1.json
export MUSIX_LASTFM_REVERSE_TAG_RESPONSE_CACHE=.cache/lastfm-reverse-tag/responses
export MUSIX_LASTFM_REVERSE_TAG_OUTPUT=.cache/lastfm-reverse-tag/lastfm-reverse-tag-evidence-v1.json
export MUSIX_LASTFM_REVERSE_TAG_OBJECT_STORE=.cache/lastfm-reverse-tag/objects
export MUSIX_LASTFM_REVERSE_TAG_RECEIPT=.cache/lastfm-reverse-tag/lastfm-reverse-tag-evidence-v1.receipt.json
uv run poe build-lastfm-reverse-tag-evidence
```

The command writes the reproducible query manifest before any network request.
If `LASTFM_API_KEY` is not set, it stops with status 2 after writing that plan;
this is the expected safe outcome for a checkout without a key. It never
attempts a live request in that state. Fixture or prior-cache replay is explicit
through the script's `--offline` flag and fails closed on a cache miss or
malformed raw response.

Last.fm documents [`tag.getTopArtists`](https://www.last.fm/api/show/tag.getTopArtists)
as returning top artists for a tag, including optional MBIDs, and
[`artist.getTopTags`](https://www.last.fm/api/show/artist.getTopTags) as
accepting an artist MBID. Their presence is source evidence only, not an
independent adjudication of genre identity.
