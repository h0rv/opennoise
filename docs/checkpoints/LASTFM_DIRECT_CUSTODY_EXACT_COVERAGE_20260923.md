# Last.fm 360K and direct-custody exact-ID coverage

This is a local-only feasibility count, not retrieval, evaluation, training,
ranking, genre quality, or a release input. It joins exact MusicBrainz artist
MBIDs only. The report emits no user identifiers, artist names, artist IDs,
seed IDs, pairs, or genre IDs.

The sealed Last.fm aggregate remains expressly ineligible for model input. Its
verified source report/receipt/database hashes are bound in the ignored local
report, as are the pinned direct proper-genre custody receipt bytes
(`41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615`), its
logical output, and its content-addressed claims object.

| Exact-MBID aggregate | Count |
| --- | ---: |
| Direct-custody artists / seed-artist pairs / seeds | 198,409 / 387,435 / 697 |
| In Last.fm observed artist endpoints | 43,173 / 89,657 / 653 |
| In endpoints of a retained >=5-user Last.fm pair | 12,037 / 34,699 / 596 |

The Last.fm sealed database has 160,131 observed artist endpoints, 485,840
retained privacy-floor pairs, and 18,001 endpoints among those pairs. These
counts indicate only possible exact-ID join capacity. Direct custody is a
MusicBrainz proper-genre source, while Last.fm is a listening source; this
does not establish independent genre gold or any predictive performance.

Local reproduction writes an ignored, non-overwritable report:

```sh
.venv/bin/python scripts/audit_lastfm_direct_custody_exact_coverage.py \
  --lastfm-artifact .cache/lastfm-360k-full-aggregate-v1/artifact.json \
  --lastfm-companion-receipt .cache/lastfm-360k-full-aggregate-v1/receipt.json \
  --lastfm-database .cache/lastfm-360k-full-aggregate-v1/aggregate.sqlite \
  --direct-custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --direct-custody-receipt-sha256 41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615 \
  --direct-custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --output .cache/lastfm-360k-full-aggregate-v1/direct-custody-exact-coverage.json
```
