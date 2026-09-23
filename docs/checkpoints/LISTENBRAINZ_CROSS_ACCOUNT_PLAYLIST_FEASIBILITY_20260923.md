# ListenBrainz cross-account playlist feasibility checkpoint

This is a read-only, local-only feasibility checkpoint. It changes no model,
source policy, static asset, deployment, release artifact, or existing
single-account cohort.

## Result

Cross-account acquisition was not run. On 2026-09-23 UTC, one bounded public
request to the documented search route,
`https://api.listenbrainz.org/1/playlist/search?query=music`, was attempted
with a 15-second deadline. It timed out before receiving response bytes. The
first sandboxed attempt could not resolve `api.listenbrainz.org`; the one
approved external retry likewise produced no body before its deadline.

A further external retry of the same URL and deadline on 2026-09-23 reached
the host, but it returned MetaBrainz's JavaScript browser-verification HTML
rather than an API JSON body. The response is not retained as a source
response, because it has no search payload and cannot support account or
playlist selection. No further retry, pagination, account enumeration, or
fallback source was attempted. This checkpoint deliberately contains no
account names or other user identifiers.

Consequently there is no auditable search response, raw JSPF, account listing,
playlist selection, or cross-account support measurement to retain.

The official API documentation says that playlist search matches public
playlist titles and descriptions, the query must have at least three
characters, and `/1/user/(playlist_user_name)/playlists` returns playlist
metadata without recordings. It also documents the exact playlist endpoint.
These routes can establish only service-level route facts, never a human,
manual/editorial selection, genre, quality, or independent-listener claim.

The official API documentation was checked again on 2026-09-23 for a global,
popular, recent, or otherwise username-free public-playlist listing. It
documents no such route. A public listing requires a known
`playlist_user_name`, and a full playlist requires a known playlist MBID.
The only documented unauthenticated discovery route is title-and-description
search. The service import routes require authorization. Therefore no alternate
read-only request can discover a second public account without either the
blocked search response or a pre-supplied account or playlist identifier.

## Bounded retry design

When API connectivity is available, use one neutral, predeclared search query
only as a discovery mechanism. Its text and search rank must not become a
genre label, relevance score, or sample-quality signal. From that one response
choose at most three distinct declared creator-account strings, in returned
order, after removing duplicates. For each selected account, request exactly
one first-page public created-playlists listing with `count=2`, then select at
most its first two valid, unique playlist UUIDs. Fetch those explicit playlist
UUIDs through `GET /1/playlist/(playlist_mbid)` only.

That plan has a hard maximum of ten HTTP calls: one search, three account
listings, and at most six JSPF playlist fetches. It stops early on any failed
request, malformed response, duplicate playlist UUID, rate-limit warning, or
response that cannot be retained under the custody limits. It makes no
pagination requests and does not probe `createdfor`, collaborator, private,
or authenticated routes.

Every request must use HTTPS, a contactable User-Agent in the documented
`Application/version ( contact-url-or-email )` form, a per-request timeout,
and no more than one request per second. The client must inspect
`X-RateLimit-Remaining` and `X-RateLimit-Reset-In` on each response and stop
instead of exceeding the advertised allowance. A 429 is terminal for that
run.

For every successful listing and exact-playlist response, retain locally only:

- the exact source URL, UTC fetch time, byte count, and SHA-256 body hash;
- the unmodified body, content-addressed under `raw/sha256/<body_sha256>`;
- the raw JSPF playlist response for every selected playlist; and
- a receipt-bound snapshot bundle whose source playlist IDs are verified
  against the corresponding account-listing body.

The raw custody directory, listing responses, and any mapping between a local
account slot and a source URL remain local-only. They are not static assets or
release inputs.

## Derived-output boundary

Any derived report that leaves local custody may expose only aggregate counts,
such as `declared_account_support_count`, `playlist_count`, and exact-recording
coverage. It must not expose account strings, listing URLs, creator fields,
playlist titles/descriptions, search text, or raw JSPF. Account support means
only that distinct service-declared account strings had retained public
created-playlists listing routes; it is not independent listener support.

This prospective cohort remains `local_only=true`, `export_allowed=false`,
`serving_allowed=false`, and `independent_genre_evaluation_eligible=false`.
It must set `human_curation_established=false` and
`manual_or_editorial_curation_established=false` for every playlist. Playlist
order and exact recording co-occurrence may be measured as source-order
metadata only; they do not establish a genre, a human curation fact, or a
model input.

## Decision

The official route design is feasible in principle, but the current network
attempt yielded no auditable body. Keep the existing one-account cohort
unchanged and do not claim cross-account support until a future, separately
retained bounded run completes with every required listing receipt, raw JSPF
object, and exact playlist receipt.

Sources: [ListenBrainz playlist API](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html)
and [ListenBrainz API requirements](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html).
