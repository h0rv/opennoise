# Selected-150 native recording catalog v3

This is a verified CC0 recording metadata acquisition for the already frozen
150 exact MusicBrainz artist identities. It expands the previous two-recording
sample to the prescribed native pagination window. It supplies neither musical
representativeness judgments nor audio permissions, and does not establish Every
Noise parity. The static catalog addon is currently a draft, not a built product.

## Actual acquisition and replay

The original v1 acquisition made 424 requests: 150 limit-two recording browse
requests and 274 individual core-only recording lookups. Its advertised
per-artist recording count sum was 161,349; 161,075 were unfetched.

The v2 full-pagination plan froze all 150 artist IDs, the v1 counts, native
page size 100, first-page and closing probes, exact URLs, implementation bytes,
and caps before HTTP. Executor transport interruption ended its worker after
157 completed native pages. Those bytes, timestamps and durable event lines
were preserved and independently verified; v2 was never restarted or appended.

The separately named v3 recipe authenticated and reused those exact 157 pages
and event lines, then made exactly 1,707 additional requests. Its 1,864-outcome
plan remained unchanged, with no retries, cap increases or post-HTTP pagination
resampling. Total actual requests across these three recording acquisitions are
2,288: 424 + 157 + 1,707, with the reused pages counted once.

The detached worker finished with exit code 0 at 2026-10-03T07:33:52Z. It retained
84,613,884 decoded native bytes, losslessly compressed with decoded and encoded
hashes. The final closed pack is 19,552,629 logical bytes. Capture peak VmHWM was
38,903,808 bytes, below the frozen 40,000,000-byte process ceiling. A separate
whole-source replay finished with exit code 0 in 6.07 seconds, at actual VmHWM
38,338,560 bytes. Both measurements use `/proc/self/status`, not inherited
`getrusage` high-water marks.

Replay checked every closed member, native compressed page, source-state ledger,
prescribed URL/offset, exact requested-artist recording credit, projection hash,
all 150 summaries, current frozen implementation bytes, and the original 157
event lines and frames byte for byte. It found:

- 147 artists with `observed_window_complete`, including nine zero-count artists
  whose initial and closing native probes both remained empty.
- Three artists with `inconsistent` status because native counts declined from
  the pre-HTTP v1 plan. These statuses remain visible and are not relabelled as
  passes.
- Zero missing pages, unapproved rows or duplicate recording rows within an
  artist's fetched nonprobe pages.
- 161,339 exact-credited nonprobe artist/recording rows against the frozen
  per-artist denominator of 161,349. These sums are not global unique recordings.

| Artist | Exact MusicBrainz artist ID | Frozen v1 count | v3 initial / closing count | Exact fetched rows | Frozen-count gap |
| --- | --- | ---: | ---: | ---: | ---: |
| Nas | `cfbc0924-0035-4d6c-8197-f024653af823` | 3,579 | 3,573 / 3,573 | 3,573 | 6 |
| Etta James | `e22d2f66-881e-41ca-9356-544697ee5f90` | 2,428 | 2,426 / 2,426 | 2,426 | 2 |
| Astor Piazzolla | `e280268a-a5ab-4bb0-be4d-ec470ca59131` | 4,659 | 4,657 / 4,657 | 4,657 | 2 |

Aphex Twin (`f22942a1-6f70-4f48-866e-238cb2308fbd`) has 1,246 exact-credited
recordings, matching both probes and the frozen count. Four Tet
(`3bcff06f-675a-451f-9075-99e8657047e8`) has 758, also matching both probes and
the frozen count. These are recording metadata identities, not claims that all
rows are distinct songs, suitable examples or defining music.

## Scope and pins

Only the approved MusicBrainz core recording envelope and exact native artist
credits enter facts under the official
[MusicBrainz data licence](https://musicbrainz.org/doc/About/Data_License).
Mixed or unsupported responses are custody-only under the frozen verifier;
none occurred in this capture. No artist-name joins, Spotify-internal data,
audio requests, playback tests or listener judgments were used.

Live API first/closing count and page consistency demonstrate an observed
window, not a transactional snapshot. The three count declines and ten-row
frozen-count gap remain engineering evidence, not a musical assessment. All
representative-recording judgments remain unassessed.

The source pack is separately named
`opennoise-selected150-recording-catalog-20261003-v3`; v1, v2, the sealed v8
explorer, and all existing recovery files remain preserved. The new source pack and its producing code/proofs are preserved outside the
executor in a two-part Library recovery ZIP: 15,372,310 bytes, SHA256
`e6138676843b8373ec7c765c5f4656c85c09e9836a8ccdf7c2a09986fcf19b83`.
Service access, sizes and hashes are confirmed, and its transfer manifest was
read back byte for byte. No independent outside binary redownload is claimed.
The data-first milestone now prioritizes a reusable compressed normalized export;
additional static-site work is deferred.

Key SHA256 pins:

- Selected 150-ID canonical roster:
  `373593fec761fdc5e9ebc512fe1858e8655af0b48bb1129a8fa9377111e54d79`.
- Authenticated original interrupted-prefix proof:
  `c0ede62497d22f1c629fd778ba7cadfcfc4ab9f6527a97b717a1620de69e9b02`.
- v3 pre-HTTP freeze:
  `d6b3dc6ca3a3cf4515ac27e2a3ee9963d180957d0fd9a52f6d50c864e02ed641`.
- Exact predeclared capture invocation:
  `bf6db16470dd573289ad25ac91c1ab737f8c55c6bc07f470dc5f6322905e5875`.
- v3 source receipt:
  `682e0e963a63c574f9f8729b4c74f8b42aa5bfcd35e41b1a21eeb1bd11b68f9d`.
- Actual native replay result:
  `ee118b79840a650f650c9d152339dd493a48ef710404363daa5d4c4055f7aabc`.
- Actual replay process proof:
  `919918bb7529a6cea8aacd2a0c5b456934d79e2545eedaf4415c12c56a82b3c2`.

The [public JSON report](../reports/SELECTED150_RECORDING_CATALOG_V3_20261003.json)
carries these pins and exact frozen source-code hashes. It is a compact evidence
summary; raw custody and full receipts are retained separately. No acceptance
criteria have been weakened.
