# Historical source inventory

Research date: 2026-09-04.

This is an acquisition record, not a coverage claim. OpenNoise keeps metadata only. It does not fetch, retain, serve, or link to audio files or previews.

| Source | Date and status | Coverage | Adapter and decision |
| --- | --- | --- | --- |
| [Quint-T final map](https://github.com/quint-t/Every-Noise-at-Once) | Pinned commit `e80265defc743b307586ac0a7a5c72d2dacdf409`; no license found | 6,291 historical genre points | `enao_html_map_v1`. Existing sealed source SHA-256 `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`. H2 only. Historical reference, not the 603-genre public model. |
| [EveryNoise-Watch](https://github.com/AyrtonB/EveryNoise-Watch) | Pinned 2021 CSV; CC-BY-SA data package | 5,453 genre coordinates | `enao_watch_csv_v1`. Existing sealed source SHA-256 `21d9e576fd3f0ae0ec2db46f72d20043f3aafd1ec84d8c14da35e58ecc5ca367`. Coordinates only. |
| [Scottsdaaale genre list](https://github.com/Scottsdaaale/List-of-All-Spotify-Genres) | Current repository advertises 6,044 names; license/status must be checked at the selected commit | Genre names only | Candidate taxonomy seed. Not acquired here. It cannot unlock artist or playlist stages. |
| [NeroYuki genre/artist map](https://github.com/NeroYuki/everynoise_enhancement_script) | Commit `88bd6f6cac0be49cf58af364af5db6f323065375`, 2024-11-16; repository MIT, source-data license unspecified | Sealed local file: 81,672,845 bytes, SHA-256 `863a513a6da89735a69373a46ba58f6975eddb5d065964c577dfcacf18fffe20` | `enao_genre_artist_map_v1`. H3 source-scoped evidence. Default policy is discovery-only; an explicit flag enables local display. |
| [ben-tanen map](https://github.com/ben-tanen/spotify-genre-map) | Public repository; license/status not relied on | Genre coordinates | Candidate H2 comparison only. Not acquired. |
| [andreantonacci scraper](https://github.com/andreantonacci/everynoise_scraper) | Code repository; no frozen output accepted | Potential lists/release endpoints | Discovery only. A scraper is not an archive and is not run by OpenNoise. |
| [Internet Archive CDX](https://web.archive.org/cdx/) | One bounded request on 2026-09-04 returned HTTP 429 | H3/H4/H5 unknown | No retry in this research round. No archive bytes acquired. |
| [Every Noise public mirror](https://furia.com/everynoise_public/engenremap.html) | One `engenremap-techtrance.html` HEAD request on 2026-09-04 returned HTTP 403 | H3/H4/H5 unknown | No bypass or retry. No mirror bytes acquired. |

## Bounded H3 proof

`config/historical_sources/neroyuki_h3_20241116.json` is a non-executable discovery manifest. It records the immutable Git source, Git blob SHA-1 `f91b03a6bdd736035f40f10b391b4bcf33978aa6`, full file size, requested range, and range SHA-256 `5e5555f2d5e68546cb599634b7cf4bd7cc5455e5cd06e9c8159e4be11f4648b4`.

The sealed projection is [neroyuki_h3_pop_sample.json](../tests/fixtures/everynoise/neroyuki_h3_pop_sample.json). Its SHA-256 is `3ec106419821b7de25bbac2590c71f3d30a3508a467d023523e878b58b5a8551`. It contains one genre and three artist identifiers. It strips `sample_song`, `preview_url`, and `track_id` before storage. The adapter counts discarded fields and never exposes them.

The sample proves the H3 adapter shape. The full source now has a local SQLite projection. [Its coverage report](reports/HISTORICAL_H3_COVERAGE_20260904.json) records 6,289 matched H2 names, 145 unmatched names, and 306,136 projected observations. It does not prove that the source matches any Every Noise data date, includes all members, or provides ranked artist pages. The default policy permits normalization only. `--enable-local-display` enables a separate local display policy; it still denies export.

## H3, H4, and H5 status

| Stage | Sealed input | Current result |
| --- | --- | --- |
| H3 genre artist pages | One full sealed local genre-to-artist artifact | 306,136 source-scoped observations on matching H2 names; date is the source commit, not an asserted Every Noise data date. |
| H4 artist pages and recordings | None | Not implemented from new source data. |
| H5 lists and playlists | None | Not implemented from new source data. |

Do not infer missing membership, recordings, ordering, or playlists from this inventory. Prefer an existing dated bulk archive with a checksum over any crawl. Any future archive import needs a pinned URL, capture time, byte size, SHA-256, source policy, coverage test, and a parser that drops audio and preview URLs.

## Excluded material

Reports of a large Every Noise dump containing thousands of HTML pages plus hundreds of thousands of MP3 previews are excluded. The media content violates OpenNoise policy and the bundle cannot establish its own source provenance. Other repositories that expose only code, live scraping, black-box Spotify data, or unpinned generated output are discovery leads, not accepted data.
