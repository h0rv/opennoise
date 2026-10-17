# Smaller native FMA track payloads

The retained catalog repeated a 34-character native URL prefix in 108,686
otherwise unique URLs. A URL dictionary would add indices without deduplicating
whole URLs. Existing browse routes already load shards on demand. We therefore
factored the literal prefix within eligible track shards, retaining every row.
This is a storage/local-transfer improvement, not a model or quality change.

## Encoding and compatibility

`fma-track-url-prefix-v1` shards declare `metadata_url_prefix` and replace the
`metadata_url` column with `metadata_url_suffix`. The central reader concatenates
strings, preserving exact spelling, escaping, queries, fragments and nulls.
The prefix must be one of the four literal HTTP(S), optional-www FMA `/music/`
prefixes. The producer uses this format only for uniform-prefix shards whose
complete canonical JSON becomes smaller; mixed, unusual and tiny shards retain
the old format. Two of the 310 actual shards remain unencoded.

Unmarked legacy shards remain readable, including refreshed historical exports.
Unknown versions, missing encoding markers, altered columns and malformed rows
fail closed. Decoding copies rows rather than mutating cached input. A decode
failure evicts that JSON cache entry so Retry can fetch a repaired file.
No infrastructure, content negotiation, decompression dependency or framework
was added. Existing 200,000-byte shard and 40,000,000-byte export limits remain.

## Measured artifact and route effects

Implementation commit: `3419a137c279ed7394a16f34703a436dd606a27a`.

| Measure | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Complete export, including receipt | 37,651,498 B | 33,989,601 B | 3,661,897 B (9.73%) |
| Track JSON | 17,395,195 B | 13,731,663 B | 3,663,532 B |
| Sum of independent gzip-9 files | 10,274,492 B | 10,232,964 B | 41,528 B (0.40%) |
| Measured genre route JSON | 449,609 B | 344,764 B | 104,845 B |
| Measured exact artist–genre route JSON | 3,675,820 B | 2,926,110 B | 749,710 B (20.4%) |

The browser runs use the same navigation sequence and a loopback server with
uncompressed, uncached HTTP responses. The application's existing cache remains
active, so route measurements are session-specific, not universal cold-load
figures. Initial genre JSON remains 94,922 bytes. Initial total resources grow
from 221,044 to 222,618 bytes: one new decoder request and 1,574 added JS bytes.
Track search and descriptor-map payloads are unchanged. Repeat, Back and Forward
navigation still request zero additional JSON files in the measured sequence.
Gzip figures are offline estimates, not observed deployment transfer or latency.
No general network-speed or render-time improvement is claimed.

The source receipt's `total_bytes` excludes its own 791-byte receipt; the complete
export figures above include it. The fresh export has 7,562 files and the same
199,999-byte largest JSON shard. The bounded build completed in 12.35 seconds
with 373,923,840 bytes peak RSS under unchanged 120-second/1-GiB guards.

## Independent validation and deliverable

Every one of 109,727 eight-field rows matched the old export exactly after
independent reconstruction; 108,686 non-null URLs and 1,041 null URLs survived.
The actual exported JavaScript decoder also passed every old and new row without
mutating input. All 7,248 unchanged non-track files are byte-identical, including
catalog/labels/licenses, search, cohorts, artists, albums, connections, the entire
descriptor map and source/corpus provenance. Closed inventories passed.

Eleven actual post-initial browser snapshots matched heading, status, record
IDs/text and source-link hrefs, including missing metadata/license/genre cases.
Initial catalog bytes, readiness and lazy loading were separately checked.
Interrupted navigation, repeated routes, Back/Forward and 390px layout passed
with no external or audio requests. Synthetic Chromium contracts additionally
cover mixed legacy/encoded shards, malformed-response Retry, delayed stale
responses and reload. This verifies local HTTP use without an external service;
it does not add a service worker or promise offline browser-cache persistence.

The standalone ZIP is `/workspace/OpenNoise-compact-catalog-20261017.zip`:
11,150,678 bytes, 7,563 members, SHA256
`363ed915fbaf150fbd89263d68437a0663a8962c89b27b81df76387b8db44895`.
Every archive member passed byte-for-byte round-trip verification. Extract it,
serve `site/` using `python3 -m http.server 8000 --bind 127.0.0.1`, and open the
printed local address. It contains no audio or raw-source acquisition.

## Reproduction and retained evidence

Run `scripts/build_fma_static_catalog.py` using retained source
`/workspace/opennoise-rebuild-20261013/metadata-source`, projected metadata
`/workspace/opennoise-rebuild-20261013/metadata`, and frozen descriptor map
`/workspace/fma-descriptor-restore-20261015/map`, into a fresh directory.
The exact wrapper and unchanged resource limits are retained in
`/workspace/opennoise-catalog-payload-run-20261017/build-bounded.py`.

- Baseline: `/workspace/opennoise-genre-artists-run-20261017/site`.
- Build and checks: `/workspace/opennoise-catalog-payload-run-20261017`.
- Full independent audit: `/workspace/opennoise-catalog-payload-independent-20261017`.
- Browser measurements: `/workspace/opennoise-catalog-payload-browser-20261017`.
- Source review: `/workspace/opennoise-catalog-payload-review-20261017`.

No new data acquisition, audio, model fitting, credentials, paid services,
Library retry or public research deployment occurred. Finished listening
packages remain untouched and actual responses remain 0/12. Musical relevance
still requires independent human responses and genuinely unexamined evaluation.
