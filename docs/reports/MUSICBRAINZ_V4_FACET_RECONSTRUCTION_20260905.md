# MusicBrainz v4 facet reconstruction

Status: completed local research reconstruction, 2026-09-05.

The v4 prefix-0 reconstruction was replayed after the stable-ID reconciler
started treating an exact MusicBrainz genre UUID and an exact MusicBrainz tag
name as corroborating facets of one retained Every Noise seed. Multiple
identifiers in either one facet, and one source identity assigned to multiple
seeds, still remain ambiguous. No historical Every Noise observations entered
construction.

## Reconstruction recovery

| Measure | Previous v4 | Facet-aware v4 | Change |
| --- | ---: | ---: | ---: |
| Reconciled seeds | 48 | 359 | +311 |
| MusicBrainz-only seeds | 317 | 704 | +387 |
| Ambiguous seeds | 735 | 37 | -698 |
| Accepted stable seed genres | 365 | 1,063 | +698 |
| Accepted direct memberships | 1,155 | 42,093 | +40,938 |
| Accepted artists | 1,026 | 11,402 | +10,376 |
| Peer candidate pairs | 14 | 2,811 | +2,797 |
| Directional peer rows | 28 | 4,213 | +4,185 |

The facet-aware reconciliation artifact is
`seed-reconciliation-v2` with logical SHA-256
`e453febf0691591f25c76e6c24ad03e002d6e7250bca015b482f754666e92af0`.
The bridge report is `reconstruction-seed-bridge-v2` with logical SHA-256
`8c15806d9cee724ab753bdab1d4a470263075412db37e89fbd5e58246ede2959`.
The peer candidate and gate are version 4; the gate passed and the candidate
logical SHA-256 is
`94c011b9a6324c5baca958683e3314365bcff22ead0dfc4c64f28ec95ca4b831`.

## H3-only evaluation

Evaluation used `.cache/musicbrainz-20-catalog/public.sqlite` as the strict
artist-name crosswalk and the custody-pinned H3 membership database with
SHA-256 `098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`.
The report contains 1,063 name-matched genres and uses `k=25`; historical data
was used only after peer construction.

| Candidate | Matched genres | Micro precision@25 | Micro recall@25 | Macro precision@25 | Macro recall@25 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior v4 bridge | 365 | 0.142857 | 0.048193 | 0.091667 | 0.022464 |
| Prior v3, same crosswalk | 756 | 0.155322 | 0.452087 | 0.146253 | 0.467979 |
| Facet-aware v4 | 1,063 | 0.166152 | 0.294613 | 0.143903 | 0.271772 |

Against the prior v4 bridge, micro precision rose by `0.023295` and micro
recall by `0.246420`. The broader facet-aware universe is not directly
comparable to v3: it adds 307 matched seed genres, and its micro recall is
`0.157474` lower than the narrower v3 candidate. The current result still
exceeds its uniform null baseline: micro precision `0.006153` and recall
`0.010911`. The report's logical SHA-256 is
`4b37df726fe6a358b58b741c742ec2481f69837927ae7852b8fdf869f7b3587f`.
