# H4 and H5 bounded source audit

Research date: 2026-09-04. This records what Musix can prove. It does not authorize crawling,
retain audio, or turn a third-party repository into historical Every Noise artist-page or playlist
evidence.

## Accepted bounded candidate: H3 and a derived H4 index

`NeroYuki/everynoise_enhancement_script` contains a pinned JSON file at commit
`88bd6f6cac0be49cf58af364af5db6f323065375`:

| Property | Value |
| --- | --- |
| File | `spotify_genres_artists_map.json` |
| Bytes | 81,672,845 (77.9 MiB) |
| SHA-256 | `863a513a6da89735a69373a46ba58f6975eddb5d065964c577dfcacf18fffe20` |
| Git blob | `f91b03a6bdd736035f40f10b391b4bcf33978aa6` |
| Repository code license | MIT |
| Upstream metadata provenance | unverified upstream-derived metadata |
| Source direction | genre to artist |

One sealed H3 adapter verifies the exact bytes and accepts only `genre`, `artist`, and
`artist_id`. It counts and removes `preview_url`, `sample_song`, `track_id`, and every unmodelled
field before persistence. Raw bytes and media-bearing values stay in ignored local storage and are
never published to the object store or compatibility artifact.

With explicit local display, the schema-12 projection has 306,136 exact source-scoped
memberships across 6,289 retained map names. It quarantines 5,445 duplicate or malformed source
rows. A single SQL reverse query provides a deterministic artist-to-genre index from those visible
H3 rows. That H4 result is `derived_partial`: it is not an artist-page capture and says nothing
about artist-page order, recordings, related artists, or complete coverage.

## H5 status: unavailable

No bounded, checksummed Every Noise list, playlist, rank, or track-order artifact was found among
the inspected repositories. H5 stays unavailable. Do not infer a playlist, rank, or track order
from the genre-to-artist source.

## Inspected but not accepted

| Candidate | Finding | Decision |
| --- | --- | --- |
| `AyrtonB/EveryNoise-Watch` | Coordinate CSV archive only | H2 comparison source, no H4/H5 rows |
| `ben-tanen/spotify-genre-map` | Daily genre-map CSV snapshots; no artist-page or playlist corpus identified | Not acquired |
| `andreantonacci/everynoise_scraper` | Scraper code and documentation, no frozen output fixtures | Not run or acquired |
| `Quint-T/Every-Noise-at-Once` | Historical map asset only | H2 source, not H4/H5 |
| Internet Archive CDX | One bounded request returned HTTP 429 | No retry; no archive bytes acquired |

A future H4 input must be a dated, checksummed artist-page corpus with explicit rights and capture
provenance. A future H5 input must be a dated, checksummed list or playlist corpus with identifier
and rank/order semantics. Neither contract is enabled by this projection.
