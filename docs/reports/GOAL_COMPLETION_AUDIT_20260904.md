# Goal completion audit

Audit basis: main `b768b64`, inspected in the current checkout. The statuses
describe the current OpenNoise implementation. They do not claim that historical
Every Noise output or any lexical label is ground truth.

| Requirement | Status | Evidence and measured result |
| --- | --- | --- |
| Open adapter pipeline | Proven, bounded | `docs/DATA_PIPELINE.md:47-61` defines the adapter boundary. The release evidence contains 62 data sources, 62 source artifacts, 62 ingest attempts, 37,011 staged records, and 2 parser releases. Large MusicBrainz release and recording archives remain unimported. |
| Privacy safe aggregate listening | Proven | The pipeline stores artist pair aggregates without listener identifiers and applies a privacy floor. The release evidence contains 30,903 co listen rows across 7 windows. |
| No audio, previews, or music files | Proven | `docs/CONTENT_POLICY.md:3-25` and the content policy tests enforce the metadata only boundary. The release database has 0 media, audio feature, and content fragment rows. |
| Explainable genre, artist membership, and similarity | Proven | The public model persists direct and one hop profiles, components, evidence references, scores, and ranks. The retained release evidence has 4,434 direct profiles, 22,091 one hop profiles, 26,525 total profiles, and 34,348 neighbors. |
| Public landscape map | Proven | The accepted production artifact has 603 nodes, 712 taxonomy edges, 4 monotonic LODs, and accepted desktop and mobile browser evidence. The current landscape map is served from the versioned artifact. |
| Open 6,291 graph | Proven, bounded | `data/model/open-construction-graph-v1.json` has 6,291 nodes and 1,059 edges. It has 5,243 components, 5,173 isolates, 216 factual taxonomy edges, 843 lexical review edges, 3,539 abstentions, 371 ambiguous names, and 0 inferred memberships. The graph does not use historical geometry, neighbours, artists, H3, or supplementary MusicBrainz genre data. |
| View selector | Proven, bounded | `src/opennoise/templates/map.html:1-7` exposes Public, Open 6,291, and Historical 6,291. Open has bounded landscape endpoints. Historical remains unavailable without its separately configured local artifact and rights decision. |
| Local MusicBrainz research graph | Proven, local only | `docs/MUSICBRAINZ_RESEARCH_GRAPH.md` defines the local scope. The current research coverage is 724 matched names. Its scores, evidence, and landscape are not exportable public model input. |
| Bridge-backed historical membership imitation | Measured, local only | The sealed `historical-imitation-v1` run joins only receipt-bound MusicBrainz-to-Spotify identities to H3's 306,136 unranked positive observations. It maps 120,288 observations to 78,954 MusicBrainz artists. Its open-only and edge-holdout Recall@50 results are 0.01582 and 0.03059 micro, respectively; 1,172 whole-label cold genres explicitly abstain. This is a bounded reconstruction experiment, not a complete membership, rank, or Every Noise parity claim. |
| Representative metadata | Partial | Candidate retrieval and published metadata examples are separate. `docs/reports/METADATA_REPRESENTATIVES_20260904.md` records 871 release group examples and 498 recording proxy examples from bounded candidates. The examples do not claim defining, popular, or quintessential works. The hydration report records 20 releases and 237 track listings. Every hydrated track is marked `track_metadata_not_playable_media`; no audio or preview data is included. |
| Artist membership quality gate | Calibration only | `docs/ARTIST_MEMBERSHIP_EVALUATION.md` and the checked in judgment fixture define a small user authored calibration artifact. It is not an independent public gold set and cannot establish production quality. |
| Reproducible publication | Partial | The release boundary and content addressed publication are implemented. `docs/PUBLIC_RELEASE_CUSTODY.md` defines a portable cache only bundle containing the sealed derived cache and evidence. The bundle does not contain raw source objects, so raw source re ingestion remains open. |

## Retained artifact measurements

The accepted public release evidence records 603 qualified public genres, 1,331
artists, 3,487 catalog entities, 712 taxonomy related edges, and 37,017
provenance records. The production map records 603 nodes, 188 communities,
3,986 edges, 4 LOD levels, 603 profiles, 4,552 neighbours, and 603
explanations.

The Open artifact records its logical SHA-256 as
`9c080faae48db9270b4d8546bec003a90b62cd764ee6e233ed2b3a47f10d1957`. The
committed path is `data/model/open-construction-graph-v1.json`.

The portable release bundle can restore the sealed serving cache, model, map,
configuration, and evidence. It cannot recreate source objects or prove raw
source re ingestion when those objects are absent.

## Highest value remaining blockers

1. Supply and retain the exact raw source vault when full source to publication
   rebuildability is required.
2. Finish the broader MusicBrainz release and track catalog chain.
3. Obtain an independent public gold set for artist membership evaluation.
4. Complete the Historical 6,291 eligibility, rights, rebuild, and browser
   gates before treating it as a product view.

These blockers remain open. This audit does not claim goal completion.
