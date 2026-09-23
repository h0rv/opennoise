# Source and signal inventory

This inventory records the source families retained in the repository and
their current use. An adapter, manifest entry, or cache path does not mean
that its data feeds the public model. A source is marked sealed only when a
receipt or checked artifact binds the input used by a build or evaluation.

| Source family | Retained state | Genre graph and membership use | Layout or diagnostic use |
| --- | --- | --- | --- |
| Every Noise historical files | The fixed vocabulary has 6,291 names. Historical artist observations, coordinates, neighbors, ranks, and representatives are retained behind evaluation custody. | No construction use. It supplies the research name universe only. | Historical compatibility tests only. It cannot tune, select, or populate the graph or layout. |
| Wikidata | Sealed public database and replay receipts contain 746 genre QIDs, 1,331 artist QIDs, 787 release group QIDs, 623 recording QIDs, 853 catalog relations, and 4,948 P136 rows. | This is the current factual source for genre identity, P279 hierarchy candidates, direct artist to genre claims, and representative metadata. The public membership output exposes direct P136 claims only. | The qualified hierarchy and privacy safe similarity input feed the production map. |
| MusicBrainz artist and derived data | Receipt bound local research artifacts exist. The documented corpus processed 2,970,393 artist records and has 212,696 contextual tag rows for 88,328 artists. The separate portable direct proper-genre custody receipt contains 387,435 exact source observations across 697 seeds and 198,409 artist MBIDs. | It does not feed the current public factual membership graph. Proper-genre rows remain custody-only; contextual tags remain local research evidence. No membership construction or public export is authorized from the custody receipt. | Exact MBIDs support prior local peer candidates and metadata context. The peer index has 28,508 canonical edges across 1,580 supported seeds. A distinct custody-only source graph records 20,178 candidate pairs across the 697-seed receipt; it is non-serving local research. |
| MusicBrainz release groups and recordings | The 2026-09-05 release group candidate is receipt bound and has 4,499,326 records, 421,427 direct pairs, and 1,546,265 release support pairs. Recording and release hydration are metadata only. A separate 24-ID exact recording-to-artist API pilot is custody-backed local research only. | Release group labels are credited artist support, not direct artist membership. The candidate and pilot are not consumed by the public model or API. | Local release support, representative metadata, peer evaluation, and the non-production exact-ID feasibility pilot only. |
| ListenBrainz aggregates and playlists | The qualified SQLite input is sealed at SHA-256 `282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`. The run has 30,903 daily aggregate pairs and 13,175 normalized artist pairs. Separately, a receipt-bound ten-playlist public JSPF bundle has 527 unique exact recording MBIDs; its 24-recording exact artist-credit bridge resolved 23 recordings and produced 27 distinct artist-pair potentials. All ten playlist curator states are `unknown`. | Privacy filtered co-listen evidence is retained as aggregate support. Playlists provide source-order recording co-occurrence only, never a genre claim or a factual membership. One hop membership propagation remains a review candidate. | The production map may use only the privacy-safe aggregate similarity input. The public-playlist bundle and artist bridge are local-only diagnostic artifacts; raw listens, user IDs, playlist titles, and curator inferences are not served. |
| Last.fm reverse tags | Adapter and tests exist, but no response cache or evidence receipt exists. | No current graph or membership use. | Review only after an approved API key, query manifest, exact MBID input, and response receipt. |
| MSD and Last.fm offline files | The three required MSD SQLite inputs remain absent. The checksum-verified local-only Last.fm 360K archive has a completed streaming plays-member aggregate: 17,559,530 rows, 160,131 strict exact artist MBIDs, 782 overlaps with the 1,331-artist catalog, and 485,840 artist pairs retained at the >=5-user floor. Its ignored SQLite is local aggregate custody (exact artist and retained pair IDs, no user identifiers), hash-bound by a counts-only companion receipt; see [the source checkpoint](LASTFM_360K_SOURCE_FEASIBILITY_20260922.md) and [count-only direct-custody exact-ID coverage](LASTFM_DIRECT_CUSTODY_EXACT_COVERAGE_20260923.md). The observed 359,349 contiguous blocks and 160,131 strict UUIDs are not equated with the source page's 359,347 users and 186,642 MBID artists. | No graph, membership, model, evaluation, or public use. The 360K result is not MSD evidence. | The source-order first-ten-per-user cap and all-time play semantics make the completed aggregate unsuitable as full similarity or independent genre evidence. It remains local-only despite exact-ID coverage and privacy-filtered pairs. |
| MusicBrainz to Spotify bridge and H3 | Receipt bound bridge and sealed H3 projection exist for historical compatibility. | Prohibited from construction and from public membership. | Evaluation only. H3 absence is unknown, not a negative label. |
| FMA, Discogs, and AcousticBrainz | No FMA or direct Discogs adapter/receipt exists. The ignored local AcousticBrainz Discogs validation TSV is checksum-pinned and has a counts-only exact-ID receipt: 71 recording-MBID overlaps, 64 release-group-consistent overlaps, and 63 additionally single-primary-artist rows. | No use. The TSV labels are not parsed, retained in the receipt, or admitted to construction. | FMA and direct Discogs still lack documented exact model bridges. AcousticBrainz is a positive-only, future recording-level diagnostic ceiling, not artist gold: its source annotations were later imported into MusicBrainz tags, so a frozen prediction must prove it excludes MusicBrainz tag, recording-genre, and release-support dependencies. |

## Signal boundaries

The current public genre graph uses Wikidata for catalog identity, factual
hierarchy, direct artist membership, and representative metadata. It uses the
privacy filtered ListenBrainz aggregate for a similarity input where the map
contract permits it. It does not use Every Noise observations, MusicBrainz
tags, MusicBrainz release group labels, H3 memberships, audio, or model
predictions as public factual membership.

The current public artist membership candidate combines direct Wikidata P136
rows with privacy filtered aggregate candidates, but it is not release
eligible because no independent public gold set has passed the evaluator. Its
direct candidate has 3,049 pairs, and its one hop candidate has 9,256 pairs.
These are candidate counts, not published factual coverage.

The public map has 603 hierarchy nodes, 712 direct taxonomy edges, and 3,274
similarity edges in the recorded qualified run. Historical coordinates are
not used for its positions. Local MusicBrainz peer layouts and historical H3
comparisons are separate diagnostics.

## Gaps

The retained source inventory has four practical gaps. First, the public P136
frontier is sparse, with 292 directly anchored names and 5,999 explicit
abstentions in the bounded membership candidate. Second, MusicBrainz release
and tag evidence is large but remains local and support only. Third, the MSD
SQLite inputs remain absent; the retained Last.fm 360K prefix diagnostic is
superseded by a completed full local aggregate, which remains intentionally
ineligible for model or evaluation input. Fourth, no
independent public artist and genre gold set is available, so no
precision or recall threshold can promote the membership candidate.

The next safe work is to preserve the existing source boundaries, then run
held out evaluations for direct, aggregate, release support, and local peer
signals separately. Any new source must provide a receipt, exact identity
joins, license scope, and a declared signal role before it enters a build.

## Source references

- [Data source audit](../ingest/DATA_SOURCE_AUDIT.md)
- [Source coverage audit](SOURCE_COVERAGE_AUDIT.md)
- [Open construction graph v2](../reports/OPEN_CONSTRUCTION_GRAPH_V2_20260904.md)
- [Public artist membership candidate](../reports/PUBLIC_ARTIST_MEMBERSHIP_REAL_INPUT_20260905.md)
- [Production map audit](../reports/PRODUCTION_MAP_20260831.md)
- [AcousticBrainz Genre Dataset evaluation audit](ACOUSTICBRAINZ_GENRE_DATASET_EVALUATION_AUDIT.md)
- [AcousticBrainz Discogs validation exact overlap](ACOUSTICBRAINZ_DISCOGS_VALIDATION_EXACT_OVERLAP_20260923.md)
- [Last.fm/direct-custody exact-ID coverage](LASTFM_DIRECT_CUSTODY_EXACT_COVERAGE_20260923.md)
- [ListenBrainz playlist exact artist-credit bridge](LISTENBRAINZ_PLAYLIST_MUSICBRAINZ_ARTIST_BRIDGE_20260923.md)
- [Listening and playlist source priority](LISTENING_PLAYLIST_SOURCE_PRIORITY_20260923.md)
- [Direct custody peer graph checkpoint](MUSICBRAINZ_DIRECT_CUSTODY_PEER_GRAPH_20260922.md)
