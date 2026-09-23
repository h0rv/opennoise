# MusicBrainz direct exact-MBID name join frontier

This is a bounded, local-only accounting checkpoint. It joins the verified
portable direct proper-genre custody object to the separately verified
canonical artist-name custody object by exact MusicBrainz artist MBID only. It
does not create memberships, change static discovery, write `dist`, authorize
export or serving, or infer similarity.

## Pinned inputs

Both receipt *bytes* were pinned before parsing so a self-consistent substitute
receipt cannot select another cohort.

The report also accepts an optional exact-MBID recovery receipt and object
store. When supplied, it verifies the recovery receipt bytes and requires its
direct and canonical-name custody bindings to match the two pinned inputs.
Only recovery rows marked `unique_canonical_name` are unioned by MBID; a
duplicate MBID is rejected. This remains a local-only accounting path: its
report flags stay false for public export, serving, membership claims, and the
release gate. Omitting all three recovery arguments preserves this baseline.

| Input | Receipt-byte SHA-256 | Embedded logical output SHA-256 | Bound object SHA-256 |
| --- | --- | --- | --- |
| Direct proper-genre custody | `41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615` | `a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9` | `b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e` |
| Canonical artist-name custody | `06445802bec5120d2068dfb51afc610211063f72994c1862bbc8bad05dda4f25` | `3c2cf86d2bc2de7014594c90337ff8c8cd18c4125cbe06ca0d589a02b3861dcb` | `48a9854906c5e430acadae70371165e7c21a6d0e365e9a24177e2e5a37fc7291` |

The name receipt also binds the direct receipt byte hash, direct receipt output
hash, and direct claims-object hash. The existing manifest-bound delta report
supplies the certified 423 candidate-only seed IDs relative to the current
344-seed static discovery asset (`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`).

## Exact-ID result

The unit of coverage is a distinct exact `(seed_id, artist_mbid)` direct pair,
not a global artist count. A pair is named if and only if the pair exists in
the verified direct stream and exactly one verified canonical-name fact has the
same MBID. Identical name text on another MBID does not match. Repeated direct
observations for one pair remain one pair.

| Candidate-only scope | Count |
| --- | ---: |
| Seeds | 423 |
| Distinct direct artist pairs | 139,398 |
| Named direct artist pairs | 115,269 |
| Unnamed direct artist pairs | 24,129 |
| Exact display coverage | 82.6905694486291% |

The deterministic report includes one lexically ordered row for every
candidate-only seed, with `direct_artist_pair_count`,
`named_direct_artist_pair_count`, and `unnamed_direct_artist_pair_count`.
Source claims and name facts are streamed into separate temporary SQLite tables
and joined only in the aggregate query. No 387k-model in-memory collection is
made.

## Recovery-supplemented local result

The completed recovery receipt has byte SHA-256
`0282dc6c7f2f99828b2aedf64c370d32a5a69bfa4322c153a13fe755ad92693b` and
logical output SHA-256
`cccb11be61d74adea12f8f0eec32bbece4bc93aadf25e8d0abd5f96ba7193a7b`.
Its verified object SHA-256 is
`192c564e9b6a0eea26a2b00d80d13338a58616bec80d5d2da513468c64191939`.
A fresh local report using the optional recovery input retained the same 423
candidate-only seeds and 139,398 direct pairs, and raised named pairs from
115,269 (82.6905694486291%) to **139,398 (100%)**. Unnamed pairs fell from
24,129 to zero. This is local accounting only; it did not write `dist`, change
the sealed discovery asset, or authorize serving or export.

## Size boundary

An honest, derivable lower-bound shape is available, but it is not a production
asset or an approved payload: canonical JSONL rows sorted by `(seed_id,
artist_mbid)` with only `artist_mbid`, `canonical_name`, and `seed_id`. A
streaming SQLite query measured 115,269 named rows at **12,206,295 uncompressed
bytes**, including one newline per row. It excludes source-claim fields and
unnamed pairs, and it says nothing about a production JSON envelope,
compression, UI metadata, asset hashes, or authorization. No payload file was
written.

The current delta API intentionally returns aggregate candidate rows rather
than claim pairs. This checkpoint first reuses that certified manifest-bound
delta to determine the candidate ID set, then makes one further verified direct
stream pass to do the exact-MBID accounting join. That extra pass avoids
changing the delta's compact, ID-only contract.

## Local reproduction

```sh
.venv/bin/python scripts/report_musicbrainz_direct_name_join_frontier.py \
  --direct-custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --direct-custody-receipt-sha256 41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615 \
  --direct-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --name-custody-receipt config/releases/musicbrainz-direct-canonical-artist-name-custody-v1/receipt.json \
  --name-custody-receipt-sha256 06445802bec5120d2068dfb51afc610211063f72994c1862bbc8bad05dda4f25 \
  --name-object-store data/release/musicbrainz-direct-canonical-artist-name-custody-v1/objects \
  --static-discovery dist/assets/static-discovery.4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c.json \
  --certified-manifest dist/opennoise-static-manifest.json \
  --certified-layout dist/assets/semantic-atlas.730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac.json \
  --output /tmp/musicbrainz-direct-name-join-frontier.json
```

To include a verified recovery object, append all three of these arguments to
that command (before `--output` is convenient):

```sh
  --recovery-receipt .cache/musicbrainz-direct-artist-name-recovery-v1/receipt.json \
  --recovery-receipt-sha256 0282dc6c7f2f99828b2aedf64c370d32a5a69bfa4322c153a13fe755ad92693b \
  --recovery-object-store .cache/musicbrainz-direct-artist-name-recovery-v1/objects
```

The writer refuses to replace an existing report. Both the report schema and
the custody receipts fix `public_export_authorized`, `serving_authorized`,
`membership_claims_authorized`, and `release_gate` to `false`.
