# ListenBrainz playlist and Last.fm 360K matched holdout

This local-only receipt compares one retained ListenBrainz JSPF playlist cohort
with the completed Last.fm 360K privacy-filtered artist aggregate. It uses exact
MusicBrainz artist MBIDs only. It is not genre truth, a cross-account result,
a human-curation result, a similarity claim, a model input, a serving input,
or a public release input.

## Inputs and receipt binding

The evaluator reads the existing JSPF embedded artist identifier receipt at
`.cache/listenbrainz-playlist-embedded-artist-ids-20260923/receipt.json`. Its
SHA-256 is `a56d079120d7948d9250ba8474c47bc1a7a75a4793cd0a880d7decdc6021f188`,
and it binds its source playlist bundle to SHA-256
`2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`.
This evaluator does not reread JSPF raw objects. It relies on that existing,
receipt-bound derived measurement.

The expected SHA-256 is a required evaluator input. The evaluator hashes the
derived receipt bytes before Pydantic parses them, and rejects any valid-shaped
replacement whose bytes do not match the required pin. This is receipt binding
to a derived measurement, not a replay of the raw JSPF source objects.

It verifies the completed Last.fm v1 artifact, its companion privacy receipt,
and the local aggregate SQLite file before querying. The aggregate contains
only pairs retained at five distinct users or more. The report records all
input hashes and validates its own logical output hash on read.

## Fixed cohort and comparison

The positive rule was fixed as an unordered exact artist pair that appears in
at least two distinct playlists. This produces 171 repeated pair potentials
from the one-account JSPF cohort. These are source positives for this
comparison, not independent truth.

Each of the 46 positive-anchor artists ranks every other one of the 344 source
artist IDs. The Last.fm arm ranks by retained distinct-user support. A missing
Last.fm edge has score zero. Equal scores use the same seeded SHA-256 artist-ID
order as the baseline. The baseline ranks the same candidate set only by that
seeded SHA-256 order. The report gives both 171 undirected pair counts and 342
directed ranking events, so the ranking expansion does not replace the pair
denominator.

## Results

| Measure | Count or rate |
| --- | ---: |
| Exact JSPF artist IDs in candidate universe | 344 |
| JSPF cross-recording pair potentials | 13,584 |
| Last.fm supported pair potentials | 1,789, 13.1699% |
| Repeated JSPF source positives | 171 |
| Last.fm recovered source positives | 41, 23.9766% |
| Unsupported source positives | 130 |
| Last.fm Recall at 10 | 36 of 342, 10.5263% |
| Baseline Recall at 10 | 6 of 342, 1.7544% |
| Last.fm mean reciprocal rank | 4.4565% |
| Baseline mean reciprocal rank | 1.4826% |

The 41 recovered pairs show cross-source agreement under this fixed local
comparison. The 130 unsupported pairs are not negatives. They can be absent
because the historical aggregate did not retain the pair, the sources cover
different populations or periods, or the playlist cohort is small. The result
therefore does not establish general pair quality or any claim about music.

The ignored local report is
`.cache/listenbrainz-playlist-lastfm-360k-matched-holdout-v1/report.json`.
Its logical SHA-256 is
`b14915837e89e71a766aeb86741951083afa26d7b63251cb66dcc5dd8d8e2954`.

## Local reproduction

Run this command only against the retained local inputs. The script refuses to
replace an existing output, writes only below `.cache` after resolving
symlinks, and does not make network requests.

```sh
.venv/bin/python scripts/evaluate_listenbrainz_playlist_lastfm_holdout.py \
  --playlist-receipt .cache/listenbrainz-playlist-embedded-artist-ids-20260923/receipt.json \
  --playlist-receipt-sha256 a56d079120d7948d9250ba8474c47bc1a7a75a4793cd0a880d7decdc6021f188 \
  --lastfm-artifact .cache/lastfm-360k-full-aggregate-v1/artifact.json \
  --lastfm-companion-receipt .cache/lastfm-360k-full-aggregate-v1/receipt.json \
  --lastfm-database .cache/lastfm-360k-full-aggregate-v1/aggregate.sqlite \
  --output .cache/listenbrainz-playlist-lastfm-360k-matched-holdout-v1/report.json
```
