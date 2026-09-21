# Source and signal inventory

This inventory records the source families retained in the repository and
their current use. An adapter, manifest entry, or cache path does not mean
that its data feeds the public model. A source is marked sealed only when a
receipt or checked artifact binds the input used by a build or evaluation.

| Source family | Retained state | Genre graph and membership use | Layout or diagnostic use |
| --- | --- | --- | --- |
| Every Noise historical files | The fixed vocabulary has 6,291 names. Historical artist observations, coordinates, neighbors, ranks, and representatives are retained behind evaluation custody. | No construction use. It supplies the research name universe only. | Historical compatibility tests only. It cannot tune, select, or populate the graph or layout. |
| Wikidata | Sealed public database and replay receipts contain 746 genre QIDs, 1,331 artist QIDs, 787 release group QIDs, 623 recording QIDs, 853 catalog relations, and 4,948 P136 rows. | This is the current factual source for genre identity, P279 hierarchy candidates, direct artist to genre claims, and representative metadata. The public membership output exposes direct P136 claims only. | The qualified hierarchy and privacy safe similarity input feed the production map. |
| MusicBrainz artist and derived data | Receipt bound local research artifacts exist. The documented corpus processed 2,970,393 artist records and has 212,696 contextual tag rows for 88,328 artists. | It does not feed the current public factual membership graph. Artist genres and tags remain local research evidence. | Exact MBIDs support local peer candidates and metadata context. The peer index has 28,508 canonical edges across 1,580 supported seeds. |
| MusicBrainz release groups and recordings | The 2026-09-05 release group candidate is receipt bound and has 4,499,326 records, 421,427 direct pairs, and 1,546,265 release support pairs. Recording and release hydration are metadata only. | Release group labels are credited artist support, not direct artist membership. The candidate is not consumed by the public model or API. | Local release support, representative metadata, and peer evaluation only. |
| ListenBrainz | The qualified SQLite input is sealed at SHA-256 `282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`. The run has 30,903 daily aggregate pairs and 13,175 normalized artist pairs. | Privacy filtered co-listen evidence is retained as aggregate support. One hop membership propagation is a review candidate and is not published as a factual claim. | The production map may use the privacy safe similarity input. Raw listens and user IDs are not served. |
| Last.fm reverse tags | Adapter and tests exist, but no response cache or evidence receipt exists. | No current graph or membership use. | Review only after an approved API key, query manifest, exact MBID input, and response receipt. |
| MSD and Last.fm offline files | The adapter and blocked manifest exist, but the required SQLite files and verified receipt are absent. | No use. | No use until all listed files and their hashes are supplied. |
| MusicBrainz to Spotify bridge and H3 | Receipt bound bridge and sealed H3 projection exist for historical compatibility. | Prohibited from construction and from public membership. | Evaluation only. H3 absence is unknown, not a negative label. |
| FMA, Discogs, and AcousticBrainz | No adapter, retained cache, or receipt exists for these sources. | No use. | Feasibility research only. FMA and Discogs lack a documented exact bridge to the model artist and genre IDs. The separate AcousticBrainz Genre Dataset has recording MBIDs and genre annotations, but no artist MBIDs. Its annotations were later imported into MusicBrainz recording tags, so it is not approved as independent production gold. |

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
and tag evidence is large but remains local and support only. Third, Last.fm
and MSD inputs are implemented but have no sealed response or database input.
Fourth, no independent public artist and genre gold set is available, so no
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
