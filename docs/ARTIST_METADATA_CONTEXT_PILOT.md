# Artist metadata context pilot

This is a separate, local-only MusicBrainz metadata pilot. It does not change
the catalog, default UI, source archive projection, artist memberships, or
model inputs. In particular, source country, area, and begin-area are retained
as provider-qualified observations only. They are not inferred current
residence, nationality, origin, or genre claims.

## Completed run

The immutable query manifest selected exactly 50 unique MusicBrainz artist
IDs: ten lexicographically ordered direct anchors from each of five fixed seed
cohorts: `item5` (hip hop), `item94` (house), `item379` (jazz), `item577`
(post-punk), and `item675` (cumbia). It is bound to the release-group evidence
SQLite SHA-256
`980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a`.

The final cache-only replay artifact is at
`.cache/artist-metadata-context-pilot-v1/artifact.json`.

| Measure | Observed value |
| --- | ---: |
| Cumulative original network attempts | 50 |
| Requests in final replay | 0 |
| Final replay cache hits | 50 |
| Successful typed source responses | 31 |
| Recorded failures | 19 |
| Country field present | 27 / 31 |
| Area field present | 27 / 31 |
| Begin-area field present | 13 / 31 |
| Alias rows | 4 across 2 artists |
| Canonical source names | 31 / 31 |

The source cache records exact success request URLs, receipt timestamps, raw
content SHA-256 values, byte sizes, and immutable content-addressed response
paths. Failed attempts retain their exact request URL and failure kind in the
request cache. The 19 failures are transient acquisition outcomes, not source
absence: 17 `ReadTimeout` and 2 HTTP 503 errors. No failure response body was
cached, and no `Retry-After` value was available in this run. No cached failure
is retried automatically. A later retry must be a separately versioned and
explicitly bounded policy rather than a cache bypass.

The query-manifest SHA-256 is
`999afe7f43c342251f1f036dc33d10cb5422dc8c0ae69ac18e781f7e35d2916e`.
The raw-source-manifest SHA-256 is
`c9d90fa4a05d9b1407d6f5d8a22e53beb8aac63f1f7e3e07d2ce35498c833438`.
The derived projection SQLite SHA-256 is
`7e55507a586af2c1fd119424fdc185a42901b941e05d96738f7f26419ef56f24`.

## Next model use proposal

Do not train or promote from this pilot. If a user elects a future experiment,
candidate inputs are source-qualified region fields and artist tag/style
features with explicit missingness. They must remain candidates, not inferred
facts, and must use a split that prevents the same artist or release group
from supplying both training and evaluation evidence.
