# ListenBrainz review-candidate H3 evaluation

The v5 evidence frontier is an upgrade of the sealed Wikidata-fused v4
frontier. It receipt-verifies the v4 aggregate and the sealed ListenBrainz v2
artifact before adding only per-seed derived-review candidate counts. It does
not reopen raw MusicBrainz, Wikidata, taxonomy, peer, or hierarchy inputs, and
it never reads H3 during construction.

The sealed local v5 run is
`.cache/all-seed-evidence-frontier-v5-sealed/artifact.json` with logical hash
`edf01e96b8ab12d7c90b49cf9119aa5fb0a01ccdea253924b7923ed3e0ecbef8`.
It preserves v4's 2,377 MusicBrainz and 292 Wikidata direct-observation seed
counts (291 overlap), peer/hierarchy summaries, and all 6,291 rows. The added
review source has 23,497 candidates across 425 seeds; all 425 overlap a direct
observation, so it creates zero new factual membership or seed coverage. It
only adds review-queue evidence to already directly observed seeds.

`evaluate-listenbrainz-propagation-h3.py` is a separate, downstream,
positive-only evaluation. It receipt-checks the sealed v5 and ListenBrainz
inputs, streams top-50 review candidates, then joins H3 page-member rows only
through accepted Spotify-to-MusicBrainz bridge identities. Missing H3 rows are
never negatives and no result is fed back into v5.

The current local evaluation artifact is
`.cache/listenbrainz-h3-evaluation-v2/artifact.json`, logical hash
`7cbcd8b6859fd8207ac271c9564963f96fea9bfe57d8cc1541c125d4fa2fb6bb`.
It resolves 120,163 unique H3 positives only through the bridge. The review
artifact covers 425 of 6,069 H3-positive genres and abstains on 5,644. Its
top-50 queue contains 11,252 predictions in the candidate-available subset:
179 hits among 15,772 positives, conditional recall@50
`0.011349226477301548`. Precision is unavailable: H3 is positive-only, so a
prediction absent from H3 is unknown rather than a false positive.

The global positive-only recall uses every 120,163 bridge-resolved H3 positive
as denominator, including abstained genres: `0.0014896432346063265`. No null
baseline or lift is reported because this positive-only data does not define a
false-positive rate. These weak retrieval
metrics are not factual membership claims and cannot feed back into v5.
