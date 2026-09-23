# ListenBrainz playlist signal quality audit

This is a local-only measurement of the retained ten-playlist ListenBrainz JSPF
cohort and its exact MusicBrainz artist-credit bridge. It changes no model,
static output, source policy, or release artifact.

## Result

The report is at
`.cache/listenbrainz-playlist-signal-quality-audit-v1/report.json`. Its logical
SHA-256 is `c7ca5e0b25f59bf231fe6dc281d14a65d72b017f9d02413425e8347b14030446`.
The direct local run completed in about 0.9 seconds and made no network request.

It pins the existing route-only cohort receipt
`dd1d3f8a5bcce73bdd28b16fb93acf23d73a2359417e4c76a6bdfa2f1f15610a`, the
exact-credit bridge receipt
`5bcb50b190685ec6b4d9352ec1426f2f0eec1eb3edd5c45bc1ae675747f52bb7`, and the
shared playlist bundle `2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`.

The selected-recording mapping has 27 playlist occurrences. Exact artist credits
cover 26 occurrences and 23 distinct artist IDs. Within that small sample there
are 30 playlist pair observations, 29 distinct pairs, and one pair occurring in
two playlists. No pair occurs in more than two playlists.

The existing sealed Last.fm 360K aggregate contains 5 of the 29 exact-credit
pairs at its five-distinct-user privacy floor, a 17.2414% overlap. Its largest
support among those retained pairs is 2,448 distinct users. This is only a count
comparison with a historical all-time aggregate. It is not a quality benchmark,
similarity result, negative label, or music claim. The earlier 171 repeated-pair
source-claim holdout remains separate because it uses JSPF embedded artist IDs,
not this smaller exact-credit sample.

All ten playlists remain service-listed under one account with unknown curator
state. The audit makes no independent-curation, manual/editorial, cross-account,
or genre claim.

## Reproduction

```sh
.venv/bin/python scripts/audit_listenbrainz_playlist_signal_quality.py \
  --cohort .cache/listenbrainz-user-created-playlist-cohort-20260923/cohort.json \
  --cohort-sha256 dd1d3f8a5bcce73bdd28b16fb93acf23d73a2359417e4c76a6bdfa2f1f15610a \
  --artist-bridge .cache/listenbrainz-playlist-artist-bridge-20260923/bridge.json \
  --artist-bridge-sha256 5bcb50b190685ec6b4d9352ec1426f2f0eec1eb3edd5c45bc1ae675747f52bb7 \
  --lastfm-artifact .cache/lastfm-360k-full-aggregate-v1/artifact.json \
  --lastfm-companion-receipt .cache/lastfm-360k-full-aggregate-v1/receipt.json \
  --lastfm-database .cache/lastfm-360k-full-aggregate-v1/aggregate.sqlite \
  --output .cache/listenbrainz-playlist-signal-quality-audit-v1/report.json
```
