# MusicBrainz artist-credit static overlap

This is a read-only, exact-MusicBrainz-ID checkpoint for the local artist-credit
candidate. It makes no name, alias, label, or genre inference; it does not alter
the candidate, public database, static asset, or any serving output.

## Hash-bound inputs

| Input | SHA-256 |
| --- | --- |
| Local artist-credit candidate | `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63` |
| Current public SQLite | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |
| Current static discovery | `b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8` |
| Derived local overlap report | `39b5cec877558a93938670f7d5b7df5c02808f3647f4d14e4dfad363be5dce89` |

The static payload declares the same public SQLite hash. The candidate contains
352 exact artist MBIDs, 87 exact release MBIDs, and 1,031 exact recording MBIDs.

## Exact-ID result

The current public direct-claim view has 1,209 artist MBIDs. Exactly 121 of the
352 candidate artist MBIDs overlap it. Those 121 public-direct artists have 654
direct observations across 214 public genres.

Static discovery exposes 1,008 artists. Exactly 101 candidate artist MBIDs
overlap those artists, covering 300 displayed direct memberships across 118
static genres. The remaining 20 public-direct overlaps are outside the static
asset's current bridge scope; this checkpoint neither explains nor fills that
gap.

Within the local candidate only, 68 releases and 737 recordings have an
artist-credit member whose exact MBID is one of the 101 static-overlap artists.
These are a bounded *metadata-example scope*, not selections or rankings.

## Publication boundary

MBID equality proves only that the candidate and public record refer to the
same artist. It does not create, strengthen, or transfer an artist-to-genre
claim. The candidate remains local, non-serving metadata. A separate
identity/provenance/policy decision is required before exposing any release or
recording. If allowed later, it must be explicitly labeled MusicBrainz credit
metadata and must not be presented as a quintessential-album claim.

Reproduce the derived report with:

```sh
.venv/bin/python scripts/audit_musicbrainz_artist_credit_static_overlap.py \
  --candidate .cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite \
  --public-database data/public.sqlite \
  --static-discovery dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json \
  --report .cache/musicbrainz-catalog-expansion-v1/artist-credit-static-overlap-v1.json
```
